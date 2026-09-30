import pathlib,json,urllib.request,time
ROOT=pathlib.Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:19083'
def call(path,body=None,token=None):
 headers={'Content-Type':'application/json'}
 if token:headers['Authorization']='Bearer '+token
 request=urllib.request.Request(BASE+path,data=None if body is None else json.dumps(body).encode(),headers=headers)
 with urllib.request.urlopen(request,timeout=75) as r:return json.load(r)
def main():
 token=call('/api/session',{'profile':'reviewer'})['token']
 result={'api_integration':True,'synthetic':True,'model_requests':0,'cases':[]}
 out=ROOT/'artifacts/live-api.json'
 for offer in ('OFFER-A','OFFER-B','OFFER-C'):
  proposal=call('/api/offers/'+offer+'/extract',{'mode':'model'},token)['proposal']
  result['model_requests']+=1
  result['cases'].append({'offer_id':offer,'model_state':proposal['model_state'],'metrics':proposal['metrics'],'proposal_id':proposal['id']})
  out.write_text(json.dumps(result,ensure_ascii=False,indent=2))
  print(json.dumps(result['cases'][-1],ensure_ascii=False),flush=True)
  if proposal['model_state']!='source_verified':break
 result['http200_is_success']=False
 out.write_text(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
