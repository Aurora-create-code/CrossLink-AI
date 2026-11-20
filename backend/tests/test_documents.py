import hashlib
from io import BytesIO
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from pypdf import PdfWriter
from app.main import create_app
from app.config import Settings
from app import database


def blank_pdf():
    writer = PdfWriter()
    writer.add_blank_page(100, 100)
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


class DocumentTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1] / 'data' / 'test-runs'
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.root = Path(self.temp.name)
        self.settings = Settings(database_path=self.root/'test.sqlite3')
        self.client_context = TestClient(create_app(self.settings))
        self.client = self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None,None,None)
        self.temp.cleanup()

    def send(self, data=b'%PDF-test', filename='test.pdf', mime='application/pdf', source=''):
        return self.client.post('/api/documents', files={'file':(filename,data,mime)}, data={'source_url':source})

    def test_invalid_files_leave_no_records(self):
        for content,name,mime,status in [(b'', 'a.pdf','application/pdf',422),(b'hello','a.pdf','application/pdf',422),(b'%PDF-corrupt','a.pdf','application/pdf',422),(b'x','../a.pdf','application/pdf',400),(b'x','a.txt','text/plain',400),(b'x','a.pdf','text/plain',415),(blank_pdf(),'scan.pdf','application/pdf',422)]:
            with self.subTest(name=name,status=status):
                response=self.send(content,name,mime)
                self.assertEqual(response.status_code,status,response.text)
                self.assertTrue(response.json()['detail'])
        self.assertEqual(self.client.get('/api/documents').json()['documents'],[])
        self.assertEqual(list((self.root/'originals').glob('*')),[])

    def test_source_size_and_multipart(self):
        self.assertEqual(self.send(source='javascript:alert(1)').status_code,400)
        with patch('app.documents.MAX_BYTES',5):
            self.assertEqual(self.send(b'%PDF-too-big').status_code,413)
        self.assertEqual(self.client.post('/api/documents',content=b'x',headers={'Content-Type':'application/pdf'}).status_code,415)
        r=self.client.post('/api/documents', files=[('file',('a.pdf',b'a','application/pdf')),('file',('b.pdf',b'b','application/pdf'))])
        self.assertEqual(r.status_code,400)
        self.assertEqual(self.client.get('/api/documents').json()['documents'],[])

    def test_transaction_duplicate_and_persistence(self):
        pages=[{'page_number':1,'text':'unit test only','has_text':True},{'page_number':2,'text':'','has_text':False}]
        # Parser mocked only for transaction tests. Real PDF extraction has a separate sample acceptance run.
        with patch('app.documents.extract_pages',return_value=pages):
            r=self.send(source='https://example.org/source.pdf');self.assertEqual(r.status_code,201,r.text)
            doc=r.json()['document'];self.assertEqual(doc['extracted_page_count'],1)
            duplicate=self.send(filename='renamed.pdf',source='https://example.org/other.pdf')
            self.assertEqual(duplicate.status_code,200)
            self.assertTrue(duplicate.json()['duplicate']);self.assertEqual(duplicate.json()['document'],doc)
        detail=self.client.get('/api/documents/'+doc['id']).json()
        self.assertEqual(detail['pages'],pages)
        original=self.client.get('/api/documents/'+doc['id']+'/original')
        self.assertEqual(hashlib.sha256(original.content).hexdigest(),doc['content_sha256'])
        database.initialize(self.settings.database_path)
        with TestClient(create_app(self.settings)) as restarted:
            self.assertEqual(restarted.get('/api/documents/'+doc['id']).json(),detail)
        # A compromised DB path must never be interpreted as a user-controlled path.
        with database.connect(self.settings.database_path) as db:
            db.execute('UPDATE documents SET storage_path=? WHERE id=?',('../private.pdf',doc['id']))
        self.assertEqual(self.client.get('/api/documents/'+doc['id']+'/original').status_code,404)

    def test_save_failure_rolls_back_and_removes_file(self):
        pages=[{'page_number':1,'text':'test only','has_text':True}]
        with database.connect(self.settings.database_path) as db:
            db.execute("CREATE TRIGGER fail_page BEFORE INSERT ON document_pages BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        with patch('app.documents.extract_pages',return_value=pages):
            response=self.send()
        self.assertEqual(response.status_code,500)
        self.assertEqual(self.client.get('/api/documents').json()['documents'],[])
        self.assertEqual(list((self.root/'originals').glob('*')),[])

    def test_v1_migration_preserves_existing_records(self):
        old=self.root/'old.sqlite3'
        with database.connect(old) as db:
            db.executescript(database.SCHEMA)
            db.execute("INSERT INTO documents(id,filename,media_type,content_sha256,storage_path) VALUES ('old','old.pdf','application/pdf','oldhash','oldpath')")
            db.execute('PRAGMA user_version=1')
        database.initialize(old)
        database.initialize(old)
        with database.connect(old) as db:
            self.assertEqual(db.execute("SELECT filename FROM documents WHERE id='old'").fetchone()[0],'old.pdf')
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],database.SCHEMA_VERSION)


if __name__=='__main__':
    unittest.main()
