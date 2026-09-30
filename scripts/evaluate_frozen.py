"""Evaluator-only fifteen frozen synthetic cases; never imported by runtime."""
import copy,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from rfq_review.extraction import extract_offer,validate_model_proposal
from rfq_review.calculation import calculate_offer,compare_offers,packet_fingerprint
def main():
 goldpath=ROOT/"evaluations/gold_v1.json";corpuspath=ROOT/"data/offers.json"
 manifest=json.loads((ROOT/"evaluations/freeze_manifest.json").read_text())
 for path,key in ((goldpath,"gold_sha256"),(corpuspath,"corpus_sha256")):
  if hashlib.sha256(path.read_bytes()).hexdigest()!=manifest[key]:raise RuntimeError("frozen_input_changed")
 gold=json.loads(goldpath.read_text());corpus=json.loads(corpuspath.read_text())
 offers={o["supplier_id"]:o for o in corpus["offers"]};ex={k:extract_offer(v) for k,v in offers.items()};scenario=corpus["rfqs"][0]["default_scenario"]
 outcomes=[]
 for case in gold["cases"]:
  kind=case["kind"];actual={}
  if kind in ("cost","lead_time"):
   terms=ex[case["supplier"]]["terms"]|case.get("terms_override",{})
   selected=scenario|{"demand_qty_each":case["demand"]}|case.get("scenario_override",{})
   actual=calculate_offer(terms,selected)
   if "exclusion_contains" in case["expected"]:actual["exclusion_contains"]=case["expected"]["exclusion_contains"] if case["expected"]["exclusion_contains"] in actual["excluded_reasons"] else None
  elif kind=="scenario":
   r=compare_offers(list(ex.values()),scenario|{"demand_qty_each":case["demand"]})
   by={row["supplier_id"]:row for row in r["rows"]}
   actual={"A":by["A"]["comparison_cost_krw"],"B":by["B"]["comparison_cost_krw"],"C":by["C"]["comparison_cost_krw"],"C_goods":by["C"]["goods_cost_krw"],"cost_order":r["cost_order"],"completeness":r["completeness"]}
  elif kind=="source_validation":
   supplier=case["supplier"];obs=ex[supplier];proposal={"fields":{name:{"raw_value":cell["raw_value"],"quote":cell["quote"]} for name,cell in obs["fields"].items()}}
   proposal["fields"][case["field"]]={"raw_value":case["proposal_raw"],"quote":case["proposal_quote"]}
   try:validate_model_proposal(offers[supplier],proposal);actual["valid"]=True
   except ValueError:actual["valid"]=False
  elif kind=="stale":
   base=packet_fingerprint(list(ex.values()),scenario);changed=[]
   for dimension in case["dimensions"]:
    selected=copy.deepcopy(list(ex.values()));s=copy.deepcopy(scenario);version=None
    if dimension=="source_hash":selected[0]["provenance"]["source_hash"]="changed"
    elif dimension=="terms":selected[0]["terms"]["price_amount_krw"]+=1
    elif dimension=="demand_qty_each":s["demand_qty_each"]=30
    elif dimension=="scenario_order_date":s["scenario_order_date"]="2026-10-02"
    elif dimension=="rule_version":version="commercial-v2"
    changed.append(packet_fingerprint(selected,s,version)!=base)
   actual["every_changed_dimension_invalidates_review"]=all(changed)
  expected=case["expected"];passed=all(actual.get(key)==value for key,value in expected.items())
  outcomes.append({"id":case["id"],"kind":kind,"expected":expected,"actual":actual,"passed":passed})
 result={"synthetic":True,"expert_validated":False,"scope":"15 predeclared development cases; not independent real-industry benchmark","model_requests":0,"passed":sum(x["passed"] for x in outcomes),"total":len(outcomes),"cases":outcomes}
 (ROOT/"artifacts").mkdir(parents=True,exist_ok=True);(ROOT/"artifacts/frozen-gold-result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))
 print(json.dumps({k:v for k,v in result.items() if k!="cases"},ensure_ascii=False))
 return 0 if result["passed"]==result["total"] else 1
if __name__=="__main__":raise SystemExit(main())
