"""Synthetic RFQ source confirmation and packet acknowledgement workflow."""
import hashlib
import json
import math
import secrets
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from . import extraction, calculation

ROLES = ("buyer", "reviewer")
SESSION_TTL = 3600


class AuthenticationError(PermissionError):
    pass


class WorkflowConflictError(ValueError):
    pass


def _id():
    return uuid.uuid4().hex


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Store:
    def __init__(self, corpus_path, db_path):
        self.corpus_path = Path(corpus_path)
        self._lock = threading.RLock()
        self._sessions = {}
        self._db = sqlite3.connect(str(db_path), check_same_thread=False, timeout=10)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS proposals (
                id TEXT PRIMARY KEY, rfq_id TEXT NOT NULL, supplier_id TEXT NOT NULL,
                offer_id TEXT NOT NULL, payload TEXT NOT NULL, source_fingerprint TEXT NOT NULL,
                proposal_fingerprint TEXT NOT NULL, invalidated INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS selections (
                rfq_id TEXT NOT NULL, supplier_id TEXT NOT NULL, proposal_id TEXT NOT NULL,
                PRIMARY KEY(rfq_id,supplier_id));
            CREATE TABLE IF NOT EXISTS confirmations (
                proposal_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS scenarios (
                rfq_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS packets (
                id TEXT PRIMARY KEY, rfq_id TEXT NOT NULL, payload TEXT NOT NULL,
                invalidated INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS reviews (
                packet_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS audit (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, rfq_id TEXT NOT NULL,
                payload TEXT NOT NULL);
        """)
        self._db.commit()
        self._refresh()

    def close(self):
        with self._lock:
            self._db.close()

    def _refresh(self):
        data = json.loads(self.corpus_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("rfqs"), list) or not isinstance(data.get("offers"), list):
            raise ValueError("invalid_corpus")
        rfqs = {}
        for rfq in data["rfqs"]:
            if not isinstance(rfq, dict) or not isinstance(rfq.get("id"), str) or not isinstance(rfq.get("item_id"), str):
                raise ValueError("invalid_rfq")
            if rfq["id"] in rfqs:
                raise ValueError("duplicate_rfq")
            rfqs[rfq["id"]] = rfq
        offers, latest, invalid = {}, {}, set()
        for offer in data["offers"]:
            if not isinstance(offer, dict):
                raise ValueError("invalid_offer")
            for field in ("id", "rfq_id", "supplier_id", "item_id"):
                if not isinstance(offer.get(field), str) or not 1 <= len(offer[field]) <= 200:
                    raise ValueError("invalid_offer_identity")
            revision = offer.get("document_revision")
            if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1 or offer["id"] in offers:
                raise ValueError("invalid_offer_revision")
            offers[offer["id"]] = offer
            try:
                extraction.offer_envelope(offer)
            except ValueError:
                invalid.add(offer["id"])
            key = self._offer_key(offer)
            previous = latest.get(key)
            if previous is not None and previous["document_revision"] == revision:
                raise ValueError("ambiguous_current_revision")
            if previous is None or revision > previous["document_revision"]:
                latest[key] = offer
        self._rfqs, self._offers, self._latest, self._invalid = rfqs, offers, latest, invalid

    @staticmethod
    def _offer_key(offer):
        return (offer["rfq_id"], offer["supplier_id"])

    @staticmethod
    def _check(principal):
        if not isinstance(principal, dict) or principal.get("role") not in ROLES or principal.get("id") != principal.get("role"):
            raise PermissionError("invalid_principal")

    def profiles(self):
        return [{"id": role, "role": role, "label": role + " (synthetic demo login)"} for role in ROLES]

    def session(self, profile):
        if profile not in ROLES:
            raise ValueError("unknown_demo_profile")
        token = secrets.token_urlsafe(32)
        principal = {"id": profile, "role": profile}
        with self._lock:
            self._sessions[token] = {"principal": principal, "expires_at": time.monotonic() + SESSION_TTL}
        return {"token": token, "principal": dict(principal), "expires_in": SESSION_TTL}

    def principal(self, token):
        with self._lock:
            value = self._sessions.get(token)
            if value is None or value["expires_at"] <= time.monotonic():
                self._sessions.pop(token, None)
                raise AuthenticationError("authentication_required")
            return dict(value["principal"])

    def _rfq(self, principal, rfq_id):
        self._check(principal)
        rfq = self._rfqs.get(rfq_id)
        if rfq is None:
            raise KeyError("rfq_not_found")
        return dict(rfq)

    def _current_offers(self, rfq_id):
        rfq = self._rfqs.get(rfq_id)
        if rfq is None:
            raise KeyError("rfq_not_found")
        return sorted([offer for offer in self._latest.values() if offer["rfq_id"] == rfq_id
                       and offer["item_id"] == rfq["item_id"]], key=lambda offer: offer["supplier_id"])

    def _offer(self, principal, offer_id):
        self._check(principal)
        offer = self._offers.get(offer_id)
        if offer is None or self._latest.get(self._offer_key(offer), {}).get("id") != offer_id:
            raise KeyError("offer_not_found")
        rfq = self._rfq(principal, offer["rfq_id"])
        if offer["item_id"] != rfq["item_id"] or offer_id in self._invalid:
            raise ValueError("source_validation_failed")
        extraction.extract_offer(offer)
        return json.loads(json.dumps(offer))

    def rfqs(self, principal):
        with self._lock:
            self._check(principal)
            self._refresh()
            return [dict(rfq) for rfq in self._rfqs.values()]

    def offer(self, principal, offer_id):
        with self._lock:
            self._check(principal)
            self._refresh()
            return self._offer(principal, offer_id)

    def _audit_event(self, principal, rfq_id, action, **fields):
        event = {"id": _id(), "timestamp": _now(), "rfq_id": rfq_id,
                 "actor_id": principal["id"], "action": action, **fields}
        self._db.execute("INSERT INTO audit(rfq_id,payload) VALUES(?,?)",
                         (rfq_id, json.dumps(event, ensure_ascii=False)))

    def _invalidate_proposal(self, principal, row, reason="source_or_selection_changed"):
        if not row["invalidated"]:
            cursor = self._db.execute("UPDATE proposals SET invalidated=1 WHERE id=? AND invalidated=0", (row["id"],))
            if cursor.rowcount:
                self._audit_event(principal, row["rfq_id"], "proposal_invalidated",
                                  proposal_id=row["id"], offer_id=row["offer_id"], reason=reason)
            row["invalidated"] = True

    def _invalidate_packet(self, principal, row):
        if not row["invalidated"]:
            cursor = self._db.execute("UPDATE packets SET invalidated=1 WHERE id=? AND invalidated=0", (row["id"],))
            if cursor.rowcount:
                self._audit_event(principal, row["rfq_id"], "packet_invalidated", packet_id=row["id"],
                                  reason="source_terms_selection_scenario_or_rule_changed")
            row["invalidated"] = True

    @staticmethod
    def _source_fingerprint(offer):
        return _hash(extraction.offer_envelope(offer))

    @staticmethod
    def _proposal_fingerprint(proposal_id, provenance, terms):
        return _hash({"proposal_id": proposal_id, "provenance": provenance, "terms": terms})

    def _proposal_row(self, principal, proposal_id):
        self._check(principal)
        selected = self._db.execute(
            "SELECT id,rfq_id,supplier_id,offer_id,payload,source_fingerprint,proposal_fingerprint,invalidated FROM proposals WHERE id=?",
            (proposal_id,)).fetchone()
        if selected is None:
            raise KeyError("proposal_not_found")
        row = dict(zip(("id", "rfq_id", "supplier_id", "offer_id", "payload", "source_fingerprint",
                        "proposal_fingerprint", "invalidated"), selected))
        payload = json.loads(row["payload"])
        selection = self._db.execute("SELECT proposal_id FROM selections WHERE rfq_id=? AND supplier_id=?",
                                     (row["rfq_id"], row["supplier_id"])).fetchone()
        stale = bool(row["invalidated"]) or selection is None or selection[0] != proposal_id
        offer = self._offers.get(row["offer_id"])
        if offer is None:
            stale = True
        else:
            try:
                offer = self._offer(principal, row["offer_id"])
                canonical = extraction.extract_offer(offer)
                stale |= self._source_fingerprint(offer) != row["source_fingerprint"]
                stale |= _hash(canonical["terms"]) != _hash(payload["terms"]) or _hash(canonical["fields"]) != _hash(payload["fields"])
                stale |= self._proposal_fingerprint(row["id"], canonical["provenance"], canonical["terms"]) != row["proposal_fingerprint"]
            except (ValueError, KeyError):
                stale = True
        if stale:
            self._invalidate_proposal(principal, row)
        return row, payload

    @staticmethod
    def _proposal_shell(row):
        return {"id": row["id"], "offer_id": row["offer_id"], "rfq_id": row["rfq_id"],
                "status": "invalidated", "stale": True, "confirmation": None,
                "fields": {}, "terms": {}, "model_state": "invalidated"}

    def _proposal_view(self, principal, proposal_id):
        row, payload = self._proposal_row(principal, proposal_id)
        if row["invalidated"]:
            return self._proposal_shell(row)
        confirmation = self._db.execute("SELECT payload FROM confirmations WHERE proposal_id=?", (proposal_id,)).fetchone()
        payload["confirmation"] = json.loads(confirmation[0]) if confirmation else None
        payload["status"] = "terms_confirmed" if confirmation else "pending_terms_confirmation"
        return payload

    def proposal(self, principal, proposal_id):
        with self._lock:
            self._check(principal)
            self._refresh()
            with self._db:
                return self._proposal_view(principal, proposal_id)

    def _scenario(self, rfq_id):
        row = self._db.execute("SELECT payload FROM scenarios WHERE rfq_id=?", (rfq_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def rfq(self, principal, rfq_id):
        with self._lock:
            self._check(principal)
            self._refresh()
            rfq = self._rfq(principal, rfq_id)
            offers = [self._offer(principal, offer["id"]) for offer in self._current_offers(rfq_id)]
            with self._db:
                proposals = [self._proposal_view(principal, row[0]) for row in self._db.execute(
                    "SELECT proposal_id FROM selections WHERE rfq_id=? ORDER BY supplier_id", (rfq_id,)).fetchall()]
            return {"rfq": rfq, "offers": offers, "current_proposals": proposals,
                    "active_scenario": self._scenario(rfq_id)}

    def extract(self, principal, offer_id, mode="baseline"):
        self._check(principal)
        if mode not in ("baseline", "model"):
            raise ValueError("invalid_mode")
        started = time.perf_counter()
        with self._lock:
            self._refresh()
            offer = self._offer(principal, offer_id)
            observed = extraction.extract_offer(offer)
            source_fingerprint = self._source_fingerprint(offer)
        result = observed
        metrics = {"requested_mode": mode, "synthetic": True}
        if mode == "model":
            try:
                from .llm import extract_offer_with_model
                proposed = extract_offer_with_model(offer)
                if (not isinstance(proposed, dict) or proposed.get("model_state") != "source_verified"
                        or any(_hash(proposed.get(field)) != _hash(observed.get(field))
                               for field in ("offer_id", "provenance", "fields", "terms", "term_errors"))):
                    raise ValueError("model_proposal_not_source_verified")
                result = {key: proposed[key] for key in observed if key in proposed}
                adapter_metrics = proposed.get("metrics", {})
                if isinstance(adapter_metrics, dict):
                    metrics.update({str(key)[:80]: value for key, value in adapter_metrics.items()
                                    if isinstance(value, (str, int, float, bool)) and len(str(value)) <= 500
                                    and (not isinstance(value, float) or math.isfinite(value))})
            except (TimeoutError, RuntimeError, ValueError, OSError, ImportError, TypeError, KeyError):
                result = dict(observed, model_state="failed", extraction_state="deterministic_manual_fallback")
                metrics["model_error_kind"] = "model_extraction_failed"
        proposal_id = _id()
        result.update({"id": proposal_id, "status": "pending_terms_confirmation", "confirmation": None,
                       "stale": False, "rfq_id": offer["rfq_id"], "metrics": metrics})
        result["metrics"]["total_ms"] = round((time.perf_counter() - started) * 1000, 3)
        proposal_fingerprint = self._proposal_fingerprint(proposal_id, observed["provenance"], observed["terms"])
        with self._lock:
            self._refresh()
            current = self._offer(principal, offer_id)
            if self._source_fingerprint(current) != source_fingerprint:
                raise WorkflowConflictError("source_changed_during_extraction")
            with self._db:
                self._db.execute("BEGIN IMMEDIATE")
                existing = self._db.execute("SELECT proposal_id FROM selections WHERE rfq_id=? AND supplier_id=?",
                                            (offer["rfq_id"], offer["supplier_id"])).fetchone()
                if existing:
                    old, _ = self._proposal_row(principal, existing[0])
                    self._invalidate_proposal(principal, old, "new_proposal_requires_new_confirmation")
                self._db.execute("INSERT INTO proposals VALUES(?,?,?,?,?,?,?,0)",
                                 (proposal_id, offer["rfq_id"], offer["supplier_id"], offer_id,
                                  json.dumps(result, ensure_ascii=False), source_fingerprint, proposal_fingerprint))
                self._db.execute("INSERT INTO selections VALUES(?,?,?) ON CONFLICT(rfq_id,supplier_id) DO UPDATE SET proposal_id=excluded.proposal_id",
                                 (offer["rfq_id"], offer["supplier_id"], proposal_id))
                self._audit_event(principal, offer["rfq_id"], "proposal_created", proposal_id=proposal_id,
                                  offer_id=offer_id, mode=mode, model_state=result["model_state"])
                self._invalidate_rfq_packets(principal, offer["rfq_id"])
            return result

    def confirm_terms(self, principal, proposal_id, manual_confirmation=False):
        self._check(principal)
        if not isinstance(manual_confirmation, bool):
            raise ValueError("invalid_manual_confirmation")
        conflict = None
        response = None
        with self._lock:
            self._refresh()
            with self._db:
                self._db.execute("BEGIN IMMEDIATE")
                row, proposal = self._proposal_row(principal, proposal_id)
                if row["invalidated"]:
                    conflict = "proposal_invalidated"
                else:
                    existing = self._db.execute("SELECT payload FROM confirmations WHERE proposal_id=?", (proposal_id,)).fetchone()
                    if existing:
                        response = {"confirmation": json.loads(existing[0]), "duplicate": True}
                    elif proposal["model_state"] == "failed" and not manual_confirmation:
                        conflict = "manual_confirmation_required"
                    else:
                        confirmation = {"id": _id(), "proposal_id": proposal_id, "offer_id": row["offer_id"],
                                        "actor_id": principal["id"], "timestamp": _now(),
                                        "fingerprint": row["proposal_fingerprint"],
                                        "manual_confirmation": manual_confirmation,
                                        "scope": "terms_confirmation_only_not_purchase_acceptance"}
                        self._db.execute("INSERT INTO confirmations VALUES(?,?)",
                                         (proposal_id, json.dumps(confirmation, ensure_ascii=False)))
                        self._audit_event(principal, row["rfq_id"], "terms_confirmed", proposal_id=proposal_id,
                                          offer_id=row["offer_id"], confirmation_id=confirmation["id"],
                                          manual_confirmation=manual_confirmation)
                        response = {"confirmation": confirmation, "duplicate": False}
        if conflict:
            raise WorkflowConflictError(conflict)
        return response

    def _current_extractions(self, principal, rfq_id):
        offers = self._current_offers(rfq_id)
        if len(offers) != 3:
            return None
        extractions, proposals, confirmations = [], [], []
        for offer in offers:
            selected = self._db.execute("SELECT proposal_id FROM selections WHERE rfq_id=? AND supplier_id=?",
                                        (rfq_id, offer["supplier_id"])).fetchone()
            if selected is None:
                return None
            row, payload = self._proposal_row(principal, selected[0])
            confirmation = self._db.execute("SELECT payload FROM confirmations WHERE proposal_id=?", (selected[0],)).fetchone()
            if row["invalidated"] or not confirmation:
                return None
            confirmed = json.loads(confirmation[0])
            if confirmed["fingerprint"] != row["proposal_fingerprint"]:
                self._invalidate_proposal(principal, row, "confirmed_terms_changed")
                return None
            extractions.append(payload)
            proposals.append(row["id"])
            confirmations.append(confirmed["id"])
        return extractions, proposals, confirmations

    @staticmethod
    def _packet_fingerprint(selected, scenario):
        extractions, proposals, confirmations = selected
        return _hash({"commercial": calculation.packet_fingerprint(extractions, scenario, rule_version=calculation.RULE_VERSION),
                      "proposal_ids": proposals, "confirmation_ids": confirmations})

    def _packet_row(self, principal, packet_id):
        self._check(principal)
        selected_row = self._db.execute("SELECT id,rfq_id,payload,invalidated FROM packets WHERE id=?", (packet_id,)).fetchone()
        if selected_row is None:
            raise KeyError("packet_not_found")
        row = dict(zip(("id", "rfq_id", "payload", "invalidated"), selected_row))
        payload = json.loads(row["payload"])
        scenario = self._scenario(row["rfq_id"])
        selected = self._current_extractions(principal, row["rfq_id"]) if row["rfq_id"] in self._rfqs else None
        stale = bool(row["invalidated"]) or scenario is None or selected is None
        if not stale:
            try:
                stale = (payload["fingerprint"] != self._packet_fingerprint(selected, scenario)
                         or payload["rule_version"] != calculation.RULE_VERSION)
            except (ValueError, KeyError, TypeError):
                stale = True
        if stale:
            self._invalidate_packet(principal, row)
        return row, payload

    def _invalidate_rfq_packets(self, principal, rfq_id):
        for (packet_id,) in self._db.execute("SELECT id FROM packets WHERE rfq_id=? AND invalidated=0", (rfq_id,)).fetchall():
            self._packet_row(principal, packet_id)

    def calculate(self, principal, rfq_id, scenario):
        self._check(principal)
        scenario = calculation.normalize_scenario(scenario)
        conflict = False
        response = None
        with self._lock:
            self._refresh()
            self._rfq(principal, rfq_id)
            with self._db:
                self._db.execute("BEGIN IMMEDIATE")
                selected = self._current_extractions(principal, rfq_id)
                if selected is None:
                    self._invalidate_rfq_packets(principal, rfq_id)
                    conflict = True
                else:
                    response = calculation.compare_offers(selected[0], scenario)
                    response.update({"id": _id(), "rfq_id": rfq_id, "proposal_ids": selected[1],
                                     "confirmation_ids": selected[2], "fingerprint": self._packet_fingerprint(selected, scenario),
                                     "status": "pending_packet_review", "review": None, "stale": False, "audit": []})
                    self._db.execute("INSERT INTO scenarios VALUES(?,?) ON CONFLICT(rfq_id) DO UPDATE SET payload=excluded.payload",
                                     (rfq_id, json.dumps(scenario, ensure_ascii=False)))
                    self._invalidate_rfq_packets(principal, rfq_id)
                    self._db.execute("INSERT INTO packets(id,rfq_id,payload) VALUES(?,?,?)",
                                     (response["id"], rfq_id, json.dumps(response, ensure_ascii=False)))
                    self._audit_event(principal, rfq_id, "packet_created", packet_id=response["id"],
                                      fingerprint=response["fingerprint"], rule_version=calculation.RULE_VERSION)
        if conflict:
            raise WorkflowConflictError("terms_confirmation_required")
        return self.packet(principal, response["id"])

    @staticmethod
    def _packet_shell(row):
        return {"id": row["id"], "rfq_id": row["rfq_id"], "status": "invalidated", "stale": True,
                "rows": [], "cost_order": [], "review": None, "audit": [],
                "invalidation_reason": "source_terms_selection_scenario_or_rule_changed"}

    def packet(self, principal, packet_id):
        with self._lock:
            self._check(principal)
            self._refresh()
            with self._db:
                row, payload = self._packet_row(principal, packet_id)
                if row["invalidated"]:
                    return self._packet_shell(row)
                review = self._db.execute("SELECT payload FROM reviews WHERE packet_id=?", (packet_id,)).fetchone()
                if review:
                    payload["review"] = json.loads(review[0])
                    payload["status"] = "review_recorded"
                payload["audit"] = self._events(row["rfq_id"], packet_id=packet_id)
                return payload

    def review_packet(self, principal, packet_id, decision, comment="", expected_fingerprint=None):
        self._check(principal)
        if principal["role"] != "reviewer":
            raise PermissionError("reviewer_required")
        if decision not in ("reviewed", "needs_followup") or not isinstance(comment, str) or len(comment) > 2000:
            raise ValueError("invalid_review")
        if not isinstance(expected_fingerprint, str) or len(expected_fingerprint) != 64:
            raise WorkflowConflictError("current_fingerprint_required")
        conflict = None
        response = None
        with self._lock:
            self._refresh()
            with self._db:
                self._db.execute("BEGIN IMMEDIATE")
                row, packet = self._packet_row(principal, packet_id)
                if row["invalidated"]:
                    conflict = "packet_invalidated"
                elif expected_fingerprint != packet["fingerprint"]:
                    conflict = "fingerprint_mismatch"
                else:
                    existing = self._db.execute("SELECT payload FROM reviews WHERE packet_id=?", (packet_id,)).fetchone()
                    if existing:
                        response = {"review": json.loads(existing[0]), "duplicate": True}
                    else:
                        review = {"id": _id(), "packet_id": packet_id, "decision": decision, "comment": comment,
                                  "reviewer_id": principal["id"], "timestamp": _now(), "fingerprint": expected_fingerprint,
                                  "scope": "packet_acknowledgement_not_supplier_or_order_approval"}
                        self._db.execute("INSERT INTO reviews VALUES(?,?)", (packet_id, json.dumps(review, ensure_ascii=False)))
                        self._audit_event(principal, row["rfq_id"], "packet_reviewed", packet_id=packet_id,
                                          decision=decision, review_id=review["id"], fingerprint=expected_fingerprint)
                        response = {"review": review, "duplicate": False}
        if conflict:
            raise WorkflowConflictError(conflict)
        return response

    def _events(self, rfq_id, packet_id=None):
        events = [json.loads(row[0]) for row in self._db.execute(
            "SELECT payload FROM audit WHERE rfq_id=? ORDER BY sequence", (rfq_id,)).fetchall()]
        for event in events:
            linked_packet = event.get("packet_id")
            linked_proposal = event.get("proposal_id")
            event["historical"] = False
            if linked_packet:
                row = self._db.execute("SELECT invalidated FROM packets WHERE id=?", (linked_packet,)).fetchone()
                event["historical"] = bool(row and row[0])
            elif linked_proposal:
                row = self._db.execute("SELECT invalidated FROM proposals WHERE id=?", (linked_proposal,)).fetchone()
                event["historical"] = bool(row and row[0])
        return [event for event in events if packet_id is None or event.get("packet_id") == packet_id]

    def audit(self, principal, rfq_id):
        with self._lock:
            self._check(principal)
            self._refresh()
            self._rfq(principal, rfq_id)
            with self._db:
                for (proposal_id,) in self._db.execute("SELECT id FROM proposals WHERE rfq_id=?", (rfq_id,)).fetchall():
                    self._proposal_row(principal, proposal_id)
                self._invalidate_rfq_packets(principal, rfq_id)
                return self._events(rfq_id)
