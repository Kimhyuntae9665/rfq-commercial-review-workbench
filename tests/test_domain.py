import copy,hashlib,json,unittest
from pathlib import Path
from rfq_review.extraction import extract_offer,validate_model_proposal
from rfq_review.calculation import calculate_offer,compare_offers,packet_fingerprint,normalize_scenario
ROOT=Path(__file__).resolve().parents[1]
class CommercialTests(unittest.TestCase):
 def setUp(self):
  corpus=json.loads((ROOT/"data/offers.json").read_text());self.offers={o["supplier_id"]:o for o in corpus["offers"]};self.scenario=corpus["rfqs"][0]["default_scenario"];self.ex={k:extract_offer(v) for k,v in self.offers.items()}
 def runrow(self,supplier="A",demand=12,overrides=None,scenario=None):
  terms=self.ex[supplier]["terms"]| (overrides or {})
  return calculate_offer(terms,self.scenario|{"demand_qty_each":demand}|(scenario or {}))
 def proposal(self,supplier="A"):
  return {"fields":{k:{"raw_value":v["raw_value"],"quote":v["quote"]} for k,v in self.ex[supplier]["fields"].items()}}
 def altered(self,supplier,before,after):
  o=copy.deepcopy(self.offers[supplier]);o["content"]=o["content"].replace(before,after);o["source_hash"]=hashlib.sha256(o["content"].encode()).hexdigest();return o
 def test_price_basis_is_separate_from_pack_qty(self):
  r=self.runrow();self.assertEqual((r["order_qty_units"],r["delivered_qty_each"],r["surplus_qty_each"],r["goods_cost_krw"],r["comparison_cost_krw"]),(2,20,8,240000,245000))
 def test_each_price_included_freight(self):
  r=self.runrow("B");self.assertEqual(r["comparison_cost_krw"],180000);self.assertEqual(r["freight_cost_krw"],0)
 def test_unknown_freight_never_zero(self):
  r=self.runrow("C");self.assertEqual(r["goods_cost_krw"],132000);self.assertIsNone(r["freight_cost_krw"]);self.assertIsNone(r["comparison_cost_krw"]);self.assertFalse(r["comparable"])
 def test_quantity_changes_limited_cost_order_with_coverage(self):
  rows=list(self.ex.values())
  small=compare_offers(rows,self.scenario);large=compare_offers(rows,self.scenario|{"demand_qty_each":30})
  self.assertEqual(small["cost_order"],["B","A"]);self.assertEqual(large["cost_order"],["A","B"]);self.assertEqual(large["completeness"],{"comparable":2,"total":3})
 def test_demand21_rounds_to_next_order_unit(self):
  r=self.runrow(demand=21);self.assertEqual((r["delivered_qty_each"],r["comparison_cost_krw"]),(30,365000))
 def test_multiple_is_zero_based_not_moq_based(self):
  r=self.runrow(overrides={"moq":3,"order_multiple":2});self.assertEqual((r["order_qty_units"],r["comparison_cost_krw"]),(4,485000))
 def test_price_per_each_does_not_mean_order_each(self):
  r=self.runrow(overrides={"price_amount_krw":10000,"price_basis_each":1,"units_per_order_unit":5,"moq":1,"freight_status":"included","freight_amount_krw":None});self.assertEqual((r["delivered_qty_each"],r["comparison_cost_krw"]),(15,150000))
 def test_unresolved_other_charges_exclude_complete_compare(self):
  for status in ("unknown","mentioned_unsupported",None):
   with self.subTest(status=status):self.assertIsNone(self.runrow(overrides={"other_mandatory_charge_status":status})["comparison_cost_krw"])
 def test_moq_and_multiple_units_must_match_order_unit(self):
  for field in ("moq_unit","order_multiple_unit"):
   with self.subTest(field=field):self.assertFalse(self.runrow(overrides={field:"each"})["comparable"])
 def test_half_won_is_excluded_without_rounding(self):
  r=self.runrow("B",1,{"price_amount_krw":1,"price_basis_each":2});self.assertEqual(r["goods_cost_exact"],"1/2");self.assertIsNone(r["goods_cost_krw"]);self.assertIn("unsupported_precision",r["excluded_reasons"])
 def test_price_validity_last_day_inclusive(self):
  self.assertTrue(self.runrow(scenario={"scenario_order_date":"2026-10-31"})["comparable"])
  self.assertIn("expired_price",self.runrow(scenario={"scenario_order_date":"2026-11-01"})["excluded_reasons"])
 def test_conditional_lead_time_never_produces_eta(self):
  r=self.runrow("C");self.assertEqual(r["delivery_state"],"conditional_no_eta");self.assertIsNone(r["delivery_date"]);self.assertEqual(r["lead_time_condition"],"PO 접수 후 7일")
 def test_late_delivery_is_separate_from_limited_cost_eligibility(self):
  r=self.runrow(overrides={"delivery_date":"2026-10-20"});self.assertEqual(r["delivery_state"],"late");self.assertEqual(r["comparison_cost_krw"],245000)
 def test_tax_included_and_unknown_are_not_removed_or_assumed(self):
  for tax in ("tax_included","unknown",None):
   with self.subTest(tax=tax):self.assertIn("tax_not_explicitly_excluded",self.runrow(overrides={"tax_status":tax})["excluded_reasons"])
 def test_missing_zero_negative_and_noninteger_inputs_rejected(self):
  for demand in (None,0,-1,1.1,True,"12"):
   with self.subTest(demand=demand),self.assertRaises(ValueError):normalize_scenario(self.scenario|{"demand_qty_each":demand})
  for field in ("price_amount_krw","price_basis_each","units_per_order_unit","moq","order_multiple"):
   for value in (0,-1,None):
    with self.subTest(field=field,value=value):self.assertFalse(self.runrow(overrides={field:value})["comparable"])
  for value in (True,1.5,"10000"):
   with self.subTest(value=value),self.assertRaises(ValueError):self.runrow(overrides={"price_amount_krw":value})
 def test_unsupported_currency_and_bad_schema(self):
  self.assertIn("unsupported_currency",self.runrow(overrides={"currency":"USD"})["excluded_reasons"])
  with self.assertRaisesRegex(ValueError,"invalid_terms_schema"):calculate_offer({},self.scenario)
  with self.assertRaises(ValueError):normalize_scenario(self.scenario|{"guess":1})
 def test_source_quote_and_span_are_exact_in_text_and_csv(self):
  for supplier in ("A","B","C"):
   verified=validate_model_proposal(self.offers[supplier],self.proposal(supplier))
   for field,cell in verified["fields"].items():
    self.assertEqual(self.offers[supplier]["content"][cell["span_start"]:cell["span_end"]],cell["quote"])
 def test_fabricated_price_or_other_field_quote_rejected(self):
  for field,value in (("raw_value","1"),("quote","Price amount KRW: 1"),("quote","Price basis each: 10")):
   proposal=self.proposal();proposal["fields"]["price_amount_krw"][field]=value
   with self.subTest(field=field,value=value),self.assertRaises(ValueError):validate_model_proposal(self.offers["A"],proposal)
 def test_part_or_supplier_identity_source_conflict(self):
  for before,after in (("RFQ item: AX-DEMO-BRACKET-01","RFQ item: OTHER"),("Supplier: A","Supplier: B")):
   with self.subTest(after=after),self.assertRaisesRegex(ValueError,"source_identity_conflict"):extract_offer(self.altered("A",before,after))
 def test_duplicate_full_field_quote_is_ambiguous(self):
  o=self.altered("A","Price amount KRW: 120000","Price amount KRW: 120000\nPrice amount KRW: 120000")
  e=extract_offer(o);self.assertEqual(e["fields"]["price_amount_krw"]["state"],"ambiguous");p={"fields":{k:{"raw_value":v["raw_value"],"quote":v["quote"]} for k,v in e["fields"].items()}}
  with self.assertRaisesRegex(ValueError,"ambiguous"):validate_model_proposal(o,p)
 def test_price_qualifier_is_not_parsed_as_plain_amount(self):
  e=extract_offer(self.altered("A","Price amount KRW: 120000","Price amount KRW: 120000 or 150000"))
  self.assertIsNone(e["terms"]["price_amount_krw"]);self.assertFalse(calculate_offer(e["terms"],self.scenario)["comparable"])
 def test_hash_change_without_updated_provenance_rejected(self):
  o=copy.deepcopy(self.offers["A"]);o["content"]+="changed"
  with self.assertRaisesRegex(ValueError,"source_hash_mismatch"):extract_offer(o)
 def test_missing_terms_model_proposal_cannot_vacuously_pass(self):
  with self.assertRaisesRegex(ValueError,"coverage"):validate_model_proposal(self.offers["A"],{"fields":{}})
 def test_source_terms_scenario_rule_version_bind_packet_fingerprint(self):
  base=packet_fingerprint(list(self.ex.values()),self.scenario)
  for kind in ("source","terms","demand","date","version"):
   ex=copy.deepcopy(list(self.ex.values()));scenario=copy.deepcopy(self.scenario);version=None
   if kind=="source":ex[0]["provenance"]["source_hash"]="changed"
   elif kind=="terms":ex[0]["terms"]["price_amount_krw"]=120001
   elif kind=="demand":scenario["demand_qty_each"]=30
   elif kind=="date":scenario["scenario_order_date"]="2026-10-02"
   else:version="commercial-v2"
   with self.subTest(kind=kind):self.assertNotEqual(base,packet_fingerprint(ex,scenario,version))
 def test_large_integer_ui_transport_preserves_decimal_digits(self):
  r=self.runrow("B",30,{"price_amount_krw":100000000000000001})
  self.assertEqual(r["exact_values"]["comparison_cost_krw"],"3000000000000000030")
 def test_no_each_unit_with_pack_qty_conflict(self):
  self.assertIn("inconsistent_each_pack_size",self.runrow("B",12,{"units_per_order_unit":5})["excluded_reasons"])
 def test_included_freight_with_separate_nonzero_charge_conflicts(self):
  self.assertFalse(self.runrow("B",12,{"freight_amount_krw":5000})["comparable"])
 def test_included_freight_parse_error_or_duplicate_never_zero(self):
  for before,after in (("Freight amount KRW,","Freight amount KRW,5000 or 7000"),("Freight amount KRW,","Freight amount KRW,\nFreight amount KRW,5000")):
   o=self.altered("B",before,after);e=extract_offer(o)
   row=compare_offers([e],self.scenario)["rows"][0]
   with self.subTest(after=after):
    self.assertFalse(row["comparable"]);self.assertIsNone(row["freight_cost_krw"]);self.assertIsNone(row["comparison_cost_krw"]);self.assertIn("freight_source_unresolved",row["excluded_reasons"])
 def test_missing_lead_field_does_not_change_supported_cost_scope(self):
  o=self.altered("B","Lead time condition,\n","");e=extract_offer(o)
  row=compare_offers([e],self.scenario)["rows"][0]
  self.assertEqual(row["comparison_cost_krw"],180000)
if __name__=="__main__":unittest.main()
