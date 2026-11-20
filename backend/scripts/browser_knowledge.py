"""Real browser verification; never starts model generation."""
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
 call('Page.navigate',{'url':'http://127.0.0.1:5173/'})
 wait("document.querySelectorAll('.knowledge-item').length===15")
 assert js("document.querySelectorAll('.document-item').length") == 1
 assert js("document.querySelector('.knowledge-items').textContent.includes('出处')")
 first="document.querySelector('.knowledge-item')"
 for label,state in [('确认','已确认'),('拒绝','已拒绝'),('恢复待审核','待审核')]:
  js(f"Array.from({first}.querySelectorAll('button')).find(b=>b.textContent==='{label}').click()")
  wait(f"{first}.querySelector('.knowledge-review').textContent.includes('当前：{state}')")
 # Keep final state pending, so browser test is not a human endorsement.
 link=js(f"{first}.querySelector('.knowledge-links a').href")
 js(f"{first}.querySelector('.knowledge-links a').click()")
 wait("!!document.querySelector('.page-text pre') && document.querySelector('#document-page')?.value==='1'")
 call('Page.reload');wait("document.querySelectorAll('.knowledge-item').length===15")
 js("document.querySelector('.knowledge-items').scrollIntoView()")
 call('Emulation.setDeviceMetricsOverride',{'width':1440,'height':1100,'deviceScaleFactor':1,'mobile':False})
 shot=call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})
 (ROOT/'acceptance/knowledge-review.png').write_bytes(base64.b64decode(shot['data']))
 evidence={'browser':'Installed Edge/CDP','visible_items':15,'confirm_reject_restore':True,'review_state_after_test':'pending','source_reading_link':link,'refresh_items':15,'runtime_errors':errors}
 assert not errors
 (ROOT/'acceptance/knowledge-browser.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
 print(json.dumps(evidence,ensure_ascii=True))
finally:ws.close()
