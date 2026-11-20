import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from app import database
from app.main import create_app
from app.config import Settings
from app.adapters.thingo import ThingoAdapter,ModelRequest,ModelResponse,ThingoCallError
from app.knowledge import validate_output,source_quote,DOCUMENT_ID

HASH='0b85c2f2140883b4da98e3a84c1bf46a906827b211736799dc25a7b1f92f8526'
SOURCE='A biomaterial is a nonliving material.\n It interacts with biological systems.'

class KnowledgeTests(unittest.TestCase):
    def test_whitespace_match_preserves_real_text(self):
        self.assertEqual(source_quote(SOURCE,'material. It interacts'), 'material.\n It interacts')
        for quote in ['material. It invents','biomaterial is X material','a']:
            with self.assertRaises(ValueError):source_quote(SOURCE,quote)

    def test_output_validation(self):
        good={'items':[{'content':'Biomaterials interact with biology','quote':'It interacts with biological systems.','page_number':1}]}
        self.assertEqual(len(validate_output(json.dumps(good),1,SOURCE)),1)
        variants=['not json',json.dumps({'items':[]}),json.dumps({'items':good['items']*6}),json.dumps({'items':[{**good['items'][0],'page_number':5}]}),json.dumps({'items':[{**good['items'][0],'quote':'An invented quotation.'}]}),json.dumps({'items':good['items']*2}),'{"items":[],"items":[]}']
        for value in variants:
            with self.subTest(value=value),self.assertRaises(ValueError):validate_output(value,1,SOURCE)

    def test_adapter_error_and_truncation_no_retry(self):
        config=Settings(thingo_endpoint='https://intlapi.thingo.com.cn/v1/chat/completions',thingo_model='gpt-6.1-sol',thingo_api_key='test-secret',thingo_protocol='thingo_intl_chat_completions_v1')
        for mode in ('timeout','http','json','truncated','good'):
            calls=[]
            def handler(request):
                calls.append(1)
                payload=json.loads(request.content);self.assertEqual(payload['max_tokens'],1600);self.assertNotIn('response_format',payload)
                if mode=='timeout':raise httpx.ReadTimeout('test-secret')
                if mode=='http':return httpx.Response(403,text='test-secret')
                if mode=='json':return httpx.Response(200,text='test-secret')
                return httpx.Response(200,json={'model':'gpt-6.1-sol','choices':[{'message':{'content':'{}'},'finish_reason':'length' if mode=='truncated' else 'stop'}],'usage':{'total_tokens':10}})
            adapter=ThingoAdapter(config,httpx.MockTransport(handler))
            if mode=='good':self.assertEqual(asyncio.run(adapter.generate(ModelRequest('short','public'))).text,'{}')
            else:
                with self.assertRaises(ThingoCallError) as raised:asyncio.run(adapter.generate(ModelRequest('short','public')))
                self.assertNotIn('test-secret',str(raised.exception))
            self.assertEqual(len(calls),1)

    def test_batch_idempotency_review_persistence_and_rollback(self):
        for bad in (False,True):
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'app.sqlite3';database.initialize(path)
                with database.connect(path) as db:
                    db.execute('INSERT INTO documents(id,filename,media_type,content_sha256,storage_path) VALUES (?,?,?,?,?)',(DOCUMENT_ID,'test.pdf','application/pdf',HASH,'test.pdf'))
                    for n in (1,5,10):db.execute('INSERT INTO document_pages VALUES (?,?,?,1)',(DOCUMENT_ID,n,SOURCE))
                calls=[]
                async def generate(self,request):
                    number=(1,5,10)[len(calls)];calls.append(number)
                    return ModelResponse(json.dumps({'items':[{'content':'A factual point','quote':'Forged quotation does not exist' if bad and number==5 else 'It interacts with biological systems.','page_number':number}]}),usage={'total_tokens':5},model='gpt-6.1-sol',finish_reason='stop')
                with patch.object(ThingoAdapter,'configuration_status',return_value={'missing_fields':[],'protocol_implemented':True}),patch.object(ThingoAdapter,'generate',generate):
                    with TestClient(create_app(Settings(database_path=path))) as client:
                        response=client.post('/api/knowledge/extract');self.assertEqual(response.status_code,502 if bad else 200)
                        data=client.get('/api/knowledge').json();self.assertEqual(len(data['items']),0 if bad else 3)
                        count=len(calls)
                        duplicate=client.post('/api/knowledge/extract').json();self.assertTrue(duplicate['duplicate']);self.assertEqual(len(calls),count)
                        if not bad:
                            item=data['items'][0];self.assertEqual(item['review_status'],'pending')
                            self.assertEqual(client.patch('/api/knowledge/'+item['id']+'/review',json={'status':'confirmed'}).json()['item']['review_status'],'confirmed')
                            self.assertEqual(client.patch('/api/knowledge/'+item['id']+'/review',json={'status':'bad'}).status_code,422)
                    with TestClient(create_app(Settings(database_path=path))) as restarted:
                        data=restarted.get('/api/knowledge').json();self.assertEqual(len(data['items']),0 if bad else 3)
                        if not bad:self.assertTrue(any(i['review_status']=='confirmed' for i in data['items']))
