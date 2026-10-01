"""RFQ loopback API, human gates and atomic retry tests; inference mocked."""
import concurrent.futures
import http.client
import json
import threading
import unittest
from unittest.mock import patch

from test_core import Fixture
from rfq_review.server import MAX_BODY, make_server


class HTTPTests(Fixture):
    def test_new_source_api_auth_role_validation_and_human_gate(self):
        from test_source_input import request, source
        path = "/api/rfqs/" + self.rfq_id + "/sources"
        self.assertEqual(self.request("POST", path, request(), role=None)[0], 401)
        self.assertEqual(self.request("POST", path, request(), role="reviewer")[0], 403)
        self.assertEqual(self.request("POST", path, request("not a quote"))[0], 400)
        self.prepare()
        status, body, _ = self.request("POST", path, request())
        self.assertEqual(status, 200)
        offer = body["offer"]
        self.assertEqual(self.request("POST", "/api/rfqs/" + self.rfq_id + "/calculate", {"scenario": self.scenario})[0], 409)
        _, body, _ = self.request("POST", "/api/offers/" + offer["id"] + "/extract", {"mode": "baseline"})
        self.assertEqual(self.request("POST", "/api/proposals/" + body["proposal"]["id"] + "/confirm", {"manual_confirmation": False})[0], 200)
        status, body, _ = self.request("POST", "/api/rfqs/" + self.rfq_id + "/calculate", {"scenario": self.scenario})
        self.assertEqual(status, 200)
        self.assertEqual(body["packet"]["completeness"]["total"], 4)
        self.assertEqual(self.request("POST", path, request(source(price=91000), offer=offer))[0], 200)
        self.assertEqual(self.request("POST", path, request(source(price=98000), offer=offer))[0], 409)
        self.assertEqual(self.request("POST", path, request("x" * 12001))[0], 400)

    def setUp(self):
        super().setUp()
        self.static = self.root / "static"
        self.static.mkdir()
        for name in ("index.html", "app.js", "styles.css"):
            (self.static / name).write_text("synthetic RFQ " + name)
        self.server = make_server(self.store, port=0, static_dir=self.static)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port
        self.tokens = {role: self.store.session(role)["token"] for role in ("buyer", "reviewer")}

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        super().tearDown()

    def request(self, method, path, body=None, role="buyer", headers=None, raw=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        selected = {}
        if role:
            selected["Authorization"] = "Bearer " + self.tokens[role]
        if body is not None:
            raw = json.dumps(body)
            selected["Content-Type"] = "application/json"
        selected.update(headers or {})
        connection.request(method, path, body=raw, headers=selected)
        response = connection.getresponse()
        payload = response.read()
        status, response_headers = response.status, dict(response.getheaders())
        connection.close()
        if response_headers.get("Content-Type", "").startswith("application/json"):
            payload = json.loads(payload)
        return status, payload, response_headers

    def calculated(self):
        self.prepare()
        status, body, _ = self.request("POST", "/api/rfqs/" + self.rfq_id + "/calculate", {"scenario": self.scenario})
        self.assertEqual(status, 200)
        return body["packet"]

    def test_public_health_static_whitelist_and_private_source_authentication(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        status, health, headers = self.request("GET", "/api/health", role=None)
        self.assertEqual(status, 200)
        self.assertTrue(health["synthetic"])
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        for path in ("/", "/app.js", "/styles.css", "/index.html"):
            self.assertEqual(self.request("GET", path, role=None)[0], 200)
        for path in ("/data/offers.json", "/evaluations/gold.json", "/rfq_review/core.py",
                     "/../data/offers.json", "/%2e%2e/data/offers.json"):
            self.assertEqual(self.request("GET", path, role=None)[0], 404)
        self.assertEqual(self.request("GET", "/api/offers/OFFER-A", role=None)[0], 401)
        self.assertEqual(self.request("GET", "/api/rfqs")[0], 200)

    def test_missing_expired_sessions_401_and_role_denial_403(self):
        self.assertEqual(self.request("GET", "/api/rfqs", role=None, headers={"X-Role": "reviewer"})[0], 401)
        self.assertEqual(self.request("GET", "/api/rfqs", headers={"Authorization": "Bearer unknown"})[0], 401)
        with patch("rfq_review.core.time.monotonic", return_value=10**15):
            self.assertEqual(self.request("GET", "/api/rfqs")[0], 401)
        self.tokens["buyer"] = self.store.session("buyer")["token"]
        packet = self.calculated()
        self.assertEqual(self.request("POST", "/api/packets/" + packet["id"] + "/review",
                         {"decision": "reviewed", "expected_fingerprint": packet["fingerprint"]})[0], 403)

    def test_full_two_human_gates_and_no_proposed_terms_edit(self):
        calculate = "/api/rfqs/" + self.rfq_id + "/calculate"
        self.assertEqual(self.request("POST", calculate, {"scenario": self.scenario})[0], 409)
        for supplier in "ABC":
            status, body, _ = self.request("POST", "/api/offers/OFFER-" + supplier + "/extract",
                                          {"mode": "baseline", "terms": {"price_amount_krw": 1}})
            self.assertEqual(status, 200)
            proposal = body["proposal"]
            self.assertIsNone(proposal["confirmation"])
            status, confirmation, _ = self.request("POST", "/api/proposals/" + proposal["id"] + "/confirm",
                                                    {"manual_confirmation": False, "terms": {"price_amount_krw": 1}})
            self.assertEqual(status, 200)
        status, body, _ = self.request("POST", calculate, {"scenario": self.scenario})
        self.assertEqual(status, 200)
        packet = body["packet"]
        self.assertIsNone(packet["review"])
        self.assertEqual(next(r for r in packet["rows"] if r["supplier_id"] == "A")["comparison_cost_krw"], 245000)
        status, review, _ = self.request("POST", "/api/packets/" + packet["id"] + "/review",
            {"decision": "reviewed", "expected_fingerprint": packet["fingerprint"]}, role="reviewer")
        self.assertEqual(status, 200)
        self.assertFalse(review["duplicate"])

    def test_model_failure_manual_confirmation_409_and_safe_errors(self):
        context, call = self.model_patch(error=TimeoutError("private path"))
        with context:
            status, body, _ = self.request("POST", "/api/offers/OFFER-A/extract", {"mode": "model"})
        self.assertEqual(status, 200)
        proposal = body["proposal"]
        self.assertEqual(proposal["model_state"], "failed")
        self.assertNotIn("private path", json.dumps(body))
        path = "/api/proposals/" + proposal["id"] + "/confirm"
        self.assertEqual(self.request("POST", path, {"manual_confirmation": False})[0], 409)
        self.assertEqual(self.request("POST", path, {"manual_confirmation": True})[0], 200)

    def test_host_origin_body_and_exact_scenario_validation(self):
        self.assertEqual(self.request("GET", "/api/health", role=None, headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.request("GET", "/api/rfqs", headers={"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.request("POST", "/api/session", raw="{}", role=None)[0], 400)
        for raw in ("[]", "{"):
            self.assertEqual(self.request("POST", "/api/session", raw=raw, role=None,
                                         headers={"Content-Type": "application/json"})[0], 400)
        self.assertEqual(self.request("POST", "/api/session", raw="x" * (MAX_BODY + 1), role=None,
                                     headers={"Content-Type": "application/json"})[0], 413)
        self.assertEqual(self.request("POST", "/api/rfqs/" + self.rfq_id + "/calculate",
                                      {"scenario": {"demand_qty_each": 12}})[0], 400)
        self.assertEqual(self.request("GET", "/api/audit?rfq_id=x&rfq_id=y")[0], 400)

    def test_new_proposal_stale_packet_hides_review_and_rows(self):
        packet = self.calculated()
        self.request("POST", "/api/packets/" + packet["id"] + "/review",
                     {"decision": "reviewed", "expected_fingerprint": packet["fingerprint"]}, role="reviewer")
        self.request("POST", "/api/offers/OFFER-A/extract", {"mode": "baseline"})
        status, body, _ = self.request("GET", "/api/packets/" + packet["id"])
        self.assertEqual(status, 200)
        self.assertTrue(body["packet"]["stale"])
        self.assertEqual(body["packet"]["rows"], [])
        self.assertIsNone(body["packet"]["review"])
        self.assertEqual(self.request("POST", "/api/packets/" + packet["id"] + "/review",
                         {"decision": "reviewed", "expected_fingerprint": packet["fingerprint"]}, role="reviewer")[0], 409)

    def test_source_revision_and_hash_fail_closed(self):
        packet = self.calculated()
        self.edit("OFFER-A", self.source("OFFER-A")["content"] + "corrupted private source", rehash=False)
        self.assertEqual(self.request("GET", "/api/offers/OFFER-A")[0], 400)
        status, body, _ = self.request("GET", "/api/packets/" + packet["id"])
        self.assertEqual(status, 200)
        self.assertEqual(body["packet"]["rows"], [])
        self.assertNotIn("corrupted private", json.dumps(body))
        self.assertEqual(self.request("POST", "/api/rfqs/" + self.rfq_id + "/calculate", {"scenario": self.scenario})[0], 409)

    def test_concurrent_confirmation_and_review_http_retries(self):
        _, body, _ = self.request("POST", "/api/offers/OFFER-A/extract", {"mode": "baseline"})
        proposal_id = body["proposal"]["id"]
        def confirm(index):
            return self.request("POST", "/api/proposals/" + proposal_id + "/confirm", {"manual_confirmation": False})
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            confirmations = list(executor.map(confirm, range(16)))
        self.assertEqual({r[0] for r in confirmations}, {200})
        self.assertEqual(sum(not r[1]["duplicate"] for r in confirmations), 1)
        for supplier in "BC":
            proposal = self.store.extract(self.buyer, "OFFER-" + supplier)
            self.store.confirm_terms(self.buyer, proposal["id"])
        _, body, _ = self.request("POST", "/api/rfqs/" + self.rfq_id + "/calculate", {"scenario": self.scenario})
        packet = body["packet"]
        def review(index):
            return self.request("POST", "/api/packets/" + packet["id"] + "/review",
                {"decision": "reviewed", "expected_fingerprint": packet["fingerprint"]}, role="reviewer")
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            reviews = list(executor.map(review, range(16)))
        self.assertEqual({r[0] for r in reviews}, {200})
        self.assertEqual(sum(not r[1]["duplicate"] for r in reviews), 1)
        _, audit, _ = self.request("GET", "/api/audit?rfq_id=" + self.rfq_id)
        self.assertEqual(sum(e["action"] == "packet_reviewed" for e in audit["events"]), 1)


if __name__ == "__main__":
    unittest.main()
