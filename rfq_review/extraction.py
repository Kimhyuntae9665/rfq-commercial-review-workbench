"""Whole-cell quote-bound offer extraction. No evaluator/model/calculation access."""
import csv,hashlib,re
FIELDS=("currency","price_amount_krw","price_basis_each","order_unit","units_per_order_unit","moq","moq_unit","order_multiple","order_multiple_unit","freight_status","freight_amount_krw","other_mandatory_charge_status","tax_status","valid_until","lead_time_type","delivery_date","lead_time_condition")
LABELS=("Currency","Price amount KRW","Price basis each","Order unit","Units per order unit","MOQ","MOQ unit","Order multiple","Order multiple unit","Freight status","Freight amount KRW","Other mandatory charge status","Tax status","Valid until","Lead time type","Delivery date","Lead time condition")
NUMBERS=set(("price_amount_krw","price_basis_each","units_per_order_unit","moq","order_multiple","freight_amount_krw"))
def offer_envelope(offer):
 if not isinstance(offer,dict) or not isinstance(offer.get("content"),str) or len(offer["content"].encode())>12000:raise ValueError("invalid_offer_content")
 digest=hashlib.sha256(offer["content"].encode()).hexdigest()
 if digest!=offer.get("source_hash"):raise ValueError("source_hash_mismatch")
 for key in ("id","supplier_id","supplier_label","rfq_id","item_id"):
  if not isinstance(offer.get(key),str) or not 1<=len(offer[key])<=200:raise ValueError("invalid_source_identity")
 revision=offer.get("document_revision")
 if not isinstance(revision,int) or isinstance(revision,bool) or revision<1:raise ValueError("invalid_document_revision")
 if offer.get("format") not in ("kv_text","kv_csv"):raise ValueError("unsupported_source_format")
 return {key:offer[key] for key in ("id","supplier_id","supplier_label","rfq_id","item_id","document_revision","format")}|{"source_hash":digest}
def _rows(offer):
 rows=[];offset=0
 for number,line in enumerate(offer["content"].splitlines(keepends=True),1):
  body=line.rstrip("\r\n");label=None;value=None
  if offer["format"]=="kv_text":
   match=re.fullmatch(r"([^:]+):[ ]?(.*)",body)
   if match:label,value=match.groups()
  else:
   try:items=next(csv.reader([body],strict=True))
   except (csv.Error,StopIteration):raise ValueError("invalid_csv_source")
   if len(items)==2:label,value=items
   elif body:raise ValueError("invalid_csv_source")
  if label is not None:rows.append((label,value,body,number,offset))
  offset+=len(line)
 return rows
def extract_offer(offer):
 envelope=offer_envelope(offer);rows=_rows(offer);content=offer["content"]
 for label,expected in (("RFQ item",envelope["item_id"]),("Supplier",envelope["supplier_id"])):
  matched=[r for r in rows if r[0]==label]
  if len(matched)!=1 or matched[0][1]!=expected:raise ValueError("source_identity_conflict")
 fields={};terms={};errors=[]
 for field,label in zip(FIELDS,LABELS):
  matches=[row for row in rows if row[0]==label]
  if not matches:
   cell={"raw_value":None,"quote":None,"line":None,"span_start":None,"span_end":None,"state":"missing"}
  else:
   _,value,quote,number,offset=matches[0]
   cell={"raw_value":value,"quote":quote,"line":number,"span_start":offset,"span_end":offset+len(quote),"state":"observed"}
   if len(matches)!=1 or content.count(quote)!=1:cell["state"]="ambiguous"
  fields[field]=cell
  if cell["state"]!="observed":
   terms[field]=None;errors.append("source_field_"+cell["state"]+":"+field);continue
  value=cell["raw_value"]
  if field in NUMBERS:
   if value=="" and field=="freight_amount_krw":terms[field]=None
   elif re.fullmatch(r"(?:0|[1-9][0-9]*)",value) and len(value)<=30:terms[field]=int(value)
   else:terms[field]=None;errors.append("invalid_integer:"+field)
  else:terms[field]=value if value!="" else None
 return {"offer_id":envelope["id"],"provenance":envelope,"fields":fields,"terms":terms,"term_errors":errors,"model_state":"not_requested","extraction_state":"deterministic_observed"}
def validate_model_proposal(offer,proposal):
 actual=extract_offer(offer)
 if not isinstance(proposal,dict) or set(proposal)!={"fields"}:raise ValueError("invalid_proposal_schema")
 proposed=proposal["fields"]
 if not isinstance(proposed,dict) or set(proposed)!=set(FIELDS):raise ValueError("required_field_coverage_missing")
 for field in FIELDS:
  value=proposed[field];source=actual["fields"][field]
  if not isinstance(value,dict) or set(value)!={"raw_value","quote"}:raise ValueError("invalid_field_schema")
  if any(value[k] is not None and not isinstance(value[k],str) for k in ("raw_value","quote")):raise ValueError("invalid_field_type")
  if value["raw_value"]!=source["raw_value"]:raise ValueError("unsupported_full_cell_value")
  if value["quote"]!=source["quote"]:raise ValueError("quote_not_full_original_field")
  if source["state"]=="ambiguous":raise ValueError("ambiguous_source_quote")
 actual.update(model_state="source_verified",extraction_state="model_proposal_source_verified")
 return actual
