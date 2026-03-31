from backend.workers.celery_app import celery
import httpx, time

LATENCY_WARNING_MS = 2000
LATENCY_CRITICAL_MS = 5000

@celery.task(bind=True, max_retries=2)
def run_test_case(self, test_case: dict, run_id: str) -> dict:
    import httpx, time
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
        response = httpx.request(
            method=test_case["method"],
            url=url,
            headers=test_case.get("headers", {}),
            json=test_case.get("body"),
            timeout=10,
        )
        latency = round((time.time() - start) * 1000, 2)
        passed = response.status_code == test_case.get("expected_status", 200)

        return {
            "run_id": run_id,
            "endpoint": endpoint,
            "method": test_case["method"],
            "status": "pass" if passed else "fail",
            "status_code": response.status_code,
            "latency_ms": latency,
            "failure_reason": None if passed else f"Expected {test_case.get('expected_status')} got {response.status_code}",
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