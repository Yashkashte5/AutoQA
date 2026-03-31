from langchain_groq import ChatGroq
from backend.core.config import settings
import json
import time

llm = ChatGroq(
    api_key=settings.groq_api_key,
    model="llama-3.1-8b-instant",
    temperature=0,
)

CATEGORIES = {
    "auth_error":        "Authentication or authorization failed — 401 or 403 returned, or auth bypass detected",
    "not_found":         "Endpoint routing issue or test used a resource ID that doesn't exist in test data",
    "schema_mismatch":   "Response body structure, content-type, or field types don't match the API spec",
    "server_error":      "Server crashed or threw an unhandled exception — 5xx returned",
    "timeout":           "Request timed out — server took too long to respond",
    "validation_error":  "API accepted invalid input it should have rejected, or rejected valid input it should have accepted",
    "unexpected_status": "Status code returned doesn't match what REST standards require for this operation",
}

SEVERITY_GUIDE = """
Severity classification:
- critical: server_error (5xx crash), auth bypass (got 200 when 401 expected), data corruption risk
- high:     validation not enforced (invalid input accepted), wrong status on write operations (POST/PUT/DELETE), security-sensitive endpoint misbehaving
- medium:   wrong status on read operations (GET), minor spec deviation, not_found on test data issues
- low:      cosmetic issues, redundant redirects, non-critical missing fields
"""

SUGGESTION_GUIDE = """
Suggestion writing rules:
- Be specific — mention the exact endpoint, method, and what should change in the code
- For not_found: explain whether it's a routing issue or a test data issue (resource doesn't exist)
- For validation_error: specify which field or parameter needs validation and what the correct behavior is
- For server_error: say to check server logs and which operation triggered the crash
- For auth_error: specify whether auth is missing, bypassed, or incorrectly enforced
- For schema_mismatch: say which field or content-type is wrong
- For unexpected_status: say what status code was expected and why per REST standards
- Never say "update the endpoint to return X" when X is the code it's already returning
- Never give generic advice — every suggestion must be actionable and specific
"""

AUTH_ENDPOINTS = ["/logout", "/login", "/auth", "/token", "/refresh", "/signin", "/signout", "/session"]


def _override_classification(result: dict) -> dict:
    """
    Rule-based overrides applied AFTER LLM classification.
    Handles clear-cut HTTP spec cases the LLM sometimes gets wrong.
    LLM handles nuance, rules handle certainty.
    """
    code = result.get("status_code")
    endpoint = result.get("endpoint", "")
    method = result.get("method", "")

    # Rule 1 — 5xx is ALWAYS server_error critical, no exceptions
    if code and str(code).startswith("5"):
        # Check for injection payload in endpoint
        injection_signals = ["%27", "OR+1", "OR 1", "<script", "%3Cscript", "1=1", "%3Cscript"]
        if any(s in endpoint for s in injection_signals):
            suggestion = (
                f"{method} {endpoint} crashed with {code} when sent an injection payload "
                f"— sanitize and validate all input parameters before processing."
            )
        else:
            suggestion = (
                f"Check server logs for {method} {endpoint} "
                f"— returned {code} unexpectedly. Fix the underlying server crash."
            )
        result["category"] = "server_error"
        result["severity"] = "critical"
        result["suggestion"] = suggestion
        return result

    # Rule 2 — Auth/session endpoints returning 200 without credentials = auth_error
    if any(ep in endpoint.lower() for ep in AUTH_ENDPOINTS):
        if code == 200 and result.get("category") not in ("server_error", "auth_error"):
            result["category"] = "auth_error"
            result["severity"] = "high"
            result["suggestion"] = (
                f"{method} {endpoint} returned 200 without valid credentials "
                f"— add authentication enforcement before returning a success response."
            )
            return result

    # Rule 3 — 405 classified as not_found is always wrong
    if code == 405 and result.get("category") == "not_found":
        result["category"] = "unexpected_status"
        result["severity"] = "medium"
        result["suggestion"] = (
            f"{method} {endpoint} returned 405 Method Not Allowed "
            f"— verify the correct HTTP method is defined for this endpoint in the spec."
        )
        return result

    return result


