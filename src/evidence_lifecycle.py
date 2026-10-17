"""Executable lifecycle and append-only history validation for evidence records.

This module enforces application-level transitions on returned record copies. It
cannot make a mutable JSON file tamper-proof; storage controls, backups, and
signed/versioned persistence would be needed for stronger immutability.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
from pathlib import Path


class LifecycleValidationError(ValueError):
    """Raised when a lifecycle transition or record violates an invariant."""


TRANSITIONS = {
    "request_status": {"PREPARED": {"AUTHORIZED", "CANCELLED"}, "AUTHORIZED": {"CANCELLED"}, "CANCELLED": set()},
    "authorization_status": {"PENDING": {"AUTHORIZED", "DENIED"}, "AUTHORIZED": set(), "DENIED": set()},
    "dispatch_status": {"NOT_SENT": {"SENT", "CANCELLED"}, "SENT": set(), "CANCELLED": set()},
    "response_status": {"PENDING": {"RECEIVED", "NOT_PROVIDED"}, "NOT_PROVIDED": {"RECEIVED"}, "RECEIVED": set()},
    "review_status": {"PENDING": {"IN_PROGRESS", "REJECTED", "INCONCLUSIVE"}, "IN_PROGRESS": {"ACCEPTED", "REJECTED", "INCONCLUSIVE"}, "INCONCLUSIVE": {"IN_PROGRESS"}, "ACCEPTED": set(), "REJECTED": set()},
    "acceptance_status": {"NOT_ASSESSED": {"ACCEPTED", "PARTIAL", "REJECTED"}, "PARTIAL": {"ACCEPTED", "REJECTED"}, "ACCEPTED": set(), "REJECTED": set()},
    "resolution_status": {"OPEN": {"RESOLVED"}, "RESOLVED": set()},
}


def _require(ok, message):
    if not ok:
        raise LifecycleValidationError(message)


def _timestamp(value, field):
    _require(isinstance(value, str) and bool(value.strip()), f"{field} must be an ISO-8601 timestamp.")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LifecycleValidationError(f"{field} must be an ISO-8601 timestamp.") from exc
    _require(parsed.tzinfo is not None, f"{field} must include a timezone.")
    return parsed


def _actor(value, field="actor"):
    _require(isinstance(value, dict) and bool(value.get("role") or value.get("identity")),
             f"{field} must contain an actor attribution claim.")


def _authorized_actor(value, scope, policy, field="actor"):
    """Match an actor claim to an explicit policy; this does not authenticate identity."""
    _actor(value, field)
    _require(isinstance(policy, dict), f"A configured authorization policy is required for {scope}.")
    _require(policy.get("status") in {"CONFIGURED", "TEST_ONLY"},
             f"No enforceable authorization policy is configured for {scope}.")
    role = value.get("role")
    identity = value.get("identity")
    allowed = policy.get("allowed_roles_by_scope", {}).get(scope, [])
    allowed_identities = policy.get("allowed_identities_by_scope", {}).get(scope, [])
    _require(bool(role and role in allowed) or bool(identity and identity in allowed_identities),
             f"{field} claim does not match the configured policy for {scope}.")
    if policy.get("status") == "CONFIGURED":
        _require(policy.get("organizational_authority_verified") is True
                 and bool(policy.get("trusted_identity_source")),
                 f"Organizational authority for {scope} is not independently verified.")


def _event_contract(event):
    """Return the required entity/domain and transition rule for a known event."""
    contracts = {
        "REQUEST_AUTHORIZATION_RECORDED": ("request", "authorization_status", {("PENDING", "AUTHORIZED")}),
        "REQUEST_AUTHORIZATION_DENIED": ("request", "authorization_status", {("PENDING", "DENIED")}),
        "REQUEST_AUTHORIZED": ("request", "request_status", {("PREPARED", "AUTHORIZED")}),
        "REQUEST_CANCELLED": ("request", "request_status", {("PREPARED", "CANCELLED"), ("AUTHORIZED", "CANCELLED")}),
        "REQUEST_DISPATCHED": ("request", "dispatch_status", {("NOT_SENT", "SENT")}),
        "DISPATCH_CANCELLED": ("request", "dispatch_status", {("NOT_SENT", "CANCELLED")}),
        "RESPONSE_RECEIVED": ("request", "response_status", {("PENDING", "RECEIVED"), ("NOT_PROVIDED", "RECEIVED")}),
        "RESPONSE_NOT_PROVIDED": ("request", "response_status", {("PENDING", "NOT_PROVIDED")}),
        "RESPONSE_SUPERSEDED": ("request", "response_status", {("RECEIVED", "RECEIVED")}),
        "REVIEW_STARTED": ("evidence", "review_status", {("PENDING", "IN_PROGRESS"), ("INCONCLUSIVE", "IN_PROGRESS")}),
        "REVIEW_COMPLETED": ("evidence", "review_status", {("IN_PROGRESS", "ACCEPTED"), ("IN_PROGRESS", "REJECTED"), ("IN_PROGRESS", "INCONCLUSIVE")}),
        "REVIEW_REOPENED_FOR_CORRECTION": ("evidence", "review_status", {("ACCEPTED", "IN_PROGRESS"), ("REJECTED", "IN_PROGRESS"), ("INCONCLUSIVE", "IN_PROGRESS")}),
        "REVIEW_INVALIDATED_BY_RESPONSE_CORRECTION": ("evidence", "review_status", {("ACCEPTED", "PENDING"), ("REJECTED", "PENDING"), ("INCONCLUSIVE", "PENDING")}),
        "EVIDENCE_ACCEPTED": ("evidence", "acceptance_status", {("NOT_ASSESSED", "ACCEPTED"), ("PARTIAL", "ACCEPTED")}),
        "EVIDENCE_PARTIAL": ("evidence", "acceptance_status", {("NOT_ASSESSED", "PARTIAL")}),
        "EVIDENCE_REJECTED": ("evidence", "acceptance_status", {("NOT_ASSESSED", "REJECTED"), ("PARTIAL", "REJECTED")}),
        "EVIDENCE_ACCEPTANCE_INVALIDATED": ("evidence", "acceptance_status", {("ACCEPTED", "NOT_ASSESSED")}),
        "DECISION_RESOLVED": ("decision", "resolution_status", {("OPEN", "RESOLVED")}),
    }
    _require(event.get("event_type") in contracts, f"Unknown event type: {event.get('event_type')}.")
    entity_type, domain, transitions = contracts[event["event_type"]]
    _require(event.get("entity_type") == entity_type, "Event entity_type is incompatible with event_type.")
    _require(event.get("domain") == domain, "Event domain is incompatible with event_type.")
    _require((event.get("previous_status"), event.get("resulting_status")) in transitions,
             "Event type is incompatible with its state transition.")
    return entity_type, domain


def _unique(values, field):
    _require(all(values) and len(values) == len(set(values)), f"{field} must be present and unique.")


def validate_transition(domain, previous, resulting):
    """Validate a normal transition; terminal-state corrections use explicit APIs."""
    _require(domain in TRANSITIONS, f"Unknown lifecycle domain: {domain}.")
    _require(previous in TRANSITIONS[domain], f"Unknown {domain} state: {previous}.")
    _require(resulting in TRANSITIONS[domain], f"Unknown {domain} state: {resulting}.")
    _require(resulting in TRANSITIONS[domain][previous], f"Invalid {domain} transition: {previous} -> {resulting}.")


def _validate_supersession(versions, new, id_field, supersedes_field, reason_field):
    ids = [v.get(id_field) for v in versions] + [new.get(id_field)]
    _unique(ids, id_field)
    old_id = new.get(supersedes_field)
    if old_id is None:
        _require(not versions, f"A new {id_field} must explicitly supersede the current version.")
        return
    _require(any(v.get(id_field) == old_id for v in versions), f"{supersedes_field} must reference an existing earlier version.")
    _require(bool(new.get(reason_field, '').strip()), "Superseding a record requires a correction reason.")
    graph = {v[id_field]: v.get(supersedes_field) for v in versions}
    graph[new[id_field]] = old_id
    for start in graph:
        seen, node = set(), start
        while node is not None:
            _require(node not in seen, "Supersession references must be acyclic.")
            seen.add(node)
            node = graph.get(node)


def _append_event(history, event, *, correction=False):
    _unique([e.get("event_id") for e in history] + [event.get("event_id")], "event_id")
    _require(event.get("entity_id") and event.get("event_type") and event.get("domain"), "Event entity, type, and domain are required.")
    _actor(event.get("actor")); _timestamp(event.get("occurred_at_utc"), "occurred_at_utc")
    _require(isinstance(event.get("supporting_record_refs", []), list), "supporting_record_refs must be a list.")
    if correction:
        _require(bool(event.get("supersedes_event_id") and event.get("reason")), "A correction event requires a superseded event and reason.")
        old = next((x for x in history if x.get("event_id") == event["supersedes_event_id"]), None)
        _require(old is not None, "A correction event must reference an earlier event.")
        _require(old.get("entity_id") == event["entity_id"] and old.get("domain") == event["domain"],
                 "A correction must refer to the same entity and domain.")
    elif event.get("supersedes_event_id") is not None:
        _require(False, "Only explicit correction workflows may supersede an event.")
    return history + [copy.deepcopy(event)]


def authorize_request(request, authorization, *, event_id, authorization_event_id, actor, occurred_at_utc, history, authorization_policy=None):
    _require(request.get("request_status") == "PREPARED", "Only a PREPARED request can be authorized.")
    auth_state = request.get("authorization", {}).get("status", "PENDING")
    validate_transition("authorization_status", auth_state, "AUTHORIZED")
    validate_transition("request_status", "PREPARED", "AUTHORIZED")
    _require(authorization.get("request_id") == request.get("request_id"), "Authorization must reference this request.")
    _require(authorization.get("status") == "AUTHORIZED" and authorization.get("authorization_id"), "An identified AUTHORIZED record is required.")
    _authorized_actor(authorization.get("authorized_by"), "request_authorization", authorization_policy, "authorized_by")
    _timestamp(authorization.get("authorized_at_utc"), "authorized_at_utc")
    _actor(actor); _timestamp(occurred_at_utc, "occurred_at_utc")
    out = copy.deepcopy(request)
    a = out.setdefault("authorization", {"status": "PENDING", "records": [], "current_authorization_id": None})
    auth_record = copy.deepcopy(authorization); auth_record["event_id"] = authorization_event_id
    a["records"].append(auth_record); a["current_authorization_id"] = authorization["authorization_id"]; a["status"] = "AUTHORIZED"
    out["request_status"] = "AUTHORIZED"
    events = list(history)
    events = _append_event(events, {"event_id": authorization_event_id, "entity_type": "request", "entity_id": request["request_id"], "domain": "authorization_status", "event_type": "REQUEST_AUTHORIZATION_RECORDED", "previous_status": auth_state, "resulting_status": "AUTHORIZED", "actor": actor, "occurred_at_utc": occurred_at_utc, "supporting_record_refs": [authorization["authorization_id"]]})
    events = _append_event(events, {"event_id": event_id, "entity_type": "request", "entity_id": request["request_id"], "domain": "request_status", "event_type": "REQUEST_AUTHORIZED", "previous_status": "PREPARED", "resulting_status": "AUTHORIZED", "actor": actor, "occurred_at_utc": occurred_at_utc, "supporting_record_refs": [authorization["authorization_id"]]})
    return out, events


def deny_authorization(request, denial, *, event_id, actor, occurred_at_utc, history, authorization_policy=None):
    """Record an attributed authorization denial without dispatching the request."""
    _require(request.get("request_status") == "PREPARED", "Only a PREPARED request can receive an authorization disposition.")
    authorization = request.get("authorization", {})
    previous = authorization.get("status", "PENDING")
    validate_transition("authorization_status", previous, "DENIED")
    _require(denial.get("request_id") == request.get("request_id")
             and denial.get("authorization_id"), "Denial must identify its request and authorization record.")
    _require(bool(denial.get("reason")), "Authorization denial requires a reason.")
    _authorized_actor(denial.get("authorized_by"), "request_authorization", authorization_policy, "authorized_by")
    _timestamp(denial.get("authorized_at_utc"), "authorized_at_utc")
    _actor(actor); _timestamp(occurred_at_utc, "occurred_at_utc")
    out = copy.deepcopy(request)
    record = copy.deepcopy(denial); record["event_id"] = event_id
    a = out.setdefault("authorization", {"status": "PENDING", "records": [], "current_authorization_id": None})
    a.setdefault("records", []).append(record)
    a["current_authorization_id"] = denial["authorization_id"]
    a["status"] = "DENIED"
    event = {"event_id": event_id, "entity_type": "request", "entity_id": request["request_id"],
             "domain": "authorization_status", "event_type": "REQUEST_AUTHORIZATION_DENIED",
             "previous_status": previous, "resulting_status": "DENIED", "actor": actor,
             "occurred_at_utc": occurred_at_utc, "supporting_record_refs": [denial["authorization_id"]]}
    return out, _append_event(history, event)


def dispatch_request(request, dispatch, *, event_id, actor, occurred_at_utc, history):
    _require(request.get("request_status") == "AUTHORIZED", "Request must be AUTHORIZED before dispatch.")
    auth = request.get("authorization", {})
    _require(auth.get("status") == "AUTHORIZED" and auth.get("current_authorization_id"), "Dispatch requires its authorization record.")
    _require(dispatch.get("request_id") == request.get("request_id"), "Dispatch must reference this request.")
    _require(dispatch.get("dispatch_id") and dispatch.get("dispatch_reference"), "Dispatch ID and provenance reference are required.")
    _actor(dispatch.get("sender"), "sender"); sent_at = _timestamp(dispatch.get("sent_at_utc"), "sent_at_utc")
    auth_record = next((x for x in auth.get("records", []) if x.get("authorization_id") == auth.get("current_authorization_id")), None)
    _require(auth_record is not None, "Dispatch authorization record is missing.")
    _require(sent_at >= _timestamp(auth_record.get("authorized_at_utc"), "authorized_at_utc"),
             "Dispatch cannot precede its authorization.")
    _actor(actor); event_time = _timestamp(occurred_at_utc, "occurred_at_utc")
    _require(event_time >= sent_at, "Dispatch event cannot precede its sent timestamp.")
    current = request.get("dispatch", {}).get("status", "NOT_SENT")
    validate_transition("dispatch_status", current, "SENT")
    out = copy.deepcopy(request); ds = out.setdefault("dispatch", {"status": "NOT_SENT", "records": [], "current_dispatch_id": None})
    dispatch_record = copy.deepcopy(dispatch); dispatch_record["event_id"] = event_id
    ds["records"].append(dispatch_record); ds["status"] = "SENT"; ds["current_dispatch_id"] = dispatch["dispatch_id"]
    event = {"event_id": event_id, "entity_type": "request", "entity_id": request["request_id"], "domain": "dispatch_status", "event_type": "REQUEST_DISPATCHED", "previous_status": current, "resulting_status": "SENT", "actor": actor, "occurred_at_utc": occurred_at_utc, "supporting_record_refs": [auth["current_authorization_id"], dispatch["dispatch_id"]]}
    return out, _append_event(history, event)


def record_not_provided(request, disposition, *, event_id, actor, occurred_at_utc, history):
    """Record an actual no-response/unavailable disposition after dispatch."""
    _require(request.get("dispatch", {}).get("status") == "SENT", "A response disposition requires a sent request.")
    previous = request.get("response_status", "PENDING"); validate_transition("response_status", previous, "NOT_PROVIDED")
    _require(disposition.get("request_id") == request.get("request_id") and disposition.get("disposition_id"), "Disposition must identify the request and record.")
    _require(bool(disposition.get("reason")), "A NOT_PROVIDED disposition requires a reason.")
    _actor(disposition.get("recorded_by")); _timestamp(disposition.get("recorded_at_utc"), "recorded_at_utc")
    _actor(actor); _timestamp(occurred_at_utc, "occurred_at_utc")
    out=copy.deepcopy(request); record=copy.deepcopy(disposition); record["event_id"]=event_id
    out.setdefault("response_disposition_records", []).append(record); out["response_status"]="NOT_PROVIDED"
    event={"event_id":event_id,"entity_type":"request","entity_id":request["request_id"],"domain":"response_status","event_type":"RESPONSE_NOT_PROVIDED","previous_status":previous,"resulting_status":"NOT_PROVIDED","actor":actor,"occurred_at_utc":occurred_at_utc,"supporting_record_refs":[disposition["disposition_id"]]}
    return out,_append_event(history,event)


def cancel_request(request, *, event_id, dispatch_event_id, actor, occurred_at_utc, reason, history):
    """Cancel a request before dispatch, preserving both status-domain events."""
    status=request.get("request_status")
    validate_transition("request_status",status,"CANCELLED")
    _require(request.get("dispatch",{}).get("status","NOT_SENT")=="NOT_SENT","A sent request cannot be cancelled through this transition.")
    _require(bool(reason and reason.strip()),"Cancellation requires a reason.")
    _actor(actor); _timestamp(occurred_at_utc,"occurred_at_utc")
    out=copy.deepcopy(request); out["request_status"]="CANCELLED"; out.setdefault("dispatch",{"status":"NOT_SENT","records":[]})["status"]="CANCELLED"
    events=list(history)
    events=_append_event(events,{"event_id":event_id,"entity_type":"request","entity_id":request["request_id"],"domain":"request_status","event_type":"REQUEST_CANCELLED","previous_status":status,"resulting_status":"CANCELLED","actor":actor,"occurred_at_utc":occurred_at_utc,"supporting_record_refs":[],"reason":reason})
    events=_append_event(events,{"event_id":dispatch_event_id,"entity_type":"request","entity_id":request["request_id"],"domain":"dispatch_status","event_type":"DISPATCH_CANCELLED","previous_status":"NOT_SENT","resulting_status":"CANCELLED","actor":actor,"occurred_at_utc":occurred_at_utc,"supporting_record_refs":[],"reason":reason})
    return out,events


def _receive_response_record(request, version, *, event_id, actor, occurred_at_utc,
                             history, material_change=None):
    _require(request.get("dispatch", {}).get("status") == "SENT", "A response can be received only for a sent request.")
    _require(version.get("request_id") == request.get("request_id"), "Response version must reference this request.")
    received_at = _timestamp(version.get("received_at_utc"), "received_at_utc"); _actor(version.get("respondent"), "respondent")
    dispatch = next((x for x in request.get("dispatch", {}).get("records", [])
                     if x.get("dispatch_id") == request.get("dispatch", {}).get("current_dispatch_id")), None)
    _require(dispatch is not None and received_at >= _timestamp(dispatch.get("sent_at_utc"), "sent_at_utc"),
             "Response receipt cannot precede dispatch.")
    _actor(actor); event_time = _timestamp(occurred_at_utc, "occurred_at_utc")
    _require(event_time >= received_at, "Response event cannot precede its receipt timestamp.")
    refs = version.get("source_references", [])
    exception = version.get("documented_provenance_exception")
    _require(version.get("provenance_status") == "VERIFIED" or bool(exception), "Response provenance must be VERIFIED or have a documented exception.")
    _require(bool(refs) or bool(exception), "Response needs source references or a documented exception.")
    prior = request.get("response_versions", [])
    _validate_supersession(prior, version, "response_version_id", "supersedes_response_version_id", "correction_reason")
    current_id = request.get("current_response_version_id")
    if current_id:
        _require(version.get("supersedes_response_version_id") == current_id, "Replacement must supersede the current response version.")
        _require(bool(version.get("supersedes_event_id")), "Replacement must link the superseded receipt event.")
        old_event = next((x for x in history if x.get("event_id") == version["supersedes_event_id"]), None)
        prior_version = next((x for x in prior if x.get("response_version_id") == current_id), None)
        _require(old_event and old_event.get("entity_id") == request["request_id"]
                 and old_event.get("domain") == "response_status"
                 and prior_version and old_event.get("event_id") == prior_version.get("event_id"),
                 "supersedes_event_id must identify the current response version's receipt event.")
        _require(bool(version.get("correction_reason", '').strip()), "Response correction requires a reason.")
        _require(isinstance(material_change, bool), "Response correction must explicitly declare materiality.")
        old_status = "RECEIVED"
        correction = True
    else:
        _require(version.get("supersedes_response_version_id") is None, "Initial response cannot supersede a missing version.")
        old_status = request.get("response_status", "PENDING")
        validate_transition("response_status", old_status, "RECEIVED")
        correction = False
    out = copy.deepcopy(request)
    stored_version = copy.deepcopy(version)
    stored_version["material_change"] = bool(material_change) if material_change is not None else False
    stored_version["event_id"] = event_id
    out.setdefault("response_versions", []).append(stored_version)
    out["current_response_version_id"] = version["response_version_id"]
    out["response_status"] = "RECEIVED"
    event = {"event_id": event_id, "entity_type": "request", "entity_id": request["request_id"], "domain": "response_status", "event_type": "RESPONSE_SUPERSEDED" if correction else "RESPONSE_RECEIVED", "previous_status": old_status, "resulting_status": "RECEIVED", "actor": actor, "occurred_at_utc": occurred_at_utc, "supporting_record_refs": [version["response_version_id"]], "source_references": list(refs), "source_provenance_exception": exception, "supersedes_event_id": version.get("supersedes_event_id") if correction else None, "reason": version.get("correction_reason") if correction else None}
    events = _append_event(history, event, correction=correction)
    return out, events


def receive_response(request, version, *, event_id, actor, occurred_at_utc, history,
                     material_change=None):
    """Record a response when no package-linked review invalidation is needed.

    Material corrections on requests linked to evidence gaps must use
    ``receive_response_with_evidence`` so every affected review is handled.
    """
    is_correction = request.get("current_response_version_id") is not None
    if is_correction and request.get("related_evidence_gap_ids"):
        raise LifecycleValidationError(
            "Correction for an evidence-linked request requires "
            "receive_response_with_evidence and the complete linked evidence results."
        )
    return _receive_response_record(
        request, version, event_id=event_id, actor=actor,
        occurred_at_utc=occurred_at_utc, history=history,
        material_change=material_change,
    )


def receive_response_with_evidence(request, version, *, event_id, actor,
                                   occurred_at_utc, history, evidence_results,
                                   material_change):
    """Record a response correction together with its linked review effects.

    The complete evidence-result collection is required so a material change
    cannot silently leave a review tied to a superseded response. Non-material
    corrections preserve existing reviews; validation permits those historical
    review links only across an explicitly non-material response chain.
    """
    _require(request.get("current_response_version_id"),
             "A package-aware correction requires a current response version.")
    _require(isinstance(material_change, bool),
             "Response correction must explicitly declare materiality.")
    linked_gap_ids = request.get("related_evidence_gap_ids", [])
    _unique(linked_gap_ids, "related_evidence_gap_ids")
    _require(isinstance(evidence_results, list),
             "The complete evidence-results list is required for a response correction.")
    ids = [result.get("evidence_gap_id") for result in evidence_results]
    _unique(ids, "evidence-result gap IDs")
    by_gap = {result["evidence_gap_id"]: result for result in evidence_results}
    _require(set(linked_gap_ids) <= set(by_gap),
             "Every linked evidence gap must have exactly one evidence result.")

    prior_response_id = request["current_response_version_id"]
    updated_request, updated_history = _receive_response_record(
        request, version, event_id=event_id, actor=actor,
        occurred_at_utc=occurred_at_utc, history=history,
        material_change=material_change,
    )
    new_response_id = version["response_version_id"]
    new_results = copy.deepcopy(evidence_results)
    results_by_gap = {result["evidence_gap_id"]: result for result in new_results}
    event_time = _timestamp(occurred_at_utc, "occurred_at_utc")

    for gap_id in linked_gap_ids:
        result = results_by_gap[gap_id]
        current_response = result.get("current_response_version_id")
        _require(current_response in {None, prior_response_id},
                 f"Evidence {gap_id} is not linked to the response being corrected.")
        review_id = result.get("current_review_version_id")
        if not material_change:
            result["current_response_version_id"] = new_response_id
            result["current_response_received_at_utc"] = version["received_at_utc"]
            continue

        if review_id is None:
            _require(result.get("review_status", "PENDING") == "PENDING"
                     and result.get("acceptance_status", "NOT_ASSESSED") == "NOT_ASSESSED",
                     f"Evidence {gap_id} has review/acceptance state without a current review.")
            result["current_response_version_id"] = new_response_id
            result["current_response_received_at_utc"] = version["received_at_utc"]
            continue

        reviews = [item for item in result.get("review_versions", [])
                   if item.get("review_id") == review_id]
        _require(len(reviews) == 1, f"Evidence {gap_id} current review is missing or ambiguous.")
        review = reviews[0]
        _require(review.get("response_version_id") == prior_response_id,
                 f"Evidence {gap_id} review is not based on the response being corrected.")
        prior_review_status = result.get("review_status")
        _require(prior_review_status in {"ACCEPTED", "REJECTED", "INCONCLUSIVE"},
                 f"Evidence {gap_id} has a non-terminal review; material correction is unsupported.")
        review_time = _timestamp(review.get("reviewed_at_utc"), "reviewed_at_utc")
        _require(event_time >= max(review_time, _timestamp(version["received_at_utc"],
                                                            "received_at_utc")),
                 "Review invalidation cannot precede the review or corrected response.")

        acceptance_status = result.get("acceptance_status", "NOT_ASSESSED")
        if acceptance_status == "ACCEPTED":
            acceptance_id = result.get("current_acceptance_id")
            acceptances = [item for item in result.get("acceptance_versions", [])
                           if item.get("acceptance_id") == acceptance_id]
            _require(len(acceptances) == 1,
                     f"Evidence {gap_id} current acceptance is missing or ambiguous.")
            updated_result, updated_history = invalidate_acceptance(
                result, event_id=f"{event_id}:acceptance-invalidated:{gap_id}",
                actor=actor, occurred_at_utc=occurred_at_utc,
                supersedes_event_id=acceptances[0].get("event_id"),
                reason=version.get("correction_reason", "Material response correction"),
                affected_response_version_id=new_response_id,
                history=updated_history,
            )
            result.clear(); result.update(updated_result)
        elif acceptance_status in {"PARTIAL", "REJECTED"}:
            raise LifecycleValidationError(
                f"Material correction for {gap_id} requires an acceptance disposition "
                "transition that this lifecycle schema does not support."
            )

        review_event = {
            "event_id": f"{event_id}:review-invalidated:{gap_id}",
            "entity_type": "evidence", "entity_id": gap_id,
            "domain": "review_status",
            "event_type": "REVIEW_INVALIDATED_BY_RESPONSE_CORRECTION",
            "previous_status": prior_review_status, "resulting_status": "PENDING",
            "actor": actor, "occurred_at_utc": occurred_at_utc,
            "supporting_record_refs": [review_id, new_response_id],
            "supersedes_event_id": review.get("event_id"),
            "reason": version.get("correction_reason", "Material response correction"),
        }
        updated_history = _append_event(updated_history, review_event, correction=True)
        result["current_response_version_id"] = new_response_id
        result["current_response_received_at_utc"] = version["received_at_utc"]
        result["current_review_version_id"] = None
        result["review_status"] = "PENDING"
        result["re_review_required"] = True

    return updated_request, new_results, updated_history


def start_review_correction(entity, *, event_id, actor, occurred_at_utc, reason, history):
    """Explicitly reopen a terminal review while preserving the prior version."""
    current_id = entity.get("current_review_version_id")
    _require(current_id is not None, "No prior review exists to correct.")
    current_review = next((x for x in entity.get("review_versions", []) if x.get("review_id") == current_id), None)
    _require(current_review is not None, "Current review pointer is invalid.")
    _require(bool(reason and reason.strip()), "Review correction requires a reason.")
    prior_status = entity.get("review_status")
    _require(prior_status in {"ACCEPTED", "REJECTED", "INCONCLUSIVE"}, "Only a completed review can be corrected.")
    _actor(actor); _timestamp(occurred_at_utc, "occurred_at_utc")
    old_event_id = current_review.get("event_id")
    _require(old_event_id, "Prior review lacks its completion event reference.")
    out = copy.deepcopy(entity); out["review_status"] = "IN_PROGRESS"
    event = {"event_id": event_id, "entity_type": "evidence", "entity_id": entity.get("evidence_gap_id", entity.get("request_id")), "domain": "review_status", "event_type": "REVIEW_REOPENED_FOR_CORRECTION", "previous_status": prior_status, "resulting_status": "IN_PROGRESS", "actor": actor, "occurred_at_utc": occurred_at_utc, "supporting_record_refs": [current_id], "supersedes_event_id": old_event_id, "reason": reason}
    return out, _append_event(history, event, correction=True)


def start_review(entity, *, event_id, actor, occurred_at_utc, history):
    """Enter review only after a response version is available for review."""
    _require(entity.get("current_response_version_id"), "Review requires a current response version.")
    previous = entity.get("review_status", "PENDING")
    validate_transition("review_status", previous, "IN_PROGRESS")
    _actor(actor); _timestamp(occurred_at_utc, "occurred_at_utc")
    out = copy.deepcopy(entity); out["review_status"] = "IN_PROGRESS"
    event = {"event_id": event_id, "entity_type": "evidence",
             "entity_id": entity.get("evidence_gap_id", entity.get("request_id")),
             "domain": "review_status", "event_type": "REVIEW_STARTED",
             "previous_status": previous, "resulting_status": "IN_PROGRESS",
             "actor": actor, "occurred_at_utc": occurred_at_utc,
             "supporting_record_refs": [entity["current_response_version_id"]]}
    return out, _append_event(history, event)


def complete_review(entity, review, *, event_id, actor, occurred_at_utc, history, authorization_policy=None):
    current_response = entity.get("current_response_version_id")
    _require(current_response, "Review requires a current response version.")
    entity_id = entity.get("evidence_gap_id", entity.get("request_id"))
    latest_review_event = next((e for e in reversed(history)
                                if e.get("entity_id") == entity_id and e.get("domain") == "review_status"), None)
    _require(latest_review_event and latest_review_event.get("resulting_status") == "IN_PROGRESS",
             "Review completion requires a recorded review-start or correction event.")
    _require(review.get("response_version_id") == current_response, "Review must cite the current response version.")
    _require(review.get("review_id"), "review_id is required.")
    _authorized_actor(review.get("reviewer"), "evidence_review", authorization_policy, "reviewer")
    reviewed_at = _timestamp(review.get("reviewed_at_utc"), "reviewed_at_utc")
    _require(reviewed_at >= _timestamp(entity.get("current_response_received_at_utc", review.get("reviewed_at_utc")), "response_received_at_utc"),
             "Review cannot precede the response receipt.")
    _actor(actor); _timestamp(occurred_at_utc, "occurred_at_utc")
    _require(bool(review.get("rationale")) and bool(review.get("source_references")), "Review requires rationale and source references.")
    outcome = review.get("outcome")
    _require(outcome in {"ACCEPTED", "REJECTED", "INCONCLUSIVE"}, "Invalid completed review outcome.")
    _require(review.get("sufficiency_assessment") in {"SUFFICIENT", "PARTIAL", "INSUFFICIENT"}, "Review requires a sufficiency assessment.")
    if outcome == "ACCEPTED": _require(review["sufficiency_assessment"] == "SUFFICIENT", "Accepted review must be SUFFICIENT.")
    prior = entity.get("review_versions", []); _validate_supersession(prior, review, "review_id", "supersedes_review_id", "correction_reason")
    current_id = entity.get("current_review_version_id")
    if current_id: _require(review.get("supersedes_review_id") == current_id, "Corrected review must supersede current review.")
    old_status = entity.get("review_status", "PENDING")
    validate_transition("review_status", old_status, outcome)
    out = copy.deepcopy(entity); version = copy.deepcopy(review); version["event_id"] = event_id
    version["evidence_gap_id"] = entity_id
    out.setdefault("review_versions", []).append(version); out["current_review_version_id"] = review["review_id"]
    out["review_status"] = outcome; out["re_review_required"] = False
    event = {"event_id": event_id, "entity_type": "evidence", "entity_id": entity.get("evidence_gap_id", entity.get("request_id")), "domain": "review_status", "event_type": "REVIEW_COMPLETED", "previous_status": old_status, "resulting_status": outcome, "actor": actor, "occurred_at_utc": occurred_at_utc, "supporting_record_refs": [review["review_id"], current_response], "source_references": list(review["source_references"])}
    return out, _append_event(history, event)


def accept_evidence(result, acceptance, *, event_id, actor, occurred_at_utc, history, authorization_policy=None):
    _require(not result.get("re_review_required"), "Evidence acceptance is blocked until the required re-review is completed.")
    _require(result.get("review_status") == "ACCEPTED", "Evidence acceptance requires an ACCEPTED current review.")
    review_id = result.get("current_review_version_id")
    review = next((x for x in result.get("review_versions", []) if x.get("review_id") == review_id), None)
    _require(review is not None and review.get("sufficiency_assessment") == "SUFFICIENT", "Current review must be sufficient.")
    review_event = next((e for e in history if e.get("event_id") == review.get("event_id")), None)
    _require(review_event and review_event.get("entity_id") == result.get("evidence_gap_id")
             and review_event.get("domain") == "review_status"
             and review_event.get("resulting_status") == "ACCEPTED",
             "Evidence acceptance requires the recorded completion event for its current review.")
    _require(acceptance.get("supporting_review_id") == review_id, "Acceptance must cite the current qualifying review.")
    _require(acceptance.get("acceptance_id") and acceptance.get("rationale"), "Acceptance ID and rationale are required.")
    _authorized_actor(acceptance.get("approver"), "evidence_acceptance", authorization_policy, "approver"); _actor(actor)
    accepted_at = _timestamp(acceptance.get("accepted_at_utc"), "accepted_at_utc")
    _require(accepted_at >= _timestamp(review.get("reviewed_at_utc"), "reviewed_at_utc"), "Acceptance cannot precede its supporting review.")
    _timestamp(occurred_at_utc, "occurred_at_utc")
    refs = acceptance.get("source_references", []); _require(bool(refs), "Acceptance requires source references.")
    prior_versions = result.get("acceptance_versions", [])
    _validate_supersession(prior_versions, acceptance, "acceptance_id",
                           "supersedes_acceptance_id", "correction_reason")
    previous = result.get("acceptance_status", "NOT_ASSESSED"); validate_transition("acceptance_status", previous, "ACCEPTED")
    out = copy.deepcopy(result); version = copy.deepcopy(acceptance); version["event_id"] = event_id
    version["evidence_gap_id"] = result["evidence_gap_id"]
    version["acceptance_status"] = "ACCEPTED"
    out.setdefault("acceptance_versions", []).append(version); out["current_acceptance_id"] = acceptance["acceptance_id"]; out["acceptance_status"] = "ACCEPTED"
    event = {"event_id": event_id, "entity_type": "evidence", "entity_id": result["evidence_gap_id"], "domain": "acceptance_status", "event_type": "EVIDENCE_ACCEPTED", "previous_status": previous, "resulting_status": "ACCEPTED", "actor": actor, "occurred_at_utc": occurred_at_utc, "supporting_record_refs": [acceptance["acceptance_id"], review_id], "source_references": list(refs)}
    return out, _append_event(history, event)


def record_evidence_disposition(result, disposition, *, event_id, actor,
                                occurred_at_utc, history, authorization_policy=None):
    """Record a partial or rejected evidence disposition with full attribution."""
    status = disposition.get("acceptance_status")
    _require(status in {"PARTIAL", "REJECTED"}, "Disposition must be PARTIAL or REJECTED.")
    _require(not result.get("re_review_required"), "Evidence disposition is blocked until required re-review is complete.")
    review_id = result.get("current_review_version_id")
    review = next((x for x in result.get("review_versions", []) if x.get("review_id") == review_id), None)
    _require(review is not None and result.get("review_status") in {"ACCEPTED", "REJECTED", "INCONCLUSIVE"},
             "Evidence disposition requires a completed current review.")
    _require(disposition.get("supporting_review_id") == review_id,
             "Evidence disposition must cite the current review.")
    if result.get("review_status") in {"REJECTED", "INCONCLUSIVE"}:
        _require(status == "REJECTED", "A rejected or inconclusive review cannot produce accepted evidence.")
    if status == "PARTIAL":
        _require(result.get("review_status") == "ACCEPTED" and review.get("sufficiency_assessment") == "SUFFICIENT",
                 "PARTIAL disposition requires an accepted, sufficient review.")
    _require(disposition.get("acceptance_id") and disposition.get("rationale"),
             "Disposition ID and rationale are required.")
    _require(bool(disposition.get("source_references")), "Disposition requires source references.")
    _authorized_actor(disposition.get("approver"), "evidence_acceptance", authorization_policy, "approver"); _actor(actor)
    accepted_at = _timestamp(disposition.get("accepted_at_utc"), "accepted_at_utc")
    _require(accepted_at >= _timestamp(review.get("reviewed_at_utc"), "reviewed_at_utc"), "Evidence disposition cannot precede its supporting review.")
    _timestamp(occurred_at_utc, "occurred_at_utc")
    prior = result.get("acceptance_versions", [])
    _validate_supersession(prior, disposition, "acceptance_id", "supersedes_acceptance_id", "correction_reason")
    previous = result.get("acceptance_status", "NOT_ASSESSED")
    validate_transition("acceptance_status", previous, status)
    out = copy.deepcopy(result); version = copy.deepcopy(disposition); version["event_id"] = event_id
    version["evidence_gap_id"] = result["evidence_gap_id"]
    out.setdefault("acceptance_versions", []).append(version)
    out["current_acceptance_id"] = disposition["acceptance_id"]
    out["acceptance_status"] = status
    event = {"event_id": event_id, "entity_type": "evidence", "entity_id": result["evidence_gap_id"],
             "domain": "acceptance_status", "event_type": f"EVIDENCE_{status}",
             "previous_status": previous, "resulting_status": status, "actor": actor,
             "occurred_at_utc": occurred_at_utc,
             "supporting_record_refs": [disposition["acceptance_id"], review_id],
             "source_references": list(disposition["source_references"])}
    return out, _append_event(history, event)


def invalidate_acceptance(result, *, event_id, actor, occurred_at_utc,
                          supersedes_event_id, reason,
                          affected_response_version_id, history):
    """Invalidate prior acceptance after a material source correction.

    The prior acceptance remains in ``acceptance_versions``. A replacement
    acceptance requires a new qualifying review and explicit acceptance.
    """
    _require(result.get("acceptance_status") == "ACCEPTED", "Only accepted evidence can be invalidated.")
    old_id = result.get("current_acceptance_id")
    _require(any(x.get("acceptance_id") == old_id for x in result.get("acceptance_versions", [])),
             "Accepted evidence lacks its current acceptance record.")
    _require(bool(reason and reason.strip()), "Acceptance invalidation requires a reason.")
    _require(bool(affected_response_version_id), "Invalidation must identify the corrected response version.")
    old_event = next((x for x in history if x.get("event_id") == supersedes_event_id), None)
    _require(old_event and old_event.get("domain") == "acceptance_status"
             and old_event.get("entity_id") == result.get("evidence_gap_id"),
             "supersedes_event_id must identify this evidence acceptance event.")
    _actor(actor); _timestamp(occurred_at_utc, "occurred_at_utc")
    out = copy.deepcopy(result)
    out["acceptance_status"] = "NOT_ASSESSED"
    out["current_acceptance_id"] = None
    out["re_review_required"] = True
    event = {
        "event_id": event_id, "entity_type": "evidence",
        "entity_id": result["evidence_gap_id"], "domain": "acceptance_status",
        "event_type": "EVIDENCE_ACCEPTANCE_INVALIDATED",
        "previous_status": "ACCEPTED", "resulting_status": "NOT_ASSESSED",
        "actor": actor, "occurred_at_utc": occurred_at_utc,
        "supporting_record_refs": [old_id, affected_response_version_id],
        "supersedes_event_id": supersedes_event_id, "reason": reason,
    }
    return out, _append_event(history, event, correction=True)


def resolve_decision(decision, resolution, *, event_id, actor, occurred_at_utc, history,
                     evidence_results=None, authorization_policy=None,
                     required_evidence_gap_ids=None):
    _require(decision.get("resolution_status") == "OPEN", "Only OPEN decisions can be resolved.")
    _require(not any(e.get("entity_id") == decision.get("decision_id")
                     and e.get("domain") == "resolution_status" for e in history),
             "Decision resolution history is terminal and cannot be silently replaced.")
    _require(resolution.get("decision_id") == decision.get("decision_id") and resolution.get("resolution_record_id"), "A distinct resolution record linked to the decision is required.")
    auth = resolution.get("authorization", {})
    _require(auth.get("status") == "AUTHORIZED", "Decision resolution requires explicit authorization.")
    _authorized_actor(auth.get("authorized_by"), "decision_resolution", authorization_policy, "decision authorization")
    authorized_at = _timestamp(auth.get("authorized_at_utc"), "authorized_at_utc")
    _authorized_actor(resolution.get("decision_maker"), "decision_resolution", authorization_policy, "decision_maker")
    _actor(actor)
    resolved_at = _timestamp(resolution.get("resolved_at_utc"), "resolved_at_utc")
    _require(resolved_at >= authorized_at, "Decision resolution cannot precede its authorization.")
    _timestamp(occurred_at_utc, "occurred_at_utc")
    refs = resolution.get("supporting_evidence_refs", []); _require(bool(refs), "Decision resolution requires evidence references.")
    _unique(refs, "supporting_evidence_refs")
    _require(isinstance(required_evidence_gap_ids, list) and bool(required_evidence_gap_ids),
             "A non-empty decision-specific evidence requirement is required.")
    _unique(required_evidence_gap_ids, "required_evidence_gap_ids")
    if decision.get("required_evidence_gap_ids") is not None:
        _require(required_evidence_gap_ids == decision["required_evidence_gap_ids"],
                 "Supplied evidence requirements disagree with the decision's authoritative mapping.")
    _require(refs == required_evidence_gap_ids,
             "Resolution evidence must exactly match every required evidence gap for this decision.")
    _require(bool(resolution.get("outcome") and resolution.get("rationale")), "Decision outcome and rationale are required.")
    _require(evidence_results is not None, "Evidence results are required to resolve a decision.")
    evidence_by_id = {}
    for result in evidence_results:
        for identifier in (result.get("evidence_gap_id"), result.get("result_id")):
            if identifier:
                evidence_by_id.setdefault(identifier, []).append(result)
    for reference in refs:
        matches = evidence_by_id.get(reference, [])
        _require(len(matches) == 1, f"Resolution evidence reference must identify exactly one evidence result: {reference}.")
        evidence = matches[0]
        _require(evidence.get("acceptance_status") == "ACCEPTED"
                 and evidence.get("review_status") == "ACCEPTED"
                 and not evidence.get("re_review_required"),
                 f"Resolution evidence is not fully accepted: {reference}.")
        _validate_current_review_and_acceptance(evidence, authorization_policy, require_acceptance=True)
    record = copy.deepcopy(resolution); record["event_id"] = event_id
    out = copy.deepcopy(decision); out.setdefault("resolution_records", []).append(record); out["current_resolution_record_id"] = resolution["resolution_record_id"]; out["resolution_status"] = "RESOLVED"
    event = {"event_id": event_id, "entity_type": "decision", "entity_id": decision["decision_id"], "domain": "resolution_status", "event_type": "DECISION_RESOLVED", "previous_status": "OPEN", "resulting_status": "RESOLVED", "actor": actor, "occurred_at_utc": occurred_at_utc, "supporting_record_refs": [resolution["resolution_record_id"], *refs]}
    return out, _append_event(history, event)


def _validate_current_review_and_acceptance(result, authorization_policy, *, require_acceptance=False):
    """Validate current evidence review and acceptance records as complete versions."""
    gap_id = result.get("evidence_gap_id")
    review_id = result.get("current_review_version_id")
    _require(bool(review_id), f"Evidence result {gap_id} has no current review.")
    reviews = [x for x in result.get("review_versions", []) if x.get("review_id") == review_id]
    _require(len(reviews) == 1, f"Current review must resolve to exactly one review record for {gap_id}.")
    review = reviews[0]
    _require(review.get("evidence_gap_id") == gap_id, "Review evidence-result reference is inconsistent.")
    _require(review.get("response_version_id") and review.get("outcome") == result.get("review_status"),
             "Current review outcome or response reference is inconsistent.")
    _authorized_actor(review.get("reviewer"), "evidence_review", authorization_policy, "reviewer")
    reviewed_at = _timestamp(review.get("reviewed_at_utc"), "reviewed_at_utc")
    _require(bool(review.get("rationale")) and bool(review.get("source_references")),
             "Current review requires rationale and source references.")
    _require(review.get("sufficiency_assessment") in {"SUFFICIENT", "PARTIAL", "INSUFFICIENT"},
             "Current review has an invalid sufficiency assessment.")
    if review.get("outcome") == "ACCEPTED":
        _require(review.get("sufficiency_assessment") == "SUFFICIENT",
                 "Accepted review must be SUFFICIENT.")
    _require(bool(review.get("event_id")), "Current review lacks event linkage.")
    if require_acceptance or result.get("acceptance_status") == "ACCEPTED":
        acceptance_id = result.get("current_acceptance_id")
        acceptances = [x for x in result.get("acceptance_versions", [])
                       if x.get("acceptance_id") == acceptance_id]
        _require(bool(acceptance_id) and len(acceptances) == 1,
                 "Accepted evidence needs exactly one current acceptance record.")
        acceptance = acceptances[0]
        _require(acceptance.get("evidence_gap_id") == gap_id,
                 "Acceptance evidence-result reference is inconsistent.")
        _require(acceptance.get("acceptance_status") == "ACCEPTED",
                 "Current acceptance record must have ACCEPTED status.")
        _require(acceptance.get("supporting_review_id") == review_id,
                 "Current acceptance must cite the exact current review.")
        _require(review.get("outcome") == "ACCEPTED"
                 and review.get("sufficiency_assessment") == "SUFFICIENT",
                 "Acceptance requires the current accepted and sufficient review.")
        _authorized_actor(acceptance.get("approver"), "evidence_acceptance", authorization_policy, "approver")
        accepted_at = _timestamp(acceptance.get("accepted_at_utc"), "accepted_at_utc")
        _require(accepted_at >= reviewed_at, "Acceptance cannot precede its supporting review.")
        _require(bool(acceptance.get("rationale")) and bool(acceptance.get("source_references")),
                 "Current acceptance requires rationale and source references.")
        _require(set(acceptance.get("source_references", [])) <= set(review.get("source_references", [])),
                 "Acceptance sources must be supported by the current review.")
        _require(bool(acceptance.get("event_id")), "Current acceptance lacks event linkage.")
    return review


def _record_index(package):
    """Index package records by ID and type for event-reference validation."""
    index = {}
    def add(identifier, kind, record):
        if identifier:
            index.setdefault(identifier, []).append((kind, record))
    for request in package.get("stakeholder_request_templates", []):
        for record in request.get("authorization", {}).get("records", []): add(record.get("authorization_id"), "authorization", record)
        for record in request.get("dispatch", {}).get("records", []): add(record.get("dispatch_id"), "dispatch", record)
        for record in request.get("response_versions", []): add(record.get("response_version_id"), "response", record)
        for record in request.get("response_disposition_records", []): add(record.get("disposition_id"), "response_disposition", record)
    for result in package.get("evidence_results", []):
        add(result.get("evidence_gap_id"), "evidence", result)
        add(result.get("result_id"), "evidence_result", result)
        for record in result.get("review_versions", []): add(record.get("review_id"), "review", record)
        for record in result.get("acceptance_versions", []): add(record.get("acceptance_id"), "acceptance", record)
    for decision in package.get("decision_resolution_records", []):
        for record in decision.get("resolution_records", []): add(record.get("resolution_record_id"), "resolution", record)
    return index


def _validate_v5_planning_source(package, planning):
    """Verify the supplied Planning object against its declared project file."""
    source_plan = package.get("source_plan")
    _require(isinstance(source_plan, dict),
             "V5 package is missing its Planning v2 source identity.")
    inventory = [item for item in package.get("source_inventory", [])
                 if item.get("source_id") == "SRC-PLAN-V2"
                 and item.get("classification") == "planning_register"]
    _require(len(inventory) == 1,
             "V5 package must identify exactly one authoritative Planning v2 source.")
    source = inventory[0]
    declared_path = source_plan.get("json_path")
    _require(isinstance(declared_path, str) and bool(declared_path),
             "V5 Planning v2 source path is missing.")
    relative_path = Path(declared_path)
    _require(not relative_path.is_absolute(),
             "V5 Planning source path must be project-relative.")
    project_root = Path(__file__).resolve().parents[1]
    candidates = sorted(project_root.glob(
        "reports/operational_planning_v2/*/operational_planning.json"
    ))
    _require(bool(candidates),
             "Authoritative Planning v2 source is unavailable; validation cannot continue.")
    _require(len(candidates) == 1,
             "Planning v2 source is ambiguous; validation requires one canonical source artifact.")
    source_path = candidates[0].resolve()
    _require(relative_path.as_posix() == source_path.relative_to(project_root).as_posix(),
             "V5 Planning source path does not identify the canonical project artifact.")
    _require(source_path.is_relative_to(project_root)
             and source_path.name == "operational_planning.json"
             and source_path.parent.parent.name == "operational_planning_v2",
             "V5 Planning source path is outside the versioned project source directory.")
    _require(source.get("path") == declared_path,
             "V5 Planning source path disagrees with the source inventory.")
    try:
        source_bytes = source_path.read_bytes()
    except OSError as exc:
        raise LifecycleValidationError(
            "Authoritative Planning v2 source is unavailable; validation cannot continue."
        ) from exc
    actual_hash = hashlib.sha256(source_bytes).hexdigest()
    _require(source_plan.get("source_sha256") == actual_hash
             and source.get("sha256") == actual_hash,
             "V5 Planning source hash does not match the authoritative file bytes.")
    try:
        authoritative_planning = json.loads(source_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LifecycleValidationError(
            "Authoritative Planning v2 source is not valid UTF-8 JSON."
        ) from exc
    _require(planning == authoritative_planning,
             "Caller-supplied Planning object does not match the authoritative source bytes.")
    for field in ("document_id", "document_version", "plan_id"):
        _require(source_plan.get(field) == authoritative_planning.get(field),
                 f"V5 Planning source identity mismatch for {field}.")


def _validate_v5_event_bindings(package, events, planning, authorization_policy):
    """Enforce the v5 exact event-to-record contract, including source citations.

    ``supporting_record_refs`` contains lifecycle record IDs only. External source
    citations are carried separately in ``source_references``. Equal timestamps
    are permitted; no event may precede the timestamp of its represented record.
    """
    _require(planning is not None, "Evidence Acquisition v5 validation requires Operational Planning v2.")
    planned = {row["decision_id"]: row.get("related_evidence_gap_ids", [])
               for row in planning["decision_register"]["decisions"]}
    policy = package.get("decision_evidence_policy", {})
    _require(policy.get("mode") == "ALL_REQUIRED_GAPS_ACCEPTED",
             "V5 decision evidence policy must require all planned evidence gaps.")
    _require(policy.get("decision_required_evidence_gap_ids") == planned,
             "V5 decision evidence mapping disagrees with Operational Planning v2.")
    record_index = _record_index(package)

    records_by_event = {}
    event_records = []
    for request in package.get("stakeholder_request_templates", []):
        auth = request.get("authorization", {})
        event_records.extend((r, "authorization", "authorization_id", request["request_id"])
                             for r in auth.get("records", []))
        event_records.extend((r, "dispatch", "dispatch_id", request["request_id"])
                             for r in request.get("dispatch", {}).get("records", []))
        event_records.extend((r, "response", "response_version_id", request["request_id"])
                             for r in request.get("response_versions", []))
        event_records.extend((r, "response_disposition", "disposition_id", request["request_id"])
                             for r in request.get("response_disposition_records", []))
    for result in package.get("evidence_results", []):
        event_records.extend((r, "review", "review_id", result["evidence_gap_id"])
                             for r in result.get("review_versions", []))
        event_records.extend((r, "acceptance", "acceptance_id", result["evidence_gap_id"])
                             for r in result.get("acceptance_versions", []))
    for decision in package.get("decision_resolution_records", []):
        event_records.extend((r, "resolution", "resolution_record_id", decision["decision_id"])
                             for r in decision.get("resolution_records", []))
    for record, kind, id_field, entity_id in event_records:
        _require(record.get("event_id"), f"V5 {kind} record lacks an event ID.")
        records_by_event.setdefault(record["event_id"], []).append((record, kind, id_field, entity_id))

    typed_refs = {
        "REQUEST_AUTHORIZATION_RECORDED": lambda e: [e["authorization"]["authorization_id"]],
        "REQUEST_AUTHORIZATION_DENIED": lambda e: [e["authorization"]["authorization_id"]],
        "REQUEST_AUTHORIZED": lambda e: [e["authorization"]["authorization_id"]],
        "REQUEST_DISPATCHED": lambda e: [e["request"]["authorization"]["current_authorization_id"], e["dispatch"]["dispatch_id"]],
        "REQUEST_CANCELLED": lambda e: [],
        "DISPATCH_CANCELLED": lambda e: [],
        "RESPONSE_RECEIVED": lambda e: [e["response"]["response_version_id"]],
        "RESPONSE_SUPERSEDED": lambda e: [e["response"]["response_version_id"]],
        "RESPONSE_NOT_PROVIDED": lambda e: [e["response_disposition"]["disposition_id"]],
        "REVIEW_STARTED": lambda e: [e["start_response"]["response_version_id"]],
        "REVIEW_COMPLETED": lambda e: [e["review"]["review_id"], e["review"]["response_version_id"]],
        "REVIEW_REOPENED_FOR_CORRECTION": lambda e: [e["review"]["review_id"]],
        "REVIEW_INVALIDATED_BY_RESPONSE_CORRECTION": lambda e: [e["old_review"]["review_id"], e["response"]["response_version_id"]],
        "EVIDENCE_ACCEPTED": lambda e: [e["acceptance"]["acceptance_id"], e["acceptance"]["supporting_review_id"]],
        "EVIDENCE_PARTIAL": lambda e: [e["acceptance"]["acceptance_id"], e["acceptance"]["supporting_review_id"]],
        "EVIDENCE_REJECTED": lambda e: [e["acceptance"]["acceptance_id"], e["acceptance"]["supporting_review_id"]],
        "EVIDENCE_ACCEPTANCE_INVALIDATED": lambda e: [e["old_acceptance"]["acceptance_id"], e["response"]["response_version_id"]],
        "DECISION_RESOLVED": lambda e: [e["resolution"]["resolution_record_id"], *e["resolution"]["supporting_evidence_refs"]],
    }
    expected_kinds = {
        "REQUEST_AUTHORIZATION_RECORDED": ["authorization"],
        "REQUEST_AUTHORIZATION_DENIED": ["authorization"],
        "REQUEST_AUTHORIZED": ["authorization"],
        "REQUEST_DISPATCHED": ["authorization", "dispatch"],
        "REQUEST_CANCELLED": [], "DISPATCH_CANCELLED": [],
        "RESPONSE_RECEIVED": ["response"], "RESPONSE_SUPERSEDED": ["response"],
        "RESPONSE_NOT_PROVIDED": ["response_disposition"],
        "REVIEW_STARTED": ["response"], "REVIEW_COMPLETED": ["review", "response"],
        "REVIEW_REOPENED_FOR_CORRECTION": ["review"],
        "REVIEW_INVALIDATED_BY_RESPONSE_CORRECTION": ["review", "response"],
        "EVIDENCE_ACCEPTED": ["acceptance", "review"],
        "EVIDENCE_PARTIAL": ["acceptance", "review"],
        "EVIDENCE_REJECTED": ["acceptance", "review"],
        "EVIDENCE_ACCEPTANCE_INVALIDATED": ["acceptance", "response"],
    }
    event_by_id = {e.get("event_id"): e for e in events}
    _require(len(event_by_id) == len(events), "V5 event IDs must be unique.")

    # Every persisted record points to one event, and that event points back to
    # the exact record and owning entity.
    for event_id, entries in records_by_event.items():
        _require(len(entries) == 1, f"V5 record event linkage is ambiguous: {event_id}.")
        record, kind, id_field, entity_id = entries[0]
        event = event_by_id.get(event_id)
        _require(event is not None, f"V5 {kind} record has no matching event: {event_id}.")
        _require(event.get("entity_id") == entity_id,
                 f"V5 event entity does not match its {kind} record.")
        _require(record.get(id_field) in event.get("supporting_record_refs", []),
                 f"V5 event omits its exact {kind} record reference.")

    def resolve_ref(ref, expected_kind):
        entries = record_index.get(ref, [])
        _require(len(entries) == 1 and entries[0][0] == expected_kind,
                 f"V5 event reference {ref} is missing, ambiguous, or not a {expected_kind} record.")
        return entries[0][1]

    for event in events:
        etype = event.get("event_type")
        _require(etype in typed_refs, f"Unknown v5 event reference contract: {etype}.")
        refs = event.get("supporting_record_refs")
        source_refs = event.get("source_references", [])
        _require(isinstance(refs, list) and all(isinstance(x, str) and x for x in refs),
                 "V5 supporting_record_refs must contain non-empty lifecycle record IDs.")
        _require(len(refs) == len(set(refs)), "V5 event lifecycle references cannot be duplicated.")
        _require(isinstance(source_refs, list) and all(isinstance(x, str) and x for x in source_refs),
                 "V5 source_references must contain non-empty source citations.")
        _require(len(source_refs) == len(set(source_refs)), "V5 source citations cannot be duplicated.")

        entity_type = event.get("entity_type")
        owner = next((x for x in package.get("stakeholder_request_templates", [])
                      if x.get("request_id") == event.get("entity_id")), None)
        evidence = next((x for x in package.get("evidence_results", [])
                         if x.get("evidence_gap_id") == event.get("entity_id")), None)
        decision = next((x for x in package.get("decision_resolution_records", [])
                         if x.get("decision_id") == event.get("entity_id")), None)
        linked = records_by_event.get(event["event_id"], [])
        record = linked[0][0] if len(linked) == 1 else None
        context = {"request": owner, "evidence": evidence, "decision": decision}
        if etype in {"REQUEST_AUTHORIZATION_RECORDED", "REQUEST_AUTHORIZATION_DENIED", "REQUEST_AUTHORIZED"}:
            context["authorization"] = record or next((r for r in owner.get("authorization", {}).get("records", [])
                if r.get("authorization_id") == owner.get("authorization", {}).get("current_authorization_id")), None)
        elif etype == "REQUEST_DISPATCHED":
            context["dispatch"] = record; context["request"] = owner
        elif etype in {"RESPONSE_RECEIVED", "RESPONSE_SUPERSEDED"}:
            context["response"] = record
        elif etype == "RESPONSE_NOT_PROVIDED":
            context["response_disposition"] = record
        elif etype == "REVIEW_COMPLETED":
            context["review"] = record
        elif etype == "REVIEW_STARTED":
            context["start_response"] = resolve_ref(refs[0], "response")
            response_request = next((x for x in package.get("stakeholder_request_templates", [])
                                     if x.get("request_id") == context["start_response"].get("request_id")), None)
            _require(response_request is not None
                     and event.get("entity_id") in response_request.get("related_evidence_gap_ids", []),
                     "V5 review-start response is not linked to its evidence entity.")
        elif etype == "REVIEW_REOPENED_FOR_CORRECTION":
            old_id = event.get("supporting_record_refs", [None])[0]
            context["review"] = resolve_ref(old_id, "review")
        elif etype == "REVIEW_INVALIDATED_BY_RESPONSE_CORRECTION":
            context["old_review"] = resolve_ref(refs[0], "review")
            context["response"] = resolve_ref(refs[1], "response")
        elif etype in {"EVIDENCE_ACCEPTED", "EVIDENCE_PARTIAL", "EVIDENCE_REJECTED"}:
            context["acceptance"] = record
        elif etype == "EVIDENCE_ACCEPTANCE_INVALIDATED":
            context["old_acceptance"] = resolve_ref(refs[0], "acceptance")
            context["response"] = resolve_ref(refs[1], "response")
        elif etype == "DECISION_RESOLVED":
            context["resolution"] = record
        _require((entity_type == "request" and owner is not None)
                 or (entity_type == "evidence" and evidence is not None)
                 or (entity_type == "decision" and decision is not None),
                 "V5 event entity type does not identify exactly one owning record.")
        expected = typed_refs[etype](context)
        _require(refs == expected,
                 f"V5 {etype} lifecycle references do not exactly match its record contract.")
        kinds = expected_kinds.get(etype)
        if etype == "DECISION_RESOLVED":
            kinds = ["resolution", *(["evidence"] * len(expected[1:]))]
        _require(kinds is not None and len(kinds) == len(refs),
                 f"V5 {etype} reference contract is incomplete.")
        for ref, kind in zip(refs, kinds):
            resolve_ref(ref, kind)

        expected_sources = []
        timestamp_value = None
        if etype in {"RESPONSE_RECEIVED", "RESPONSE_SUPERSEDED"}:
            expected_sources = record.get("source_references", [])
            timestamp_value = record.get("received_at_utc")
            _require(event.get("source_provenance_exception") == record.get("documented_provenance_exception"),
                     "V5 response event provenance exception disagrees with its record.")
        elif etype == "REVIEW_COMPLETED":
            expected_sources = record.get("source_references", [])
            timestamp_value = record.get("reviewed_at_utc")
        elif etype in {"EVIDENCE_ACCEPTED", "EVIDENCE_PARTIAL", "EVIDENCE_REJECTED"}:
            expected_sources = record.get("source_references", [])
            timestamp_value = record.get("accepted_at_utc")
        elif etype in {"REQUEST_AUTHORIZATION_RECORDED", "REQUEST_AUTHORIZATION_DENIED", "REQUEST_AUTHORIZED"}:
            timestamp_value = context["authorization"].get("authorized_at_utc")
        elif etype == "REQUEST_DISPATCHED":
            timestamp_value = record.get("sent_at_utc")
        elif etype == "RESPONSE_NOT_PROVIDED":
            timestamp_value = record.get("recorded_at_utc")
        elif etype == "REVIEW_STARTED":
            response = resolve_ref(refs[0], "response")
            timestamp_value = response.get("received_at_utc")
        elif etype == "REVIEW_REOPENED_FOR_CORRECTION":
            timestamp_value = context["review"].get("reviewed_at_utc")
        elif etype == "REVIEW_INVALIDATED_BY_RESPONSE_CORRECTION":
            timestamp_value = max(_timestamp(context["old_review"].get("reviewed_at_utc"), "reviewed_at_utc"),
                                  _timestamp(context["response"].get("received_at_utc"), "received_at_utc"))
        elif etype == "EVIDENCE_ACCEPTANCE_INVALIDATED":
            timestamp_value = max(_timestamp(context["old_acceptance"].get("accepted_at_utc"), "accepted_at_utc"),
                                  _timestamp(context["response"].get("received_at_utc"), "received_at_utc"))
        elif etype == "DECISION_RESOLVED":
            timestamp_value = record.get("resolved_at_utc")
        _require(source_refs == expected_sources,
                 f"V5 {etype} source citations do not match the associated record.")
        if timestamp_value is not None:
            record_stamp = (timestamp_value if isinstance(timestamp_value, dt.datetime)
                            else _timestamp(timestamp_value, "associated record timestamp"))
            _require(_timestamp(event.get("occurred_at_utc"), "occurred_at_utc")
                     >= record_stamp,
                     f"V5 {etype} event precedes its associated record timestamp.")

    # Resolved decisions require exact Planning v2 mappings and every required
    # gap to have its own fully eligible current evidence result.
    results_by_gap = {}
    for result in package.get("evidence_results", []):
        results_by_gap.setdefault(result.get("evidence_gap_id"), []).append(result)
    for decision in package.get("decision_resolution_records", []):
        decision_id = decision.get("decision_id")
        _require(decision_id in planned, f"Decision has no authoritative Planning v2 mapping: {decision_id}.")
        required = planned[decision_id]
        _require(bool(required) and len(required) == len(set(required)),
                 f"Planning v2 required evidence gaps are missing or duplicated for {decision_id}.")
        _require(decision.get("required_evidence_gap_ids") == required,
                 f"Decision record evidence mapping disagrees with Planning v2 for {decision_id}.")
        if decision.get("resolution_status") != "RESOLVED":
            continue
        records = [r for r in decision.get("resolution_records", [])
                   if r.get("resolution_record_id") == decision.get("current_resolution_record_id")]
        _require(len(records) == 1, "Resolved decision requires exactly one current resolution record.")
        resolution = records[0]
        _require(resolution.get("supporting_evidence_refs") == required,
                 f"Resolution must cite every and only required evidence gap for {decision_id}.")
        for gap_id in required:
            _require(len(results_by_gap.get(gap_id, [])) == 1,
                     f"Required evidence gap has no unique result: {gap_id}.")
            result = results_by_gap[gap_id][0]
            _require(result.get("acceptance_status") == "ACCEPTED"
                     and result.get("review_status") == "ACCEPTED"
                     and not result.get("re_review_required"),
                     f"Required evidence gap is not fully accepted: {gap_id}.")
            _validate_current_review_and_acceptance(result, authorization_policy,
                                                    require_acceptance=True)


def _v5_decision_event_binding(package, events):
    """Ensure exactly one resolution event mirrors the current record exactly."""
    for decision in package.get("decision_resolution_records", []):
        if decision.get("resolution_status") != "RESOLVED":
            continue
        records = [x for x in decision.get("resolution_records", [])
                   if x.get("resolution_record_id") == decision.get("current_resolution_record_id")]
        _require(len(records) == 1, "Resolved decision requires exactly one current resolution record.")
        record = records[0]
        matching = [e for e in events if e.get("entity_id") == decision["decision_id"]
                    and e.get("event_type") == "DECISION_RESOLVED"]
        _require(len(matching) == 1, "Resolved decision requires exactly one DECISION_RESOLVED event.")
        event = matching[0]
        _require(record.get("event_id") == event.get("event_id"),
                 "Resolution record and event IDs disagree.")
        _require(event.get("supporting_record_refs") == [record["resolution_record_id"],
                 *record.get("supporting_evidence_refs", [])],
                 "Resolution event evidence references must exactly match its resolution record.")
        _require(_timestamp(event.get("occurred_at_utc"), "occurred_at_utc")
                 >= _timestamp(record.get("resolved_at_utc"), "resolved_at_utc"),
                 "Decision resolution event precedes its resolution record timestamp.")


def validate_event_history(events, *, entity_ids, initial_states, record_index=None,
                           authorization_policy=None):
    """Replay events deterministically and reject bad order, references, or transitions."""
    _unique([e.get("event_id") for e in events], "event_id")
    current = dict(initial_states); seen = {}; last_time = {}; last_global_time = None
    for event in events:
        _require(event.get("entity_id") in entity_ids, f"Unknown history entity: {event.get('entity_id')}.")
        key = (event["entity_id"], event.get("domain")); _require(key in current, f"No initial state for {key}.")
        _require(event.get("previous_status") == current[key], f"Previous-state mismatch for {key}.")
        _event_contract(event)
        if event.get("event_type") in {"REQUEST_CANCELLED", "DISPATCH_CANCELLED"}:
            _require(isinstance(event.get("reason"), str) and bool(event["reason"].strip()),
                     "Cancellation events require a non-empty reason.")
        stamp = _timestamp(event.get("occurred_at_utc"), "occurred_at_utc")
        if last_global_time is not None:
            _require(stamp >= last_global_time, "Lifecycle events are out of order globally (chronology).")
        last_global_time = stamp
        _actor(event.get("actor"))
        if event.get("event_type") in {"REQUEST_AUTHORIZATION_RECORDED", "REQUEST_AUTHORIZATION_DENIED"}:
            _authorized_actor(event.get("actor"), "request_authorization", authorization_policy)
        elif event.get("event_type") == "REVIEW_COMPLETED":
            _authorized_actor(event.get("actor"), "evidence_review", authorization_policy)
        elif event.get("event_type") in {"EVIDENCE_ACCEPTED", "EVIDENCE_PARTIAL", "EVIDENCE_REJECTED"}:
            _authorized_actor(event.get("actor"), "evidence_acceptance", authorization_policy)
        elif event.get("event_type") == "DECISION_RESOLVED":
            _authorized_actor(event.get("actor"), "decision_resolution", authorization_policy)
        refs = event.get("supporting_record_refs")
        _require(isinstance(refs, list) and all(isinstance(ref, str) and ref for ref in refs),
                 "supporting_record_refs must be a list of non-empty identifiers.")
        required_ref_types = {
            "REQUEST_AUTHORIZATION_RECORDED": {"authorization": 1},
            "REQUEST_AUTHORIZATION_DENIED": {"authorization": 1},
            "REQUEST_AUTHORIZED": {"authorization": 1},
            "REQUEST_DISPATCHED": {"authorization": 1, "dispatch": 1},
            "RESPONSE_RECEIVED": {"response": 1},
            "RESPONSE_SUPERSEDED": {"response": 1},
            "RESPONSE_NOT_PROVIDED": {"response_disposition": 1},
            "REVIEW_STARTED": {"response": 1},
            "REVIEW_COMPLETED": {"review": 1, "response": 1},
            "REVIEW_REOPENED_FOR_CORRECTION": {"review": 1},
            "EVIDENCE_ACCEPTED": {"acceptance": 1, "review": 1},
            "EVIDENCE_PARTIAL": {"acceptance": 1, "review": 1},
            "EVIDENCE_REJECTED": {"acceptance": 1, "review": 1},
            "EVIDENCE_ACCEPTANCE_INVALIDATED": {"acceptance": 1, "response": 1},
            "DECISION_RESOLVED": {"resolution": 1},
        }
        if record_index is not None:
            for kind in required_ref_types.get(event["event_type"], {}):
                matching = [ref for ref in refs if len(record_index.get(ref, [])) == 1
                            and record_index[ref][0][0] == kind]
                _require(len(matching) >= required_ref_types[event["event_type"]][kind],
                         f"Event {event['event_id']} lacks a valid {kind} supporting record reference.")
        if key in last_time: _require(stamp >= last_time[key], f"Events are out of order for {key}.")
        last_time[key] = stamp
        correction = event.get("event_type") in {"RESPONSE_SUPERSEDED", "REVIEW_REOPENED_FOR_CORRECTION", "REVIEW_INVALIDATED_BY_RESPONSE_CORRECTION", "EVIDENCE_ACCEPTANCE_INVALIDATED"}
        if correction:
            old_id = event.get("supersedes_event_id")
            _require(old_id in seen and bool(event.get("reason")), "Correction must supersede a prior event and explain why.")
            _require(seen[old_id]["entity_id"] == event["entity_id"] and seen[old_id]["domain"] == event["domain"], "Correction event must target the same entity/domain.")
            if event["event_type"] == "RESPONSE_SUPERSEDED":
                _require(key[1] == "response_status" and event["previous_status"] == event["resulting_status"] == "RECEIVED", "Response correction must preserve RECEIVED state.")
            elif event["event_type"] == "REVIEW_REOPENED_FOR_CORRECTION":
                _require(key[1] == "review_status" and event["previous_status"] in {"ACCEPTED", "REJECTED", "INCONCLUSIVE"} and event["resulting_status"] == "IN_PROGRESS", "Review correction must reopen a completed review.")
            elif event["event_type"] == "REVIEW_INVALIDATED_BY_RESPONSE_CORRECTION":
                _require(key[1] == "review_status" and event["previous_status"] in {"ACCEPTED", "REJECTED", "INCONCLUSIVE"} and event["resulting_status"] == "PENDING", "Material response correction must require re-review.")
            else:
                _require(key[1] == "acceptance_status" and event["previous_status"] == "ACCEPTED" and event["resulting_status"] == "NOT_ASSESSED", "Acceptance invalidation must require re-review.")
        else:
            validate_transition(key[1], event["previous_status"], event.get("resulting_status"))
            _require(not event.get("supersedes_event_id"), "Only correction events may supersede history.")
        current[key] = event["resulting_status"]; seen[event["event_id"]] = event
    return current


def validate_package(package, planning=None, *, authorization_policy=None):
    """Check package current states, unique IDs, event-history replay, and links."""
    schema_version = package.get("schema_version")
    _require(schema_version in {"3.0.0", "4.0.0", "5.0.0"}, "Expected schema version 3.0.0, 4.0.0, or 5.0.0.")
    strict_v5 = schema_version == "5.0.0"
    strict_v4 = schema_version in {"4.0.0", "5.0.0"}
    authorization_policy = authorization_policy or package.get("authorization_policy")
    requests = package.get("stakeholder_request_templates", []); gaps = package.get("evidence_availability_inventory", []); tasks = package.get("acquisition_tasks", []); decisions = package.get("decision_resolution_records", [])
    req_ids = {r.get("request_id") for r in requests}; gap_ids = {g.get("evidence_gap_id") for g in gaps}; task_ids = {t.get("task_id") for t in tasks}; dec_ids = {d.get("decision_id") for d in decisions}
    for values, records, label in ((req_ids, requests, "request"), (gap_ids, gaps, "gap"), (task_ids, tasks, "task"), (dec_ids, decisions, "decision")):
        _require(None not in values and len(values) == len(records), f"{label} IDs must be present and unique.")
    if strict_v4:
        for request in requests:
            for field in ("related_planning_task_ids", "related_acquisition_task_ids",
                          "related_evidence_gap_ids", "related_decision_ids", "related_requirement_ids"):
                _unique(request.get(field, []), f"{field} on {request.get('request_id')}")
    _require({f"STREQ-{i:02}" for i in range(1,10)} <= req_ids, "Original request IDs must remain present.")
    planning_task_ids = set(package.get("planning_task_ids", []))
    for r in requests:
        forbidden = {"status", "authorization_status", "review_status", "review_versions",
                     "current_review_version_id", "previous_review_version_id", "initial_review_status"}
        _require(not (forbidden & set(r)), "Duplicate request lifecycle status is forbidden; request, authorization, dispatch, response, and evidence review each have one authority.")
        _require("status" not in r.get("response", {}), "Nested response status duplicates authoritative response_status.")
        _require(r.get("request_status") in {"PREPARED", "AUTHORIZED", "CANCELLED"}, "Invalid request_status.")
        _require(set(r.get("related_planning_task_ids", [])) <= planning_task_ids, f"Unknown planning task on {r['request_id']}.")
        _require(set(r.get("related_acquisition_task_ids", [])) <= task_ids, f"Unknown acquisition task on {r['request_id']}.")
        if strict_v4:
            for task_id in r.get("related_acquisition_task_ids", []):
                task = next(x for x in tasks if x["task_id"] == task_id)
                _require(r["request_id"] in task.get("related_request_ids", []),
                         f"Task/request links are not reciprocal for {task_id} and {r['request_id']}.")
        _require(set(r.get("related_evidence_gap_ids", [])) <= gap_ids, f"Unknown evidence gap on {r['request_id']}.")
        _require(set(r.get("related_decision_ids", [])) <= dec_ids, f"Unknown decision on {r['request_id']}.")
        _require(all(isinstance(x, str) and x for x in r.get("related_requirement_ids", [])),
                 f"Invalid planning requirement link on {r['request_id']}.")
        auth = r.get("authorization", {})
        _require(auth.get("status") in {"PENDING", "AUTHORIZED", "DENIED"}, "Invalid authorization status.")
        auth_records = auth.get("records", []); _unique([x.get("authorization_id") for x in auth_records], "authorization IDs")
        current_auth_id = auth.get("current_authorization_id")
        _require((auth.get("status") == "PENDING") == (current_auth_id is None), "Authorization status and current record pointer contradict.")
        if current_auth_id is not None:
            current_auth = next((x for x in auth_records if x.get("authorization_id") == current_auth_id), None)
            _require(current_auth and current_auth.get("request_id") == r["request_id"] and current_auth.get("status") == auth["status"], "Current authorization record is missing or inconsistent.")
            _actor(current_auth.get("authorized_by"), "authorized_by"); _timestamp(current_auth.get("authorized_at_utc"), "authorized_at_utc")
            if strict_v4:
                _authorized_actor(current_auth.get("authorized_by"), "request_authorization",
                                  authorization_policy, "authorized_by")
        if r["request_status"] == "AUTHORIZED":
            _require(auth.get("status") == "AUTHORIZED", "AUTHORIZED request lacks matching authorization state.")
        if r["request_status"] == "CANCELLED":
            _require(r.get("dispatch", {}).get("status") == "CANCELLED", "CANCELLED request requires matching dispatch cancellation state.")
        if r.get("dispatch", {}).get("status") == "CANCELLED":
            _require(r["request_status"] == "CANCELLED", "Cancelled dispatch contradicts request state.")
        if r["request_status"] == "PREPARED":
            _require(auth.get("status") in {"PENDING", "DENIED"}, "PREPARED request contradicts authorization state.")
        dispatch = r.get("dispatch", {}); ds = dispatch.get("status")
        _require(ds in {"NOT_SENT", "SENT", "CANCELLED"}, "Invalid dispatch status.")
        dispatch_records = dispatch.get("records", []); _unique([x.get("dispatch_id") for x in dispatch_records], "dispatch IDs")
        current_dispatch_id = dispatch.get("current_dispatch_id")
        _require((ds == "SENT") == (current_dispatch_id is not None), "Dispatch status and current record pointer contradict.")
        if ds == "SENT":
            current_dispatch = next((x for x in dispatch_records if x.get("dispatch_id") == current_dispatch_id), None)
            _require(r["request_status"] == "AUTHORIZED" and current_dispatch and current_dispatch.get("request_id") == r["request_id"], "SENT request lacks authorization or matching dispatch record.")
            _actor(current_dispatch.get("sender"), "sender"); _timestamp(current_dispatch.get("sent_at_utc"), "sent_at_utc")
        response_status = r.get("response_status")
        _require(response_status in {"PENDING", "RECEIVED", "NOT_PROVIDED"}, "Invalid response status.")
        versions = r.get("response_versions", []); _unique([x.get("response_version_id") for x in versions], "response version IDs")
        _validate_version_chain(versions, "response_version_id", "supersedes_response_version_id",
                                "correction_reason", r.get("current_response_version_id"))
        current_response = r.get("current_response_version_id")
        _require(current_response is None or current_response in {x["response_version_id"] for x in versions}, "Current response pointer is invalid.")
        _require((response_status == "RECEIVED") == (current_response is not None), "Response status and current version contradict.")
        if response_status == "RECEIVED":
            _require(ds == "SENT", "Received response requires actual dispatch.")
            current_version = next(x for x in versions if x["response_version_id"] == current_response)
            _require(current_version.get("request_id") == r["request_id"], "Current response belongs to a different request.")
            _timestamp(current_version.get("received_at_utc"), "received_at_utc"); _actor(current_version.get("respondent"), "respondent")
            _require(current_version.get("provenance_status") == "VERIFIED" or current_version.get("documented_provenance_exception"), "Current response lacks verified provenance or an explicit exception.")
            _require(bool(current_version.get("source_references")) or current_version.get("documented_provenance_exception"), "Current response lacks source references.")
        if response_status == "NOT_PROVIDED":
            dispositions = r.get("response_disposition_records", [])
            _require(bool(dispositions), "NOT_PROVIDED response status requires a disposition record.")
            _unique([x.get("disposition_id") for x in dispositions], "response disposition IDs")
            current_disposition = dispositions[-1]
            _require(current_disposition.get("request_id") == r["request_id"] and current_disposition.get("reason"), "Response disposition is incomplete.")
            _actor(current_disposition.get("recorded_by"), "recorded_by"); _timestamp(current_disposition.get("recorded_at_utc"), "recorded_at_utc")
    for t in tasks:
        _require(set(t.get("dependencies", [])) <= task_ids, "Unknown task dependency.")
        _require(set(t.get("related_request_ids", [])) <= req_ids, "Unknown request linked to task.")
        if strict_v4:
            _unique(t.get("related_evidence_gap_ids", []), f"related_evidence_gap_ids on {t.get('task_id')}")
            _require(set(t.get("related_evidence_gap_ids", [])) <= gap_ids,
                     f"Unknown evidence gap linked to task {t.get('task_id')}.")
            for request_id in t.get("related_request_ids", []):
                request = next(x for x in requests if x["request_id"] == request_id)
                _require(t["task_id"] in request.get("related_acquisition_task_ids", []),
                         f"Task/request links are not reciprocal for {t['task_id']} and {request_id}.")
    for g in gaps:
        fields = ("direct_related_requirement_ids", "downstream_requirement_dependency_ids", "direct_related_decision_ids", "downstream_decision_dependency_ids")
        _require(all(f in g for f in fields), f"Incomplete direct/downstream links for {g['evidence_gap_id']}.")
        _require(not set(g[fields[0]]) & set(g[fields[1]]), "Direct and downstream requirements overlap.")
        _require(not set(g[fields[2]]) & set(g[fields[3]]), "Direct and downstream decisions overlap.")
        for field in fields:
            _unique(g[field], f"{field} for {g['evidence_gap_id']}")
    result_records = package.get("evidence_results", [])
    result_ids = [x.get("evidence_gap_id") for x in result_records]
    if strict_v4:
        _unique(result_ids, "evidence-result gap IDs")
        _require(len(result_records) == len(gap_ids) and set(result_ids) == gap_ids,
                 "There must be exactly one evidence result per gap.")
    results = {x.get("evidence_gap_id"): x for x in result_records}
    _require(set(results) == gap_ids, "There must be exactly one evidence result per gap.")
    for request in requests:
        current_response_id = request.get("current_response_version_id")
        current_response = next((v for v in request.get("response_versions", [])
                                 if v.get("response_version_id") == current_response_id), None)
        if current_response and current_response.get("material_change"):
            for gap_id in request.get("related_evidence_gap_ids", []):
                linked_result = results.get(gap_id)
                if linked_result and linked_result.get("current_review_version_id"):
                    current_review = next((v for v in linked_result.get("review_versions", [])
                                           if v.get("review_id") == linked_result["current_review_version_id"]), None)
                    _require(current_review and current_review.get("response_version_id") == current_response_id,
                             "Material response correction requires linked evidence to be re-reviewed against the current response version.")
    response_owners = {}
    for request in requests:
        for version in request.get("response_versions", []):
            response_id = version["response_version_id"]
            _require(response_id not in response_owners, "Response version IDs must be globally unique.")
            response_owners[response_id] = request
    for result in results.values():
        _validate_version_chain(result.get("review_versions", []), "review_id",
                                "supersedes_review_id", "correction_reason",
                                result.get("current_review_version_id"),
                                allow_no_current=bool(result.get("re_review_required")))
        _validate_version_chain(result.get("acceptance_versions", []), "acceptance_id",
                                "supersedes_acceptance_id", "correction_reason",
                                result.get("current_acceptance_id"),
                                allow_no_current=bool(result.get("re_review_required")))
        if result.get("current_review_version_id"):
            current_review = next((x for x in result.get("review_versions", []) if x["review_id"] == result["current_review_version_id"]), None)
            _require(current_review is not None, "Current review pointer is invalid.")
            owner = response_owners.get(current_review.get("response_version_id"))
            _require(owner is not None and result["evidence_gap_id"] in owner.get("related_evidence_gap_ids", []),
                     "Review must reference a response version from a linked request.")
            if owner.get("current_response_version_id") != current_review.get("response_version_id"):
                current_response = next((item for item in owner.get("response_versions", [])
                                         if item.get("response_version_id") == owner.get("current_response_version_id")), None)
                _require(current_response is not None
                         and current_response.get("material_change") is False
                         and _review_response_chain_is_non_material(
                             owner, current_response.get("response_version_id"),
                             current_review.get("response_version_id")),
                         "Review must cite the current response version unless every later response correction is explicitly non-material.")
            if strict_v4:
                _validate_current_review_and_acceptance(result, authorization_policy)
        if result.get("acceptance_status") == "ACCEPTED":
            _require(result.get("review_status") == "ACCEPTED" and result.get("current_review_version_id"), "Accepted evidence needs a current accepted review.")
            review = next((x for x in result.get("review_versions", []) if x["review_id"] == result["current_review_version_id"]), None)
            _require(review and review.get("sufficiency_assessment") == "SUFFICIENT", "Accepted evidence needs a sufficient review.")
            _require(result.get("current_acceptance_id") in {x.get("acceptance_id") for x in result.get("acceptance_versions", [])}, "Accepted evidence needs an acceptance record.")
            if strict_v4:
                _validate_current_review_and_acceptance(result, authorization_policy, require_acceptance=True)
        if result.get("acceptance_status") in {"PARTIAL", "REJECTED"}:
            disposition = next((x for x in result.get("acceptance_versions", [])
                                if x.get("acceptance_id") == result.get("current_acceptance_id")), None)
            _require(disposition and disposition.get("acceptance_status") == result["acceptance_status"]
                     and disposition.get("rationale") and disposition.get("source_references"),
                     "Partial/rejected evidence needs a current disposition record, rationale, and source references.")
            _require(disposition.get("supporting_review_id") == result.get("current_review_version_id"),
                     "Evidence disposition must cite the current review.")
            if result.get("review_status") in {"REJECTED", "INCONCLUSIVE"}:
                _require(result.get("acceptance_status") == "REJECTED",
                         "Rejected or inconclusive review cannot yield accepted evidence.")
    for d in decisions:
        if d.get("resolution_status") == "RESOLVED":
            rec = next((x for x in d.get("resolution_records", []) if x.get("resolution_record_id") == d.get("current_resolution_record_id")), None)
            _require(rec and rec.get("authorization", {}).get("status") == "AUTHORIZED", "Resolved decision requires an authorized resolution record.")
            if strict_v4:
                _require(rec.get("decision_id") == d.get("decision_id"), "Resolution record decision reference is inconsistent.")
                _authorized_actor(rec.get("authorization", {}).get("authorized_by"), "decision_resolution", authorization_policy, "decision authorization")
                _authorized_actor(rec.get("decision_maker"), "decision_resolution", authorization_policy, "decision_maker")
                _timestamp(rec.get("authorization", {}).get("authorized_at_utc"), "authorized_at_utc")
                resolved_at = _timestamp(rec.get("resolved_at_utc"), "resolved_at_utc")
                _require(bool(rec.get("outcome") and rec.get("rationale")), "Resolution requires an outcome and rationale.")
                _require(bool(rec.get("supporting_evidence_refs")), "Resolution requires supporting evidence references.")
                evidence_by_id = {}
                for result in result_records:
                    evidence_by_id.setdefault(result.get("evidence_gap_id"), []).append(result)
                    evidence_by_id.setdefault(result.get("result_id"), []).append(result)
                for ref in rec["supporting_evidence_refs"]:
                    matches = evidence_by_id.get(ref, [])
                    _require(len(matches) == 1, f"Resolution reference must identify exactly one evidence result: {ref}.")
                    evidence = matches[0]
                    _require(evidence.get("acceptance_status") == "ACCEPTED"
                             and evidence.get("review_status") == "ACCEPTED"
                             and not evidence.get("re_review_required"),
                             f"Resolution evidence is not fully accepted: {ref}.")
                    review = _validate_current_review_and_acceptance(evidence, authorization_policy, require_acceptance=True)
                    acceptance = next(x for x in evidence["acceptance_versions"]
                                      if x["acceptance_id"] == evidence["current_acceptance_id"])
                    _require(resolved_at >= _timestamp(acceptance["accepted_at_utc"], "accepted_at_utc"),
                             "Decision resolution cannot precede accepted evidence.")
    _validate_package_trace(package)
    if strict_v5:
        _validate_v5_planning_source(package, planning)
    if planning is not None: validate_traceability(package, planning)
    initial = initial_history_states(package)
    _require(package.get("history_initial_states", {}).get("by_entity") == _nest_initial_states(initial),
             "Recorded initial history states disagree with lifecycle records.")
    record_index = _record_index(package)
    events = package.get("lifecycle_events", [])
    current = validate_event_history(events, entity_ids=req_ids | gap_ids | dec_ids,
                                     initial_states=initial, record_index=record_index,
                                     authorization_policy=authorization_policy)
    if strict_v5:
        _validate_v5_event_bindings(package, events, planning, authorization_policy)
        _v5_decision_event_binding(package, events)
    if strict_v4:
        event_by_id = {event["event_id"]: event for event in events}
        def require_link(record, identifier, expected_type, entity_id, expected_event_types):
            event_id = record.get("event_id")
            linked = event_by_id.get(event_id)
            _require(linked is not None and linked.get("entity_id") == entity_id
                     and linked.get("entity_type") == expected_type
                     and linked.get("event_type") in expected_event_types
                     and identifier in linked.get("supporting_record_refs", []),
                     f"Record {identifier} must link to its matching lifecycle event.")
        for request in requests:
            for record in request.get("authorization", {}).get("records", []):
                if record.get("authorization_id") == request.get("authorization", {}).get("current_authorization_id"):
                    event_types = {"REQUEST_AUTHORIZATION_DENIED"} if record.get("status") == "DENIED" else {"REQUEST_AUTHORIZATION_RECORDED"}
                    require_link(record, record["authorization_id"], "request", request["request_id"], event_types)
            for record in request.get("dispatch", {}).get("records", []):
                if record.get("dispatch_id") == request.get("dispatch", {}).get("current_dispatch_id"):
                    require_link(record, record["dispatch_id"], "request", request["request_id"], {"REQUEST_DISPATCHED"})
            for record in request.get("response_versions", []):
                event_type = "RESPONSE_SUPERSEDED" if record.get("supersedes_response_version_id") else "RESPONSE_RECEIVED"
                require_link(record, record["response_version_id"], "request", request["request_id"], {event_type})
            for record in request.get("response_disposition_records", []):
                require_link(record, record["disposition_id"], "request", request["request_id"], {"RESPONSE_NOT_PROVIDED"})
        for result in results.values():
            for record in result.get("review_versions", []):
                require_link(record, record["review_id"], "evidence", result["evidence_gap_id"], {"REVIEW_COMPLETED"})
            for record in result.get("acceptance_versions", []):
                if record.get("acceptance_status") == "ACCEPTED" or record.get("acceptance_id") == result.get("current_acceptance_id"):
                    event_type = {"ACCEPTED": "EVIDENCE_ACCEPTED", "PARTIAL": "EVIDENCE_PARTIAL", "REJECTED": "EVIDENCE_REJECTED"}.get(record.get("acceptance_status"))
                    require_link(record, record["acceptance_id"], "evidence", result["evidence_gap_id"], {event_type})
        for decision in decisions:
            for record in decision.get("resolution_records", []):
                require_link(record, record["resolution_record_id"], "decision", decision["decision_id"], {"DECISION_RESOLVED"})
        for identifier, entries in record_index.items():
            _require(len(entries) == 1, f"Record identifier is ambiguous or duplicated: {identifier}.")
        event_timestamps = {event["event_id"]: _timestamp(event["occurred_at_utc"], "occurred_at_utc")
                            for event in events}
        for request in requests:
            auth_id = request.get("authorization", {}).get("current_authorization_id")
            dispatch_id = request.get("dispatch", {}).get("current_dispatch_id")
            response_id = request.get("current_response_version_id")
            auth_rec = next((x for x in request.get("authorization", {}).get("records", []) if x.get("authorization_id") == auth_id), None)
            dispatch_rec = next((x for x in request.get("dispatch", {}).get("records", []) if x.get("dispatch_id") == dispatch_id), None)
            response_rec = next((x for x in request.get("response_versions", []) if x.get("response_version_id") == response_id), None)
            if auth_rec and dispatch_rec:
                _require(_timestamp(dispatch_rec.get("sent_at_utc"), "sent_at_utc") >= _timestamp(auth_rec.get("authorized_at_utc"), "authorized_at_utc"),
                         "Dispatch cannot precede its authorization.")
            if dispatch_rec and response_rec:
                _require(_timestamp(response_rec.get("received_at_utc"), "received_at_utc") >= _timestamp(dispatch_rec.get("sent_at_utc"), "sent_at_utc"),
                         "Response receipt cannot precede dispatch.")
        for result in results.values():
            review = next((x for x in result.get("review_versions", []) if x.get("review_id") == result.get("current_review_version_id")), None)
            if review:
                owner = response_owners[review["response_version_id"]]
                response = next(x for x in owner["response_versions"] if x["response_version_id"] == review["response_version_id"])
                _require(_timestamp(review.get("reviewed_at_utc"), "reviewed_at_utc") >= _timestamp(response.get("received_at_utc"), "received_at_utc"),
                         "Review cannot precede response receipt.")
                _require(event_timestamps[review["event_id"]] >= _timestamp(review.get("reviewed_at_utc"), "reviewed_at_utc"),
                         "Review event cannot precede review timestamp.")
            acceptance = next((x for x in result.get("acceptance_versions", []) if x.get("acceptance_id") == result.get("current_acceptance_id")), None)
            if acceptance:
                _require(review is not None and _timestamp(acceptance.get("accepted_at_utc"), "accepted_at_utc") >= _timestamp(review.get("reviewed_at_utc"), "reviewed_at_utc"),
                         "Acceptance cannot precede its supporting review.")
                _require(event_timestamps[acceptance["event_id"]] >= _timestamp(acceptance.get("accepted_at_utc"), "accepted_at_utc"),
                         "Acceptance event cannot precede acceptance timestamp.")
        for decision in decisions:
            resolution = next((x for x in decision.get("resolution_records", []) if x.get("resolution_record_id") == decision.get("current_resolution_record_id")), None)
            if resolution:
                auth_at = _timestamp(resolution.get("authorization", {}).get("authorized_at_utc"), "authorized_at_utc")
                resolved_at = _timestamp(resolution.get("resolved_at_utc"), "resolved_at_utc")
                _require(resolved_at >= auth_at and event_timestamps[resolution["event_id"]] >= resolved_at,
                         "Decision resolution chronology is inconsistent.")
    for r in requests:
        rid=r["request_id"]
        for domain,actual in (("request_status",r["request_status"]),("authorization_status",r["authorization"]["status"]),("dispatch_status",r["dispatch"]["status"]),("response_status",r["response_status"])):
            _require(current[(rid,domain)] == actual, f"Event history does not derive current {domain} for {rid}.")
    for g in gaps:
        result=results[g["evidence_gap_id"]]; gid=g["evidence_gap_id"]
        for domain,actual in (("review_status",result["review_status"]),("acceptance_status",result["acceptance_status"])):
            _require(current[(gid,domain)] == actual, f"Event history does not derive {domain} for {gid}.")
    for d in decisions: _require(current[(d["decision_id"],"resolution_status")] == d["resolution_status"], "Decision state disagrees with event history.")


def _validate_package_trace(package):
    gaps = {x["evidence_gap_id"]: x for x in package["evidence_availability_inventory"]}
    rows = {x["evidence_gap_id"]: x for x in package["traceability"]}
    _require(len(rows) == len(package["traceability"]) and set(rows) == set(gaps),
             "Traceability must contain one row per gap.")
    for gap_id, gap in gaps.items():
        row = rows[gap_id]
        request_ids = sorted(r["request_id"] for r in package["stakeholder_request_templates"]
                             if gap_id in r.get("related_evidence_gap_ids", []))
        _require(row.get("request_template_ids") == request_ids,
                 f"Request traceability mismatch for {gap_id}.")
        task_ids = sorted(t["task_id"] for t in package["acquisition_tasks"]
                          if gap_id in t.get("related_evidence_gap_ids", []))
        _require(row.get("acquisition_task_ids") == task_ids,
                 f"Acquisition task traceability mismatch for {gap_id}.")
        mapping = (
            ("requirement_ids", "direct_related_requirement_ids"),
            ("downstream_requirement_dependency_ids", "downstream_requirement_dependency_ids"),
            ("direct_decision_ids", "direct_related_decision_ids"),
            ("downstream_decision_ids", "downstream_decision_dependency_ids"),
        )
        for row_field, gap_field in mapping:
            _require(row.get(row_field) == gap.get(gap_field),
                     f"{row_field} traceability mismatch for {gap_id}.")


def validate_traceability(package, planning):
    """Enforce exact request/table agreement, references, and direct semantics."""
    plan_tasks={x["task_id"] for x in planning["dependency_and_execution_plan"]["tasks"]}
    plan_reqs={x["requirement_id"]:x for x in planning["operational_requirements_register"]["requirements"]}
    plan_decs={x["decision_id"]:x for x in planning["decision_register"]["decisions"]}
    acq_tasks={x["task_id"] for x in package["acquisition_tasks"]}
    trace_by_gap = {row["evidence_gap_id"]: row for row in package["traceability"]}
    gaps_by_id = {gap["evidence_gap_id"]: gap for gap in package["evidence_availability_inventory"]}
    for r in package["stakeholder_request_templates"]:
        for field in ("related_planning_task_ids", "related_acquisition_task_ids", "related_evidence_gap_ids", "related_decision_ids", "related_requirement_ids"):
            _unique(r.get(field, []), f"{field} on {r['request_id']}")
        _require(bool(r.get("related_planning_task_ids")) and bool(r.get("related_acquisition_task_ids")), f"{r['request_id']} needs direct task links.")
        _require(set(r["related_planning_task_ids"])<=plan_tasks and set(r["related_acquisition_task_ids"])<=acq_tasks, f"Invalid task reference on {r['request_id']}.")
        _require(set(r.get("related_requirement_ids", [])) <= set(plan_reqs), f"Invalid planning requirement on {r['request_id']}.")
        _require(set(r.get("related_decision_ids", [])) <= set(plan_decs), f"Invalid planning decision on {r['request_id']}.")
        linked_gaps = r.get("related_evidence_gap_ids", [])
        _require(bool(linked_gaps), f"{r['request_id']} must link at least one evidence gap.")
        _require(set(r["related_planning_task_ids"]) <= {x for gid in linked_gaps for x in trace_by_gap[gid].get("planning_task_ids", [])},
                 f"Planning task traceability mismatch for {r['request_id']}.")
        _require(set(r["related_acquisition_task_ids"]) <= {x for gid in linked_gaps for x in trace_by_gap[gid].get("acquisition_task_ids", [])},
                 f"Acquisition task traceability mismatch for {r['request_id']}.")
        linked_requirements = {x for gap_id in linked_gaps for x in
                               gaps_by_id[gap_id]["direct_related_requirement_ids"] +
                               gaps_by_id[gap_id]["downstream_requirement_dependency_ids"]}
        linked_decisions = {x for gap_id in linked_gaps for x in
                            gaps_by_id[gap_id]["direct_related_decision_ids"] +
                            gaps_by_id[gap_id]["downstream_decision_dependency_ids"]}
        _require(set(r.get("related_requirement_ids", [])) <= linked_requirements,
                 f"Request requirement links disagree with its linked evidence gaps: {r['request_id']}.")
        _require(set(r.get("related_decision_ids", [])) <= linked_decisions,
                 f"Request decision links disagree with its linked evidence gaps: {r['request_id']}.")
    for g in package["evidence_availability_inventory"]:
        direct_reqs=set(g["direct_related_requirement_ids"]); downstream_reqs=set(g["downstream_requirement_dependency_ids"])
        direct_decs=set(g["direct_related_decision_ids"]); downstream_decs=set(g["downstream_decision_dependency_ids"])
        _require(direct_reqs|downstream_reqs <= set(plan_reqs), f"Unknown planning requirement on {g['evidence_gap_id']}.")
        _require(direct_decs|downstream_decs <= set(plan_decs), f"Unknown planning decision on {g['evidence_gap_id']}.")
        _require(not direct_reqs&downstream_reqs and not direct_decs&downstream_decs, "Direct and downstream links overlap.")
        decisions_supporting={rid for did in direct_decs for rid in plan_decs[did].get("related_requirement_ids",[])}
        _require(direct_reqs<=decisions_supporting, f"Direct requirement link is not supported by a directly related decision for {g['evidence_gap_id']}.")
        for rid in direct_reqs:
            _require(g["evidence_gap_id"] in plan_reqs[rid].get("related_evidence_gap_ids",[]), f"Requirement {rid} does not reference gap {g['evidence_gap_id']} in Planning v2.")
    for row in package["traceability"]:
        gap=next(x for x in package["evidence_availability_inventory"] if x["evidence_gap_id"]==row["evidence_gap_id"])
        _require(row.get("requirement_ids")==gap["direct_related_requirement_ids"], "Trace direct requirement links disagree.")
        _require(row.get("downstream_requirement_dependency_ids")==gap["downstream_requirement_dependency_ids"], "Trace downstream requirement links disagree.")
        _require(row.get("direct_decision_ids")==gap["direct_related_decision_ids"], "Trace direct decision links disagree.")
        _require(row.get("downstream_decision_ids")==gap["downstream_decision_dependency_ids"], "Trace downstream decision links disagree.")


def initial_history_states(package):
    """Return initial per-entity states used to replay the append-only log."""
    states={}
    for r in package["stakeholder_request_templates"]:
        rid=r["request_id"]
        states[(rid,"request_status")]=r.get("initial_request_status","PREPARED")
        states[(rid,"authorization_status")]=r.get("initial_authorization_status","PENDING")
        states[(rid,"dispatch_status")]=r.get("initial_dispatch_status","NOT_SENT")
        states[(rid,"response_status")]=r.get("initial_response_status","PENDING")
    for g in package["evidence_availability_inventory"]:
        states[(g["evidence_gap_id"],"review_status")]=g.get("initial_review_status","PENDING")
        states[(g["evidence_gap_id"],"acceptance_status")]=g.get("initial_acceptance_status","NOT_ASSESSED")
    for d in package["decision_resolution_records"]:
        states[(d["decision_id"],"resolution_status")]=d.get("initial_resolution_status","OPEN")
    return states


def _nest_initial_states(states):
    nested = {}
    for (entity_id, domain), status in states.items():
        nested.setdefault(entity_id, {})[domain] = status
    return nested


def _validate_version_chain(records, id_field, supersedes_field, reason_field, current_id,
                            allow_no_current=False):
    """Require an ordered, acyclic chain and a current pointer to its tip."""
    _unique([x.get(id_field) for x in records], id_field)
    previous_id = None
    for index, record in enumerate(records):
        _validate_supersession(records[:index], record, id_field, supersedes_field, reason_field)
        if index:
            _require(record.get(supersedes_field) == previous_id,
                     f"{id_field} versions must form one ordered supersession chain.")
        previous_id = record[id_field]
    _require(current_id == previous_id or (allow_no_current and current_id is None),
             f"Current {id_field} must point to the latest version or be absent after explicit invalidation.")


def _review_response_chain_is_non_material(request, current_id, reviewed_id):
    """Return whether all response versions after a review were non-material."""
    versions = {item.get("response_version_id"): item
                for item in request.get("response_versions", [])}
    seen = set()
    cursor = current_id
    while cursor and cursor != reviewed_id:
        if cursor in seen:
            return False
        seen.add(cursor)
        version = versions.get(cursor)
        if version is None or version.get("material_change") is not False:
            return False
        cursor = version.get("supersedes_response_version_id")
    return cursor == reviewed_id
