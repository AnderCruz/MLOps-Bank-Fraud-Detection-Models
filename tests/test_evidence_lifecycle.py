"""Behavioral tests for Evidence Acquisition v3 lifecycle enforcement."""
import copy
import json
import unittest
from pathlib import Path

from src.evidence_lifecycle import (
    LifecycleValidationError,
    TRANSITIONS,
    accept_evidence,
    authorize_request,
    complete_review,
    dispatch_request,
    deny_authorization,
    invalidate_acceptance,
    receive_response,
    record_evidence_disposition,
    resolve_decision,
    start_review,
    start_review_correction,
    validate_event_history,
    validate_package,
)


ACTOR = {"role": "TEST_REVIEWER"}
WHEN = "2026-10-16T12:00:00+00:00"
TEST_AUTHORIZATION_POLICY = {
    "policy_id": "SYNTHETIC-TEST-POLICY", "status": "TEST_ONLY",
    "allowed_roles_by_scope": {
        "request_authorization": ["TEST_REVIEWER"],
        "evidence_review": ["TEST_REVIEWER"],
        "evidence_acceptance": ["TEST_REVIEWER"],
        "decision_resolution": ["TEST_REVIEWER"],
    },
}


def request_record():
    return {
        "request_id": "REQ-TEST-1", "request_status": "PREPARED",
        "authorization": {"status": "PENDING", "records": [], "current_authorization_id": None},
        "dispatch": {"status": "NOT_SENT", "records": [], "current_dispatch_id": None},
        "response_status": "PENDING", "response_versions": [],
        "current_response_version_id": None, "review_status": "PENDING",
        "review_versions": [], "current_review_version_id": None,
    }


def response_version(version_id="RESP-1", supersedes=None, **extra):
    value = {
        "response_version_id": version_id, "supersedes_response_version_id": supersedes,
        "correction_reason": "Corrected source record" if supersedes else None,
        "request_id": "REQ-TEST-1", "received_at_utc": WHEN,
        "respondent": {"role": "TEST_RESPONDENT"}, "provenance_status": "VERIFIED",
        "source_references": ["SYNTHETIC-SOURCE-1"],
    }
    value.update(extra)
    return value


def authorized_and_sent():
    req, history = request_record(), []
    req, history = authorize_request(
        req,
        {"authorization_id": "AUTH-1", "request_id": req["request_id"],
         "status": "AUTHORIZED", "authorized_by": ACTOR, "authorized_at_utc": WHEN},
        event_id="EV-AUTH-REQ", authorization_event_id="EV-AUTH-RECORD",
        actor=ACTOR, occurred_at_utc=WHEN, history=history,
        authorization_policy=TEST_AUTHORIZATION_POLICY,
    )
    req, history = dispatch_request(
        req, {"dispatch_id": "DSP-1", "request_id": req["request_id"],
              "dispatch_reference": "SYNTHETIC-OUTBOUND-REF", "sender": ACTOR,
              "sent_at_utc": WHEN}, event_id="EV-DISPATCH", actor=ACTOR,
        occurred_at_utc=WHEN, history=history,
    )
    return req, history


