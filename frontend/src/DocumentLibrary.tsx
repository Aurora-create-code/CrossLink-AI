import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import './DocumentLibrary.css';

type Doc = {
  id: string;
  filename: string;
  content_sha256: string;
  source_url: string | null;
  page_count: number;
  extracted_page_count: number;
  created_at: string;
  size_bytes: number;
};
type Page = { page_number: number; text: string; has_text: boolean };
type Detail = { document: Doc; pages: Page[] };
type Selection = { id: string; page: number };
const MAX_BYTES = 20 * 1024 * 1024;
const MIT_SOURCE = 'https://www.ocw.mit.edu/courses/3-051j-materials-for-biomedical-applications-spring-2006/860c4719a25cc2154e95f27165c8bbbe_lecture1.pdf';

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
function nonnegativeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}
function isDoc(value: unknown): value is Doc {
  return record(value) && typeof value.id === 'string' && typeof value.filename === 'string' &&
    typeof value.content_sha256 === 'string' && (value.source_url === null || typeof value.source_url === 'string') &&
    nonnegativeInteger(value.page_count) && nonnegativeInteger(value.extracted_page_count) &&
    typeof value.created_at === 'string' && nonnegativeInteger(value.size_bytes);
}
function isPage(value: unknown): value is Page {
  return record(value) && nonnegativeInteger(value.page_number) && value.page_number > 0 &&
    typeof value.text === 'string' && typeof value.has_text === 'boolean';
}
function detailMessage(value: unknown): string {
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) return value.map(detailMessage).filter(Boolean).join('；');
  if (record(value)) {
    if (typeof value.msg === 'string') {
      const location = Array.isArray(value.loc) ? value.loc.map(String).join(' / ') : '';
      return `${location ? `${location}：` : ''}${value.msg}`;
    }
    if (typeof value.message === 'string') return value.message;
    return JSON.stringify(value);
  }
  return value == null ? '' : String(value);
}
async function request(url: string, options: RequestInit = {}): Promise<unknown> {
  const response = await fetch(url, { ...options, headers: { Accept: 'application/json', ...options.headers }, cache: 'no-store' });
  let data: unknown;
  try { data = await response.json(); } catch {
    throw new Error(`服务返回了无法读取的响应（HTTP ${response.status}）。`);
  }
  if (!response.ok) {
    const message = record(data) ? detailMessage(data.detail) : '';
    throw new Error(message || `请求失败（HTTP ${response.status}），请重试。`);
  }
  return data;
}
function errorMessage(error: unknown): string {
  return error instanceof TypeError ? '无法连接服务，请检查网络或后端服务后重试。' :
    error instanceof Error ? error.message : '请求失败，请重试。';
}
function readSelection(): Selection {
  const params = new URLSearchParams(window.location.search);
  const page = Number(params.get('page'));
  return { id: params.get('document') || '', page: Number.isSafeInteger(page) && page > 0 ? page : 1 };
}
function safeSource(value: string): string | undefined {
  try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) ? url.href : undefined; } catch { return undefined; }
}
function formatSize(bytes: number): string {
  return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(2)} MiB` : `${(bytes / 1024).toFixed(1)} KiB`;
}
function formatDate(value: string): string {
  const date = new Date(/^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$/.test(value) ? `${value.replace(' ', 'T')}Z` : value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false });
}

export default function DocumentLibrary() {
  const [documents, setDocuments] = useState<Doc[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState('');
  const [listAttempt, setListAttempt] = useState(0);
  const [selection, setSelection] = useState<Selection>(readSelection);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState('');
  const [detailAttempt, setDetailAttempt] = useState(0);
  const [file, setFile] = useState<File | null>(null);
  const [source, setSource] = useState('');
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState('');
  const [notice, setNotice] = useState('');
  const fileInput = useRef<HTMLInputElement>(null);
  const uploadLock = useRef(false);

  useEffect(() => {
    const onPopState = () => setSelection(readSelection());
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  useEffect(() => {
    const url = new URL(window.location.href);
    if (selection.id) {
      url.searchParams.set('document', selection.id);
      url.searchParams.set('page', String(selection.page));
    } else {
      url.searchParams.delete('document');
      url.searchParams.delete('page');
    }
    window.history.replaceState(window.history.state, '', url);
  }, [selection]);

  useEffect(() => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 15000);
    let active = true;
    setListLoading(true);
    setListError('');
    void request('/api/documents', { signal: controller.signal }).then((data) => {
      if (!record(data) || !Array.isArray(data.documents) || !data.documents.every(isDoc)) {
        throw new Error('资料列表响应格式不正确。');
      }
      if (!active) return;
      const items = data.documents as Doc[];
      setDocuments(items);
      setSelection((current) => current.id || !items.length ? current : { id: items[0].id, page: 1 });
    }).catch((error: unknown) => {
      if (active) setListError(controller.signal.aborted ? '读取列表超时，请刷新重试。' : errorMessage(error));
    }).finally(() => {
      window.clearTimeout(timeout);
      if (active) setListLoading(false);
    });
    return () => { active = false; window.clearTimeout(timeout); controller.abort(); };
  }, [listAttempt]);

  useEffect(() => {
    setDetail(null);
    setDetailError('');
    if (!selection.id) { setDetailLoading(false); return; }
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 30000);
    let active = true;
    setDetailLoading(true);
    void request(`/api/documents/${encodeURIComponent(selection.id)}`, { signal: controller.signal }).then((data) => {
      if (!record(data) || !isDoc(data.document) || data.document.id !== selection.id ||
          !Array.isArray(data.pages) || !data.pages.every(isPage)) {
        throw new Error('资料详情响应格式不正确。');
      }
      if (!active) return;
      const result = data as Detail;
      setDetail(result);
      setSelection((current) => current.id === result.document.id ? {
        ...current, page: Math.min(current.page, Math.max(1, result.document.page_count)),
      } : current);
    }).catch((error: unknown) => {
      if (active) setDetailError(controller.signal.aborted ? '读取详情超时，请重试。' : errorMessage(error));
    }).finally(() => {
      window.clearTimeout(timeout);
      if (active) setDetailLoading(false);
    });
    return () => { active = false; window.clearTimeout(timeout); controller.abort(); };
  }, [selection.id, detailAttempt]);

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (uploadLock.current) return;
    setUploadError('');
    setNotice('');
    if (!file) { setUploadError('请先选择一份 PDF 文件。'); return; }
    if (!/\.pdf$/i.test(file.name) || (file.type && file.type !== 'application/pdf')) {
      setUploadError('仅支持单份 PDF 文件，请重新选择。'); return;
    }
    if (file.size === 0 || file.size > MAX_BYTES) {
      setUploadError('PDF 文件不能为空，且不得超过 20 MiB。'); return;
    }
    const sourceUrl = source.trim();
    if (sourceUrl && !safeSource(sourceUrl)) {
      setUploadError('来源 URL 请输入完整的 http:// 或 https:// 地址，也可以留空。'); return;
    }
    const submittedFile = file;
    const body = new FormData();
    body.append('file', submittedFile);
    if (sourceUrl) body.append('source_url', sourceUrl);
    uploadLock.current = true;
    setUploading(true);
    try {
      const data = await request('/api/documents', { method: 'POST', body });
      if (!record(data) || !isDoc(data.document) || typeof data.duplicate !== 'boolean') {
        throw new Error('上传响应格式不正确。请先刷新资料列表确认结果，再决定是否重试。');
      }
      const document = data.document;
      setDocuments((current) => [document, ...current.filter((item) => item.id !== document.id)]);
      setSelection({ id: document.id, page: 1 });
      setDetailAttempt((value) => value + 1);
      setListAttempt((value) => value + 1);
      setNotice(data.duplicate ? '检测到相同内容：已复用已有资料，原文件名、来源等元数据保持不变。' : 'PDF 已上传，现可逐页查看提取的文字和原始文件。');
      // Only clear after confirmed success; never discard a selection on failure.
      if (fileInput.current?.files?.[0] === submittedFile) {
        fileInput.current.value = '';
        setFile(null);
      }
    } catch (error: unknown) {
      setUploadError(`${errorMessage(error)} 已保留所选文件；若结果不确定，请先刷新列表确认。`);
    } finally {
      uploadLock.current = false;
      setUploading(false);
    }
  }

  const currentDetail = detail?.document.id === selection.id ? detail : null;
  const currentDoc = currentDetail?.document;
  const currentPage = currentDetail?.pages.find((page) => page.page_number === selection.page);
  const sourceHref = currentDoc?.source_url ? safeSource(currentDoc.source_url) : undefined;

  return (
    <section className="document-library" aria-labelledby="documents-title">
      <div className="section-heading">
        <div><p className="section-kicker">DOCUMENT LIBRARY · 第二阶段</p><h2 id="documents-title">资料库</h2></div>
        <button type="button" className="refresh-button" disabled={listLoading} onClick={() => setListAttempt((value) => value + 1)}>{listLoading ? '正在读取' : '刷新资料列表'}</button>
      </div>
      <p className="library-intro">上传一份 PDF，保留来源与原文件，按页核对真实提取文字。资料库不提供 OCR；MIT 指定页的模型知识提取与人工审核见下方知识面板。</p>
      <form className="document-upload" onSubmit={(event) => void upload(event)} aria-busy={uploading}>
        <div className="upload-fields">
          <div className="document-field">
            <label htmlFor="document-file">PDF 文件</label>
            <input ref={fileInput} id="document-file" type="file" accept=".pdf,application/pdf" disabled={uploading} aria-describedby="file-help upload-error" onChange={(event) => { setFile(event.currentTarget.files?.[0] ?? null); setUploadError(''); setNotice(''); }} />
            <p id="file-help" className="field-help">每次仅上传一份 PDF，最大 20 MiB。选择文件后点击上传。</p>
          </div>
          <div className="document-field">
            <label htmlFor="document-source">来源 URL <span>（可选）</span></label>
            <input id="document-source" type="url" value={source} placeholder="https://…（默认留空）" disabled={uploading} aria-describedby="source-help" onChange={(event) => setSource(event.target.value)} />
            <p id="source-help" className="field-help">建议来源：<a href={MIT_SOURCE} target="_blank" rel="noopener noreferrer">MIT OpenCourseWare（新窗口）</a>。<button type="button" className="text-button" disabled={uploading} onClick={() => setSource(MIT_SOURCE)}>填入 MIT 来源</button>，可再改为具体资料网址。</p>
          </div>
        </div>
        <div className="upload-actions"><button className="primary-button" type="submit" disabled={uploading || !file}>{uploading ? '正在上传并提取…' : '上传单份 PDF'}</button><p className="field-help">相同内容复用已有资料，不覆盖原文件名或来源。</p></div>
        <div id="upload-error" role="alert">{uploadError && <p className="error-message">{uploadError}</p>}</div>
        <div role="status" aria-live="polite">{notice && <p className="document-notice">{notice}</p>}</div>
      </form>
      {listError && <p className="error-message" role="alert">{listError} 可点击“刷新资料列表”重试。</p>}
      <div className="library-layout">
        <aside className="document-list" aria-labelledby="document-list-title" aria-busy={listLoading}>
          <h3 id="document-list-title">已存资料 <span>（{documents.length}）</span></h3>
          {listLoading && <p className="library-empty" role="status">正在读取资料列表…</p>}
          {!listLoading && !listError && !documents.length && <p className="library-empty">资料库还是空的。上传第一份 PDF 后即可查看。</p>}
          <ul>{documents.map((document) => <li key={document.id}><button type="button" className={`document-item${document.id === selection.id ? ' selected' : ''}`} aria-current={document.id === selection.id ? 'true' : undefined} onClick={() => setSelection({ id: document.id, page: 1 })}><span className="document-name">{document.filename}</span><span>{document.page_count} 页 · {document.extracted_page_count} 页有文字</span><span>{formatSize(document.size_bytes)}</span></button></li>)}</ul>
        </aside>
        <div className="document-reader" aria-busy={detailLoading}>
          {!selection.id && <p className="library-empty">从左侧选择资料，查看逐页提取结果。</p>}
          {selection.id && (!currentDetail && !detailError) && <p className="library-empty" role="status">正在读取资料详情…</p>}
          {detailError && <div role="alert"><p className="error-message">{detailError}</p><button type="button" className="refresh-button" onClick={() => setDetailAttempt((value) => value + 1)}>重试读取资料</button></div>}
          {currentDoc && <>
            <h3 className="reader-title">{currentDoc.filename}</h3>
            <dl className="document-metadata">
              <div><dt>来源</dt><dd>{currentDoc.source_url ? sourceHref ? <a href={sourceHref} target="_blank" rel="noopener noreferrer">{currentDoc.source_url}<span className="sr-only">（新窗口打开）</span></a> : currentDoc.source_url : '未提供来源'}</dd></div>
              <div><dt>SHA-256</dt><dd><code>{currentDoc.content_sha256}</code></dd></div>
              <div><dt>页数</dt><dd>共 {currentDoc.page_count} 页 / 有文字 {currentDoc.extracted_page_count} 页</dd></div>
              <div><dt>文件大小</dt><dd>{formatSize(currentDoc.size_bytes)}</dd></div>
              <div><dt>入库时间</dt><dd>{formatDate(currentDoc.created_at)}</dd></div>
            </dl>
            {currentDoc.extracted_page_count < currentDoc.page_count && <p className="empty-page-note">有 {currentDoc.page_count - currentDoc.extracted_page_count} 页未提取到文字，可能为空白页、图片或扫描页；请打开原 PDF 核对，当前未做 OCR。</p>}
            {currentDoc.page_count > 0 ? <>
              <nav className="page-controls" aria-label="PDF 页码">
                <button type="button" className="refresh-button" disabled={selection.page <= 1} onClick={() => setSelection((value) => ({ ...value, page: value.page - 1 }))}>上一页</button>
                <label htmlFor="document-page">页码 <select id="document-page" value={selection.page} onChange={(event) => setSelection((value) => ({ ...value, page: Number(event.target.value) }))}>{Array.from({ length: currentDoc.page_count }, (_, index) => <option key={index + 1} value={index + 1}>第 {index + 1} 页</option>)}</select> / {currentDoc.page_count}</label>
                <button type="button" className="refresh-button" disabled={selection.page >= currentDoc.page_count} onClick={() => setSelection((value) => ({ ...value, page: value.page + 1 }))}>下一页</button>
                <a className="original-link" href={`/api/documents/${encodeURIComponent(currentDoc.id)}/original#page=${selection.page}`} target="_blank" rel="noopener noreferrer">打开原 PDF 第 {selection.page} 页 ↗<span className="sr-only">（新窗口）</span></a>
              </nav>
              <div className="page-text" aria-live="polite" aria-atomic="true">
                <h4>第 {selection.page} 页 · 提取文字</h4>
                {currentPage ? <>{!currentPage.has_text && <p className="empty-page-note">本页未提取到文字。可能为空白页或扫描图片，请核对原 PDF。</p>}<pre tabIndex={0} aria-label={`第 ${selection.page} 页的原始提取文字`}>{currentPage.text}</pre></> : <p className="empty-page-note">服务未返回本页提取记录，请刷新详情或打开原 PDF 核对。</p>}
              </div>
            </> : <p className="empty-page-note">此资料没有可浏览的页面。</p>}
          </>}
        </div>
      </div>
    </section>
  );
}
