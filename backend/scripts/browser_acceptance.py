"""Drive installed Edge via CDP; no additional browser dependencies."""
import base64
import json
from pathlib import Path
import time
import httpx
import websocket

ROOT=Path(__file__).resolve().parents[2]
SAMPLE=r'D:\codex\2026-11-19\referenced-chatgpt-conversation-this-is-an-3\outputs\MIT_Biomaterials_Lecture_1.pdf'
http=httpx.Client(trust_env=False,timeout=15)
target=http.put('http://127.0.0.1:9223/json/new?about:blank').json()
ws=websocket.create_connection(target['webSocketDebuggerUrl'],origin='http://localhost:9223',timeout=20)
seq=0
errors=[]
def call(method,params=None):
 global seq
 seq+=1; current=seq;ws.send(json.dumps({'id':current,'method':method,'params':params or {}}))
 while True:
  result=json.loads(ws.recv())
  if result.get('method')=='Runtime.exceptionThrown':errors.append(result['params'])
  if result.get('id')==current:
   if 'error' in result:raise RuntimeError(result['error'])
   return result.get('result',{})
def js(expression):
 result=call('Runtime.evaluate',{'expression':expression,'returnByValue':True,'awaitPromise':True,'userGesture':True})
 if result.get('exceptionDetails'):raise RuntimeError(result)
 return result.get('result',{}).get('value')
def wait(expression):
 deadline=time.monotonic()+25
 while time.monotonic()<deadline:
  if js(expression):return
  time.sleep(.2)
 raise AssertionError('Browser wait failed: '+expression)
try:
 call('Page.enable');call('Runtime.enable');call('Emulation.setDeviceMetricsOverride',{'width':1440,'height':1100,'deviceScaleFactor':1,'mobile':False})
 call('Page.navigate',{'url':'http://127.0.0.1:5173/'})
 wait("!!document.querySelector('#document-file') && !!document.querySelector('.page-text pre')")
 call('DOM.getDocument');node=call('DOM.querySelector',{'nodeId':call('DOM.getDocument')['root']['nodeId'],'selector':'#document-file'})['nodeId']
 call('DOM.setFileInputFiles',{'nodeId':node,'files':[SAMPLE]})
 wait("!document.querySelector('.document-upload button[type=submit]').disabled")
 js("document.querySelector('.document-upload button[type=submit]').click()")
 wait("document.querySelector('.document-notice')?.textContent.includes('复用')")
 assert js("document.querySelectorAll('.document-item').length")==1
 evidence={'browser':'Installed Microsoft Edge via CDP','real_file_selected':True,'web_upload_duplicate_notice':js("document.querySelector('.document-notice').textContent"),'pages':[]}
 for n,phrase in [(1,'Intro. to Biomaterials'),(5,'LENGTH SCALES OF STRUCTURE'),(10,'Porosity')]:
  js(f"document.querySelector('#document-page').value='{n}';document.querySelector('#document-page').dispatchEvent(new Event('change',{{bubbles:true}}))")
  wait(f"document.querySelector('.page-text pre')?.textContent.includes({json.dumps(phrase)})")
  link=js("document.querySelector('.original-link').href");assert link.endswith('#page='+str(n))
  evidence['pages'].append({'page':n,'text_excerpt':js("document.querySelector('.page-text pre').textContent.slice(0,350)"),'original_link':link})
 call('Page.reload')
 wait("document.querySelector('#document-page')?.value==='10' && document.querySelector('.page-text pre')?.textContent.includes('Porosity')")
 evidence['refresh_preserved_page']=10
 js("document.querySelector('.document-library').scrollIntoView()")
 shot=call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})
 (ROOT/'acceptance'/'browser-library.png').write_bytes(base64.b64decode(shot['data']))
 # Clicking the actual original link must create a target with the chosen page fragment.
 js("document.querySelector('.original-link').click()")
 time.sleep(.6)
 targets=http.get('http://127.0.0.1:9223/json').json()
 evidence['original_clicked_target']=next((t['url'] for t in targets if '/original#page=10' in t['url']),None)
 assert evidence['original_clicked_target']
 evidence['runtime_errors']=errors
 assert not errors
 (ROOT/'acceptance'/'browser.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(evidence,ensure_ascii=True,indent=2))
finally:
 ws.close()