class TestRequestAndResponseLifecycle(unittest.TestCase):
    def test_authorize_then_dispatch_is_valid(self):
        req, history = authorized_and_sent()
        self.assertEqual(req["request_status"], "AUTHORIZED")
        self.assertEqual(req["dispatch"]["status"], "SENT")
        self.assertEqual(len(history), 3)

    def test_dispatch_without_authorization_is_rejected(self):
        with self.assertRaisesRegex(LifecycleValidationError, "AUTHORIZED"):
            dispatch_request(request_record(), {}, event_id="EV", actor=ACTOR,
                             occurred_at_utc=WHEN, history=[])

    def test_denial_is_recorded_and_remains_undispatched(self):
        req, history = request_record(), []
        req, history = deny_authorization(
            req, {"authorization_id": "DENY-1", "request_id": req["request_id"],
                  "reason": "Synthetic denial", "authorized_by": ACTOR,
                  "authorized_at_utc": WHEN}, event_id="EV-DENY", actor=ACTOR,
            occurred_at_utc=WHEN, history=history,
            authorization_policy=TEST_AUTHORIZATION_POLICY)
        self.assertEqual(req["authorization"]["status"], "DENIED")
        self.assertEqual(req["dispatch"]["status"], "NOT_SENT")

    def test_missing_authorization_attribution_or_timestamp_is_rejected(self):
        req = request_record()
        auth = {"authorization_id": "A", "request_id": req["request_id"],
                "status": "AUTHORIZED", "authorized_by": {}, "authorized_at_utc": WHEN}
        with self.assertRaises(LifecycleValidationError):
            authorize_request(req, auth, event_id="E1", authorization_event_id="E2",
                              actor=ACTOR, occurred_at_utc=WHEN, history=[], authorization_policy=TEST_AUTHORIZATION_POLICY)
        auth["authorized_by"] = ACTOR
        auth["authorized_at_utc"] = "not-a-date"
        with self.assertRaises(LifecycleValidationError):
            authorize_request(req, auth, event_id="E1", authorization_event_id="E2",
                              actor=ACTOR, occurred_at_utc=WHEN, history=[], authorization_policy=TEST_AUTHORIZATION_POLICY)

    def test_response_requires_verified_provenance_or_documented_exception(self):
        req, history = authorized_and_sent()
        bad = response_version(provenance_status="UNKNOWN", source_references=[])
        with self.assertRaisesRegex(LifecycleValidationError, "provenance"):
            receive_response(req, bad, event_id="EV-RESPONSE", actor=ACTOR,
                             occurred_at_utc=WHEN, history=history)

    def test_response_correction_preserves_history_and_requires_explicit_supersession(self):
        req, history = authorized_and_sent()
        req, history = receive_response(req, response_version(), event_id="EV-RESP-1",
                                        actor=ACTOR, occurred_at_utc=WHEN, history=history)
        replacement = response_version("RESP-2", "RESP-1", supersedes_event_id="EV-RESP-1")
        replacement["correction_reason"] = "Source correction"
        req2, history2 = receive_response(req, replacement, event_id="EV-RESP-2",
                                          actor=ACTOR, occurred_at_utc=WHEN,
                                          history=history, material_change=True)
        self.assertEqual([x["response_version_id"] for x in req2["response_versions"]], ["RESP-1", "RESP-2"])
        self.assertEqual(req2["current_response_version_id"], "RESP-2")
        self.assertTrue(req2["response_versions"][-1]["material_change"])
        self.assertEqual(len(history2), len(history) + 1)  # correction event
        initial = {("REQ-TEST-1", "request_status"): "PREPARED",
                   ("REQ-TEST-1", "authorization_status"): "PENDING",
                   ("REQ-TEST-1", "dispatch_status"): "NOT_SENT",
                   ("REQ-TEST-1", "response_status"): "PENDING"}
        replayed = validate_event_history(history2, entity_ids={"REQ-TEST-1"}, initial_states=initial,
                                          authorization_policy=TEST_AUTHORIZATION_POLICY)
        self.assertEqual(replayed[("REQ-TEST-1", "response_status")], "RECEIVED")

    def test_cyclic_supersession_chain_is_rejected(self):
        req, history = authorized_and_sent()
        req.update({"response_status": "RECEIVED", "current_response_version_id": "RESP-1",
                    "response_versions": [
                        {"response_version_id": "RESP-1", "supersedes_response_version_id": "RESP-2"},
                        {"response_version_id": "RESP-2", "supersedes_response_version_id": "RESP-1"},
                    ]})
        history.append({"event_id": "EV-RESP-1", "entity_type": "request",
                        "entity_id": req["request_id"], "domain": "response_status",
                        "event_type": "RESPONSE_RECEIVED", "previous_status": "PENDING",
                        "resulting_status": "RECEIVED", "actor": ACTOR,
                        "occurred_at_utc": WHEN, "supporting_record_refs": ["SRC"]})
        replacement = response_version("RESP-3", "RESP-1", supersedes_event_id="EV-RESP-1")
        with self.assertRaisesRegex(LifecycleValidationError, "acyclic"):
            receive_response(req, replacement, event_id="EV-RESP-3", actor=ACTOR,
                             occurred_at_utc=WHEN, history=history, material_change=True)

    def test_invalid_supersession_reference_is_rejected(self):
        req, history = authorized_and_sent()
        req, history = receive_response(req, response_version(), event_id="EV-RESP-1",
                                        actor=ACTOR, occurred_at_utc=WHEN, history=history)
        replacement = response_version("RESP-2", "RESP-1", supersedes_event_id="MISSING")
        with self.assertRaisesRegex(LifecycleValidationError, "current response version's receipt event"):
            receive_response(req, replacement, event_id="EV-RESP-2", actor=ACTOR,
                             occurred_at_utc=WHEN, history=history, material_change=True)


