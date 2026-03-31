from langchain_groq import ChatGroq
from backend.core.config import settings
import json
import re
import time

llm = ChatGroq(
    api_key=settings.groq_api_key,
    model="llama-3.1-8b-instant",
    temperature=0,
)

FORBIDDEN_SUGGESTION_TERMS = [
    "database",
    "db",
    "internal server",
    "server internals",
    "backend code",
    "microservice",
    "orm",
    "sql",
]

def _fallback_suggestion(result: dict) -> str:
    code = result.get("status_code")
    endpoint = result.get("endpoint", "")
    method = result.get("method", "")
    reason = result.get("failure_reason", "")

    if code and str(code).startswith("5"):
        return f"{method} {endpoint} returned {code}, which may indicate an unhandled API error path for this request."
    if "timeout" in str(reason).lower():
        return f"{method} {endpoint} timed out, which could suggest a slow dependency or missing timeout-safe handling."
    if code == 404:
        return f"{method} {endpoint} returned 404, which may indicate a missing route mapping or unavailable test resource."
    if code is not None and str(code).startswith("4"):
        return f"{method} {endpoint} returned {code}, which could suggest request handling differs from the expected API contract."
    return f"{method} {endpoint} failed and may indicate a mismatch between request assumptions and current endpoint behavior ({reason})."


def _sanitize_suggestion(text: str, result: dict) -> str:
    """Ensure suggestion stays one-sentence, cautious, and avoids backend internals."""
    cleaned = " ".join(str(text or "").splitlines()).strip().strip('"')
    if not cleaned:
        return _fallback_suggestion(result)

    lowered = cleaned.lower()
    if any(term in lowered for term in FORBIDDEN_SUGGESTION_TERMS):
        return _fallback_suggestion(result)

    if "may indicate" not in lowered and "could suggest" not in lowered:
        cleaned = f"{cleaned} This may indicate a contract or request-handling issue."

    # Keep a single sentence to avoid verbose/hallucinatory output.
    # Use punctuation followed by whitespace/end so URL dots do not truncate text.
    sentence_match = re.search(r"(.+?[.!?])(?:\s|$)", cleaned)
    if sentence_match:
        first_sentence = sentence_match.group(1).strip()
    else:
        first_sentence = cleaned.strip()

    if not first_sentence:
        return _fallback_suggestion(result)
    if first_sentence[-1] not in ".!?":
        first_sentence += "."
    return first_sentence


def _deterministic_classify(result: dict) -> dict:
    """Rule-based deterministic classifier for production stability."""
    code = result.get("status_code")
    reason = str(result.get("failure_reason", "") or "").lower()

    if code is not None and str(code).startswith("5"):
        return {**result, "category": "server_error", "severity": "critical"}
    if "timeout" in reason:
        return {**result, "category": "timeout", "severity": "low"}
    if code == 404:
        return {**result, "category": "not_found", "severity": "low"}
    if code is not None and str(code).startswith("4"):
        return {**result, "category": "unexpected_status", "severity": "medium"}
    return {**result, "category": "unexpected_status", "severity": "medium"}


def generate_suggestion(result: dict) -> str:
    """LLM-generated single-sentence suggestion using cautious language only."""
    payload = {
        "method": result.get("method", "GET"),
        "endpoint": result.get("endpoint", ""),
        "status_code": result.get("status_code"),
        "failure_reason": result.get("failure_reason", ""),
        "category": result.get("category", "unexpected_status"),
        "severity": result.get("severity", "medium"),
    }

    prompt = f"""Write one concise sentence suggesting what to inspect next for this API test failure.

Rules:
- Do not claim backend internals (no database/server internals assumptions).
- Use cautious language such as 'may indicate' or 'could suggest'.
- Mention method, endpoint, and observed code/reason context.
- Return exactly one plain sentence.

Failure:
{json.dumps(payload)}
"""
    try:
        response = llm.invoke(prompt)
        text = str(getattr(response, "content", "") or "").strip()
        if text.startswith("```"):
            parts = text.split("```")
            text = parts[1] if len(parts) > 1 else text
            if text.startswith("json"):
                text = text[4:]
        line = " ".join(text.splitlines()).strip().strip('"')
        return _sanitize_suggestion(line, result)
    except Exception as e:
        print(f"DEBUG suggestion generation failed: {e}")
        return _fallback_suggestion(result)


