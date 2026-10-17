"""Behavioral regression coverage for Evidence Acquisition v5 integrity rules."""
import copy
import glob
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.evidence_lifecycle import (
    LifecycleValidationError, accept_evidence, authorize_request, complete_review,
    dispatch_request, receive_response, receive_response_with_evidence,
    resolve_decision, start_review,
    validate_package,
)

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PATH = next((ROOT / "reports/evidence_acquisition_v5").glob("*/evidence_acquisition.json"))
PLAN_PATH = next((ROOT / "reports/operational_planning_v2").glob("*/operational_planning.json"))
ACTOR = {"role": "TEST_REVIEWER"}
WHEN = "2026-10-16T12:00:00+00:00"
POLICY = {"policy_id": "SYNTHETIC-ONLY", "status": "TEST_ONLY",
          "allowed_roles_by_scope": {s: ["TEST_REVIEWER"] for s in (
              "request_authorization", "evidence_review", "evidence_acceptance", "decision_resolution")}}


def load_inputs():
    return json.loads(PACKAGE_PATH.read_text()), json.loads(PLAN_PATH.read_text())


def fully_supported_decision(decision_id="DEC-OPS-01"):
    """Build a complete synthetic accepted chain for every Planning v2 gap."""
    package, plan = load_inputs()
    # Synthetic-only fixture relationship: EVD-10 is currently blocked and has
    # no routed request. This isolated test models a hypothetical routed intake
    # without changing the persisted package or asserting that it exists.
    synthetic_request = next(r for r in package["stakeholder_request_templates"]
                             if r["request_id"] == "STREQ-08")
    synthetic_request["related_evidence_gap_ids"].append("EVD-10")
    synthetic_trace = next(t for t in package["traceability"] if t["evidence_gap_id"] == "EVD-10")
    synthetic_trace["request_template_ids"] = ["STREQ-08"]
    synthetic_trace["planning_task_ids"] = ["TASK-12"]
    synthetic_trace["acquisition_task_ids"] = sorted(set(synthetic_request["related_acquisition_task_ids"])
                                                    | {t["task_id"] for t in package["acquisition_tasks"]
                                                       if "EVD-10" in t["related_evidence_gap_ids"]})
    for task_id in synthetic_request["related_acquisition_task_ids"]:
        task = next(t for t in package["acquisition_tasks"] if t["task_id"] == task_id)
        if "EVD-10" not in task["related_evidence_gap_ids"]:
            task["related_evidence_gap_ids"].append("EVD-10")
    decision_plan = next(x for x in plan["decision_register"]["decisions"] if x["decision_id"] == decision_id)
    required = decision_plan["related_evidence_gap_ids"]
    history = []
    responses_by_request = {}
    for index, gap_id in enumerate(required, 1):
        request = next(x for x in package["stakeholder_request_templates"]
                       if gap_id in x["related_evidence_gap_ids"])
        request_id = request["request_id"]
        if request_id not in responses_by_request:
            request, events = authorize_request(
                request, {"authorization_id": f"AUTH-{request_id}", "request_id": request_id,
                          "status": "AUTHORIZED", "authorized_by": ACTOR, "authorized_at_utc": WHEN},
                event_id=f"EV-AUTH-{request_id}", authorization_event_id=f"EV-AUTH-REC-{request_id}",
                actor=ACTOR, occurred_at_utc=WHEN, history=history, authorization_policy=POLICY)
            history = events
            request, history = dispatch_request(
                request, {"dispatch_id": f"DSP-{request_id}", "request_id": request_id,
                          "dispatch_reference": "SYNTHETIC", "sender": ACTOR, "sent_at_utc": WHEN},
                event_id=f"EV-DSP-{request_id}", actor=ACTOR, occurred_at_utc=WHEN, history=history)
            response_id = f"RESP-{request_id}"
            request, history = receive_response(
                request, {"response_version_id": response_id, "supersedes_response_version_id": None,
                          "request_id": request_id, "received_at_utc": WHEN, "respondent": ACTOR,
                          "provenance_status": "VERIFIED", "source_references": [f"SRC-{request_id}"]},
                event_id=f"EV-RESP-{request_id}", actor=ACTOR, occurred_at_utc=WHEN, history=history)
            responses_by_request[request_id] = response_id
            package["stakeholder_request_templates"] = [
                request if r["request_id"] == request_id else r
                for r in package["stakeholder_request_templates"]]
        response_id = responses_by_request[request_id]
        result = next(r for r in package["evidence_results"] if r["evidence_gap_id"] == gap_id)
        result["current_response_version_id"] = response_id
        result["current_response_received_at_utc"] = WHEN
        review_id = f"REV-{gap_id}"
        result, history = start_review(result, event_id=f"EV-REV-START-{gap_id}", actor=ACTOR,
                                       occurred_at_utc=WHEN, history=history)
        result, history = complete_review(
            result, {"review_id": review_id, "supersedes_review_id": None,
                     "response_version_id": response_id, "reviewer": ACTOR,
                     "reviewed_at_utc": WHEN, "rationale": "Synthetic review",
                     "source_references": [f"SRC-{request_id}"], "outcome": "ACCEPTED",
                     "sufficiency_assessment": "SUFFICIENT"},
            event_id=f"EV-REV-DONE-{gap_id}", actor=ACTOR, occurred_at_utc=WHEN,
            history=history, authorization_policy=POLICY)
        result, history = accept_evidence(
            result, {"acceptance_id": f"ACC-{gap_id}", "supporting_review_id": review_id,
                     "rationale": "Synthetic acceptance", "source_references": [f"SRC-{request_id}"],
                     "approver": ACTOR, "accepted_at_utc": WHEN},
            event_id=f"EV-ACC-{gap_id}", actor=ACTOR, occurred_at_utc=WHEN,
            history=history, authorization_policy=POLICY)
        package["evidence_results"] = [result if r["evidence_gap_id"] == gap_id else r
                                       for r in package["evidence_results"]]
    package["lifecycle_events"] = history
    decision = next(d for d in package["decision_resolution_records"] if d["decision_id"] == decision_id)
    resolution, history = resolve_decision(
        decision, {"decision_id": decision_id, "resolution_record_id": f"RES-{decision_id}",
                   "authorization": {"status": "AUTHORIZED", "authorized_by": ACTOR,
                                    "authorized_at_utc": WHEN},
                   "decision_maker": ACTOR, "resolved_at_utc": WHEN,
                   "supporting_evidence_refs": list(required), "outcome": "RECORDED",
                   "rationale": "Synthetic all-required-gaps control"},
        event_id=f"EV-RES-{decision_id}", actor=ACTOR, occurred_at_utc=WHEN,
        history=history, evidence_results=package["evidence_results"],
        authorization_policy=POLICY, required_evidence_gap_ids=list(required))
    package["decision_resolution_records"] = [resolution if d["decision_id"] == decision_id else d
                                               for d in package["decision_resolution_records"]]
    package["lifecycle_events"] = history
    return package, plan, required


