import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import database
from app.config import Settings
from app.main import create_app
from app.adapters.thingo import ThingoAdapter
from app.reports import DEMO_ID
from test_opportunities import candidate
from app.knowledge import DOCUMENT_ID

class ReportTests(unittest.TestCase):
 def test_report_download_changes_and_missing_do_not_call_model(self):
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'app.sqlite3';database.initialize(path)
   source={'id':'k','content':'PLA used in regeneration','quote':'polylactide (PLA) used for tissue\nregeneration','document_id':DOCUMENT_ID,'page_number':10,'review_status':'confirmed'}
   with database.connect(path) as db:
    db.execute('INSERT INTO documents(id,filename,media_type,content_sha256,storage_path) VALUES (?,?,?,?,?)',(DOCUMENT_ID,'test.pdf','application/pdf','hash','test.pdf'))
    db.execute('INSERT INTO document_pages VALUES (?,10,?,1)',(DOCUMENT_ID,source['quote']))
    db.execute("INSERT INTO extraction_batches(id,document_id,fingerprint,model,status) VALUES ('kb',?,'x','gpt-6.1-sol','completed')",(DOCUMENT_ID,))
    db.execute("INSERT INTO knowledge_items(id,batch_id,document_id,page_number,content,quote,model,extraction_status,review_status) VALUES ('k','kb',?,10,?,?,'gpt-6.1-sol','source_verified','confirmed')",(DOCUMENT_ID,source['content'],source['quote']))
    db.execute("INSERT INTO opportunity_batches(id,fingerprint,model,status,snapshot_json) VALUES ('b','f','gpt-6.1-sol','completed',?)",(json.dumps([source]),))
    payload=candidate(['k']);payload['title']='梯度孔径PLA支架'
    db.execute('INSERT INTO opportunity_items(id,batch_id,payload_json) VALUES (?,?,?)',(DEMO_ID,'b',json.dumps(payload)))
    payload['title']='其他已保存候选'
    db.execute('INSERT INTO opportunity_items(id,batch_id,payload_json) VALUES (?,?,?)',('other','b',json.dumps(payload)))
   with patch.object(ThingoAdapter,'generate',side_effect=AssertionError('No network')),TestClient(create_app(Settings(database_path=path))) as c:
    self.assertEqual(c.get('/api/reports/missing').status_code,404)
    self.assertEqual(c.get('/api/reports/missing/markdown').status_code,404)
    report=c.get('/api/reports/'+DEMO_ID).json();self.assertFalse(report['basis_changed']);self.assertIn('可降解塑料',report['sections'][0]['body'])
    self.assertEqual(report['sources'][0]['quote'],source['quote'])
    exported=c.get('/api/reports/'+DEMO_ID+'/markdown')
    self.assertIn('attachment;',exported.headers['content-disposition']);self.assertIn('text/markdown',exported.headers['content-type'])
    for text in (DEMO_ID,'gpt-6.1-sol','物理页码：10','知识ID：k','实验未执行','/original#page=10'):
     self.assertIn(text,exported.text)
    other=c.get('/api/reports/other').json();self.assertEqual(other['title'],'其他已保存候选');self.assertEqual(other['sections'][0]['body'],payload['need_hypothesis'])
    with database.connect(path) as db:db.execute("UPDATE knowledge_items SET review_status='rejected' WHERE id='k'")
    changed=c.get('/api/reports/'+DEMO_ID).json();self.assertTrue(changed['basis_changed']);self.assertTrue(changed['warning']);self.assertEqual(changed['sources'][0]['review_status'],'rejected')
    text=c.get('/api/reports/'+DEMO_ID+'/markdown').text;self.assertIn('依据已变化，需要重新核对',text);self.assertIn('当前审核：已拒绝',text)
    with database.connect(path) as db:db.execute("DELETE FROM knowledge_items WHERE id='k'")
    self.assertEqual(c.get('/api/reports/'+DEMO_ID).json()['sources'][0]['review_status'],'missing')