class TestReviewAcceptanceAndDecision(unittest.TestCase):
    def setUp(self):
        req, events = authorized_and_sent()
        req, events = receive_response(req, response_version(), event_id="EV-RESP-1",
                                       actor=ACTOR, occurred_at_utc=WHEN, history=events)
        self.entity = {**req, "evidence_gap_id": "EVD-SYNTH-1", "review_versions": [],
                       "current_review_version_id": None, "review_status": "PENDING"}
        self.events = events

    def review(self, review_id="REV-1", supersedes=None, outcome="ACCEPTED", sufficiency="SUFFICIENT"):
        return {"review_id": review_id, "supersedes_review_id": supersedes,
                "correction_reason": "Review correction" if supersedes else None,
                "response_version_id": "RESP-1", "reviewer": ACTOR,
                "reviewed_at_utc": WHEN, "rationale": "Synthetic test rationale",
                "source_references": ["SYNTHETIC-SOURCE-1"],
                "outcome": outcome, "sufficiency_assessment": sufficiency}

    def test_review_requires_current_response_and_provenance_fields(self):
        started, events = start_review(self.entity, event_id="EV-REVIEW-START",
                                       actor=ACTOR, occurred_at_utc=WHEN, history=self.events)
        bad = self.review()
        bad["response_version_id"] = "WRONG"
        with self.assertRaisesRegex(LifecycleValidationError, "current response"):
            complete_review(started, bad, event_id="EV-REV", actor=ACTOR,
                            occurred_at_utc=WHEN, history=events,
                            authorization_policy=TEST_AUTHORIZATION_POLICY)

    def test_acceptance_requires_qualifying_review_and_support(self):
        with self.assertRaisesRegex(LifecycleValidationError, "ACCEPTED current review"):
            accept_evidence({"evidence_gap_id": "EVD-SYNTH-1", "review_status": "PENDING"}, {},
                            event_id="EV-ACC", actor=ACTOR, occurred_at_utc=WHEN, history=[])
        started, events = start_review(self.entity, event_id="EV-REVIEW-START",
                                       actor=ACTOR, occurred_at_utc=WHEN, history=self.events)
        reviewed, events = complete_review(started, self.review(), event_id="EV-REV-1",
                                           actor=ACTOR, occurred_at_utc=WHEN, history=events,
                                           authorization_policy=TEST_AUTHORIZATION_POLICY)
        acceptance = {"acceptance_id": "ACC-1", "supporting_review_id": "REV-1",
                      "rationale": "Supported by reviewed synthetic source.",
                      "source_references": ["SYNTHETIC-SOURCE-1"], "approver": ACTOR,
                      "accepted_at_utc": WHEN}
        accepted, events = accept_evidence({**reviewed, "acceptance_status": "NOT_ASSESSED"}, acceptance,
                                           event_id="EV-ACC-1", actor=ACTOR,
                                           occurred_at_utc=WHEN, history=events,
                                           authorization_policy=TEST_AUTHORIZATION_POLICY)
        self.assertEqual(accepted["acceptance_status"], "ACCEPTED")
        self.assertEqual(len(accepted["acceptance_versions"]), 1)
        with self.assertRaisesRegex(LifecycleValidationError, "source references"):
            broken = dict(acceptance, acceptance_id="ACC-2", source_references=[])
            accept_evidence({**reviewed, "acceptance_status": "NOT_ASSESSED"}, broken,
                            event_id="EV-ACC-2", actor=ACTOR, occurred_at_utc=WHEN,
                            history=events, authorization_policy=TEST_AUTHORIZATION_POLICY)

    def test_inconclusive_review_cannot_produce_partial_acceptance(self):
        started, events = start_review(self.entity, event_id="EV-REVIEW-START",
                                       actor=ACTOR, occurred_at_utc=WHEN, history=self.events)
        reviewed, events = complete_review(started,
                                           self.review(outcome="INCONCLUSIVE", sufficiency="INSUFFICIENT"),
                                           event_id="EV-REV-INCONCLUSIVE", actor=ACTOR,
                                           occurred_at_utc=WHEN, history=events,
                                           authorization_policy=TEST_AUTHORIZATION_POLICY)
        disposition = {"acceptance_status": "PARTIAL", "acceptance_id": "ACC-PARTIAL",
                      "supporting_review_id": "REV-1", "rationale": "Synthetic disposition",
                      "source_references": ["SYNTHETIC-SOURCE-1"], "approver": ACTOR,
                      "accepted_at_utc": WHEN}
        with self.assertRaisesRegex(LifecycleValidationError, "cannot produce accepted evidence"):
            record_evidence_disposition({**reviewed, "acceptance_status": "NOT_ASSESSED"}, disposition,
                                        event_id="EV-DISPOSITION", actor=ACTOR,
                                        occurred_at_utc=WHEN, history=events,
                                        authorization_policy=TEST_AUTHORIZATION_POLICY)
        disposition["acceptance_status"] = "REJECTED"
        rejected, events = record_evidence_disposition(
            {**reviewed, "acceptance_status": "NOT_ASSESSED"}, disposition,
            event_id="EV-DISPOSITION-REJECTED", actor=ACTOR,
            occurred_at_utc=WHEN, history=events,
            authorization_policy=TEST_AUTHORIZATION_POLICY)
        self.assertEqual(rejected["acceptance_status"], "REJECTED")
        replayed = validate_event_history(
            events, entity_ids={"REQ-TEST-1", "EVD-SYNTH-1"},
            initial_states={("REQ-TEST-1", "request_status"): "PREPARED",
                            ("REQ-TEST-1", "authorization_status"): "PENDING",
                            ("REQ-TEST-1", "dispatch_status"): "NOT_SENT",
                            ("REQ-TEST-1", "response_status"): "PENDING",
                            ("EVD-SYNTH-1", "review_status"): "PENDING",
                            ("EVD-SYNTH-1", "acceptance_status"): "NOT_ASSESSED"},
            authorization_policy=TEST_AUTHORIZATION_POLICY)
        self.assertEqual(replayed[("EVD-SYNTH-1", "acceptance_status")], "REJECTED")

    def test_review_correction_preserves_previous_version(self):
        started, events = start_review(self.entity, event_id="EV-REVIEW-START",
                                       actor=ACTOR, occurred_at_utc=WHEN, history=self.events)
        reviewed, events = complete_review(started, self.review(), event_id="EV-REV-1",
                                           actor=ACTOR, occurred_at_utc=WHEN, history=events,
                                           authorization_policy=TEST_AUTHORIZATION_POLICY)
        reopened, events = start_review_correction(reviewed, event_id="EV-REOPEN",
                                                    actor=ACTOR, occurred_at_utc=WHEN,
                                                    reason="Material source correction",
                                                    history=events)
        corrected = self.review("REV-2", "REV-1")
        final, events = complete_review(reopened, corrected, event_id="EV-REV-2",
                                        actor=ACTOR, occurred_at_utc=WHEN, history=events,
                                        authorization_policy=TEST_AUTHORIZATION_POLICY)
        self.assertEqual([x["review_id"] for x in final["review_versions"]], ["REV-1", "REV-2"])
        self.assertEqual(final["current_review_version_id"], "REV-2")
        self.assertFalse(final["re_review_required"])
        initial = {("REQ-TEST-1", "request_status"): "PREPARED",
                   ("REQ-TEST-1", "authorization_status"): "PENDING",
                   ("REQ-TEST-1", "dispatch_status"): "NOT_SENT",
                   ("REQ-TEST-1", "response_status"): "PENDING",
                   ("EVD-SYNTH-1", "review_status"): "PENDING"}
        replayed = validate_event_history(events, entity_ids={"REQ-TEST-1", "EVD-SYNTH-1"},
                                          initial_states=initial, authorization_policy=TEST_AUTHORIZATION_POLICY)
        self.assertEqual(replayed[("EVD-SYNTH-1", "review_status")], "ACCEPTED")

    def test_acceptance_invalidation_keeps_prior_record_and_requires_rereview(self):
        started, events = start_review(self.entity, event_id="EV-REVIEW-START",
                                       actor=ACTOR, occurred_at_utc=WHEN, history=self.events)
        reviewed, events = complete_review(started, self.review(), event_id="EV-REV-1",
                                           actor=ACTOR, occurred_at_utc=WHEN, history=events,
                                           authorization_policy=TEST_AUTHORIZATION_POLICY)
        acceptance = {"acceptance_id": "ACC-1", "supporting_review_id": "REV-1",
                      "rationale": "Rationale", "source_references": ["SRC"],
                      "approver": ACTOR, "accepted_at_utc": WHEN}
        accepted, events = accept_evidence({**reviewed, "acceptance_status": "NOT_ASSESSED"}, acceptance,
                                           event_id="EV-ACC-1", actor=ACTOR,
                                           occurred_at_utc=WHEN, history=events,
                                           authorization_policy=TEST_AUTHORIZATION_POLICY)
        invalidated, events = invalidate_acceptance(
            accepted, event_id="EV-ACC-INVALID", actor=ACTOR, occurred_at_utc=WHEN,
            supersedes_event_id="EV-ACC-1", reason="Material response correction",
            affected_response_version_id="RESP-2", history=events)
        self.assertEqual(invalidated["acceptance_status"], "NOT_ASSESSED")
        self.assertIsNone(invalidated["current_acceptance_id"])
        self.assertEqual(len(invalidated["acceptance_versions"]), 1)
        self.assertTrue(invalidated["re_review_required"])

    def test_decision_resolution_requires_authorization_and_record(self):
        decision = {"decision_id": "DEC-SYNTH-1", "resolution_status": "OPEN", "resolution_records": []}
        resolution = {"decision_id": "DEC-SYNTH-1", "resolution_record_id": "RES-1",
                      "authorization": {"status": "PENDING"}, "decision_maker": ACTOR,
                      "resolved_at_utc": WHEN, "supporting_evidence_refs": ["EVD-SYNTH-1"],
                      "outcome": "RECORDED", "rationale": "Synthetic test"}
        with self.assertRaisesRegex(LifecycleValidationError, "explicit authorization"):
            resolve_decision(decision, resolution, event_id="EV-RES", actor=ACTOR,
                             occurred_at_utc=WHEN, history=[])