def classify_batch(failures: list[dict]) -> list[dict]:
    numbered = [
        {
            "index": i,
            "method": f.get("method"),
            "endpoint": f.get("endpoint"),
            "status_code_returned": f.get("status_code"),
            "failure_reason": f.get("failure_reason"),
            "description": f.get("description", ""),
        }
        for i, f in enumerate(failures)
    ]

    categories_str = "\n".join(f"  - {k}: {v}" for k, v in CATEGORIES.items())

    prompt = f"""You are a senior QA engineer analyzing API test failures. Classify each failure accurately.

Categories and when to use them:
{categories_str}

{SEVERITY_GUIDE}

{SUGGESTION_GUIDE}

Test failures to classify:
{json.dumps(numbered, indent=2)}

Return ONLY a JSON array, one object per failure, same order as input, with:
- index: same as input
- category: one of [{", ".join(CATEGORIES.keys())}]
- severity: critical | high | medium | low
- suggestion: specific, actionable one-sentence fix (follow the suggestion writing rules above)

No markdown, no explanation, just the JSON array."""

    try:
        response = llm.invoke(prompt)
        text = response.content.strip()
        if text.startswith("```"):
            parts = text.split("```")
            text = parts[1] if len(parts) > 1 else text
            if text.startswith("json"):
                text = text[4:]
        classifications = json.loads(text.strip())

        enriched = list(failures)
        for c in classifications:
            idx = c.get("index", 0)
            if 0 <= idx < len(enriched):
                enriched[idx] = {
                    **enriched[idx],
                    "category": c.get("category", "unexpected_status"),
                    "severity": c.get("severity", "medium"),
                    "suggestion": c.get("suggestion", "Review endpoint behavior and compare against API spec."),
                }
        return enriched

    except Exception as e:
        print(f"DEBUG bug reporter batch failed: {e}")
        return [_fallback_classify(f) for f in failures]


def _fallback_classify(result: dict) -> dict:
    """Pure rule-based fallback if LLM call fails entirely."""
    code = result.get("status_code")
    endpoint = result.get("endpoint", "")
    method = result.get("method", "")
    reason = result.get("failure_reason", "")

    if code and str(code).startswith("5"):
        return {**result, "category": "server_error", "severity": "critical",
                "suggestion": f"Check server logs for crash triggered by {method} {endpoint} — returned {code}."}
    if code in (401, 403):
        return {**result, "category": "auth_error", "severity": "high",
                "suggestion": f"Check authentication logic on {method} {endpoint} — returned {code} unexpectedly."}
    if code == 404:
        return {**result, "category": "not_found", "severity": "medium",
                "suggestion": f"Verify routing for {method} {endpoint} or ensure test data exists."}
    if code in (400, 422):
        return {**result, "category": "validation_error", "severity": "high",
                "suggestion": f"Review input validation on {method} {endpoint} — returned {code}."}
    if code == 415:
        return {**result, "category": "schema_mismatch", "severity": "medium",
                "suggestion": f"Check content-type handling on {method} {endpoint}."}
    if code in (307, 308):
        return {**result, "category": "unexpected_status", "severity": "medium",
                "suggestion": f"Remove unexpected redirect on {method} {endpoint} — clients may not follow redirects."}
    if code == 405:
        return {**result, "category": "unexpected_status", "severity": "medium",
                "suggestion": f"{method} {endpoint} returned 405 — verify the correct HTTP method for this endpoint."}
    return {**result, "category": "unexpected_status", "severity": "medium",
            "suggestion": f"Review {method} {endpoint} — {reason}."}


def run_bug_reporter(results: list[dict], batch_size: int = 10) -> dict:
    failures = [r for r in results if r and r.get("status") in ("fail", "error")]
    passes = [r for r in results if r and r.get("status") == "pass"]

    # Step 1 — LLM classification in batches with rate limit delay
    enriched_failures = []
    for i in range(0, len(failures), batch_size):
        batch = failures[i:i + batch_size]
        enriched_failures.extend(classify_batch(batch))
        time.sleep(0.5)  # prevent rate limit buildup between batches

    # Step 2 — Rule-based overrides (catches what LLM gets wrong)
    enriched_failures = [_override_classification(r) for r in enriched_failures]

    # Step 3 — Sort by severity
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    enriched_failures.sort(key=lambda x: severity_order.get(x.get("severity", "low"), 3))

    enriched_results = passes + enriched_failures

    summary = {}
    for r in enriched_failures:
        cat = r.get("category", "unknown")
        summary[cat] = summary.get(cat, 0) + 1

    return {
        "enriched_results": enriched_results,
        "failure_summary": summary,
        "failures_by_severity": {
            "critical": [r for r in enriched_failures if r.get("severity") == "critical"],
            "high":     [r for r in enriched_failures if r.get("severity") == "high"],
            "medium":   [r for r in enriched_failures if r.get("severity") == "medium"],
            "low":      [r for r in enriched_failures if r.get("severity") == "low"],
        }
    }