def add_resolution(package, plan, refs, decision_id="DEC-OPS-01"):
    decision = next(x for x in package["decision_resolution_records"] if x["decision_id"] == decision_id)
    record = {"decision_id": decision_id, "resolution_record_id": f"RES-{decision_id}",
              "authorization": {"status": "AUTHORIZED", "authorized_by": ACTOR, "authorized_at_utc": WHEN},
              "decision_maker": ACTOR, "resolved_at_utc": WHEN,
              "supporting_evidence_refs": list(refs), "outcome": "RECORDED", "rationale": "Synthetic"}
    event_id = f"EV-RES-{decision_id}"
    record["event_id"] = event_id
    decision.update(resolution_records=[record], current_resolution_record_id=record["resolution_record_id"],
                    resolution_status="RESOLVED")
    package["lifecycle_events"].append({"event_id": event_id, "entity_type": "decision", "entity_id": decision_id,
        "domain": "resolution_status", "event_type": "DECISION_RESOLVED", "previous_status": "OPEN",
        "resulting_status": "RESOLVED", "actor": ACTOR, "occurred_at_utc": WHEN,
        "supporting_record_refs": [record["resolution_record_id"], *refs]})
    return package


class EvidenceAcquisitionV5Tests(unittest.TestCase):
    def test_planning_object_is_bound_to_authoritative_source_bytes(self):
        package, plan = load_inputs()
        validate_package(package, plan)

        altered_plan = copy.deepcopy(plan)
        next(row for row in altered_plan["decision_register"]["decisions"]
             if row["decision_id"] == "DEC-OPS-10")["related_evidence_gap_ids"] = ["EVD-01"]
        altered_package = copy.deepcopy(package)
        next(row for row in altered_package["decision_resolution_records"]
             if row["decision_id"] == "DEC-OPS-10")["required_evidence_gap_ids"] = ["EVD-01"]
        altered_package["decision_evidence_policy"]["decision_required_evidence_gap_ids"]["DEC-OPS-10"] = ["EVD-01"]
        with self.assertRaisesRegex(LifecycleValidationError, "does not match the authoritative source bytes"):
            validate_package(altered_package, altered_plan)

    def test_package_only_planning_mapping_mutation_is_rejected(self):
        package, plan = load_inputs()
        altered = copy.deepcopy(package)
        next(row for row in altered["decision_resolution_records"]
             if row["decision_id"] == "DEC-OPS-10")["required_evidence_gap_ids"] = ["EVD-01"]
        altered["decision_evidence_policy"]["decision_required_evidence_gap_ids"]["DEC-OPS-10"] = ["EVD-01"]
        with self.assertRaisesRegex(LifecycleValidationError, "mapping disagrees"):
            validate_package(altered, plan)

    def test_planning_source_hash_mismatch_is_rejected(self):
        package, plan = load_inputs()
        package["source_plan"]["source_sha256"] = "0" * 64
        with self.assertRaisesRegex(LifecycleValidationError, "source hash does not match"):
            validate_package(package, plan)

    def test_missing_authoritative_planning_source_fails_closed(self):
        package, plan = load_inputs()
        with tempfile.TemporaryDirectory() as temporary_directory:
            fake_module = Path(temporary_directory) / "src" / "evidence_lifecycle.py"
            fake_module.parent.mkdir()
            fake_module.touch()
            with mock.patch("src.evidence_lifecycle.__file__", str(fake_module)):
                with self.assertRaisesRegex(LifecycleValidationError, "source is unavailable"):
                    validate_package(package, plan)

    def test_open_v5_package_preserves_lifecycle_state_and_planning_mapping(self):
        package, plan = load_inputs()
        validate_package(package, plan)
        self.assertEqual(package["lifecycle_events"], [])
        self.assertEqual(len(package["evidence_availability_inventory"]), 13)
        self.assertEqual(len(package["stakeholder_request_templates"]), 13)
        self.assertEqual(len(package["evidence_results"]), 13)
        self.assertEqual(len(package["decision_resolution_records"]), 13)
        self.assertTrue(all(d["resolution_status"] == "OPEN" for d in package["decision_resolution_records"]))

    def test_all_required_gap_positive_control_and_decision_specific_rejections(self):
        package, plan, required = fully_supported_decision()
        validate_package(package, plan, authorization_policy=POLICY)
        for refs in (required[:-1], ["EVD-01"], [required[0], "EVD-01"],
                     ["EVD-UNKNOWN", *required[1:]]):
            bad = copy.deepcopy(package)
            rec = bad["decision_resolution_records"][0]["resolution_records"][0]
            rec["supporting_evidence_refs"] = list(refs)
            with self.subTest(refs=refs), self.assertRaises(LifecycleValidationError):
                validate_package(bad, plan, authorization_policy=POLICY)
        bad_plan = copy.deepcopy(plan)
        next(d for d in bad_plan["decision_register"]["decisions"] if d["decision_id"] == "DEC-OPS-01")["related_evidence_gap_ids"].append("EVD-UNKNOWN")
        with self.assertRaisesRegex(LifecycleValidationError, "authoritative source bytes"):
            validate_package(package, bad_plan, authorization_policy=POLICY)
        bad_package = copy.deepcopy(package)
        bad_package["decision_resolution_records"][0]["required_evidence_gap_ids"].pop()
        with self.assertRaisesRegex(LifecycleValidationError, "Decision record evidence mapping"):
            validate_package(bad_package, plan, authorization_policy=POLICY)

    def test_decision_resolution_api_requires_exact_gap_mapping_when_supplied(self):
        package, plan = load_inputs()
        decision = next(d for d in package["decision_resolution_records"] if d["decision_id"] == "DEC-OPS-10")
        resolution = {"decision_id": decision["decision_id"], "resolution_record_id": "RES-X",
            "authorization": {"status": "AUTHORIZED", "authorized_by": ACTOR, "authorized_at_utc": WHEN},
            "decision_maker": ACTOR, "resolved_at_utc": WHEN,
            "supporting_evidence_refs": ["EVD-01"], "outcome": "RECORDED", "rationale": "Synthetic"}
        with self.assertRaisesRegex(LifecycleValidationError, "exactly match"):
            resolve_decision(decision, resolution, event_id="EV-X", actor=ACTOR, occurred_at_utc=WHEN,
                history=[], evidence_results=package["evidence_results"], authorization_policy=POLICY,
                required_evidence_gap_ids=["EVD-10", "EVD-11", "EVD-13"])
        with self.assertRaisesRegex(LifecycleValidationError, "authoritative mapping"):
            resolve_decision(decision, resolution, event_id="EV-Y", actor=ACTOR, occurred_at_utc=WHEN,
                history=[], evidence_results=package["evidence_results"], authorization_policy=POLICY,
                required_evidence_gap_ids=["EVD-01"])

    def test_resolution_event_reference_mutations_all_fail(self):
        base, plan, required = fully_supported_decision()
        changes = {
            "missing required evidence": lambda e, r: e["supporting_record_refs"].pop(),
            "extra evidence": lambda e, r: e["supporting_record_refs"].append("EVD-EXTRA"),
            "unknown evidence": lambda e, r: e["supporting_record_refs"].__setitem__(1, "EVD-UNKNOWN"),
            "wrong resolution ID": lambda e, r: e["supporting_record_refs"].__setitem__(0, "RES-WRONG"),
            "event timestamp before record": lambda e, r: e.update(occurred_at_utc="2026-10-16T11:59:59+00:00"),
        }
        for label, mutate in changes.items():
            bad = copy.deepcopy(base)
            event = next(e for e in bad["lifecycle_events"] if e["event_type"] == "DECISION_RESOLVED")
            record = next(d for d in bad["decision_resolution_records"] if d["resolution_status"] == "RESOLVED")["resolution_records"][0]
            mutate(event, record)
            with self.subTest(label=label), self.assertRaises(LifecycleValidationError):
                validate_package(bad, plan, authorization_policy=POLICY)

    def test_resolution_record_event_disagreement_and_cardinality_fail(self):
        base, plan, required = fully_supported_decision()
        mutations = [
            lambda p: p["decision_resolution_records"][0]["resolution_records"][0]["supporting_evidence_refs"].pop(),
            lambda p: p["lifecycle_events"].append(copy.deepcopy(next(e for e in p["lifecycle_events"] if e["event_type"] == "DECISION_RESOLVED"))),
            lambda p: p["lifecycle_events"].remove(next(e for e in p["lifecycle_events"] if e["event_type"] == "DECISION_RESOLVED")),
            lambda p: p["decision_resolution_records"][0].update(current_resolution_record_id="RES-OTHER"),
        ]
        for mutate in mutations:
            bad = copy.deepcopy(base); mutate(bad)
            with self.assertRaises(LifecycleValidationError):
                validate_package(bad, plan, authorization_policy=POLICY)

    def test_typed_event_reference_mutations_and_timestamp_binding_fail(self):
        base, plan, _ = fully_supported_decision()
        acceptance_event = next(e for e in base["lifecycle_events"] if e["event_type"] == "EVIDENCE_ACCEPTED")
        other_review_id = next(r["current_review_version_id"] for r in base["evidence_results"]
                               if r["evidence_gap_id"] != acceptance_event["entity_id"]
                               and r.get("current_review_version_id"))
        mutations = [
            lambda e: e["supporting_record_refs"].__setitem__(1, other_review_id),
            lambda e: e["supporting_record_refs"].append("GHOST-RECORD"),
            lambda e: e["supporting_record_refs"].__setitem__(0, "RESP-STREQ-01"),
            lambda e: e["supporting_record_refs"].pop(),
            lambda e: e["supporting_record_refs"].append(e["supporting_record_refs"][0]),
            lambda e: e["source_references"].append("UNDECLARED-SOURCE"),
            lambda e: e.update(occurred_at_utc="2026-10-16T11:59:59+00:00"),
        ]
        for mutate in mutations:
            bad = copy.deepcopy(base)
            target = next(e for e in bad["lifecycle_events"] if e["event_id"] == acceptance_event["event_id"])
            mutate(target)
            with self.assertRaises(LifecycleValidationError):
                validate_package(bad, plan, authorization_policy=POLICY)

    def test_response_authorization_dispatch_and_review_event_timestamps_are_bound(self):
        base, plan, _ = fully_supported_decision()
        cases = {
            "authorization": "REQUEST_AUTHORIZATION_RECORDED",
            "dispatch": "REQUEST_DISPATCHED",
            "response": "RESPONSE_RECEIVED",
            "review": "REVIEW_COMPLETED",
        }
        for _, event_type in cases.items():
            bad = copy.deepcopy(base)
            event = next(e for e in bad["lifecycle_events"] if e["event_type"] == event_type)
            event["occurred_at_utc"] = "2026-10-16T11:59:59+00:00"
            with self.assertRaises(LifecycleValidationError):
                validate_package(bad, plan, authorization_policy=POLICY)

    def test_current_record_versions_and_response_event_are_exactly_bound(self):
        base, plan, _ = fully_supported_decision()
        mutations = []
        bad = copy.deepcopy(base)
        result = next(r for r in bad["evidence_results"] if r["evidence_gap_id"] == "EVD-01")
        other_review = next(r["current_review_version_id"] for r in bad["evidence_results"]
                            if r["evidence_gap_id"] == "EVD-04")
        result["acceptance_versions"][-1]["supporting_review_id"] = other_review
        mutations.append(bad)
        bad = copy.deepcopy(base)
        result = next(r for r in bad["evidence_results"] if r["evidence_gap_id"] == "EVD-01")
        result["review_versions"][-1]["response_version_id"] = "RESP-STREQ-08"
        mutations.append(bad)
        bad = copy.deepcopy(base)
        response_event = next(e for e in bad["lifecycle_events"] if e["event_type"] == "RESPONSE_RECEIVED")
        response_event["supporting_record_refs"] = ["RESP-STREQ-08"]
        mutations.append(bad)
        for package in mutations:
            with self.assertRaises(LifecycleValidationError):
                validate_package(package, plan, authorization_policy=POLICY)

    def test_planning_policy_requires_all_gaps_for_dec10_not_just_evd01(self):
        package, plan = load_inputs()
        decision = next(d for d in package["decision_resolution_records"] if d["decision_id"] == "DEC-OPS-10")
        with self.assertRaisesRegex(LifecycleValidationError, "fully accepted|exactly match"):
            resolve_decision(decision, {"decision_id": decision["decision_id"], "resolution_record_id": "RES-10",
                "authorization": {"status": "AUTHORIZED", "authorized_by": ACTOR, "authorized_at_utc": WHEN},
                "decision_maker": ACTOR, "resolved_at_utc": WHEN, "supporting_evidence_refs": ["EVD-01"],
                "outcome": "RECORDED", "rationale": "Synthetic"}, event_id="EV-10", actor=ACTOR,
                occurred_at_utc=WHEN, history=[], evidence_results=package["evidence_results"],
                authorization_policy=POLICY, required_evidence_gap_ids=["EVD-10", "EVD-11", "EVD-13"])

    def _package_after_response_correction(self, *, material_change):
        package, plan, _ = fully_supported_decision()
        decision = next(row for row in package["decision_resolution_records"]
                        if row["decision_id"] == "DEC-OPS-01")
        decision.update(resolution_status="OPEN", current_resolution_record_id=None,
                        resolution_records=[])
        package["lifecycle_events"] = [event for event in package["lifecycle_events"]
                                        if event.get("event_type") != "DECISION_RESOLVED"]

        request = next(row for row in package["stakeholder_request_templates"]
                       if "EVD-01" in row["related_evidence_gap_ids"])
        old_response = request["response_versions"][-1]
        new_response = {
            "response_version_id": "RESP-CORRECTED-STREQ-01",
            "supersedes_response_version_id": old_response["response_version_id"],
            "supersedes_event_id": old_response["event_id"],
            "request_id": request["request_id"],
            "received_at_utc": WHEN,
            "respondent": ACTOR,
            "provenance_status": "VERIFIED",
            "source_references": ["SRC-CORRECTED-STREQ-01"],
            "correction_reason": "Synthetic materiality control",
        }
        updated_request, updated_results, events = receive_response_with_evidence(
            request, new_response, event_id="EV-RESP-CORRECTED-STREQ-01",
            actor=ACTOR, occurred_at_utc=WHEN,
            history=package["lifecycle_events"],
            evidence_results=package["evidence_results"],
            material_change=material_change,
        )
        package["stakeholder_request_templates"] = [
            updated_request if row["request_id"] == request["request_id"] else row
            for row in package["stakeholder_request_templates"]
        ]
        package["evidence_results"] = updated_results
        package["lifecycle_events"] = events
        return package, plan

    def test_material_response_correction_invalidates_reviews_and_replays(self):
        package, plan = self._package_after_response_correction(material_change=True)
        result = next(row for row in package["evidence_results"]
                      if row["evidence_gap_id"] == "EVD-01")
        self.assertEqual(result["review_status"], "PENDING")
        self.assertIsNone(result["current_review_version_id"])
        self.assertEqual(result["acceptance_status"], "NOT_ASSESSED")
        self.assertTrue(result["re_review_required"])
        self.assertEqual([row["review_id"] for row in result["review_versions"]], ["REV-EVD-01"])
        self.assertEqual([row["acceptance_id"] for row in result["acceptance_versions"]], ["ACC-EVD-01"])
        self.assertTrue(any(event["event_type"] == "REVIEW_INVALIDATED_BY_RESPONSE_CORRECTION"
                            and event["entity_type"] == "evidence"
                            and event["entity_id"] == "EVD-01"
                            for event in package["lifecycle_events"]))
        validate_package(package, plan, authorization_policy=POLICY)

    def test_material_response_correction_rejects_wrong_invalidation_entity(self):
        for field, value in (("entity_type", "request"), ("domain", "request_status"),
                             ("supporting_record_refs", ["WRONG-REVIEW", "WRONG-RESPONSE"])):
            package, plan = self._package_after_response_correction(material_change=True)
            event = next(row for row in package["lifecycle_events"]
                         if row["event_type"] == "REVIEW_INVALIDATED_BY_RESPONSE_CORRECTION")
            event[field] = value
            with self.subTest(field=field), self.assertRaises(LifecycleValidationError):
                validate_package(package, plan, authorization_policy=POLICY)

    def test_linked_material_correction_requires_evidence_context(self):
        package, _, _ = fully_supported_decision()
        request = next(row for row in package["stakeholder_request_templates"]
                       if row.get("current_response_version_id"))
        prior = request["response_versions"][-1]
        replacement = {
            "response_version_id": "RESP-UNSAFE-CORRECTION",
            "supersedes_response_version_id": prior["response_version_id"],
            "supersedes_event_id": prior["event_id"],
            "request_id": request["request_id"], "received_at_utc": WHEN,
            "respondent": ACTOR, "provenance_status": "VERIFIED",
            "source_references": ["SRC-CORRECTION"], "correction_reason": "Test",
        }
        with self.assertRaisesRegex(LifecycleValidationError, "requires receive_response_with_evidence"):
            receive_response(request, replacement, event_id="EV-UNSAFE-CORRECTION",
                             actor=ACTOR, occurred_at_utc=WHEN,
                             history=package["lifecycle_events"], material_change=True)

    def test_non_material_response_correction_preserves_review_and_acceptance(self):
        package, plan = self._package_after_response_correction(material_change=False)
        result = next(row for row in package["evidence_results"]
                      if row["evidence_gap_id"] == "EVD-01")
        self.assertEqual(result["review_status"], "ACCEPTED")
        self.assertEqual(result["current_review_version_id"], "REV-EVD-01")
        self.assertEqual(result["acceptance_status"], "ACCEPTED")
        self.assertEqual(result["current_acceptance_id"], "ACC-EVD-01")
        self.assertFalse(any(event["event_type"] == "REVIEW_INVALIDATED_BY_RESPONSE_CORRECTION"
                             for event in package["lifecycle_events"]))
        validate_package(package, plan, authorization_policy=POLICY)


if __name__ == "__main__":
    unittest.main()
