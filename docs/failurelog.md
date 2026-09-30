# Observed failures
1. Initial real A model proposal returned Supplier:A for every field's quote and changed price120000 to120:000. Server rejected quote_not_full_original_field. HTTP200 did not count as success.
2. Explicit field/header mapping corrected quotes but price120:000 remained; rejected unsupported_full_cell_value.
3. A passed after the raw cell candidate grammar was constrained to all original cells (same candidate set for every field). B CSV still quoted field,value everywhere; rejected. Candidate constraints are not field-specific gold.
All raw synthetic requests/responses remain in private artifacts/model-calls; sanitized metrics/failure extracts are published separately.
Security review found excluded order_unit could render HTML inside a table; esc() and a literal-markup regression fixed it. CSP alone did not prevent UI spoofing.
Calculation review found malformed/multiple freight amount under included status could collapse to blank0. source_errors now propagate unresolved status and exclusion; missing/ambiguous is distinct from explicit blank.

4. Supplying ALL source rows as header/cell/fulloriginal-line alongside original text corrected CSV source association. A/B/C passed bounded validation, then3same offers passed runningAPI validation. This is prompt-development on a fixed synthetic corpus, not independent heldout performance.
5. Recording first attempted to access JS state before Page.load; helper now waits for defined state. Test contract was updated for source_rows without changing its no-gold boundary. Final69tests pass; artifacts record success separately from prior helper errors.
