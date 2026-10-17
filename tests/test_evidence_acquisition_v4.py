"""Behavioral regression tests for Evidence Acquisition v4 integrity controls."""
import copy
import json
import unittest
from pathlib import Path

from src.evidence_lifecycle import (
    LifecycleValidationError,
    accept_evidence,
    authorize_request,
    complete_review,
    dispatch_request,
    receive_response,
    resolve_decision,
    start_review,
    validate_event_history,
    validate_package,
)


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PATH = next((ROOT / "reports/evidence_acquisition_v4").glob("*/evidence_acquisition.json"))
PLAN_PATH = next((ROOT / "reports/operational_planning_v2").glob("*/operational_planning.json"))
ACTOR = {"role": "TEST_REVIEWER"}
WHEN = "2026-10-16T12:00:00+00:00"
POLICY = {
    "policy_id": "SYNTHETIC-ONLY",
    "status": "TEST_ONLY",
    "allowed_roles_by_scope": {
        scope: ["TEST_REVIEWER"] for scope in (
            "request_authorization", "evidence_review",
            "evidence_acceptance", "decision_resolution",
        )
    },
}


def package_and_plan():
    return json.loads(PACKAGE_PATH.read_text()), json.loads(PLAN_PATH.read_text())


def accepted_package():
    """Build a valid synthetic request/response/review/acceptance package."""
    package, _ = package_and_plan()
    request = next(x for x in package["stakeholder_request_templates"] if x["request_id"] == "STREQ-01")
    request, events = authorize_request(
        request,
        {"authorization_id": "AUTH-SYN", "request_id": "STREQ-01", "status": "AUTHORIZED",
         "authorized_by": ACTOR, "authorized_at_utc": WHEN},
        event_id="EV-AUTH-REQUEST", authorization_event_id="EV-AUTH-RECORD",
        actor=ACTOR, occurred_at_utc=WHEN, history=[], authorization_policy=POLICY,
    )
    request, events = dispatch_request(
        request, {"dispatch_id": "DSP-SYN", "request_id": "STREQ-01",
                  "dispatch_reference": "SYNTHETIC", "sender": ACTOR, "sent_at_utc": WHEN},
        event_id="EV-DISPATCH", actor=ACTOR, occurred_at_utc=WHEN, history=events,
    )
    request, events = receive_response(
        request, {"response_version_id": "RESP-SYN", "supersedes_response_version_id": None,
                  "request_id": "STREQ-01", "received_at_utc": WHEN, "respondent": ACTOR,
                  "provenance_status": "VERIFIED", "source_references": ["SOURCE-SYN"]},
        event_id="EV-RESPONSE", actor=ACTOR, occurred_at_utc=WHEN, history=events,
    )
    package["stakeholder_request_templates"] = [
        request if x["request_id"] == "STREQ-01" else x
        for x in package["stakeholder_request_templates"]
    ]
    result = next(x for x in package["evidence_results"] if x["evidence_gap_id"] == "EVD-01")
    result["current_response_version_id"] = "RESP-SYN"
    result["current_response_received_at_utc"] = WHEN
    result, events = start_review(result, event_id="EV-REVIEW-START", actor=ACTOR,
                                  occurred_at_utc=WHEN, history=events)
    result, events = complete_review(
        result, {"review_id": "REV-SYN", "supersedes_review_id": None,
                 "response_version_id": "RESP-SYN", "reviewer": ACTOR,
                 "reviewed_at_utc": WHEN, "rationale": "Synthetic review",
                 "source_references": ["SOURCE-SYN"], "outcome": "ACCEPTED",
                 "sufficiency_assessment": "SUFFICIENT"},
        event_id="EV-REVIEW-COMPLETE", actor=ACTOR, occurred_at_utc=WHEN,
        history=events, authorization_policy=POLICY,
    )
    result, events = accept_evidence(
        result, {"acceptance_id": "ACC-SYN", "supporting_review_id": "REV-SYN",
                 "rationale": "Synthetic acceptance", "source_references": ["SOURCE-SYN"],
                 "approver": ACTOR, "accepted_at_utc": WHEN},
        event_id="EV-ACCEPTANCE", actor=ACTOR, occurred_at_utc=WHEN,
        history=events, authorization_policy=POLICY,
    )
    package["evidence_results"] = [
        result if x["evidence_gap_id"] == "EVD-01" else x
        for x in package["evidence_results"]
    ]
    package["lifecycle_events"] = events
    return package


