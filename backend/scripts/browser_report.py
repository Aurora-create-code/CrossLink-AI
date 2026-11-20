"""Report UI and real browser download; no generating/review requests."""
import base64,json,time
from pathlib import Path
import httpx,websocket
ROOT=Path(__file__).resolve().parents[2]
ID='74d147f4570446e9b6bc75d04493beb7'
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
 downloads=ROOT/'acceptance/report-download';downloads.mkdir(exist_ok=True)
 call('Browser.setDownloadBehavior',{'behavior':'allow','downloadPath':str(downloads.resolve()),'eventsEnabled':True})
 call('Page.navigate',{'url':'http://127.0.0.1:5173/?report='+ID+'#report'})
 wait("!!document.querySelector('a[href*=\"/markdown\"]')")
 assert js("document.body.textContent.includes('可降解塑料')")
 link=js("document.querySelector('a[href*=\"/markdown\"]').href")
 js("document.querySelector('a[href*=\"/markdown\"]').click()")
 file=downloads/('crosslink-report-'+ID+'.md')
 deadline=time.monotonic()+25
 while not file.exists() and time.monotonic()<deadline:time.sleep(.2)
 assert file.exists(),'Browser download did not complete'
 text=file.read_text(encoding='utf-8')
 for phrase in (ID,'4885b036afd04c61989cea7cf9238dc7','gpt-6.1-sol','物理页码：10','实验未执行','PLA'):
  assert phrase in text,phrase
 expected=http.get('http://127.0.0.1:8000/api/reports/'+ID+'/markdown').text
 assert text==expected
 source=js("document.querySelector('#report a[href*=\"?document=\"]').href")
 js("document.querySelector('#report a[href*=\"?document=\"]').click()")
 wait("location.href==="+json.dumps(source)+" && document.querySelector('#document-page')?.value==='10' && !!document.querySelector('.page-text pre')")
 call('Page.navigate',{'url':'http://127.0.0.1:5173/?report='+ID+'#report'})
 wait("!!document.querySelector('#report a[href*=\"/markdown\"]')")
 js("document.querySelector('#report').scrollIntoView()")
 shot=call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})
 (ROOT/'acceptance/report-browser.png').write_bytes(base64.b64decode(shot['data']))
 assert not errors
 result={'browser':'Edge/CDP','report_opened':True,'download_url':link,'download_file':str(file.relative_to(ROOT)),'download_exact_api_match':True,'source_link':source,'source_page':10,'runtime_errors':errors}
 (ROOT/'acceptance/report-browser.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
 print(json.dumps(result))
finally:ws.close()
