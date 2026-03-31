from backend.workers.celery_app import celery
import httpx, time

LATENCY_WARNING_MS = 2000
LATENCY_CRITICAL_MS = 5000

HTTP_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
HTTP_LIMITS = httpx.Limits(max_keepalive_connections=100, max_connections=200)
HTTP_CLIENT = httpx.Client(timeout=HTTP_TIMEOUT, limits=HTTP_LIMITS)

@celery.task(bind=True, max_retries=2)
def run_test_case(self, test_case: dict, run_id: str) -> dict:
    from urllib.parse import urlparse

    try:
        base_url = test_case["base_url"].rstrip("/")
        endpoint = test_case["endpoint"]

        # Strip base_url from endpoint if LLM accidentally included it
        if endpoint.startswith("http"):
            parsed = urlparse(endpoint)
            endpoint = parsed.path
            if parsed.query:
                endpoint += f"?{parsed.query}"

        # Ensure endpoint starts with /
        if not endpoint.startswith("/"):
            endpoint = "/" + endpoint

        url = base_url + endpoint

        start = time.time()
        response = HTTP_CLIENT.request(
            method=test_case["method"],
            url=url,
            headers=test_case.get("headers", {}),
            json=test_case.get("body"),
        )
        latency = round((time.time() - start) * 1000, 2)
        expected_status = test_case.get("expected_status", 200)
        if expected_status is None:
            passed = True
        else:
            passed = response.status_code == expected_status

        return {
            "run_id": run_id,
            "endpoint": endpoint,
            "method": test_case["method"],
            "status": "pass" if passed else "fail",
            "status_code": response.status_code,
            "latency_ms": latency,
            "failure_reason": None if passed else f"Expected {expected_status} got {response.status_code}",
        }
    except Exception as exc:
        return {
            "run_id": run_id,
            "endpoint": test_case.get("endpoint", "unknown"),
            "method": test_case.get("method", "GET"),
            "status": "error",
            "status_code": None,
            "latency_ms": None,
            "failure_reason": str(exc),
        }