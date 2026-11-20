"""Real local MIT sample acceptance; no synthetic text enters production storage."""
import hashlib
import json
from pathlib import Path
import sys

import httpx
from pypdf import PdfReader

SAMPLE = Path(r'D:\codex\2026-11-19\referenced-chatgpt-conversation-this-is-an-3\outputs\MIT_Biomaterials_Lecture_1.pdf')
SOURCE = 'https://www.ocw.mit.edu/courses/3-051j-materials-for-biomedical-applications-spring-2006/860c4719a25cc2154e95f27165c8bbbe_lecture1.pdf'
OUT = Path(__file__).resolve().parents[2] / 'acceptance'
BASE = 'http://127.0.0.1:8000'


def run():
    OUT.mkdir(exist_ok=True)
    content = SAMPLE.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    reader = PdfReader(SAMPLE, strict=True)
    expected = [page.extract_text() or '' for page in reader.pages]
    with httpx.Client(base_url=BASE, timeout=90, trust_env=False) as client:
        if '--restart-check' in sys.argv:
            saved = json.loads((OUT/'mit-upload.json').read_text(encoding='utf-8'))
            doc = saved['document']
            details = client.get('/api/documents/'+doc['id']);details.raise_for_status()
            assert details.json() == saved['detail']
            original = client.get('/api/documents/'+doc['id']+'/original');original.raise_for_status()
            assert hashlib.sha256(original.content).hexdigest()==digest
            health=client.get('/api/health');health.raise_for_status()
            result={'restart_persistence_verified':True,'document_id':doc['id'],'original_sha256':digest,'page_count':len(details.json()['pages']),'health':health.json()}
            (OUT/'mit-restart.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(result,ensure_ascii=True));return
        before=client.get('/api/documents').json()['documents']
        with SAMPLE.open('rb') as file:
            upload=client.post('/api/documents',files={'file':(SAMPLE.name,file,'application/pdf')},data={'source_url':SOURCE})
        upload.raise_for_status();doc=upload.json()['document']
        assert doc['content_sha256']==digest and doc['source_url']==SOURCE
        assert doc['page_count']==len(expected)==10
        assert doc['extracted_page_count']==sum(bool(t.strip()) for t in expected)==10
        detail_response=client.get('/api/documents/'+doc['id']);detail_response.raise_for_status();detail=detail_response.json()
        assert [p['text'] for p in detail['pages']]==expected
        original=client.get('/api/documents/'+doc['id']+'/original');original.raise_for_status()
        assert original.content==content
        # An actual Range request used by PDF viewers must be served correctly.
        part=client.get('/api/documents/'+doc['id']+'/original',headers={'Range':'bytes=0-15'})
        assert part.status_code==206 and part.content==content[:16]
        with SAMPLE.open('rb') as file:
            duplicate=client.post('/api/documents',files={'file':('renamed.pdf',file,'application/pdf')},data={'source_url':'https://example.org/other'})
        assert duplicate.status_code==200 and duplicate.json()['duplicate'] and duplicate.json()['document']==doc
        checks=[]
        for filename,data,mime,status in [('fake.pdf',b'not a PDF','application/pdf',422),('broken.pdf',b'%PDF-1.4\nbroken','application/pdf',422),('../escape.pdf',b'%PDF-1.4','application/pdf',400),('wrong.pdf',b'bad','text/plain',415)]:
            r=client.post('/api/documents',files={'file':(filename,data,mime)})
            assert r.status_code==status,(r.status_code,r.text)
            checks.append({'filename':filename,'status':r.status_code,'detail':r.json()['detail']})
        after=client.get('/api/documents').json()['documents']; assert len(after)==len(before)+(0 if upload.json()['duplicate'] else 1)
        samples=[]
        for number in (1,5,10):
            p=detail['pages'][number-1];assert p['page_number']==number
            samples.append({'page_number':number,'characters':len(p['text']),'excerpt':p['text'][:350],'original_page_url':BASE+'/api/documents/'+doc['id']+'/original#page='+str(number)})
        result={'sample_path':str(SAMPLE),'source_url':SOURCE,'sample_sha256':digest,'size_bytes':len(content),'upload_status':upload.status_code,'document':doc,'detail':detail,'page_checks':samples,'original_bytes_identical':True,'range_status':part.status_code,'duplicate_verified':True,'invalid_uploads':checks,'records_before':len(before),'records_after':len(after),'page_text_characters':[len(t) for t in expected]}
        (OUT/'mit-upload.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in result.items() if k!='detail'},ensure_ascii=True,indent=2))


if __name__=='__main__':run()