def add_resolution_record(package, evidence_refs):
    decision = next(x for x in package["decision_resolution_records"] if x["decision_id"] == "DEC-OPS-01")
    record = {
        "decision_id": "DEC-OPS-01", "resolution_record_id": "RES-SYN",
        "authorization": {"status": "AUTHORIZED", "authorized_by": ACTOR,
                          "authorized_at_utc": WHEN},
        "decision_maker": ACTOR, "resolved_at_utc": WHEN,
        "supporting_evidence_refs": list(evidence_refs),
        "outcome": "RECORDED", "rationale": "Synthetic resolution",
        "event_id": "EV-RESOLUTION",
    }
    decision["resolution_records"] = [record]
    decision["current_resolution_record_id"] = "RES-SYN"
    decision["resolution_status"] = "RESOLVED"
    package["lifecycle_events"].append({
        "event_id": "EV-RESOLUTION", "entity_type": "decision",
        "entity_id": "DEC-OPS-01", "domain": "resolution_status",
        "event_type": "DECISION_RESOLVED", "previous_status": "OPEN",
        "resulting_status": "RESOLVED", "actor": ACTOR,
        "occurred_at_utc": WHEN,
        "supporting_record_refs": ["RES-SYN", *evidence_refs],
    })
    return package


class TestEvidenceAcquisitionV4Package(unittest.TestCase):
    def test_open_v4_package_validates_and_keeps_all_evidence_open(self):
        package, plan = package_and_plan()
        validate_package(package, plan)
        self.assertEqual(len(package["evidence_availability_inventory"]), 13)
        self.assertEqual(len(package["stakeholder_request_templates"]), 13)
        self.assertEqual(len(package["evidence_results"]), 13)
        self.assertEqual(len(package["decision_resolution_records"]), 13)
        self.assertEqual(package["lifecycle_events"], [])
        self.assertTrue(all(x["request_status"] == "PREPARED" for x in package["stakeholder_request_templates"]))
        self.assertTrue(all(x["dispatch"]["status"] == "NOT_SENT" for x in package["stakeholder_request_templates"]))
        self.assertTrue(all(x["acceptance_status"] == "NOT_ASSESSED" for x in package["evidence_results"]))
        self.assertTrue(all(x["resolution_status"] == "OPEN" for x in package["decision_resolution_records"]))

    def test_valid_synthetic_accepted_evidence_and_decision_pass(self):
        package, plan = package_and_plan()
        package = accepted_package()
        validate_package(package, plan, authorization_policy=POLICY)
        decision, events = resolve_decision(
            next(x for x in package["decision_resolution_records"] if x["decision_id"] == "DEC-OPS-01"),
            {"decision_id": "DEC-OPS-01", "resolution_record_id": "RES-API",
             "authorization": {"status": "AUTHORIZED", "authorized_by": ACTOR, "authorized_at_utc": WHEN},
             "decision_maker": ACTOR, "resolved_at_utc": WHEN,
             "supporting_evidence_refs": ["EVD-01"], "outcome": "RECORDED",
             "rationale": "Synthetic accepted evidence"},
            event_id="EV-RES-API", actor=ACTOR, occurred_at_utc=WHEN,
            history=package["lifecycle_events"], evidence_results=package["evidence_results"],
            authorization_policy=POLICY, required_evidence_gap_ids=["EVD-01"],
        )
        package["decision_resolution_records"] = [
            decision if x["decision_id"] == "DEC-OPS-01" else x
            for x in package["decision_resolution_records"]
        ]
        package["lifecycle_events"] = events
        validate_package(package, plan, authorization_policy=POLICY)

    def test_resolution_rejects_pending_rejected_partial_missing_and_mixed_evidence(self):
        plan = package_and_plan()[1]
        cases = {
            "pending": (package_and_plan()[0], ["EVD-01"]),
            "nonexistent": (accepted_package(), ["EVD-MISSING"]),
            "mixed": (accepted_package(), ["EVD-01", "EVD-MISSING"]),
        }
        rejected = accepted_package()
        rejected_result = next(x for x in rejected["evidence_results"] if x["evidence_gap_id"] == "EVD-01")
        rejected_result["acceptance_status"] = "REJECTED"
        rejected_result["acceptance_versions"][-1]["acceptance_status"] = "REJECTED"
        cases["rejected"] = (rejected, ["EVD-01"])
        partial = accepted_package()
        partial_result = next(x for x in partial["evidence_results"] if x["evidence_gap_id"] == "EVD-01")
        partial_result["acceptance_status"] = "PARTIAL"
        partial_result["acceptance_versions"][-1]["acceptance_status"] = "PARTIAL"
        cases["partial"] = (partial, ["EVD-01"])
        for label, (package, refs) in cases.items():
            with self.subTest(label=label), self.assertRaises(LifecycleValidationError):
                validate_package(add_resolution_record(package, refs), plan, authorization_policy=POLICY)

    def test_resolution_record_requires_authorized_actor_claim_matching_policy(self):
        package, plan = package_and_plan()
        actor = {"role": "ARBITRARY_ROLE"}
        package["authorization_policy"] = package.get("authorization_policy", {})
        with self.assertRaisesRegex(LifecycleValidationError, "does not match the configured policy"):
            resolve_decision(
                {"decision_id": "D", "resolution_status": "OPEN", "resolution_records": []},
                {"decision_id": "D", "resolution_record_id": "R",
                 "authorization": {"status": "AUTHORIZED", "authorized_by": actor, "authorized_at_utc": WHEN},
                 "decision_maker": actor, "resolved_at_utc": WHEN,
                 "supporting_evidence_refs": ["EVD-01"], "outcome": "RECORDED", "rationale": "Synthetic"},
                event_id="EV", actor=actor, occurred_at_utc=WHEN, history=[],
                evidence_results=package["evidence_results"], authorization_policy=POLICY,
            )

    def test_current_acceptance_fields_and_review_binding_are_enforced(self):
        plan = package_and_plan()[1]
        mutations = {
            "review reference": lambda a: a.update(supporting_review_id="REV-OLD"),
            "rationale": lambda a: a.update(rationale=""),
            "source references": lambda a: a.update(source_references=[]),
            "approver": lambda a: a.update(approver={}),
            "timestamp": lambda a: a.update(accepted_at_utc="invalid"),
            "event link": lambda a: a.update(event_id="EV-MISSING"),
            "status": lambda a: a.update(acceptance_status="PARTIAL"),
        }
        for label, mutate in mutations.items():
            package = accepted_package()
            acceptance = next(x for x in package["evidence_results"] if x["evidence_gap_id"] == "EVD-01")["acceptance_versions"][0]
            mutate(acceptance)
            with self.subTest(label=label), self.assertRaises(LifecycleValidationError):
                validate_package(package, plan, authorization_policy=POLICY)

        package = accepted_package()
        result = next(x for x in package["evidence_results"] if x["evidence_gap_id"] == "EVD-01")
        result["review_versions"][0]["outcome"] = "REJECTED"
        with self.assertRaises(LifecycleValidationError):
            validate_package(package, plan, authorization_policy=POLICY)

    def test_duplicate_results_unknown_task_gaps_and_nonreciprocal_links_fail(self):
        plan = package_and_plan()[1]
        package = package_and_plan()[0]
        package["evidence_results"].append(copy.deepcopy(package["evidence_results"][0]))
        with self.assertRaisesRegex(LifecycleValidationError, "evidence-result gap IDs"):
            validate_package(package, plan)
        package = package_and_plan()[0]
        package["acquisition_tasks"][0]["related_evidence_gap_ids"].append("EVD-MISSING")
        with self.assertRaisesRegex(LifecycleValidationError, "Unknown evidence gap linked to task"):
            validate_package(package, plan)
        package = package_and_plan()[0]
        task_id = package["stakeholder_request_templates"][0]["related_acquisition_task_ids"][0]
        request_id = package["stakeholder_request_templates"][0]["request_id"]
        next(x for x in package["stakeholder_request_templates"] if x["request_id"] == request_id)["related_acquisition_task_ids"].remove(task_id)
        with self.assertRaisesRegex(LifecycleValidationError, "not reciprocal"):
            validate_package(package, plan)
        package = package_and_plan()[0]
        task_id = package["stakeholder_request_templates"][0]["related_acquisition_task_ids"][0]
        next(x for x in package["acquisition_tasks"] if x["task_id"] == task_id)["related_request_ids"].remove("STREQ-01")
        with self.assertRaisesRegex(LifecycleValidationError, "not reciprocal"):
            validate_package(package, plan)

    def test_duplicate_identifiers_direct_downstream_and_unknown_plan_ids_fail(self):
        plan = package_and_plan()[1]
        package = package_and_plan()[0]
        package["acquisition_tasks"][1]["task_id"] = package["acquisition_tasks"][0]["task_id"]
        with self.assertRaisesRegex(LifecycleValidationError, "task IDs"):
            validate_package(package, plan)
        package = package_and_plan()[0]
        gap = next(x for x in package["evidence_availability_inventory"] if x["evidence_gap_id"] == "EVD-06")
        gap["direct_related_requirement_ids"].append("OPS-10")
        gap["downstream_requirement_dependency_ids"].remove("OPS-10")
        with self.assertRaises(LifecycleValidationError):
            validate_package(package, plan)
        package = package_and_plan()[0]
        package["evidence_availability_inventory"][0]["direct_related_requirement_ids"].append("OPS-UNKNOWN")
        with self.assertRaises(LifecycleValidationError):
            validate_package(package, plan)
        package = package_and_plan()[0]
        package["evidence_availability_inventory"][0]["direct_related_decision_ids"].append("DEC-UNKNOWN")
        with self.assertRaises(LifecycleValidationError):
            validate_package(package, plan)

    def test_orphaned_review_acceptance_and_invalid_supersession_fail(self):
        plan = package_and_plan()[1]
        package = accepted_package()
        result = next(x for x in package["evidence_results"] if x["evidence_gap_id"] == "EVD-01")
        result["review_versions"][0]["event_id"] = "EV-ORPHAN"
        with self.assertRaisesRegex(LifecycleValidationError, "matching lifecycle event"):
            validate_package(package, plan, authorization_policy=POLICY)
        package = accepted_package()
        result = next(x for x in package["evidence_results"] if x["evidence_gap_id"] == "EVD-01")
        result["acceptance_versions"][0]["event_id"] = "EV-ORPHAN"
        with self.assertRaisesRegex(LifecycleValidationError, "matching lifecycle event"):
            validate_package(package, plan, authorization_policy=POLICY)
        package = accepted_package()
        request = next(x for x in package["stakeholder_request_templates"] if x["request_id"] == "STREQ-01")
        request["response_versions"][0]["supersedes_response_version_id"] = "RESP-MISSING"
        with self.assertRaisesRegex(LifecycleValidationError, "existing earlier version"):
            validate_package(package, plan, authorization_policy=POLICY)


