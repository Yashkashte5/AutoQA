from langchain_groq import ChatGroq
from backend.core.config import settings
import json
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
  - 2 happy-path tests: valid input, correct expected_status for success
  - 3 negative tests: invalid/missing/malformed input with correct error expected_status

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


def _resolve_schema(ref: str, components: dict) -> dict:
    """Resolve $ref like '#/components/schemas/TaskRequest' to actual schema."""
    if not ref or not ref.startswith("#/components/schemas/"):
        return {}
    name = ref.split("/")[-1]
    return components.get("schemas", {}).get(name, {})


def generate_batch(endpoints: list[dict], base_url: str) -> list[dict]:
    endpoint_defs = []
    for e in endpoints:
        responses = e.get("responses", {})
        success_codes = []
        error_codes = []
        for k in responses.keys():
            try:
                code = int(k)
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

    prompt = f"""Generate test cases for these {len(endpoints)} API endpoints.
Base URL (for base_url field only, NOT for endpoint field): {base_url}

REMINDER:
- endpoint field = path only (e.g. /users/123 NOT {base_url}/users/123)
- expected_status = what REST standards say it SHOULD return, not what it might return
- Use the exact request_body_schema to construct valid and invalid bodies
- 2 happy-path + 3 negative tests per endpoint minimum

Endpoints to test:
{json.dumps(endpoint_defs, indent=2)}

Return a single flat JSON array of all test cases."""

    try:
        response = llm.invoke([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ])
        text = response.content.strip()
        if text.startswith("```"):
            parts = text.split("```")
            text = parts[1] if len(parts) > 1 else text
            if text.startswith("json"):
                text = text[4:]
        cases = json.loads(text.strip())

        for case in cases:
            case["base_url"] = base_url
            ep = case.get("endpoint", "")
            if ep.startswith("http"):
                parsed = urlparse(ep)
                ep = parsed.path
                if parsed.query:
                    ep += f"?{parsed.query}"
                case["endpoint"] = ep
        return cases
    except Exception as e:
        print(f"DEBUG batch generation failed: {e}")
        return []


def run_test_generator(endpoints: list[dict], base_url: str, batch_size: int = 3) -> list[dict]:
    # Filter out streaming/SSE endpoints — they hold connections open and always timeout
    testable = [
        e for e in endpoints
        if not any(s in e["path"] for s in STREAMING_PATTERNS)
    ]
    skipped = len(endpoints) - len(testable)
    if skipped > 0:
        print(f"DEBUG skipped {skipped} streaming endpoints")

    all_cases = []
    for i in range(0, len(testable), batch_size):
        batch = testable[i:i + batch_size]
        cases = generate_batch(batch, base_url)
        all_cases.extend(cases)
        time.sleep(1)
    return all_cases