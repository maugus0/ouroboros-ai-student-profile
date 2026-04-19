"""ReAct-style clarification decision engine for profile data."""

from typing import Any

from app.services.profile_value_utils import normalize_degree_level_value, normalize_field_name


def apply_react_decision_pattern(profile_data: dict[str, Any]) -> dict[str, Any]:
    """Apply an internal Reason-Act-Observe pass for all fields requiring clarification.

    Reason: Evaluate if fields are missing, contradictory, or low-confidence.
    Act: Mark fields that need clarification in the decision trace.
    Observe: Derive the clarification queue from the decision trace (single source of truth).
    """
    normalized = dict(profile_data or {})

    # Canonicalize legacy extraction key to the readiness-facing field name.
    if "gpa" not in normalized and "gpa_highest" in normalized:
        normalized["gpa"] = normalized.get("gpa_highest")

    confidence_map = normalized.get("confidence_map") if isinstance(normalized.get("confidence_map"), dict) else {}
    if "gpa" not in confidence_map and "gpa_highest" in confidence_map:
        confidence_map["gpa"] = confidence_map.get("gpa_highest")
    contradiction_flags = (
        normalized.get("contradiction_flags") if isinstance(normalized.get("contradiction_flags"), list) else []
    )

    contradicted_fields: set[str] = set()
    for item in contradiction_flags:
        if not isinstance(item, dict):
            continue
        field = normalize_field_name(item.get("field") or item.get("field_name"))
        if field:
            contradicted_fields.add(field)

    critical_rules = {
        "full_name": {
            "question": "What is your full name?",
            "min_confidence": 0.75,
            "require_when_missing": False,
        },
        "email": {
            "question": "What is your email address?",
            "min_confidence": 0.75,
            "require_when_missing": False,
        },
        "current_degree_level": {
            "question": "What is your current degree level?",
            "min_confidence": 0.7,
            "require_when_missing": True,
        },
        "target_degree_level": {
            "question": "What is your target degree level?",
            "min_confidence": 0.7,
            "require_when_missing": True,
        },
        "gpa": {
            "question": "What is your highest GPA?",
            "min_confidence": 0.65,
            "require_when_missing": False,
        },
    }

    default_questions = {
        "publications": "Do you have publications? Please provide title, venue, and year if available.",
        "phone": "What is your phone number?",
        "nationality": "What is your nationality?",
        "date_of_birth": "What is your date of birth?",
        "gpa_scale": "What GPA scale is used?",
    }

    decision_trace: dict[str, Any] = {}

    for field, rule in critical_rules.items():
        value = normalized.get(field)
        reason = None

        if field in {"current_degree_level", "target_degree_level"}:
            normalized_degree = normalize_degree_level_value(field, value)
            if normalized_degree is None or normalized_degree == "unknown":
                reason = "missing_or_unknown"
        else:
            is_missing = value is None or (isinstance(value, str) and not value.strip())
            if is_missing and rule["require_when_missing"]:
                reason = "missing_or_unknown"

        if reason is None and field in contradicted_fields:
            reason = "contradiction_detected"

        if reason is None and field in confidence_map:
            try:
                confidence = float(confidence_map[field])
                min_confidence = rule.get("min_confidence")
                if isinstance(min_confidence, (int, float)) and confidence < float(min_confidence):
                    reason = "low_confidence"
            except (TypeError, ValueError):
                reason = "invalid_confidence"

        if reason is None:
            decision_trace[field] = {"decision": "accept"}
        else:
            decision_trace[field] = {"decision": "clarify", "reason": reason}

    current_normalized = normalize_degree_level_value("current_degree_level", normalized.get("current_degree_level"))
    target_normalized = normalize_degree_level_value("target_degree_level", normalized.get("target_degree_level"))

    if (
        current_normalized not in {None, "unknown"}
        and target_normalized not in {None, "unknown"}
        and current_normalized == target_normalized
    ):
        decision_trace["target_degree_level"] = {
            "decision": "clarify",
            "reason": "ambiguous_current_equals_target",
        }

    fields_to_check = set()

    queue = list(normalized.get("clarification_queue") or [])
    for item in queue:
        if isinstance(item, dict):
            field = normalize_field_name(item.get("field"))
            if field:
                field_confidence = confidence_map.get(field)
                try:
                    is_user_answered = field_confidence is not None and float(field_confidence) == 1.0
                except (TypeError, ValueError):
                    is_user_answered = False

                if not is_user_answered:
                    fields_to_check.add(field)

    missing_fields = list(normalized.get("missing_critical_fields") or [])
    for field in missing_fields:
        field_norm = normalize_field_name(field)
        if field_norm:
            fields_to_check.add(field_norm)

    for field in fields_to_check:
        if field not in decision_trace:
            decision_trace[field] = {"decision": "clarify", "reason": "missing_or_unknown"}

    target_degree_normalized = normalize_degree_level_value(
        "target_degree_level", normalized.get("target_degree_level")
    )
    publications = normalized.get("publications")
    has_publications = isinstance(publications, list) and len(publications) > 0
    publications_confidence = confidence_map.get("publications")

    publications_already_answered = False
    if publications_confidence is not None:
        try:
            is_user_answered = float(publications_confidence) == 1.0
            publications_already_answered = is_user_answered
        except (TypeError, ValueError):
            pass

    if publications_already_answered and "publications" not in decision_trace:
        decision_trace["publications"] = {"decision": "accept"}

    if (
        target_degree_normalized == "phd"
        and not has_publications
        and not publications_already_answered
        and "publications" not in decision_trace
    ):
        decision_trace["publications"] = {"decision": "clarify", "reason": "missing_or_unknown"}

    new_queue: list[dict[str, Any]] = []
    for field, trace_entry in decision_trace.items():
        if isinstance(trace_entry, dict) and trace_entry.get("decision") == "clarify":
            question = critical_rules.get(field, {}).get("question") or default_questions.get(
                field, f"Please provide your {field.replace('_', ' ')}."
            )
            new_queue.append({"field": field, "question": question})

    normalized["clarification_queue"] = new_queue
    normalized.pop("missing_critical_fields", None)
    normalized["react_decision_trace"] = decision_trace
    target_degree_trace = decision_trace.get("target_degree_level")
    normalized["target_degree_needs_clarification"] = bool(
        isinstance(target_degree_trace, dict) and target_degree_trace.get("decision") == "clarify"
    )
    return normalized
