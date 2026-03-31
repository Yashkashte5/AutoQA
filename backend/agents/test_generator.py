from langchain_groq import ChatGroq
from backend.core.config import settings
from backend.agents.validator import validate_test_cases
import json
import random
import re
import time
from urllib.parse import urlparse

llm = ChatGroq(
    api_key=settings.groq_api_key,
    model="llama-3.1-8b-instant",
    temperature=0.1,
)

SYSTEM_PROMPT = """You are a senior API QA engineer with 10 years of experience finding bugs in REST APIs.
Your job is to write test cases that FIND BUGS, not confirm that everything works.

STRICT RULES — violating any of these is a failure:

RULE 1 — endpoint field must be a PATH ONLY:
  CORRECT: /pet/123
  WRONG:   https://api.example.com/pet/123
  Never include the base URL in the endpoint field. Ever.

RULE 2 — expected_status must reflect REST standards, NOT what you think the server returns:
  - Valid request with existing resource → 200 or 201 or 202 or 204
  - Resource not found → 404
  - Missing required field or invalid format → 400 or 422
  - Wrong content-type → 415
  - Unauthorized → 401
  - Forbidden → 403
  - Method not allowed → 405
  NEVER set expected_status: 200 for a test that sends invalid, missing, or malformed input.

RULE 3 — generate a balanced mix per endpoint:
    - 1 happy-path test: valid input, correct expected_status for success
    - 1 negative test: invalid/missing/malformed input with correct error expected_status

RULE 4 — negative tests must be genuinely adversarial:
  - String where integer expected (e.g. /pet/abc instead of /pet/123)
  - Negative numbers where positive expected (e.g. /pet/-1)
  - Empty required fields
  - Missing required body fields
  - Wrong content-type header
  - Extremely large values
  - SQL injection strings (e.g. /pet/1%27%20OR%201%3D1)

RULE 5 — path parameters must be filled with concrete values:
  CORRECT: /pet/123
  WRONG:   /pet/{petId}

RULE 6 — For POST/PUT endpoints, use the exact request body schema provided.
  If schema says {"task": "string"}, body must be {"task": "some value"}.
  For negative tests, omit required fields or send wrong types.

RULE 7 — Return ONLY a valid JSON array. No markdown, no explanation, no code fences.

RULE 8 — endpoint field must be path only, never the full URL.

Each test case object must have exactly:
- endpoint: path only (e.g. /pet/123)
- method: HTTP method uppercase (GET, POST, PUT, DELETE, PATCH)
- headers: object ({"Content-Type": "application/json"} for JSON body requests)
- body: request body object or null
- expected_status: integer reflecting REST standards for this input
- description: one sentence — what bug or behavior this test validates
- base_url: copy exactly from input
"""

# Endpoints that hold connections open — skip them for standard HTTP testing
STREAMING_PATTERNS = ["/stream", "/ws", "/websocket", "/sse", "/events", "/synthesizer-stream"]
GENERATOR_BASE_DELAY_SEC = 0.25
GENERATOR_MAX_BACKOFF_SEC = 4.0


def _resolve_schema(ref: str, components: dict) -> dict:
    """Resolve $ref like '#/components/schemas/TaskRequest' to actual schema."""
    if not ref or not ref.startswith("#/components/schemas/"):
        return {}
    name = ref.split("/")[-1]
    return components.get("schemas", {}).get(name, {})


def _extract_json_array(raw_text: str) -> str:
    """Best-effort extraction of the first JSON array from model output."""
    text = str(raw_text or "").strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]
    return text


def _parse_model_cases(raw_text: str) -> list[dict]:
    """Parse model output into list[dict] with defensive recovery."""
    candidate = _extract_json_array(raw_text)
    parsed = json.loads(candidate)
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    return []


def _invoke_llm_with_backoff(messages: list[dict], max_attempts: int = 3):
    """Invoke LLM with small adaptive backoff to reduce rate-limit failures."""
    attempt = 0
    while True:
        try:
            return llm.invoke(messages)
        except Exception as exc:
            attempt += 1
            if attempt >= max_attempts:
                raise
            err = str(exc).lower()
            # Be conservative on generic failures; stronger pause for throttling-like errors.
            if any(k in err for k in ["429", "rate", "quota", "throttle", "timeout"]):
                delay = min(GENERATOR_MAX_BACKOFF_SEC, GENERATOR_BASE_DELAY_SEC * (2 ** attempt))
            else:
                delay = min(GENERATOR_MAX_BACKOFF_SEC, GENERATOR_BASE_DELAY_SEC * (1.5 ** attempt))
            # jitter avoids synchronized retries
            delay += random.uniform(0.0, 0.15)
            time.sleep(delay)


def _concretize_path(path: str) -> str:
    """Replace templated path params with stable concrete values."""
    value = str(path or "").strip()
    if not value:
        return ""
    value = re.sub(r"\{[^/{}]+\}", "1", value)
    if not value.startswith("/"):
        value = "/" + value
    return value


