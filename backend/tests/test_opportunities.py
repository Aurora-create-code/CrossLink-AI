import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import database
from app.main import create_app
from app.config import Settings
from app.adapters.thingo import ThingoAdapter,ModelResponse
from app.knowledge import DOCUMENT_ID
from app.opportunities import validate


def candidate(ids):
 return {'title':'孔隙结构对比实验','need_hypothesis':'假设需要比较材料结构对功能的影响','knowledge_connection':'根据已有知识提出结构与性能连接的推理','proposed_solution':'设计两种孔隙结构对照并保持材料一致','potential_value':'假设可以筛选更适合后续验证的结构','validation_plan':'制备两组相同尺寸样品，以显微图像和渗透实验比较孔隙大小与通量','unverified_assumptions':['结构差异会影响功能，尚未验证'],'knowledge_ids':ids}

class OpportunityTests(unittest.TestCase):
 def test_wrong_output_and_forged_references(self):
  good={'candidates':[candidate(['yes'])],'insufficiency':'仅一个依据适合小范围探索'}
  self.assertEqual(len(validate(json.dumps(good),{'yes'}).candidates),1)
  variants=['bad',json.dumps({**good,'candidates':[candidate(['no'])]}),json.dumps({**good,'candidates':[candidate(['yes','yes'])]}),json.dumps({'candidates':[],'insufficiency':''}),json.dumps({**good,'candidates':[candidate(['yes'])]*4}),'{"candidates":[],"candidates":[],"insufficiency":"x"}']
  for text in variants:
   with self.subTest(text=text),self.assertRaises(ValueError):validate(text,{'yes'})

 def test_confirmed_snapshot_idempotency_changes_and_restart(self):
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'app.sqlite3';database.initialize(path)
   with database.connect(path) as db:
    db.execute('INSERT INTO documents(id,filename,media_type,content_sha256,storage_path) VALUES (?,?,?,?,?)',(DOCUMENT_ID,'test.pdf','application/pdf','hash','test.pdf'))
    db.execute('INSERT INTO document_pages VALUES (?,1,?,1)',(DOCUMENT_ID,'A real source quotation.'))
    db.execute("INSERT INTO extraction_batches(id,document_id,fingerprint,model,status) VALUES ('b',?,'test','gpt-6.1-sol','completed')",(DOCUMENT_ID,))
    for key,status in [('yes','confirmed'),('no','rejected'),('wait','pending')]:
     db.execute("INSERT INTO knowledge_items(id,batch_id,document_id,page_number,content,quote,model,extraction_status,review_status) VALUES (?,'b',?,1,?,?,?,'source_verified',?)",(key,DOCUMENT_ID,'Factual source content '+key,'A real source quotation.','gpt-6.1-sol',status))
   calls=[]
   async def generate(self,request):
    data=json.loads(request.context);self_test.assertEqual([k['id'] for k in data],['yes']);calls.append(1)
    return ModelResponse(json.dumps({'candidates':[candidate(['yes'])],'insufficiency':'仅有一个依据，不强凑3条'}),usage={'total_tokens':20},model='gpt-6.1-sol',finish_reason='stop')
   self_test=self
   with patch.object(ThingoAdapter,'configuration_status',return_value={'missing_fields':[],'protocol_implemented':True}),patch.object(ThingoAdapter,'generate',generate):
    with TestClient(create_app(Settings(database_path=path))) as c:
     self.assertEqual(c.post('/api/opportunities/generate').status_code,200)
     self.assertTrue(c.post('/api/opportunities/generate').json()['duplicate']);self.assertEqual(len(calls),1)
     item=c.get('/api/opportunities').json()['items'][0];self.assertFalse(item['basis_changed']);self.assertEqual(item['sources'][0]['snapshot_review_status'],'confirmed')
     c.patch('/api/knowledge/yes/review',json={'status':'rejected'})
     item=c.get('/api/opportunities').json()['items'][0];self.assertTrue(item['basis_changed']);self.assertEqual(item['sources'][0]['review_status'],'rejected')
     self.assertEqual(c.post('/api/opportunities/generate').status_code,422);self.assertEqual(len(calls),1)
    with TestClient(create_app(Settings(database_path=path))) as c:
     self.assertTrue(c.get('/api/opportunities').json()['items'][0]['basis_changed'])

 def test_failed_reference_persists_usage_and_reuses_failure(self):
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'app.sqlite3';database.initialize(path)
   with database.connect(path) as db:
    db.execute('INSERT INTO documents(id,filename,media_type,content_sha256,storage_path) VALUES (?,?,?,?,?)',(DOCUMENT_ID,'test.pdf','application/pdf','hash','test.pdf'))
    db.execute('INSERT INTO document_pages VALUES (?,1,?,1)',(DOCUMENT_ID,'A real source quotation.'))
    db.execute("INSERT INTO extraction_batches(id,document_id,fingerprint,model,status) VALUES ('b',?,'test','gpt-6.1-sol','completed')",(DOCUMENT_ID,))
    db.execute("INSERT INTO knowledge_items(id,batch_id,document_id,page_number,content,quote,model,extraction_status,review_status) VALUES ('yes','b',?,1,'content','A real source quotation.','gpt-6.1-sol','source_verified','confirmed')",(DOCUMENT_ID,))
   calls=[]
   async def generate(self,request):
    calls.append(1)
    return ModelResponse(json.dumps({'candidates':[candidate(['forged'])],'insufficiency':'少量依据'}),usage={'total_tokens':10},model='gpt-6.1-sol',finish_reason='stop')
   with patch.object(ThingoAdapter,'configuration_status',return_value={'missing_fields':[],'protocol_implemented':True}),patch.object(ThingoAdapter,'generate',generate),TestClient(create_app(Settings(database_path=path))) as c:
    self.assertEqual(c.post('/api/opportunities/generate').status_code,502)
    data=c.get('/api/opportunities').json();self.assertEqual(data['items'],[]);self.assertIn('10',data['batches'][0]['usage_json']);self.assertEqual(data['batches'][0]['status'],'failed')
    self.assertTrue(c.post('/api/opportunities/generate').json()['duplicate']);self.assertEqual(len(calls),1)
