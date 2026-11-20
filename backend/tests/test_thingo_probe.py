from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import httpx
from app.adapters.thingo_probe import probe, AUTHORIZATION_ID


class ProbeTests(unittest.TestCase):
    def test_committed_before_send_and_duplicate_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger=Path(folder)/'ledger.sqlite3'
            calls=[]
            def handler(request):
                with closing(sqlite3.connect(ledger)) as db:
                    self.assertEqual(db.execute('SELECT authorization_id FROM attempts').fetchone()[0],AUTHORIZATION_ID)
                payload=json.loads(request.content)
                self.assertEqual(payload['max_tokens'],200)
                self.assertFalse(payload['stream'])
                self.assertEqual(set(payload),{'model','messages','max_tokens','stream'})
                calls.append(1)
                return httpx.Response(200,json={'model':'gpt-6.1-sol','choices':[{'message':{'content':'test-secret example'},'finish_reason':'stop'}],'usage':{'prompt_tokens':3,'completion_tokens':2,'total_tokens':5}})
            result=probe(key='test-secret',excerpt='public text',ledger=ledger,transport=httpx.MockTransport(handler))
            self.assertEqual(result['status'],'text_received')
            self.assertNotIn('test-secret',json.dumps(result))
            with self.assertRaises(RuntimeError):
                probe(key='test-secret',excerpt='public text',ledger=ledger,transport=httpx.MockTransport(handler))
            self.assertEqual(len(calls),1)

    def test_failures_consume_permit_and_hide_errors(self):
        for mode in ('timeout','http','json','empty'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as folder:
                ledger=Path(folder)/'ledger.sqlite3'
                calls=[]
                def handler(request):
                    calls.append(1)
                    if mode=='timeout':raise httpx.ReadTimeout('test-secret',request=request)
                    if mode=='http':return httpx.Response(403,text='test-secret')
                    if mode=='json':return httpx.Response(200,text='test-secret')
                    return httpx.Response(200,json={'choices':[]})
                result=probe(key='test-secret',excerpt='public text',ledger=ledger,transport=httpx.MockTransport(handler))
                self.assertEqual(result['status'],'failed')
                self.assertNotIn('test-secret',json.dumps(result))
                with self.assertRaises(RuntimeError):
                    probe(key='test-secret',excerpt='public text',ledger=ledger,transport=httpx.MockTransport(handler))
                self.assertEqual(len(calls),1)

    def test_invalid_input_does_not_send(self):
        with tempfile.TemporaryDirectory() as folder:
            def handler(request):raise AssertionError('Network must not run')
            for key,text in [('', 'text'),('key','x'*301)]:
                with self.assertRaises(ValueError):
                    probe(key=key,excerpt=text,ledger=Path(folder)/'ledger',transport=httpx.MockTransport(handler))