class TestHistoryIntegrity(unittest.TestCase):
    def test_duplicate_ids_unknown_entities_and_bad_previous_state_are_rejected(self):
        base = {"event_id": "E1", "entity_type": "request", "entity_id": "R1",
                "domain": "request_status", "event_type": "REQUEST_AUTHORIZED",
                "previous_status": "PREPARED", "resulting_status": "AUTHORIZED",
                "actor": ACTOR, "occurred_at_utc": WHEN, "supporting_record_refs": []}
        initial = {("R1", "request_status"): "PREPARED"}
        replay = validate_event_history([base], entity_ids={"R1"}, initial_states=initial)
        self.assertEqual(replay[("R1", "request_status")], "AUTHORIZED")
        with self.assertRaisesRegex(LifecycleValidationError, "unique"):
            validate_event_history([base, dict(base)], entity_ids={"R1"}, initial_states=initial)
        with self.assertRaisesRegex(LifecycleValidationError, "Unknown history entity"):
            validate_event_history([dict(base, entity_id="MISSING")], entity_ids={"R1"}, initial_states=initial)
        with self.assertRaisesRegex(LifecycleValidationError, "Previous-state mismatch"):
            validate_event_history([dict(base, previous_status="CANCELLED")], entity_ids={"R1"}, initial_states=initial)

    def test_terminal_state_transition_requires_explicit_correction(self):
        from src.evidence_lifecycle import validate_transition
        with self.assertRaisesRegex(LifecycleValidationError, "Invalid request_status transition"):
            validate_transition("request_status", "CANCELLED", "AUTHORIZED")

    def test_event_order_and_supersession_cycles_are_rejected(self):
        e1 = {"event_id": "E1", "entity_type": "request", "entity_id": "R1",
              "domain": "response_status", "event_type": "RESPONSE_RECEIVED",
              "previous_status": "PENDING", "resulting_status": "RECEIVED",
              "actor": ACTOR, "occurred_at_utc": WHEN, "supporting_record_refs": []}
        e2 = dict(e1, event_id="E2", event_type="RESPONSE_SUPERSEDED",
                  previous_status="RECEIVED", resulting_status="RECEIVED",
                  supersedes_event_id="E1", reason="Correction",
                  occurred_at_utc="2026-10-16T11:00:00+00:00")
        with self.assertRaisesRegex(LifecycleValidationError, "out of order"):
            validate_event_history([e1, e2], entity_ids={"R1"},
                                   initial_states={("R1", "response_status"): "PENDING"})


