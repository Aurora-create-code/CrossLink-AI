"""Local PDF ingestion. Files are addressed by server IDs, never user paths."""
import hashlib
from io import BytesIO
import logging
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pypdf import PdfReader
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.database import connect

MAX_BYTES = 20 * 1024 * 1024
MAX_BODY = MAX_BYTES + 64 * 1024
MAX_PAGES = 300
MAX_PAGE_TEXT = 500_000
MAX_TOTAL_TEXT = 5_000_000
logger = logging.getLogger(__name__)


def fail(status: int, message: str):
    raise HTTPException(status_code=status, detail=message)


class UploadLimitMiddleware:
    """Bound the streamed request, including multipart framing, before form parsing."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope.get('method') != 'POST' or scope.get('path') != '/api/documents':
            return await self.app(scope, receive, send)
        headers = dict(scope.get('headers', []))
        try:
            if int(headers.get(b'content-length', b'0')) > MAX_BODY:
                return await JSONResponse({'detail': '上传请求过大；单份 PDF 上限为 20 MiB。'}, status_code=413)(scope, receive, send)
        except ValueError:
            return await JSONResponse({'detail': '无效的 Content-Length。'}, status_code=400)(scope, receive, send)
        received = 0

        async def bounded_receive():
            nonlocal received
            message = await receive()
            received += len(message.get('body', b''))
            if received > MAX_BODY:
                raise HTTPException(413, '上传请求过大；单份 PDF 上限为 20 MiB。')
            return message
        await self.app(scope, bounded_receive, send)


def validate_filename(name: str | None) -> str:
    if not name or len(name) > 240 or name != name.strip() or any(ord(c) < 32 for c in name):
        fail(400, '文件名无效，请使用普通 PDF 文件名。')
    if any(c in name for c in '/\\:<>"|?*') or name in ('.', '..') or not name.lower().endswith('.pdf'):
        fail(400, '仅支持 .pdf 文件，文件名不能包含路径或特殊路径字符。')
    return name


def validate_source(source: str) -> str | None:
    source = source.strip()
    if not source:
        return None
    try:
        parsed = urlsplit(source)
        valid = parsed.scheme in ('http', 'https') and parsed.hostname and not parsed.username and not parsed.password
        if len(source) > 2048 or any(c.isspace() or ord(c) < 32 for c in source) or not valid:
            raise ValueError()
    except ValueError:
        fail(400, '来源必须为不含账号密码的 HTTP(S) 链接。')
    return source


def extract_pages(content: bytes) -> list[dict]:
    if not content.startswith(b'%PDF-'):
        fail(422, '文件内容不是有效 PDF，不能仅修改扩展名。')
    try:
        reader = PdfReader(BytesIO(content), strict=True)
        if reader.is_encrypted:
            fail(422, '暂不支持加密或受密码保护的 PDF。')
        if not 1 <= len(reader.pages) <= MAX_PAGES:
            fail(422, f'PDF 页数必须介于 1 与 {MAX_PAGES} 页。')
        pages = []
        total = 0
        for number, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ''
            total += len(text)
            if len(text) > MAX_PAGE_TEXT or total > MAX_TOTAL_TEXT:
                fail(422, 'PDF 提取文本超过当前处理上限。')
            pages.append({'page_number': number, 'text': text, 'has_text': bool(text.strip())})
    except HTTPException:
        raise
    except Exception:
        logger.warning('PDF parsing failed; no document persisted')
        fail(422, 'PDF 损坏、结构不受支持或无法提取文字，请检查原文件。')
    if not any(p['has_text'] for p in pages):
        fail(422, '未发现可提取文字；该 PDF 可能为扫描件。本阶段不支持 OCR，未保存资料。')
    return pages


def to_document(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in ('id', 'filename', 'content_sha256', 'source_url', 'page_count', 'extracted_page_count', 'created_at', 'size_bytes')}


def router_for(database_path: Path) -> APIRouter:
    router = APIRouter(prefix='/api/documents', tags=['documents'])
    root = (database_path.parent / 'originals').resolve()

    def open_db():
        db = connect(database_path)
        db.row_factory = sqlite3.Row
        return db

    def lookup(db, document_id):
        if not re.fullmatch(r'[a-f0-9]{32}', document_id):
            fail(404, '资料不存在。')
        row = db.execute('SELECT * FROM documents WHERE id=? AND page_count IS NOT NULL', (document_id,)).fetchone()
        if row is None:
            fail(404, '资料不存在。')
        return row

    def save(content, filename, source):
        digest = hashlib.sha256(content).hexdigest()
        pages = extract_pages(content)
        root.mkdir(parents=True, exist_ok=True)
        document_id = uuid4().hex
        path = (root / f'{document_id}.pdf').resolve()
        if path.parent != root:
            fail(400, '文件保存路径无效。')
        created = False
        try:
            with open_db() as db:
                db.execute('BEGIN IMMEDIATE')
                existing = db.execute('SELECT * FROM documents WHERE content_sha256=? AND page_count IS NOT NULL ORDER BY created_at,id LIMIT 1', (digest,)).fetchone()
                if existing:
                    return {'document': to_document(existing), 'duplicate': True}
                # Exclusive creation prevents overwriting a previously saved original.
                with path.open('xb') as stream:
                    created = True
                    stream.write(content)
                    stream.flush()
                db.execute('''INSERT INTO documents(id,filename,media_type,content_sha256,storage_path,source_url,size_bytes,page_count,extracted_page_count)
                    VALUES (?,?,?,?,?,?,?,?,?)''', (document_id, filename, 'application/pdf', digest, path.name, source, len(content), len(pages), sum(p['has_text'] for p in pages)))
                db.executemany('INSERT INTO document_pages(document_id,page_number,text,has_text) VALUES (?,?,?,?)', [(document_id,p['page_number'],p['text'],int(p['has_text'])) for p in pages])
                result = to_document(db.execute('SELECT * FROM documents WHERE id=?', (document_id,)).fetchone())
            return {'document': result, 'duplicate': False}
        except Exception:
            # Only unlink the exact UUID path exclusively created by this request.
            if created and path.parent == root:
                path.unlink(missing_ok=True)
            raise

    @router.post('')
    async def upload(request: Request):
        if not request.headers.get('content-type', '').lower().startswith('multipart/form-data'):
            fail(415, '请通过 multipart/form-data 上传单份 PDF。')
        try:
            async with request.form(max_files=1, max_fields=1, max_part_size=4096) as form:
                files = form.getlist('file')
                sources = form.getlist('source_url')
                if set(form.keys()) - {'file','source_url'} or len(files) != 1 or len(sources) > 1 or not isinstance(files[0], UploadFile):
                    fail(400, '每次仅能上传一个 file，并可附带一个 source_url。')
                file = files[0]
                filename = validate_filename(file.filename)
                if file.content_type not in ('application/pdf', 'application/octet-stream'):
                    fail(415, '文件类型必须为 PDF。')
                if sources and not isinstance(sources[0], str):
                    fail(400, '来源链接格式无效。')
                source = validate_source(sources[0] if sources else '')
                content = await file.read(MAX_BYTES + 1)
                if not content:
                    fail(422, 'PDF 文件为空。')
                if len(content) > MAX_BYTES:
                    fail(413, 'PDF 大小超过 20 MiB 上限。')
                result = await run_in_threadpool(save, content, filename, source)
                return JSONResponse(result, status_code=200 if result['duplicate'] else 201)
        except StarletteHTTPException:
            raise
        except (OSError, sqlite3.Error):
            logger.error('Document persistence failed')
            fail(500, '资料保存失败，请重试；没有新增成功记录。')

    @router.get('')
    def listing():
        with open_db() as db:
            rows = db.execute('SELECT * FROM documents WHERE page_count IS NOT NULL ORDER BY created_at DESC,id DESC').fetchall()
            return {'documents': [to_document(row) for row in rows]}

    @router.get('/{document_id}')
    def detail(document_id: str):
        with open_db() as db:
            row = lookup(db, document_id)
            pages = db.execute('SELECT page_number,text,has_text FROM document_pages WHERE document_id=? ORDER BY page_number', (document_id,)).fetchall()
            return {'document': to_document(row), 'pages': [{'page_number':p['page_number'],'text':p['text'],'has_text':bool(p['has_text'])} for p in pages]}

    @router.get('/{document_id}/original')
    def original(document_id: str):
        with open_db() as db:
            row = lookup(db, document_id)
            name = row['storage_path']
            if name != f'{document_id}.pdf':
                fail(404, '原文件路径无效。')
            path = (root / name).resolve()
            if path.parent != root or not path.is_file():
                fail(404, '原 PDF 不存在或路径无效。')
            return FileResponse(path, media_type='application/pdf', filename=row['filename'], content_disposition_type='inline', headers={'X-Content-Type-Options':'nosniff','Content-Security-Policy':"sandbox"})

    return router
