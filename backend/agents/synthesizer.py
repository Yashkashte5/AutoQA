"""
Synthesizer Agent
-----------------
Responsible for:
1. Computing final pass rate and run metrics
2. Logging all metrics to MLflow
3. Persisting enriched test results to PostgreSQL
4. Updating run status to done/failed
"""
import uuid
import mlflow
from backend.core.models import TestRun, TestResult


def compute_pass_rate(enriched_results: list[dict]) -> float:
    total = len(enriched_results)
    if total == 0:
        return 0.0
    passed = sum(1 for r in enriched_results if r and r.get("status") == "pass")
    return round(passed / total * 100, 2)


def log_to_mlflow(
    endpoints_found: int,
    test_cases_generated: int,
    pass_rate: float,
    coverage_pct: float,
    total_tests: int,
    passed: int,
    failure_summary: dict,
):
    """Log all run metrics to the active MLflow run."""
    mlflow.log_metric("endpoints_found", endpoints_found)
    mlflow.log_metric("test_cases_generated", test_cases_generated)
    mlflow.log_metric("pass_rate", pass_rate)
    mlflow.log_metric("coverage_pct", coverage_pct)
    mlflow.log_metric("total_tests", total_tests)
    mlflow.log_metric("passed", passed)
    for category, count in failure_summary.items():
        mlflow.log_metric(f"failures_{category}", count)


def persist_results(
    db,
    run: TestRun,
    enriched_results: list[dict],
    pass_rate: float,
    coverage_pct: float,
    mlflow_run_id: str,
):
    """
    Save all enriched test results to PostgreSQL.
    Updates run status, pass_rate, coverage_pct, and mlflow_run_id.
    """
    for r in enriched_results:
        if not r:
            continue
        db.add(TestResult(
            id=uuid.uuid4(),
            run_id=run.id,
            endpoint=r.get("endpoint"),
            method=r.get("method"),
            status=r.get("status"),
            status_code=r.get("status_code"),
            latency_ms=r.get("latency_ms"),
            failure_reason=r.get("failure_reason"),
            category=r.get("category"),
            severity=r.get("severity"),
            suggestion=r.get("suggestion"),
        ))

    run.status = "done"
    run.pass_rate = pass_rate
    run.coverage_pct = coverage_pct
    run.mlflow_run_id = mlflow_run_id
    db.commit()