"""New input CPU workflow, independent of frozen evaluation gold."""
import concurrent.futures
import hashlib

from test_core import Fixture
from rfq_review.core import Store, WorkflowConflictError


def source(supplier="NEW-TEST", price=84000):
    return f"""RFQ item: AX-DEMO-BRACKET-01
Supplier: {supplier}
Currency: KRW
Price amount KRW: {price}
Price basis each: 7
Order unit: pack
Units per order unit: 7
MOQ: 3
MOQ unit: pack
Order multiple: 2
Order multiple unit: pack
Freight status: fixed_per_order
Freight amount KRW: 6500
Other mandatory charge status: none_explicit
Tax status: tax_excluded
Valid until: 2026-10-31
Lead time type: absolute_date
Delivery date: 2026-10-10
Lead time condition:
"""


def request(content=None, label="Independent synthetic test", offer=None):
    return {"supplier_label": label, "content": source() if content is None else content,
            "offer_id": offer["id"] if offer else None,
            "expected_source_hash": offer["source_hash"] if offer else None,
            "expected_document_revision": offer["document_revision"] if offer else None}


class SourceInputTests(Fixture):
    def add(self, body=None):
        return self.store.save_source(self.buyer, self.rfq_id, body or request())

    def test_new_source_preserves_fixtures_requires_confirmation_and_calculates_pack_moq_freight(self):
        original = self.corpus.read_bytes()
        self.prepare()
        before = self.packet()
        offer = self.add()
        self.assertEqual(self.corpus.read_bytes(), original)
        self.assertEqual(offer["source_hash"], hashlib.sha256(source().encode()).hexdigest())
        self.assertTrue(self.store.packet(self.buyer, before["id"])["stale"])
        self.assertEqual(len(self.store.rfq(self.buyer, self.rfq_id)["offers"]), 4)
        with self.assertRaises(WorkflowConflictError):
            self.packet()
        proposal = self.store.extract(self.buyer, offer["id"])
        self.assertEqual(proposal["model_state"], "not_requested")
        self.assertIsNone(proposal["confirmation"])
        for field in proposal["fields"].values():
            self.assertEqual(offer["content"][field["span_start"]:field["span_end"]], field["quote"])
        with self.assertRaises(WorkflowConflictError):
            self.packet()
        self.store.confirm_terms(self.buyer, proposal["id"])
        packet = self.packet()
        row = next(r for r in packet["rows"] if r["supplier_id"] == "NEW-TEST")
        self.assertEqual((row["order_qty_units"], row["delivered_qty_each"], row["surplus_qty_each"]), (4, 28, 16))
        self.assertEqual(row["comparison_cost_krw"], 342500)
        self.assertEqual(packet["completeness"], {"comparable": 3, "total": 4})
        with self.assertRaises(PermissionError):
            self.store.review_packet(self.buyer, packet["id"], "reviewed", expected_fingerprint=packet["fingerprint"])
        self.store.review_packet(self.reviewer, packet["id"], "reviewed", expected_fingerprint=packet["fingerprint"])

    def test_revision_invalidates_confirmation_review_and_stale_write_and_persists(self):
        self.prepare()
        offer = self.add()
        proposal = self.store.extract(self.buyer, offer["id"])
        self.store.confirm_terms(self.buyer, proposal["id"])
        packet = self.packet()
        self.store.review_packet(self.reviewer, packet["id"], "reviewed", expected_fingerprint=packet["fingerprint"])
        revised = self.add(request(source(price=91000), offer=offer))
        self.assertEqual(revised["document_revision"], 2)
        self.assertEqual(revised["id"], offer["id"])
        stale = self.store.proposal(self.buyer, proposal["id"])
        self.assertTrue(stale["stale"])
        self.assertEqual(stale["fields"], {})
        stale_packet = self.store.packet(self.reviewer, packet["id"])
        self.assertEqual(stale_packet["rows"], [])
        self.assertIsNone(stale_packet["review"])
        with self.assertRaises(WorkflowConflictError):
            self.add(request(source(price=98000), offer=offer))
        with self.assertRaises(WorkflowConflictError):
            self.store.confirm_terms(self.buyer, proposal["id"])
        self.store.close()
        self.store = Store(self.corpus, self.db)
        self.assertEqual(self.store.offer(self.buyer, offer["id"])["source_hash"], revised["source_hash"])
        fresh = self.store.extract(self.buyer, offer["id"])
        self.store.confirm_terms(self.buyer, fresh["id"])
        self.assertEqual(next(r for r in self.packet()["rows"] if r["supplier_id"] == "NEW-TEST")["comparison_cost_krw"], 370500)

    def test_role_schema_and_fixture_replacement_denied(self):
        with self.assertRaises(PermissionError):
            self.store.save_source(self.reviewer, self.rfq_id, request())
        for body in (request(source("A")), request() | {"terms": {}}, request() | {"offer_id": "OFFER-A"},
                     request(label="\x00label"), request(label="x" * 81), request() | {"expected_source_hash": "x"}):
            with self.subTest(body=body), self.assertRaises(ValueError):
                self.add(body)
        self.assertEqual(len(self.store.rfq(self.buyer, self.rfq_id)["offers"]), 3)

    def test_malformed_sources_fail_without_mutation(self):
        invalid = ["", "x" * 12001, source() + "Notes: extra\n", source() + "MOQ: 3\n",
                   source().replace("MOQ: 3\n", ""), source().replace("MOQ: 3", "MOQ: -3"),
                   source().replace("MOQ: 3", "MOQ: 0"), source().replace("Price amount KRW: 84000", "Price amount KRW: 1.2"),
                   source().replace("Currency: KRW", "Currency: USD"), source().replace("MOQ unit: pack", "MOQ unit: each"),
                   source().replace("2026-10-31", "2026-02-30"), source().replace("NEW-TEST", "NEW-test"),
                   source().replace("AX-DEMO-BRACKET-01", "other"), source().replace("Freight amount KRW: 6500", "Freight amount KRW: "),
                   source().replace("Freight status: fixed_per_order", "Freight status: included"), source() + "\x00",
                   source().replace("Lead time condition:", "Lead time condition: " + "x" * 501)]
        for content in invalid:
            with self.subTest(content=content[:40]), self.assertRaises(ValueError):
                self.add(request(content))
        self.assertEqual(len(self.store.rfq(self.buyer, self.rfq_id)["offers"]), 3)
        self.assertEqual(self.store.audit(self.buyer, self.rfq_id), [])

    def test_unknown_freight_stays_excluded_and_untrusted_text_is_literal(self):
        self.prepare()
        text = source().replace("fixed_per_order", "unknown").replace("Freight amount KRW: 6500", "Freight amount KRW: ")
        text = text.replace("absolute_date", "conditional").replace("Delivery date: 2026-10-10", "Delivery date: ")
        text = text.replace("Lead time condition:", "Lead time condition: <img src=x onerror=alert(1)>")
        offer = self.add(request(text, label="<script>alert(1)</script>"))
        proposal = self.store.extract(self.buyer, offer["id"])
        self.store.confirm_terms(self.buyer, proposal["id"])
        row = next(r for r in self.packet()["rows"] if r["supplier_id"] == "NEW-TEST")
        self.assertIsNone(row["comparison_cost_krw"])
        self.assertIn("freight_unknown", row["excluded_reasons"])
        self.assertEqual(row["terms"]["lead_time_condition"], "<img src=x onerror=alert(1)>")

    def test_capacity_duplicate_and_immutable_identity(self):
        first = self.add()
        with self.assertRaises(ValueError):
            self.add()
        with self.assertRaises(ValueError):
            self.add(request(source("NEW-OTHER"), offer=first))
        for n in range(4):
            self.add(request(source("NEW-" + str(n))))
        with self.assertRaises(ValueError):
            self.add(request(source("NEW-SIXTH")))
        self.add(request(source(price=91000), offer=first))
        self.assertEqual(len(self.store.rfq(self.buyer, self.rfq_id)["offers"]), 8)

    def test_crlf_source_hash_and_quote_offsets_preserve_exact_original(self):
        original = source().replace("Lead time condition:", "Lead time condition: 검토 메모 🧾")
        original_bytes = original.replace("\n", "\r\n").encode("utf-8")
        offer = self.add(request(original_bytes.decode("utf-8")))
        self.assertEqual(offer["source_hash"], hashlib.sha256(original_bytes).hexdigest())
        self.assertNotEqual(offer["source_hash"], hashlib.sha256(original.encode("utf-8")).hexdigest())
        stored = self.store.offer(self.buyer, offer["id"])
        self.assertEqual(stored["content"].encode("utf-8"), original_bytes)
        proposal = self.store.extract(self.buyer, offer["id"])
        for cell in proposal["fields"].values():
            self.assertEqual(stored["content"][cell["span_start"]:cell["span_end"]], cell["quote"])
            self.assertEqual(stored["content"].splitlines()[cell["line"] - 1], cell["quote"])
        self.store.confirm_terms(self.buyer, proposal["id"])
        self.assertEqual(proposal["provenance"]["source_hash"], hashlib.sha256(original_bytes).hexdigest())

    def test_concurrent_creates_and_same_content_revisions_are_bound(self):
        other = Store(self.corpus, self.db)
        try:
            def create(store):
                try:
                    return store.save_source(self.buyer, self.rfq_id, request())
                except ValueError:
                    return None
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                outcomes = list(executor.map(create, (self.store, other)))
            self.assertEqual(sum(o is not None for o in outcomes), 1)
            offer = next(o for o in outcomes if o)
            revised = self.add(request(offer=offer, label="new display label"))
            self.assertEqual(revised["source_hash"], offer["source_hash"])
            with self.assertRaises(WorkflowConflictError):
                other.save_source(self.buyer, self.rfq_id, request(offer=offer))
            self.assertEqual(len(self.store.rfq(self.buyer, self.rfq_id)["offers"]), 4)
        finally:
            other.close()

    def test_source_change_during_mocked_model_extraction_is_rejected(self):
        offer = self.add()
        def change_during_extraction(current):
            from rfq_review import extraction
            result = extraction.extract_offer(current)
            self.add(request(source(price=91000), offer=offer))
            return dict(result, model_state="source_verified")
        context, adapter = self.model_patch(function=change_during_extraction)
        with context, self.assertRaises(WorkflowConflictError):
            self.store.extract(self.buyer, offer["id"], mode="model")
        adapter.assert_called_once()
