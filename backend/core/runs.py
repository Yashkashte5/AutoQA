from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from backend.core.database import get_db
from backend.core.models import TestSuite, TestRun, TestResult
from backend.agents.supervisor import run_pipeline
import uuid, redis
from backend.core.config import settings

router = APIRouter()

_redis = redis.from_url(settings.redis_url, decode_responses=True)


def _fallback_ai_summary(by_category: dict, total_failures: int) -> str:
    if total_failures == 0:
        return "System health is good with no failing tests observed."

    ordered = sorted(by_category.items(), key=lambda x: x[1], reverse=True)
    top = ordered[:3]
    top_text = ", ".join(f"{k} ({v})" for k, v in top)

    health = "good"
    if by_category.get("server_error", 0) > 0 or total_failures >= 5:
        health = "poor"
    elif total_failures >= 2 or by_category.get("timeout", 0) > 0:
        health = "moderate"

    return f"System health is {health}; top issues are {top_text}."


@router.post("/{suite_id}")
def trigger_run(suite_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    suite = db.query(TestSuite).filter(TestSuite.id == suite_id).first()
    if not suite:
        raise HTTPException(status_code=404, detail="Suite not found")

    run = TestRun(id=uuid.uuid4(), suite_id=suite.id, status="running")
    db.add(run)
    db.commit()
    db.refresh(run)

    run_id = str(run.id)
    _redis.hset(f"run_progress:{run_id}", mapping={"stage": "queued", "pct": 0, "message": "Run queued..."})
    _redis.expire(f"run_progress:{run_id}", 3600)

    background_tasks.add_task(run_pipeline, run_id, suite_id, _redis)

    return {
        "run_id": run_id,
        "status": "running",
        "message": "Run started. Poll /runs/{run_id}/progress for updates.",
    }


@router.get("/{run_id}/progress")
def get_progress(run_id: str, db: Session = Depends(get_db)):
    run = db.query(TestRun).filter(TestRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    progress = _redis.hgetall(f"run_progress:{run_id}")
    return {
        "run_id": run_id,
        "status": run.status,
        "stage": progress.get("stage", "queued"),
        "pct": int(progress.get("pct", 0)),
        "message": progress.get("message", ""),
        "pass_rate": run.pass_rate,
        "coverage_pct": run.coverage_pct,
    }


@router.get("/{run_id}")
def get_run(run_id: str, db: Session = Depends(get_db)):
    run = db.query(TestRun).filter(TestRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    results = db.query(TestResult).filter(TestResult.run_id == run.id).all()
    return {
        "run_id": str(run.id),
        "status": run.status,
        "pass_rate": run.pass_rate,
        "coverage_pct": run.coverage_pct,
        "mlflow_run_id": run.mlflow_run_id,
        "results": [
            {
                "endpoint": r.endpoint,
                "method": r.method,
                "status": r.status,
                "status_code": r.status_code,
                "latency_ms": r.latency_ms,
                "failure_reason": r.failure_reason,
                "category": r.category,
                "severity": r.severity,
                "suggestion": r.suggestion,
            }
            for r in results
        ],
    }


@router.get("/{run_id}/results")
def get_run_results(
    run_id: str,
    status: str = None,
    severity: str = None,
    db: Session = Depends(get_db),
):
    run = db.query(TestRun).filter(TestRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    query = db.query(TestResult).filter(TestResult.run_id == run.id)
    if status:
        query = query.filter(TestResult.status == status)
    if severity:
        query = query.filter(TestResult.severity == severity)

    results = query.all()

    summary = {
        "total": len(results),
        "passed": sum(1 for r in results if r.status == "pass"),
        "failed": sum(1 for r in results if r.status == "fail"),
        "errors": sum(1 for r in results if r.status == "error"),
    }

    by_category = {}
    by_severity = {}
    for r in results:
        if r.category:
            by_category[r.category] = by_category.get(r.category, 0) + 1
        if r.severity:
            by_severity[r.severity] = by_severity.get(r.severity, 0) + 1

    progress = _redis.hgetall(f"run_progress:{run_id}")
    ai_summary = progress.get("summary", "")
    if not ai_summary:
        total_failures = summary["failed"] + summary["errors"]
        ai_summary = _fallback_ai_summary(by_category, total_failures)

    return {
        "run_id": run_id,
        "summary": summary,
        "ai_summary": ai_summary,
        "by_category": by_category,
        "by_severity": by_severity,
        "results": [
            {
                "endpoint": r.endpoint,
                "method": r.method,
                "status": r.status,
                "status_code": r.status_code,
                "latency_ms": r.latency_ms,
                "failure_reason": r.failure_reason,
                "category": r.category,
                "severity": r.severity,
                "suggestion": r.suggestion,
            }
            for r in results
        ],
    }