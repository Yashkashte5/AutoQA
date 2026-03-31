from typing import Any
from urllib.parse import urlparse


def _normalize_endpoint(endpoint: Any) -> str:
    if endpoint is None:
        return ""
    value = str(endpoint).strip()
    if not value:
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        parsed = urlparse(value)
        value = parsed.path or ""
        if parsed.query:
            value = f"{value}?{parsed.query}"
        if not value:
            return ""
    if not value.startswith("/"):
        value = "/" + value
    return value


def validate_test_cases(cases: list[dict]) -> list[dict]:
    """
    Validate and normalize generated test cases.

    Rules:
    - endpoint must be a concrete path, no unresolved path params like {id}
    - ensure required fields exist
    - expected_status must be present and must be in allowed_statuses when provided
    - return only valid cases
    """
    if not isinstance(cases, list):
        return []

    validated: list[dict] = []

    for raw_case in cases:
        if not isinstance(raw_case, dict):
            continue

        case = dict(raw_case)
        endpoint = _normalize_endpoint(case.get("endpoint"))
        if not endpoint:
            continue

        # Remove unresolved templated endpoints, e.g. /users/{id}
        if "{" in endpoint or "}" in endpoint:
            continue

        case["endpoint"] = endpoint
        case.setdefault("headers", {})
        if not isinstance(case.get("headers"), dict):
            case["headers"] = {}

        case.setdefault("body", None)
        case.setdefault("description", "")
        if not isinstance(case.get("description"), str):
            case["description"] = str(case.get("description", ""))

        case.setdefault("base_url", "")
        if case.get("base_url") is None:
            case["base_url"] = ""

        if "expected_status" not in case:
            continue

        expected_status = case.get("expected_status")
        if expected_status is not None and not isinstance(expected_status, int):
            try:
                expected_status = int(expected_status)
            except (ValueError, TypeError):
                continue
            case["expected_status"] = expected_status

        allowed_statuses = case.get("allowed_statuses", [])
        if isinstance(allowed_statuses, list):
            normalized_allowed = []
            for code in allowed_statuses:
                try:
                    normalized_allowed.append(int(code))
                except (ValueError, TypeError):
                    continue
            case["allowed_statuses"] = normalized_allowed
            if not normalized_allowed:
                continue
            if expected_status is not None and expected_status not in normalized_allowed:
                continue
        else:
            continue

        validated.append(case)

    return validated
