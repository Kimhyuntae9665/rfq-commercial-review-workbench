import pathlib,json,time,threading,subprocess,urllib.request
ROOT=pathlib.Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0,str(ROOT))
from rfq_review.llm import extract_offer_with_model,INFERENCE_LOCK
def resources():
    try:
        gpu=subprocess.check_output(['nvidia-smi','--query-gpu=memory.used,utilization.gpu','--format=csv,noheader,nounits'],text=True).strip()
    except Exception:gpu='unavailable'
    mem={}
    for line in pathlib.Path('/proc/meminfo').read_text().splitlines():
        if line.startswith(('MemAvailable:','MemTotal:')):mem[line.split(':')[0]]=int(line.split()[1])
    return {'gpu_used_mib':int(gpu.split(',')[0]) if gpu!='unavailable' else None,'gpu_utilization':gpu.split(',')[-1].strip(),'ram_kib':mem}
def main():
    marker=pathlib.Path(str(INFERENCE_LOCK)+'.blocked')
    if marker.exists():raise SystemExit('shared inference blocked; no request sent')
    offers=json.loads((ROOT/'data/offers.json').read_text())['offers']
    out=ROOT/'artifacts/live-model';out.mkdir(parents=True,exist_ok=True)
    result={'synthetic':True,'gold_exposed':False,'calculation_by_model':False,'cases':[],'before':resources()}
    for offer in offers:
        samples=[];done=threading.Event()
        def sample():
            while not done.is_set():
                samples.append(resources());done.wait(.25)
        t=threading.Thread(target=sample,daemon=True);t.start()
        started=time.monotonic()
        row={'offer_id':offer['id']}
        try:
            extraction=extract_offer_with_model(offer)
            row.update(success=True,metrics=extraction['metrics'],terms=extraction['terms'],field_count=len(extraction['fields']))
        except Exception as error:
            row.update(success=False,error=str(error),elapsed_s=round(time.monotonic()-started,3))
        finally:done.set();t.join(2)
        row['peak_gpu_used_mib']=max((x['gpu_used_mib'] or 0 for x in samples),default=0)
        row['resource_samples']=samples
        result['cases'].append(row)
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        print(json.dumps({k:v for k,v in row.items() if k not in ('terms','resource_samples')},ensure_ascii=False),flush=True)
        if not row['success']:break
    result['after']=resources()
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
