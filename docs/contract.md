# Frozen project03 interface contract v1
Source: data/offers.json {version,synthetic,rfqs:[...],offers:[...]}; 3 offers A/B/C for RFQ-SYN-001, item AX-DEMO-BRACKET-01.
Default scenario {demand_qty_each:12,scenario_order_date:"2026-10-01",required_by_date:"2026-10-15"}. Explicit scenario order date required, required date nullable. Positive integer demand, KRW only. No quote edits/uploads/ERP/selection API.
Offer fields id,supplier_id,supplier_label,rfq_id,item_id,document_revision,format(kv_text|kv_csv),source_hash,content. Server envelope validates SHA256 and identity original RFQ item/Supplier rows. Proposed fields:
currency,price_amount_krw,price_basis_each,order_unit,units_per_order_unit,moq,moq_unit,order_multiple,order_multiple_unit,freight_status,freight_amount_krw,other_mandatory_charge_status,tax_status,valid_until,lead_time_type,delivery_date,lead_time_condition.
Source lines are English header/value; CSV has field,value header and one key/value row per field. Full original line quote/span must match, duplicate fields/quotes ambiguous; model may not supply metadata.

## Domain root-owned functions
extraction.offer_envelope(offer) -> metadata+computedhash, raises ValueError for identity/hash/content invalid.
extraction.extract_offer(offer) -> {offer_id,provenance,fields:{field:{raw_value,quote,line,span_start,span_end,state}},terms:{17 typed values},term_errors:[strings],model_state:"not_requested",extraction_state:"deterministic_observed"}.
extraction.validate_model_proposal(offer,proposal) accepts exactly {fields:{all17:{raw_value:str|null,quote:str|null}}}; returns server extraction with model_state source_verified. All cells/whole original quotes must agree, no partial/code-substring/field swaps/ambiguousmatch.
llm.extract_offer_with_model(offer) -> same shape+metrics. Existing qwen3:4b only, one offer per request, shared user runtime lease/timeout marker copied from02, localhost, boundedcontext/output. No modelmath/guess/selection. CPU fallback retained on model failure, model_state failed, explicit manual_confirmation required.
calculation.RULE_VERSION="commercial-v1".
calculation.normalize_scenario(scenario) -> exact schema canonical validated dict.
calculation.calculate_offer(terms,scenario) -> {order_qty_units,delivered_qty_each,surplus_qty_each,goods_cost_krw:int|null,goods_cost_exact:str|null,freight_cost_krw:int|null,comparison_cost_krw:int|null,comparable:bool,excluded_reasons:[...],delivery_state,delivery_date,lead_time_condition,scope,rule_version}.
ceil demand/units; >=MOQ and minimum ZERO-based order_multiple; delivered=orderunits*units; goods Fraction(delivered*price_amount,price_basis_each). Fractional KRW -> unsupported_precision, no rounding. Included freight explicitly adds0; unknown not0. Other charges only none_explicit; tax only tax_excluded; expired orderdate>valid_until excludes (lastdateinclusive).
Only absolute_date computes on_time/late vs required date; conditional retains text and NO ETA. Cost eligibility is separate from lead-time/technical/review suitability.
calculation.compare_offers(extractions:list,scenario) -> {scenario,rows:[row+offer_id/supplier_id/provenance],cost_order:[supplierids sorted ONLY comparable],completeness:{comparable,total},scope,rule_version}. No global best/overall cheapest claim.
calculation.packet_fingerprint(extractions,scenario,rule_version=None) -> SHA256 canonical source envelopes+typedterms+scenario+ruleversion (includes all selected offers).

## Core backend-owned Store(corpus_path,db_path)
Demo profiles buyer/reviewer only, label explicitly synthetic. Sessions ephemeral opaque bearer; missing/expired auth MUST401, genuine role denial403. Readonly listings/source/evidence recheck current corpus/hash/revision. No old authorized fallback. Both roles may inspect all synthetic RFQ data; terms confirmation buyer/reviewer, final packet review reviewer only.
Store.profiles(),session(profile),principal(token),rfqs(principal),rfq(principal,id),offer(principal,id),extract(principal,offer_id,mode),proposal(principal,id),confirm_terms(principal,proposal_id,manual_confirmation=False),calculate(principal,rfq_id,scenario),packet(principal,id),review_packet(principal,id,decision,comment="",expected_fingerprint=None),audit(principal,rfq_id).
extract produces stored proposal {id,offer_id,...rootdomainshape,status:"pending_terms_confirmation",confirmation:null,metrics}; failure fallback clearlyfailed/manual.
New proposal per offer replaces current selection and invalidates old confirmations/packets even if source unchanged; it needs fresh human confirmation. Confirmation idempotent uniqueperproposal, actor/time/source+terms fingerprint, no editing normalizedterms. Model failure requires manual confirmation flag.
calculate only after all3 current selected proposals humanconfirmed; otherwise409 terms_confirmation_required. Unknown freight/charges may be confirmed as unknown, but excluded from complete comparison.
Persist active scenario perRFQ on calculate. A change to quantity/orderdate/required date makes oldpacket stale against current active scenario. Stored old packets remain historical and publicview hides old review/content when stale. Changing source/hash/revision/typedterms/current proposal/ruleversion also invalidates stored review. Source refresh before reads/writes and after slow modelcalls. If sources invalid/missing or changed while processing, failclosed.
review decisions reviewed|needs_followup, acknowledgement of this comparison packet only, not supplierapproval/order. expected_fingerprint must matchcurrent; unique idempotent+atomicSQLite review/audit. No role-less metadatawrite.
audit includes scoped synthetic events, source/proposal/packet changes, confirm and review, no bearer/rawrequestbody/privatepaths.

## HTTP routes
GET /api/health,/api/profiles public; POST /api/session {profile}.
GET /api/rfqs -> {rfqs}; GET /api/rfqs/<id> -> {rfq,offers,current_proposals:[...],active_scenario}.
GET /api/offers/<id> -> {offer}; POST /api/offers/<id>/extract {mode:"baseline"|"model"} -> {proposal}.
GET /api/proposals/<id> -> {proposal}; POST /api/proposals/<id>/confirm {manual_confirmation:boolean} -> {confirmation,duplicate}.
POST /api/rfqs/<id>/calculate {scenario:{...}} -> {packet}.
GET /api/packets/<id> -> {packet}; POST /api/packets/<id>/review {decision,comment,expected_fingerprint} -> {review,duplicate}.
GET /api/audit?rfq_id=... -> {events}.
Server127.0.0.1:19083, exactstatic3allowlist, Host/OriginstrictnoCORS, limitbody32768, sanitizederrors. Missing/expired401, role403, invalid404/400, stale/termsnotconfirmed409.
No actual supplier contacts, orders, payment, tax rates, purchase approvals, legal quote acceptance.

## Exact integer transport
Every row additionally includes exact_values for quantity and money fields as decimal strings/null. UI must format those strings without Number conversion to preserve integers beyond JavaScript safe-number range. Render source price/basis from original raw field strings; do not round prices to floats. Numeric JSON fields remain for Python evaluation, cost sorting is performed by server integer arithmetic.