def generate_suggestions_batch(results: list[dict]) -> list[str]:
    """Generate one cautious suggestion sentence per result in a single LLM call."""
    if not isinstance(results, list) or not results:
        return []

    payload = [
        {
            "index": idx,
            "method": r.get("method", "GET"),
            "endpoint": r.get("endpoint", ""),
            "status_code": r.get("status_code"),
            "failure_reason": r.get("failure_reason", ""),
            "category": r.get("category", "unexpected_status"),
            "severity": r.get("severity", "medium"),
        }
        for idx, r in enumerate(results)
    ]

    prompt = f"""For each API failure item below, write exactly one concise suggestion sentence.

Rules:
- Do not claim backend internals (no database/server internals assumptions).
- Use cautious language such as 'may indicate' or 'could suggest'.
- Mention method, endpoint, and observed status/reason context.
- Return ONLY a JSON array with objects:
  {{"index": <int>, "suggestion": <string>}}

Input items:
{json.dumps(payload)}
"""

    try:
        response = llm.invoke(prompt)
        text = str(getattr(response, "content", "") or "").strip()
        if text.startswith("```"):
            parts = text.split("```")
            text = parts[1] if len(parts) > 1 else text
            if text.startswith("json"):
                text = text[4:]

        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            text = text[start:end + 1]

        parsed = json.loads(text)
        if not isinstance(parsed, list):
            raise ValueError("batch suggestion response is not a list")

        suggestions = [_fallback_suggestion(r) for r in results]
        for item in parsed:
            if not isinstance(item, dict):
                continue
            idx = item.get("index")
            if isinstance(idx, int) and 0 <= idx < len(results):
                suggestions[idx] = _sanitize_suggestion(item.get("suggestion", ""), results[idx])
        return suggestions
    except Exception as e:
        print(f"DEBUG batch suggestion generation failed: {e}")
        return [generate_suggestion(r) for r in results]


def generate_summary(failures: list[dict]) -> str:
    """Generate a concise system-health summary from failures."""
    if not isinstance(failures, list):
        failures = []

    total = len(failures)
    if total == 0:
        return "System health is good with no failing tests observed."

    counts = {}
    for f in failures:
        cat = (f or {}).get("category", "unexpected_status")
        counts[cat] = counts.get(cat, 0) + 1

    ordered = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    top = ordered[:3]
    top_text = ", ".join(f"{k} ({v})" for k, v in top)

    critical_count = counts.get("server_error", 0)
    timeout_count = counts.get("timeout", 0)
    health = "good"
    if critical_count > 0 or total >= 5:
        health = "poor"
    elif total >= 2 or timeout_count > 0:
        health = "moderate"

    prompt = f"""Write one concise sentence summarizing API test failure health.

Rules:
- Include health level explicitly: good, moderate, or poor.
- Mention top 2-3 issue categories with counts.
- Use cautious language; do not invent root causes.
- Return exactly one sentence.

Facts:
- health: {health}
- total_failures: {total}
- top_issues: {top_text}
"""
    try:
        response = llm.invoke(prompt)
        text = str(getattr(response, "content", "") or "").strip()
        if text.startswith("```"):
            parts = text.split("```")
            text = parts[1] if len(parts) > 1 else text
            if text.startswith("json"):
                text = text[4:]
        one_line = " ".join(text.splitlines()).strip().strip('"')
        if one_line:
            return one_line
    except Exception as e:
        print(f"DEBUG summary generation failed: {e}")

    return f"System health is {health}; top issues are {top_text}."


def run_bug_reporter(results: list[dict], batch_size: int = 10) -> dict:
    failures = [r for r in results if r and r.get("status") in ("fail", "error")]
    passes = [r for r in results if r and r.get("status") == "pass"]

    # Deterministic classification first
    enriched_failures = []
    for i in range(0, len(failures), max(batch_size, 1)):
        batch = failures[i:i + max(batch_size, 1)]
        classified = [_deterministic_classify(f) for f in batch]
        batch_suggestions = generate_suggestions_batch(classified)
        for idx, item in enumerate(classified):
            item["suggestion"] = batch_suggestions[idx] if idx < len(batch_suggestions) else _fallback_suggestion(item)
        enriched_failures.extend(classified)
        time.sleep(0.02)

    # Sort by severity
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    enriched_failures.sort(key=lambda x: severity_order.get(x.get("severity", "low"), 3))

    enriched_results = passes + enriched_failures

    summary = {}
    for r in enriched_failures:
        cat = r.get("category", "unknown")
        summary[cat] = summary.get(cat, 0) + 1

    summary_text = generate_summary(enriched_failures)

    return {
        "enriched_results": enriched_results,
        "failure_summary": summary,
        "summary": summary_text,
        "failures_by_severity": {
            "critical": [r for r in enriched_failures if r.get("severity") == "critical"],
            "high":     [r for r in enriched_failures if r.get("severity") == "high"],
            "medium":   [r for r in enriched_failures if r.get("severity") == "medium"],
            "low":      [r for r in enriched_failures if r.get("severity") == "low"],
        }
    }