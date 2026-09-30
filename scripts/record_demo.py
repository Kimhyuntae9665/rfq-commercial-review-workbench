import pathlib,sys,json,urllib.request,base64,time,subprocess
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from browser_check import Browser
def main():
 cdp='http://127.0.0.1:19085'
 request=urllib.request.Request(cdp+'/json/new?about:blank',method='PUT')
 page=json.load(urllib.request.urlopen(request,timeout=10))
 b=Browser(page['webSocketDebuggerUrl'])
 out=ROOT/'artifacts/model-demo';out.mkdir(parents=True,exist_ok=True)
 frames=[];started=time.monotonic()
 def shot(name):
  data=b.call('Page.captureScreenshot',format='png')['data'];(out/name).write_bytes(base64.b64decode(data))
 def frame(count=2):
  for _ in range(count):
   n='frame-%03d.jpg'%len(frames);t=time.monotonic()-started
   data=b.call('Page.captureScreenshot',format='jpeg',quality=85)['data']
   (out/n).write_bytes(base64.b64decode(data));frames.append({'file':n,'elapsed_s':t});time.sleep(.25)
 try:
  b.call('Page.enable');b.call('Runtime.enable')
  b.call('Emulation.setDeviceMetricsOverride',width=1440,height=1000,deviceScaleFactor=1,mobile=False)
  b.call('Page.navigate',url='http://127.0.0.1:19083')
  b.until("typeof state!==\'undefined\'&&state.offers.length===3&&!state.busy")
  b.js("document.querySelector('#profile').value='reviewer';document.querySelector('#profile').dispatchEvent(new Event('change'))")
  b.until("state.principal?.role==='reviewer'&&!state.busy")
  assert b.js("state.proposals.every(p=>p.model_state==='source_verified')")
  shot('08-actual-model-proposals.png');frame(3)
  for i,offer in enumerate(('OFFER-A','OFFER-B','OFFER-C')):
   b.js("document.querySelector('[data-evidence=\\\""+offer+"\\\"]').click()")
   b.until("document.querySelector('#evidence-dialog').open&&!state.busy")
   if i==0:
    b.js("document.querySelector('[data-field=price_amount_krw]').click()")
    shot('09-actual-model-source.png')
   frame(3)
   b.js("document.querySelector('#terms-ack').checked=true;document.querySelector('#terms-ack').dispatchEvent(new Event('change'));document.querySelector('#confirm-form').requestSubmit()")
   b.until("!document.querySelector('#evidence-dialog').open&&!state.busy")
   frame(1)
  b.js("document.querySelector('#demand').value='12';document.querySelector('#demand').dispatchEvent(new Event('input'));document.querySelector('#scenario-form').requestSubmit()")
  b.until("state.packet?.scenario?.demand_qty_each===12&&!state.busy")
  assert b.js("JSON.stringify(state.packet.cost_order)==='[\\\"B\\\",\\\"A\\\"]'")
  shot('10-actual-model-demand12.png');frame(4)
  b.js("document.querySelector('[data-qty=\\\"30\\\"]').click();document.querySelector('#scenario-form').requestSubmit()")
  b.until("state.packet?.scenario?.demand_qty_each===30&&!state.busy")
  shot('11-actual-model-demand30.png');frame(4)
  b.js("document.querySelector('#packet-ack').checked=true;document.querySelector('#packet-ack').dispatchEvent(new Event('change'));document.querySelector('#review-comment').value='합성 시나리오: 비교가능2/3와 운임 미확정 확인';document.querySelector('#review-form').requestSubmit()")
  b.until("state.packet?.review&&!state.busy")
  shot('12-actual-model-reviewed.png');frame(4)
  (out/'frames.json').write_text(json.dumps({'capture':'native browser JPEG viewport frames','model_requests_during_recording':0,'source':'stored actual API model proposals','frames':frames},indent=2))
  lines=[]
  for i,f in enumerate(frames):
   duration=(frames[i+1]['elapsed_s']-f['elapsed_s']) if i+1<len(frames) else .25
   lines+=["file '"+f['file']+"'","duration %.6f"%duration]
  lines+=["file '"+frames[-1]['file']+"'"]
  (out/'frames.ffconcat').write_text('ffconcat version 1.0\n'+'\n'.join(lines)+'\n')
  subprocess.run(['ffmpeg','-y','-v','error','-safe','0','-f','concat','-i',str(out/'frames.ffconcat'),'-vf','fps=30,format=yuv420p','-c:v','libx264','-preset','veryfast','-crf','23','-movflags','+faststart',str(out/'workflow.mp4')],check=True)
  print(json.dumps({'frames':len(frames),'elapsed_s':round(time.monotonic()-started,2),'model_requests_during_capture':0,'synthetic_demo_confirmation':True}))
 finally:
  urllib.request.urlopen(cdp+'/json/close/'+page['id'],timeout=10).read()
if __name__=='__main__':main()