class TestV3PackageTraceability(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        self.package = json.loads(next((root / "reports/evidence_acquisition_v3").glob("*/evidence_acquisition.json")).read_text())
        self.plan = json.loads(next((root / "reports/operational_planning_v2").glob("*/operational_planning.json")).read_text())

    def test_current_package_validates_and_contains_only_open_lifecycle_states(self):
        validate_package(self.package, self.plan)
        self.assertEqual(self.package["lifecycle_events"], [])
        self.assertTrue(all(r["request_status"] == "PREPARED" for r in self.package["stakeholder_request_templates"]))
        self.assertTrue(all(r["dispatch"]["status"] == "NOT_SENT" for r in self.package["stakeholder_request_templates"]))
        self.assertTrue(all(x["acceptance_status"] == "NOT_ASSESSED" for x in self.package["evidence_results"]))
        self.assertTrue(all(x["resolution_status"] == "OPEN" for x in self.package["decision_resolution_records"]))

    def test_transition_table_and_materialized_state_match_the_validator(self):
        expected = {domain: {state: sorted(targets) for state, targets in states.items()}
                    for domain, states in TRANSITIONS.items()}
        recorded = {domain: {state: sorted(targets) for state, targets in states.items()}
                    for domain, states in self.package["lifecycle_transition_rules"].items()}
        self.assertEqual(recorded, expected)

    def test_accepted_evidence_without_completed_review_is_rejected(self):
        bad = copy.deepcopy(self.package)
        bad["evidence_results"][0]["acceptance_status"] = "ACCEPTED"
        bad["evidence_results"][0]["current_acceptance_id"] = "ACC-SYNTH"
        bad["evidence_results"][0]["acceptance_versions"] = [{"acceptance_id": "ACC-SYNTH"}]
        with self.assertRaisesRegex(LifecycleValidationError, "current accepted review"):
            validate_package(bad, self.plan)

    def test_duplicate_legacy_status_and_direct_link_divergence_are_rejected(self):
        bad = copy.deepcopy(self.package)
        bad["stakeholder_request_templates"][0]["status"] = "NOT_SENT"
        with self.assertRaisesRegex(LifecycleValidationError, "Duplicate request lifecycle status"):
            validate_package(bad, self.plan)
        bad = copy.deepcopy(self.package)
        bad["stakeholder_request_templates"][0]["response"]["status"] = "RECEIVED"
        with self.assertRaisesRegex(LifecycleValidationError, "Nested response status"):
            validate_package(bad, self.plan)
        bad = copy.deepcopy(self.package)
        bad["traceability"][5]["requirement_ids"] = ["OPS-10"]
        with self.assertRaisesRegex(LifecycleValidationError, "traceability mismatch"):
            validate_package(bad, self.plan)
        bad = copy.deepcopy(self.package)
        bad["traceability"][5]["direct_decision_ids"] = ["DEC-OPS-10"]
        with self.assertRaisesRegex(LifecycleValidationError, "traceability mismatch"):
            validate_package(bad, self.plan)
        bad = copy.deepcopy(self.package)
        bad["traceability"][5]["acquisition_task_ids"] = []
        with self.assertRaisesRegex(LifecycleValidationError, "Acquisition task traceability mismatch"):
            validate_package(bad, self.plan)


if __name__ == "__main__":
    unittest.main()
