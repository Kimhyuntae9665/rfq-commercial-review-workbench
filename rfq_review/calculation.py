"""Exact limited pre-tax goods-plus-freight scenarios. No model/vendor selection."""
import datetime,hashlib,json,re
from fractions import Fraction
from .extraction import FIELDS
RULE_VERSION="commercial-v1"
SCOPE="explicit_tax_excluded_goods_plus_freight_only"
def _date(value,name,optional=False):
 if optional and value is None:return None
 if not isinstance(value,str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}",value):raise ValueError("invalid_"+name)
 try:return datetime.date.fromisoformat(value)
 except ValueError:raise ValueError("invalid_"+name) from None
def normalize_scenario(scenario):
 if not isinstance(scenario,dict) or set(scenario)!={"demand_qty_each","scenario_order_date","required_by_date"}:raise ValueError("invalid_scenario_schema")
 demand=scenario["demand_qty_each"]
 if not isinstance(demand,int) or isinstance(demand,bool) or not 1<=demand<=10**12:raise ValueError("invalid_demand_qty")
 order=_date(scenario["scenario_order_date"],"scenario_order_date")
 required=_date(scenario["required_by_date"],"required_by_date",True)
 return {"demand_qty_each":demand,"scenario_order_date":order.isoformat(),"required_by_date":required.isoformat() if required else None}
def _integer(value,positive=True):
 return isinstance(value,int) and not isinstance(value,bool) and (0<value<=10**30 if positive else 0<=value<=10**30)
