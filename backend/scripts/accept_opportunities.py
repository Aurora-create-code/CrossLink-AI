"""One explicit real generation; deterministic duplicate acceptance is non-generating."""
import json
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[2]
with httpx.Client(base_url='http://127.0.0.1:8000',trust_env=False,timeout=150) as c:
 baseline=json.loads((ROOT/'acceptance/stage4-review-baseline.json').read_text(encoding='utf-8'))
 knowledge=c.get('/api/knowledge').json()['items']
 assert sorted([[k['id'],k['review_status']] for k in knowledge])==baseline['items']
 response=c.post('/api/opportunities/generate')
 result={'http_status':response.status_code,'response':response.json(),'opportunities':c.get('/api/opportunities').json()}
 if response.status_code==200 and response.json()['batch']['status']=='completed':
  allowed={k['id'] for k in knowledge if k['review_status']=='confirmed'}
  for item in result['opportunities']['items']:
   assert set(item['knowledge_ids'])<=allowed
   assert not item['basis_changed']
  duplicate=c.post('/api/opportunities/generate').json()
  assert duplicate['duplicate'] and duplicate['batch']['id']==response.json()['batch']['id']
  result['duplicate_reused']=True
 (ROOT/'acceptance/opportunities-real.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(result,ensure_ascii=True,indent=2))
