"""
Spec Reader Agent
-----------------
Runs an agentic RAG loop over the indexed OpenAPI spec.
Uses CRAG (Corrective RAG) — queries ChromaDB with diverse queries,
grades retrieval quality, retries if insufficient.
Scales retrieval depth dynamically based on spec size.
"""
from backend.rag.retriever import retrieve_endpoints, get_collection_size
from backend.rag.grader import grade_retrieval

QUERIES = [
    "GET endpoints that retrieve single resources by ID or path parameter",
    "GET endpoints that list or search resources with query parameters",
    "POST endpoints that create new resources",
    "PUT and PATCH endpoints that update existing resources",
    "DELETE endpoints that remove resources",
    "endpoints that require authentication, API keys, or authorization headers",
    "endpoints with required request body schemas or content-type requirements",
    "health check, status, and utility endpoints",
    "streaming, websocket, or async endpoints",
    "endpoints with pagination, filtering, or sorting parameters",
]


def run_spec_reader(suite_id: str, base_url: str) -> list[dict]:
    """
    Agentic RAG loop over the indexed spec.

    Dynamically scales n (results per query) based on collection size:
    - Small APIs  (< 10 endpoints): n=5
    - Medium APIs (10-30 endpoints): n=5-7
    - Large APIs  (30+ endpoints):  n=8-15

    Formula: n = max(5, min(15, spec_size // len(QUERIES) + 3))
    Examples:
      - AgentOS (6 endpoints):    n = max(5, min(15, 0+3)) = 5
      - Petstore (20 endpoints):  n = max(5, min(15, 2+3)) = 5
      - httpbin (73 endpoints):   n = max(5, min(15, 7+3)) = 10
    """
    spec_size = get_collection_size(suite_id)
    n = max(5, min(15, spec_size // len(QUERIES) + 3))

    seen_paths = set()
    resolved_endpoints = []

    for query in QUERIES:
        attempts = 0
        while attempts < 3:
            retrieved = retrieve_endpoints(suite_id, query, n=n)
            sufficient = grade_retrieval(query, retrieved)

            if sufficient or attempts == 2:
                for ep in retrieved:
                    key = f"{ep['method']}:{ep['path']}"
                    if key not in seen_paths:
                        seen_paths.add(key)
                        resolved_endpoints.append({
                            "path": ep["path"],
                            "method": ep["method"],
                            "summary": ep.get("summary", ""),
                            "parameters": ep.get("parameters", []),
                            "request_body": ep.get("request_body", {}),
                            "responses": ep.get("responses", {}),
                            "security": ep.get("security", []),
                            "components": ep.get("components", {}),
                            "base_url": base_url,
                        })
                break
            attempts += 1

    return resolved_endpoints