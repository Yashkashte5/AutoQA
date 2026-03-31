"""
Coverage Agent
--------------
Responsible for:
1. Deduplicating generated test cases (same method + endpoint = duplicate)
2. Computing endpoint coverage after execution
3. Returning coverage metrics for MLflow logging
"""


def deduplicate_test_cases(test_cases: list[dict]) -> list[dict]:
    """
    Remove duplicate test cases while preserving one success and one negative
    variant for each method + endpoint pair.

    Buckets per method+endpoint:
    - success: expected_status is 2xx
    - non_success: expected_status is not 2xx or missing

    This keeps runtime bounded while retaining basic positive/negative coverage.
    """
    seen = set()
    unique = []

    def _bucket(tc: dict) -> str:
        code = tc.get("expected_status")
        if isinstance(code, int) and 200 <= code < 300:
            return "success"
        return "non_success"

    for tc in test_cases:
        key = f"{tc.get('method')}:{tc.get('endpoint')}:{_bucket(tc)}"
        if key not in seen:
            seen.add(key)
            unique.append(tc)
    return unique


def compute_coverage(results: list[dict], test_cases: list[dict]) -> dict:
    """
    Compute endpoint coverage after test execution.

    Returns:
        dict with:
        - coverage_pct: % of unique endpoints that were actually tested
        - tested_endpoints: set of endpoint paths that got a response
        - all_endpoints: set of all unique endpoint paths in the test suite
        - untested_endpoints: endpoints that were in test_cases but got no result
    """
    tested_endpoints = {r["endpoint"] for r in results if r and r.get("endpoint")}
    all_endpoints = {tc["endpoint"] for tc in test_cases if tc.get("endpoint")}
    untested = all_endpoints - tested_endpoints

    coverage_pct = (
        round(len(tested_endpoints) / len(all_endpoints) * 100, 2)
        if all_endpoints else 0.0
    )

    return {
        "coverage_pct": coverage_pct,
        "tested_endpoints": tested_endpoints,
        "all_endpoints": all_endpoints,
        "untested_endpoints": untested,
    }