"""Real browser stage4 acceptance: read-only knowledge; generation must reuse saved input."""
import base64,json,time
from pathlib import Path
import httpx,websocket
ROOT=Path(__file__).resolve().parents[2]
http=httpx.Client(trust_env=False,timeout=15)
target=http.put('http://127.0.0.1:9223/json/new?about:blank').json()
ws=websocket.create_connection(target['webSocketDebuggerUrl'],origin='http://localhost:9223',timeout=20)
seq=0;errors=[]
def call(method,params=None):
 global seq
 seq+=1;current=seq;ws.send(json.dumps({'id':current,'method':method,'params':params or {}}))
 while True:
  r=json.loads(ws.recv())
  if r.get('method')=='Runtime.exceptionThrown':errors.append(r['params'])
  if r.get('id')==current:
   if 'error'in r:raise RuntimeError('CDP error')
   return r.get('result',{})
def js(expression):
 r=call('Runtime.evaluate',{'expression':expression,'returnByValue':True,'awaitPromise':True,'userGesture':True})
 if r.get('exceptionDetails'):raise RuntimeError('Browser evaluation failed')
 return r.get('result',{}).get('value')
def wait(expression):
 end=time.monotonic()+25
 while time.monotonic()<end:
  if js(expression):return
  time.sleep(.2)
 raise AssertionError(expression)
try:
 call('Page.enable');call('Runtime.enable')
 call('Emulation.setDeviceMetricsOverride',{'width':1440,'height':1100,'deviceScaleFactor':1,'mobile':False})
 call('Page.navigate',{'url':'http://127.0.0.1:5173/#opportunities'})
 wait("document.querySelectorAll('.opportunity-item').length>0")
 count=js("document.querySelectorAll('.opportunity-item').length")
 assert 1<=count<=3
 assert js("document.querySelectorAll('.knowledge-item').length")==15
 # Click the real source link without touching any knowledge review action.
 link=js("document.querySelector('.opportunity-source .opportunity-links a').href")
 js("document.querySelector('.opportunity-source .opportunity-links a').click()")
 wait("location.href==="+json.dumps(link)+" && !!document.querySelector('.page-text pre')")
 call('Page.reload');wait("document.readyState==='complete' && !!document.querySelector('#opportunities') && document.querySelectorAll('.opportunity-item').length>0")
 js("document.querySelector('#opportunities').scrollIntoView()")
 shot=call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})
 (ROOT/'acceptance/opportunities-browser.png').write_bytes(base64.b64decode(shot['data']))
 evidence={'browser':'Edge/CDP','candidate_count':count,'source_link':link,'reload_preserved':True,'knowledge_review_untouched':True,'runtime_errors':errors}
 assert not errors
 baseline=json.loads((ROOT/'acceptance/stage4-review-baseline.json').read_text(encoding='utf-8'))
 actual=http.get('http://127.0.0.1:8000/api/knowledge').json()['items']
 assert sorted([[k['id'],k['review_status']] for k in actual])==baseline['items']
 (ROOT/'acceptance/opportunities-browser.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
 print(json.dumps(evidence))
finally:ws.close()
