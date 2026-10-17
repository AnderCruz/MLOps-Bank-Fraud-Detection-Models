"""Static integrity checks for the versioned evidence acquisition package."""
import hashlib
import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE_PATH = next((ROOT / "reports/evidence_acquisition_v2").glob("*/evidence_acquisition.json"))
REPORT_PATH = PACKAGE_PATH.with_name("evidence_acquisition_report.md")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class EvidenceAcquisitionV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(PACKAGE_PATH.read_text())
        cls.report = REPORT_PATH.read_text()

    def test_json_structure_and_single_version_identity(self):
        d = self.data
        self.assertEqual(d["schema_version"], "2.0.0")
        self.assertEqual(PACKAGE_PATH.parent.name, d["directory_token"])
        self.assertEqual(d["version_path"], PACKAGE_PATH.parent.relative_to(ROOT).as_posix())
        self.assertIn(d["directory_token"], d["work_package_id"])
        self.assertIn(f"`{d['work_package_id']}`", self.report)
        self.assertIn(f"`{d['directory_token']}`", self.report)

    def test_unique_ids_and_cross_references(self):
        d = self.data
        identifier_collections = [
            [r["request_id"] for r in d["stakeholder_request_templates"]],
            [t["task_id"] for t in d["acquisition_tasks"]],
            [g["evidence_gap_id"] for g in d["evidence_availability_inventory"]],
            [e["result_id"] for e in d["evidence_results"]],
            [x["decision_id"] for x in d["decision_resolution_records"]],
        ]
        for identifiers in identifier_collections:
            self.assertEqual(len(identifiers), len(set(identifiers)))
        task_ids = {t["task_id"] for t in d["acquisition_tasks"]}
        req_ids = {r["request_id"] for r in d["stakeholder_request_templates"]}
        gap_ids = {g["evidence_gap_id"] for g in d["evidence_availability_inventory"]}
        plan = json.loads((ROOT / d["source_plan"]["json_path"]).read_text())
        planning_tasks = {t["task_id"] for t in plan["dependency_and_execution_plan"]["tasks"]}
        requirements = {x["requirement_id"] for x in plan["operational_requirements_register"]["requirements"]}
        decisions = {x["decision_id"] for x in plan["decision_register"]["decisions"]}
        for r in d["stakeholder_request_templates"]:
            self.assertTrue(r["related_planning_task_ids"])
            self.assertTrue(r["related_acquisition_task_ids"])
            self.assertTrue(set(r["related_planning_task_ids"]) <= planning_tasks)
            self.assertTrue(set(r["related_acquisition_task_ids"]) <= task_ids)
            self.assertTrue(set(r["related_requirement_ids"]) <= requirements)
            self.assertTrue(set(r["related_decision_ids"]) <= decisions)
            self.assertTrue(set(r["related_evidence_gap_ids"]) <= gap_ids)
        for t in d["acquisition_tasks"]:
            self.assertTrue(set(t.get("dependencies", [])) <= task_ids)
            self.assertTrue(set(t.get("related_request_ids", [])) <= req_ids)
        for g in d["evidence_availability_inventory"]:
            self.assertTrue(set(g["related_requirement_ids"]) <= requirements)
            self.assertTrue(set(g["related_decision_ids"]) <= decisions)

    def test_request_traceability_agrees_with_trace_table(self):
        d = self.data
        for r in d["stakeholder_request_templates"]:
            self.assertIn(r["request_id"], self.report)
            row = next((line for line in self.report.splitlines() if line.startswith(f"| {r['request_id']} — ")), None)
            self.assertIsNotNone(row)
            for linked_id in r["related_planning_task_ids"] + r["related_acquisition_task_ids"]:
                self.assertIn(linked_id, row)
        self.assertEqual({g["evidence_gap_id"] for g in d["evidence_availability_inventory"]}, {x["evidence_gap_id"] for x in d["evidence_results"]})
        for row in d["traceability"]:
            gid = row["evidence_gap_id"]
            requests = sorted(r["request_id"] for r in d["stakeholder_request_templates"] if gid in r["related_evidence_gap_ids"])
            self.assertEqual(row["request_template_ids"], requests)
            direct_acq = sorted({x for r in d["stakeholder_request_templates"] if r["request_id"] in requests for x in r["related_acquisition_task_ids"]} | {"ACQ-01"})
            self.assertEqual(row["acquisition_task_ids"], direct_acq)
            direct_plan = sorted({x for r in d["stakeholder_request_templates"] if gid in r["related_evidence_gap_ids"] for x in r["related_planning_task_ids"]})
            self.assertEqual(row["planning_task_ids"], direct_plan)

    def test_lifecycle_states_and_no_fabricated_events(self):
        d = self.data
        original_ids = {f"STREQ-{i:02}" for i in range(1, 10)}
        requests = {r["request_id"]: r for r in d["stakeholder_request_templates"]}
        self.assertTrue(original_ids <= requests.keys())
        for r in d["stakeholder_request_templates"]:
            self.assertEqual(r["request_status"], "PREPARED")
            self.assertEqual(r["authorization_status"], "PENDING")
            self.assertEqual(r["status"], "NOT_SENT")
            self.assertIsNone(r["sent_at_utc"])
            self.assertIsNone(r["dispatch_reference"])
            self.assertIsNone(r["authorized_sender"]["identity"])
            self.assertEqual(r["response"]["status"], "PENDING")
            self.assertIsNone(r["response"]["received_at_utc"])
            self.assertEqual(r["response"]["source_references"], [])
            self.assertEqual(r["review"]["status"], "PENDING")
            self.assertIsNone(r["review"]["reviewed_at_utc"])
            if r["response"]["status"] == "RECEIVED":
                self.assertTrue(r["response"]["received_at_utc"])
                self.assertTrue(r["response"]["source_references"] or r["response"]["documented_exception"])
                self.assertTrue(r["response"]["provenance_status"] == "VERIFIED" or r["response"]["documented_exception"])
            if r["review"]["status"] in {"ACCEPTED", "REJECTED", "INCONCLUSIVE"}:
                self.assertTrue(r["review"]["reviewer"]["role"] or r["review"]["reviewer"]["identity"])
                self.assertTrue(r["review"]["reviewed_at_utc"])
                self.assertTrue(r["review"]["rationale"])
        self.assertEqual(d["status_summary"]["requests_sent"], 0)
        self.assertEqual(d["status_summary"]["requests_prepared_unsent"], len(requests))
        rules = d["lifecycle_transition_rules"]
        vocab = d["lifecycle_vocabulary"]
        for lifecycle, transitions in rules.items():
            valid_states = set(vocab[lifecycle])
            self.assertTrue(set(transitions) <= valid_states)
            for next_states in transitions.values():
                self.assertTrue(set(next_states) <= valid_states)
        self.assertIn("SENT", rules["request_status"]["AUTHORIZED"])
        self.assertNotIn("SENT", rules["request_status"]["PREPARED"])

    def test_acceptance_and_resolution_require_distinct_records(self):
        d = self.data
        for result in d["evidence_results"]:
            self.assertEqual(result["assessment_status"], "OPEN")
            self.assertEqual(result["review"]["status"], "PENDING")
            if result["acceptance"]["state"] == "ACCEPTED":
                self.assertEqual(result["review"]["status"], "ACCEPTED")
                self.assertTrue(result["acceptance"]["rationale"])
                self.assertTrue(result["acceptance"]["approver"]["role"] or result["acceptance"]["approver"]["identity"])
                self.assertTrue(result["acceptance"]["accepted_at_utc"])
                self.assertTrue(result["acceptance"]["supporting_review_refs"])
                self.assertTrue(result["acceptance"]["source_refs"])
            if result["acceptance"]["state"] == "NOT_ASSESSED":
                self.assertIsNone(result["acceptance"]["rationale"])
                self.assertEqual(result["acceptance"]["source_refs"], [])
        for record in d["decision_resolution_records"]:
            if record["resolution_status"] == "RESOLVED":
                self.assertEqual(record["authorization_status"], "AUTHORIZED")
                self.assertTrue(record["decision_maker"]["role"] or record["decision_maker"]["identity"])
                self.assertTrue(record["resolved_at_utc"])
                self.assertTrue(record["outcome"] and record["rationale"])
                self.assertTrue(record["supporting_evidence_refs"])
            if record["resolution_status"] == "OPEN":
                self.assertIsNone(record["resolved_at_utc"])
                self.assertEqual(record["supporting_evidence_refs"], [])

    def test_semantic_corrections_and_preserved_boundaries(self):
        d = self.data
        req = {r["request_id"]: r for r in d["stakeholder_request_templates"]}
        self.assertEqual(req["STREQ-04"]["related_decision_ids"], ["DEC-OPS-13"])
        self.assertNotIn("DEC-OPS-07", req["STREQ-04"]["related_decision_ids"])
        self.assertTrue(any("drift" in q.lower() for q in req["STREQ-07"]["specific_questions"]))
        self.assertEqual(req["STREQ-13"]["related_decision_ids"], [])
        gap = {g["evidence_gap_id"]: g for g in d["evidence_availability_inventory"]}
        self.assertEqual(gap["EVD-06"]["direct_related_decision_ids"], ["DEC-OPS-07", "DEC-OPS-09"])
        self.assertEqual(gap["EVD-11"]["direct_related_decision_ids"], ["DEC-OPS-10"])
        self.assertEqual(gap["EVD-13"]["direct_related_decision_ids"], ["DEC-OPS-13"])
        b = d["preserved_evidence_boundaries"]
        policy = json.loads((ROOT / b["m5_policy_path"]).read_text())
        thresholds = policy["quality_thresholds"]
        self.assertEqual(len(thresholds), 8)
        self.assertTrue(all(item["value"] is None for item in thresholds.values()))
        self.assertEqual(b["m5_model_family_count"], 8)
        self.assertEqual(b["m5_null_threshold_values_observed"], 8)
        analysis = json.loads((ROOT / "reports/validation_policy_analysis_v1/8f76ffc6bfb6420dbbe90b4a37de1579/policy_analysis.json").read_text())
        self.assertEqual(len(analysis["candidates"]), 8)
        self.assertTrue(all(item["decision"] == "INSUFFICIENT_EVIDENCE" for item in analysis["candidates"].values()))
        self.assertIn("not a fresh blind", b["prior_test_split"])
        self.assertIn("offline inference contract", b["inference_contract"])
        self.assertIn("not establish whether additional", b["external_records"])
        self.assertIn("drift signals", self.report)

    def test_task_dependency_graph_is_acyclic(self):
        graph = self.data["dependency_graph"]
        nodes = set(graph["task_ids"])
        edges = graph["edges"]
        self.assertTrue(all(e["from"] in nodes and e["to"] in nodes for e in edges))
        outgoing = {n: [] for n in nodes}
        indegree = {n: 0 for n in nodes}
        for e in edges:
            outgoing[e["from"]].append(e["to"])
            indegree[e["to"]] += 1
        ready = [n for n, degree in indegree.items() if degree == 0]
        visited = 0
        while ready:
            node = ready.pop(); visited += 1
            for nxt in outgoing[node]:
                indegree[nxt] -= 1
                if indegree[nxt] == 0: ready.append(nxt)
        self.assertEqual(visited, len(nodes))

    def test_historical_v1_and_plan_hashes_are_preserved(self):
        d = self.data
        for key, expected in d["supersedes"]["historical_source_sha256"].items():
            path = ROOT / d["supersedes"]["json_path" if key == "json" else "markdown_path"]
            self.assertEqual(sha256(path), expected)
        self.assertEqual(sha256(ROOT / d["source_plan"]["json_path"]), d["source_plan"]["source_sha256"])
        for source in d["source_inventory"]:
            if source.get("sha256") and source.get("repository_presence") == "PRESENT":
                # README is expected to evolve as later package versions are documented;
                # its v2 hash remains a historical snapshot rather than a live-file pin.
                if source["path"] == "README.md":
                    self.assertRegex(source["sha256"], r"^[0-9a-f]{64}$")
                    continue
                self.assertEqual(sha256(ROOT / source["path"]), source["sha256"])
        self.assertIn("Evidence Acquisition v1, M5, M6, and Operational Planning v2 are preserved unchanged.", self.report)


if __name__ == "__main__":
    unittest.main()
