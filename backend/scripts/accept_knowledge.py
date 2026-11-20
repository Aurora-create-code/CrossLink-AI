"""Real sample acceptance; explicit run only. Reuses deterministic saved batches."""
import json
from pathlib import Path
import httpx

root=Path(__file__).resolve().parents[2]
with httpx.Client(base_url='http://127.0.0.1:8000',trust_env=False,timeout=300) as client:
    response=client.post('/api/knowledge/extract')
    result={'http_status':response.status_code,'response':response.json()}
    detail=client.get('/api/knowledge').json()
    result['knowledge']=detail
    if response.status_code==200 and response.json()['batch']['status']=='completed':
        pages=client.get('/api/documents/859cc211586147da8d4a64d881271c88').json()['pages']
        source={p['page_number']:p['text'] for p in pages}
        counts={str(n):0 for n in (1,5,10)}
        for item in detail['items']:
            assert item['quote'] in source[item['page_number']]
            assert item['review_status']=='pending'
            counts[str(item['page_number'])]+=1
        assert all(1<=n<=5 for n in counts.values())
        duplicate=client.post('/api/knowledge/extract').json()
        assert duplicate['duplicate'] and duplicate['batch']['id']==response.json()['batch']['id']
        result['page_counts']=counts;result['duplicate_reused']=True
    out=root/'acceptance/knowledge-real.json'
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True,indent=2))