def _build_spec_fallback_cases(endpoints: list[dict], base_url: str) -> list[dict]:
    """
    Deterministic fallback when LLM output is unusable.
    Produces one minimal valid case per endpoint using only spec-defined statuses.
    """
    fallback_cases = []
    for endpoint in endpoints:
        method = str(endpoint.get("method", "GET") or "GET").upper()
        raw_path = endpoint.get("path", "")
        path = _concretize_path(raw_path)
        if not path or "{" in path or "}" in path:
            continue

        responses = endpoint.get("responses", {}) or {}
        allowed = []
        for code in responses.keys():
            try:
                allowed.append(int(code))
            except (ValueError, TypeError):
                continue
        allowed = sorted(set(allowed))
        if not allowed:
            continue

        expected = next((c for c in allowed if str(c).startswith("2")), allowed[0])
        case = {
            "endpoint": path,
            "method": method,
            "headers": {},
            "body": None,
            "expected_status": expected,
            "description": f"Spec fallback smoke test for {method} {path}.",
            "base_url": base_url,
            "allowed_statuses": allowed,
        }
        fallback_cases.append(case)
    return fallback_cases


def _is_complex_endpoint(endpoint: dict) -> bool:
    """Heuristic: route only complex endpoints to LLM generation."""
    method = str(endpoint.get("method", "") or "").upper()
    params = endpoint.get("parameters", []) or []
    request_body = endpoint.get("request_body", {}) or {}
    security = endpoint.get("security", []) or []

    has_path_or_query_params = any(
        isinstance(p, dict) and str(p.get("in", "")).lower() in ("path", "query", "cookie")
        for p in params
    )

    has_json_body = bool(
        request_body.get("content", {}).get("application/json")
    )

    # Treat write operations and auth/parameter-heavy endpoints as complex.
    return (
        method in ("POST", "PUT", "PATCH", "DELETE")
        or has_path_or_query_params
        or has_json_body
        or bool(security)
    )


def _build_spec_baseline_cases(endpoints: list[dict], base_url: str) -> list[dict]:
    """
    Deterministic two-case baseline per endpoint:
    - one success case (2xx if available)
    - one non-success case (first non-2xx if available)
    """
    baseline = []
    for endpoint in endpoints:
        method = str(endpoint.get("method", "GET") or "GET").upper()
        path = _concretize_path(endpoint.get("path", ""))
        if not path or "{" in path or "}" in path:
            continue

        responses = endpoint.get("responses", {}) or {}
        allowed = []
        for code in responses.keys():
            try:
                allowed.append(int(code))
            except (ValueError, TypeError):
                continue
        allowed = sorted(set(allowed))
        if not allowed:
            continue

        success_code = next((c for c in allowed if 200 <= c < 300), None)
        non_success_code = next((c for c in allowed if c < 200 or c >= 300), None)

        if success_code is not None:
            baseline.append({
                "endpoint": path,
                "method": method,
                "headers": {},
                "body": None,
                "expected_status": success_code,
                "description": f"Baseline success case for {method} {path}.",
                "base_url": base_url,
                "allowed_statuses": allowed,
            })

        if non_success_code is not None:
            baseline.append({
                "endpoint": path,
                "method": method,
                "headers": {},
                "body": None,
                "expected_status": non_success_code,
                "description": f"Baseline negative case for {method} {path}.",
                "base_url": base_url,
                "allowed_statuses": allowed,
            })

        # If only one code exists, include exactly one case.
        if success_code is None and non_success_code is None and allowed:
            baseline.append({
                "endpoint": path,
                "method": method,
                "headers": {},
                "body": None,
                "expected_status": allowed[0],
                "description": f"Baseline fallback case for {method} {path}.",
                "base_url": base_url,
                "allowed_statuses": allowed,
            })

    return baseline