def calculate_offer(terms,scenario,source_errors=None):
 scenario=normalize_scenario(scenario)
 if not isinstance(terms,dict) or set(terms)!=set(FIELDS):raise ValueError("invalid_terms_schema")
 for field,value in terms.items():
  if field in ("price_amount_krw","price_basis_each","units_per_order_unit","moq","order_multiple","freight_amount_krw"):
   if value is not None and (not isinstance(value,int) or isinstance(value,bool)):raise ValueError("invalid_terms_type")
  elif value is not None and not isinstance(value,str):raise ValueError("invalid_terms_type")
 errors=[]
 source_errors=[] if source_errors is None else source_errors
 if not isinstance(source_errors,list) or any(not isinstance(error,str) for error in source_errors):raise ValueError("invalid_source_errors")
 cost_source_errors=[error for error in source_errors if error.rsplit(":",1)[-1] not in ("lead_time_type","delivery_date","lead_time_condition")]
 errors.extend("source_extraction_unresolved:"+error for error in cost_source_errors)
 freight_source_unresolved=any(error.rsplit(":",1)[-1] in ("freight_amount_krw","freight_status") for error in cost_source_errors)
 orderunits=delivered=surplus=goods=goods_exact=freight=total=None
 for field in ("price_amount_krw","price_basis_each","units_per_order_unit","moq","order_multiple"):
  if not _integer(terms[field]):errors.append("invalid_"+field)
 unit=terms["order_unit"]
 if unit not in ("each","pack"):errors.append("unsupported_order_unit")
 if terms["moq_unit"]!=unit or unit not in ("each","pack"):errors.append("ambiguous_moq_unit")
 if terms["order_multiple_unit"]!=unit or unit not in ("each","pack"):errors.append("ambiguous_order_multiple_unit")
 if unit=="each" and terms["units_per_order_unit"]!=1:errors.append("inconsistent_each_pack_size")
 if terms["currency"]!="KRW":errors.append("unsupported_currency")
 if terms["tax_status"]!="tax_excluded":errors.append("tax_not_explicitly_excluded")
 if terms["other_mandatory_charge_status"]!="none_explicit":errors.append("other_mandatory_charge_unresolved")
 try:valid_until=_date(terms["valid_until"],"valid_until")
 except ValueError:valid_until=None;errors.append("invalid_valid_until")
 orderdate=_date(scenario["scenario_order_date"],"scenario_order_date")
 if valid_until and orderdate>valid_until:errors.append("expired_price")
 qtyerrors={"invalid_units_per_order_unit","invalid_moq","invalid_order_multiple","unsupported_order_unit","ambiguous_moq_unit","ambiguous_order_multiple_unit","inconsistent_each_pack_size"}
 if not qtyerrors.intersection(errors):
  size=terms["units_per_order_unit"];multiple=terms["order_multiple"]
  requiredunits=(scenario["demand_qty_each"]+size-1)//size
  base=max(requiredunits,terms["moq"]);orderunits=((base+multiple-1)//multiple)*multiple
  delivered=orderunits*size;surplus=delivered-scenario["demand_qty_each"]
 if delivered is not None and _integer(terms["price_amount_krw"]) and _integer(terms["price_basis_each"]) and terms["currency"]=="KRW":
  fraction=Fraction(delivered*terms["price_amount_krw"],terms["price_basis_each"])
  goods_exact=str(fraction)
  if fraction.denominator!=1:errors.append("unsupported_precision")
  else:goods=fraction.numerator
 status=terms["freight_status"]
 if freight_source_unresolved:errors.append("freight_source_unresolved")
 elif status=="included":
  if terms["freight_amount_krw"] not in (None,0) or isinstance(terms["freight_amount_krw"],bool):errors.append("conflicting_included_freight")
  else:freight=0
 elif status=="fixed_per_order":
  if _integer(terms["freight_amount_krw"],False):freight=terms["freight_amount_krw"]
  else:errors.append("invalid_freight_amount_krw")
 elif status=="unknown":errors.append("freight_unknown")
 else:errors.append("unsupported_freight_status")
 delivery=None;condition=terms["lead_time_condition"];delivery_state="unresolved"
 if terms["lead_time_type"]=="absolute_date":
  try:delivery=_date(terms["delivery_date"],"delivery_date")
  except ValueError:delivery_state="invalid_absolute_date"
  else:
   if delivery<orderdate:delivery_state="before_order_date"
   elif scenario["required_by_date"] is None:delivery_state="absolute_date_no_required_date"
   else:delivery_state="late" if delivery>_date(scenario["required_by_date"],"required_by_date") else "on_time"
 elif terms["lead_time_type"]=="conditional":delivery_state="conditional_no_eta"
 elif terms["lead_time_type"] is None:delivery_state="unknown_no_eta"
 else:delivery_state="unsupported_no_eta"
 if not errors and goods is not None and freight is not None:total=goods+freight
 exact_values={name:str(value) if value is not None else None for name,value in (("order_qty_units",orderunits),("delivered_qty_each",delivered),("surplus_qty_each",surplus),("goods_cost_krw",goods),("freight_cost_krw",freight),("comparison_cost_krw",total))}
 return {"exact_values":exact_values,"order_qty_units":orderunits,"delivered_qty_each":delivered,"surplus_qty_each":surplus,"goods_cost_krw":goods,"goods_cost_exact":goods_exact,"freight_cost_krw":freight,"comparison_cost_krw":total,"comparable":total is not None,"excluded_reasons":list(dict.fromkeys(errors)),"delivery_state":delivery_state,"delivery_date":delivery.isoformat() if delivery else None,"lead_time_condition":condition,"scope":SCOPE,"rule_version":RULE_VERSION}
def packet_fingerprint(extractions,scenario,rule_version=None):
 payload={"offers":[{"provenance":e["provenance"],"terms":e["terms"]} for e in sorted(extractions,key=lambda e:e["offer_id"])],"scenario":normalize_scenario(scenario),"rule_version":RULE_VERSION if rule_version is None else rule_version}
 return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
def compare_offers(extractions,scenario):
 scenario=normalize_scenario(scenario)
 if not isinstance(extractions,list) or not extractions:raise ValueError("no_offers")
 if len({e["offer_id"] for e in extractions})!=len(extractions):raise ValueError("duplicate_offer")
 rows=[]
 for ex in extractions:
  row=calculate_offer(ex["terms"],scenario,source_errors=ex.get("term_errors",[]))
  row.update(offer_id=ex["offer_id"],supplier_id=ex["provenance"]["supplier_id"],supplier_label=ex["provenance"]["supplier_label"],provenance=ex["provenance"],terms=ex["terms"])
  rows.append(row)
 ordered=sorted((r for r in rows if r["comparable"]),key=lambda r:(r["comparison_cost_krw"],r["supplier_id"]))
 return {"scenario":scenario,"rows":rows,"cost_order":[r["supplier_id"] for r in ordered],"completeness":{"comparable":len(ordered),"total":len(rows)},"scope":SCOPE,"rule_version":RULE_VERSION,"fingerprint":packet_fingerprint(extractions,scenario)}