class TestEvidenceAcquisitionV4EventContract(unittest.TestCase):
    def test_event_contract_rejects_unknown_type_entity_transition_and_refs(self):
        base = {"event_id": "EV-1", "entity_type": "request", "entity_id": "R1",
                "domain": "request_status", "event_type": "REQUEST_AUTHORIZED",
                "previous_status": "PREPARED", "resulting_status": "AUTHORIZED",
                "actor": ACTOR, "occurred_at_utc": WHEN, "supporting_record_refs": ["AUTH-1"]}
        initial = {("R1", "request_status"): "PREPARED"}
        with self.assertRaisesRegex(LifecycleValidationError, "Unknown event type"):
            validate_event_history([dict(base, event_type="MADE_UP")], entity_ids={"R1"}, initial_states=initial)
        with self.assertRaisesRegex(LifecycleValidationError, "entity_type"):
            validate_event_history([dict(base, entity_type="decision")], entity_ids={"R1"}, initial_states=initial)
        with self.assertRaisesRegex(LifecycleValidationError, "incompatible with its state transition"):
            validate_event_history([dict(base, resulting_status="CANCELLED")], entity_ids={"R1"}, initial_states=initial)
        cancellation = dict(base, event_type="REQUEST_CANCELLED", resulting_status="CANCELLED",
                            supporting_record_refs=[])
        with self.assertRaisesRegex(LifecycleValidationError, "require a non-empty reason"):
            validate_event_history([cancellation], entity_ids={"R1"}, initial_states=initial)
        with self.assertRaisesRegex(LifecycleValidationError, "valid authorization supporting record"):
            validate_event_history([base], entity_ids={"R1"}, initial_states=initial, record_index={})
        wrong_type = {"AUTH-1": [("dispatch", {})]}
        with self.assertRaisesRegex(LifecycleValidationError, "valid authorization supporting record"):
            validate_event_history([base], entity_ids={"R1"}, initial_states=initial, record_index=wrong_type)

    def test_event_contract_rejects_missing_or_unverified_actor_and_bad_history(self):
        event = {"event_id": "EV-A", "entity_type": "request", "entity_id": "R1",
                 "domain": "authorization_status", "event_type": "REQUEST_AUTHORIZATION_RECORDED",
                 "previous_status": "PENDING", "resulting_status": "AUTHORIZED",
                 "actor": ACTOR, "occurred_at_utc": WHEN, "supporting_record_refs": ["A1"]}
        states = {("R1", "authorization_status"): "PENDING"}
        index = {"A1": [("authorization", {})]}
        with self.assertRaises(LifecycleValidationError):
            validate_event_history([dict(event, actor={})], entity_ids={"R1"}, initial_states=states,
                                   record_index=index, authorization_policy=POLICY)
        with self.assertRaisesRegex(LifecycleValidationError, "does not match the configured policy"):
            validate_event_history([dict(event, actor={"role": "UNAUTHORIZED"})], entity_ids={"R1"},
                                   initial_states=states, record_index=index, authorization_policy=POLICY)
        with self.assertRaisesRegex(LifecycleValidationError, "unique"):
            validate_event_history([event, event], entity_ids={"R1"}, initial_states=states,
                                   record_index=index, authorization_policy=POLICY)
        with self.assertRaisesRegex(LifecycleValidationError, "Previous-state mismatch"):
            validate_event_history([dict(event, previous_status="AUTHORIZED")], entity_ids={"R1"},
                                   initial_states=states, record_index=index, authorization_policy=POLICY)

    def test_missing_reordered_duplicate_and_supersession_events_fail(self):
        package, plan = package_and_plan()
        request = package["stakeholder_request_templates"][0]
        authorized, _ = authorize_request(
            request, {"authorization_id": "AUTH-NO-EVENT", "request_id": request["request_id"],
                      "status": "AUTHORIZED", "authorized_by": ACTOR, "authorized_at_utc": WHEN},
            event_id="EV-MISSING", authorization_event_id="EV-AUTH-MISSING", actor=ACTOR,
            occurred_at_utc=WHEN, history=[], authorization_policy=POLICY,
        )
        package["stakeholder_request_templates"][0] = authorized
        with self.assertRaisesRegex(LifecycleValidationError, "event"):
            validate_package(package, plan, authorization_policy=POLICY)
        accepted = accepted_package()
        accepted["lifecycle_events"].reverse()
        with self.assertRaises(LifecycleValidationError):
            validate_package(accepted, plan, authorization_policy=POLICY)
        accepted = accepted_package()
        accepted["lifecycle_events"].append(copy.deepcopy(accepted["lifecycle_events"][-1]))
        with self.assertRaisesRegex(LifecycleValidationError, "unique"):
            validate_package(accepted, plan, authorization_policy=POLICY)
        event = {"event_id": "EV-CORR", "entity_type": "request", "entity_id": "R1",
                 "domain": "response_status", "event_type": "RESPONSE_SUPERSEDED",
                 "previous_status": "RECEIVED", "resulting_status": "RECEIVED",
                 "actor": ACTOR, "occurred_at_utc": WHEN, "supporting_record_refs": ["RESP-2"],
                 "supersedes_event_id": "EV-DOES-NOT-EXIST", "reason": "Correction"}
        with self.assertRaisesRegex(LifecycleValidationError, "prior event"):
            validate_event_history([event], entity_ids={"R1"},
                                   initial_states={("R1", "response_status"): "RECEIVED"})

    def test_dispatch_before_authorization_and_modified_acceptance_link_fail(self):
        package, plan = package_and_plan()
        request = next(x for x in package["stakeholder_request_templates"] if x["request_id"] == "STREQ-01")
        request, events = authorize_request(
            request, {"authorization_id": "AUTH-T", "request_id": "STREQ-01", "status": "AUTHORIZED",
                      "authorized_by": ACTOR, "authorized_at_utc": "2026-10-16T12:00:00+00:00"},
            event_id="EV-AUTH-T", authorization_event_id="EV-AUTH-REC-T", actor=ACTOR,
            occurred_at_utc="2026-10-16T12:00:00+00:00", history=[], authorization_policy=POLICY)
        with self.assertRaisesRegex(LifecycleValidationError, "cannot precede its authorization"):
            dispatch_request(request, {"dispatch_id": "DSP-T", "request_id": "STREQ-01",
                                       "dispatch_reference": "SYN", "sender": ACTOR,
                                       "sent_at_utc": "2026-10-16T11:00:00+00:00"},
                             event_id="EV-DSP-T", actor=ACTOR,
                             occurred_at_utc="2026-10-16T11:00:00+00:00", history=events)
        accepted = accepted_package()
        next(x for x in accepted["evidence_results"] if x["evidence_gap_id"] == "EVD-01")["acceptance_versions"][0]["event_id"] = "EV-WRONG"
        with self.assertRaisesRegex(LifecycleValidationError, "must link to its matching lifecycle event"):
            validate_package(accepted, plan, authorization_policy=POLICY)


if __name__ == "__main__":
    unittest.main()