def generate_batch(endpoints: list[dict], base_url: str) -> list[dict]:
    endpoint_index = {}
    endpoint_defs = []
    for e in endpoints:
        responses = e.get("responses", {})
        success_codes = []
        error_codes = []
        allowed_status_codes = []
        for k in responses.keys():
            try:
                code = int(k)
                allowed_status_codes.append(code)
                if str(k).startswith("2"):
                    success_codes.append(code)
                else:
                    error_codes.append(code)
            except (ValueError, TypeError):
                pass

        # Resolve request body schema from $ref if present
        request_body = e.get("request_body", {})
        components = e.get("components", {})
        resolved_body_schema = {}
        try:
            ref = (request_body.get("content", {})
                   .get("application/json", {})
                   .get("schema", {})
                   .get("$ref", ""))
            if ref:
                resolved_body_schema = _resolve_schema(ref, components)
        except Exception:
            pass

        endpoint_defs.append({
            "method": e["method"],
            "path": e["path"],
            "summary": e.get("summary", ""),
            "parameters": e.get("parameters", []),
            "request_body_schema": resolved_body_schema or request_body,
            "success_status_codes": success_codes,
            "error_status_codes": error_codes,
        })
        endpoint_index[(str(e.get("method", "")).upper(), e.get("path", ""))] = {
            "allowed_statuses": sorted(set(allowed_status_codes)),
        }

    prompt = f"""Generate test cases for these {len(endpoints)} API endpoints.
Base URL (for base_url field only, NOT for endpoint field): {base_url}

REMINDER:
- endpoint field = path only (e.g. /users/123 NOT {base_url}/users/123)
- expected_status MUST be one of the response status codes defined for that endpoint in the spec
- Use the exact request_body_schema to construct valid and invalid bodies
- Prefer exactly 2 tests per endpoint: 1 happy-path + 1 negative-path

Endpoints to test:
{json.dumps(endpoint_defs, separators=(",", ":"))}

Return a single flat JSON array of all test cases."""

    try:
        response = _invoke_llm_with_backoff([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ])
        text = str(getattr(response, "content", "") or "")

        try:
            raw_cases = _parse_model_cases(text)
        except Exception:
            # Retry once with a stricter recovery prompt on malformed JSON
            retry_prompt = (
                "Your previous output was not valid JSON. Return ONLY a valid JSON array of test cases "
                "for the same endpoints, with no markdown or extra text."
            )
            retry_response = _invoke_llm_with_backoff([
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
                {"role": "user", "content": retry_prompt},
            ])
            retry_text = str(getattr(retry_response, "content", "") or "")
            raw_cases = _parse_model_cases(retry_text)

        if not isinstance(raw_cases, list):
            raw_cases = []

        cases = []
        for case in raw_cases:
            if not isinstance(case, dict):
                continue
            case["base_url"] = base_url

            ep = str(case.get("endpoint", "") or "")
            if ep.startswith("http"):
                parsed = urlparse(ep)
                ep = parsed.path
                if parsed.query:
                    ep += f"?{parsed.query}"
            case["endpoint"] = ep

            method = str(case.get("method", "")).upper()
            path_only = ep.split("?", 1)[0]
            spec_meta = endpoint_index.get((method, path_only), {})
            case["allowed_statuses"] = spec_meta.get("allowed_statuses", [])
            cases.append(case)

        validated = validate_test_cases(cases)
        if isinstance(validated, list) and validated:
            return validated

        # Deterministic safety net so single malformed model outputs do not erase coverage.
        fallback = _build_spec_fallback_cases(endpoints, base_url)
        fallback_validated = validate_test_cases(fallback)
        return fallback_validated if isinstance(fallback_validated, list) else []
    except Exception as e:
        print(f"DEBUG batch generation failed: {e}")
        fallback = _build_spec_fallback_cases(endpoints, base_url)
        fallback_validated = validate_test_cases(fallback)
        return fallback_validated if isinstance(fallback_validated, list) else []


def _generate_with_fallback(batch: list[dict], base_url: str) -> list[dict]:
    """Generate tests for a batch, then fall back to one-by-one on empty batch output."""
    cases = generate_batch(batch, base_url)
    if isinstance(cases, list) and cases:
        return cases

    # If a multi-endpoint batch failed to parse/validate, retry per endpoint
    if len(batch) > 1:
        recovered = []
        for endpoint in batch:
            single_cases = generate_batch([endpoint], base_url)
            if isinstance(single_cases, list) and single_cases:
                recovered.extend(single_cases)
            time.sleep(0.1)
        return recovered

    return cases if isinstance(cases, list) else []


def run_test_generator(endpoints: list[dict], base_url: str, batch_size: int = 2) -> list[dict]:
    # Filter out streaming/SSE endpoints — they hold connections open and always timeout
    testable = [
        e for e in endpoints
        if not any(s in e["path"] for s in STREAMING_PATTERNS)
    ]
    skipped = len(endpoints) - len(testable)
    if skipped > 0:
        print(f"DEBUG skipped {skipped} streaming endpoints")

    simple_endpoints = [e for e in testable if not _is_complex_endpoint(e)]
    complex_endpoints = [e for e in testable if _is_complex_endpoint(e)]

    all_cases = []

    # Fast deterministic baseline for simple routes.
    baseline_cases = _build_spec_baseline_cases(simple_endpoints, base_url)
    all_cases.extend(baseline_cases)

    # LLM-driven generation for complex routes only.
    for i in range(0, len(complex_endpoints), batch_size):
        loop_start = time.time()
        batch = complex_endpoints[i:i + batch_size]
        cases = _generate_with_fallback(batch, base_url)
        if not isinstance(cases, list):
            cases = []
        all_cases.extend(cases)
        elapsed = time.time() - loop_start
        if elapsed < GENERATOR_BASE_DELAY_SEC:
            time.sleep(GENERATOR_BASE_DELAY_SEC - elapsed)

    validated = validate_test_cases(all_cases)
    return validated if isinstance(validated, list) else []