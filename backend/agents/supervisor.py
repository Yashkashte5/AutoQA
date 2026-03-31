"""
Supervisor Agent
----------------
Orchestrates the full AutoQA multi-agent pipeline.
Acts as the LangGraph-style supervisor that sequences agent calls,
manages progress updates, and handles failures at each stage.

Pipeline:
  SpecReaderAgent → TestGeneratorAgent → ExecutorAgents (parallel via RabbitMQ)
      → CoverageAgent → BugReporterAgent → SynthesizerAgent
"""
import mlflow
from celery import group
from celery.exceptions import TimeoutError as CeleryTimeoutError

from backend.agents.spec_reader import run_spec_reader
from backend.agents.test_generator import run_test_generator
from backend.agents.bug_reporter import run_bug_reporter
from backend.agents.coverage import deduplicate_test_cases, compute_coverage
from backend.agents.synthesizer import compute_pass_rate, log_to_mlflow, persist_results
from backend.workers.tasks import run_test_case
from backend.core.database import SessionLocal
from backend.core.models import TestSuite, TestRun
from backend.core.config import settings


def _set_progress(redis_client, run_id: str, stage: str, pct: int, message: str = ""):
    redis_client.hset(f"run_progress:{run_id}", mapping={
        "stage": stage,
        "pct": pct,
        "message": message,
    })
    redis_client.expire(f"run_progress:{run_id}", 3600)


def run_pipeline(run_id: str, suite_id: str, redis_client):
    """
    Main supervisor entry point. Called as a FastAPI BackgroundTask.
    Coordinates all agents in sequence, updates progress after each stage.
    """
    import redis as redis_lib
    db = SessionLocal()

    try:
        suite = db.query(TestSuite).filter(TestSuite.id == suite_id).first()
        run = db.query(TestRun).filter(TestRun.id == run_id).first()

        mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
        mlflow.set_experiment("autoqa")

        with mlflow.start_run(run_name=f"run-{run_id}") as mlrun:
            mlflow.log_param("suite_id", suite_id)
            mlflow.log_param("base_url", suite.base_url)

            # ── Stage 1: Spec Reader Agent ─────────────────────────────────
            _set_progress(redis_client, run_id, "parsing", 10, "Spec reader agent running...")
            endpoints = run_spec_reader(str(suite.id), suite.base_url)

            if not endpoints:
                run.status = "failed"
                db.commit()
                _set_progress(redis_client, run_id, "failed", 0, "No endpoints found in spec")
                return

            # ── Stage 2: Test Generator Agent ──────────────────────────────
            _set_progress(redis_client, run_id, "generating", 30,
                          f"Generating tests for {len(endpoints)} endpoints...")
            test_cases = run_test_generator(endpoints, suite.base_url, batch_size=2)

            if not test_cases:
                run.status = "failed"
                db.commit()
                _set_progress(redis_client, run_id, "failed", 0, "Test generation failed")
                return

            # ── Stage 3: Coverage Agent — dedup ────────────────────────────
            test_cases = deduplicate_test_cases(test_cases)

            # ── Stage 4: Executor Agents (parallel via RabbitMQ + Celery) ──
            _set_progress(redis_client, run_id, "executing", 45,
                          f"Executing {len(test_cases)} unique tests in parallel...")
            job_group = group(run_test_case.s(tc, str(run_id)) for tc in test_cases)
            result = job_group.apply_async()
            wait_timeout = max(300, len(test_cases) * 15)

            try:
                raw_results = result.get(timeout=wait_timeout)
            except CeleryTimeoutError:
                try:
                    result.revoke(terminate=False)
                except Exception:
                    pass
                run.status = "failed"
                db.commit()
                _set_progress(redis_client, run_id, "failed", 0,
                               f"Timed out after {wait_timeout}s")
                return

            # ── Stage 5: Bug Reporter Agent ────────────────────────────────
            _set_progress(redis_client, run_id, "reporting", 80, "Classifying failures...")
            bug_report = run_bug_reporter(raw_results, batch_size=10)
            enriched_results = bug_report["enriched_results"]
            failure_summary = bug_report["failure_summary"]
            summary_text = bug_report.get("summary", "")

            if summary_text:
                redis_client.hset(f"run_progress:{run_id}", mapping={"summary": summary_text})
                redis_client.expire(f"run_progress:{run_id}", 3600)

            # ── Stage 6: Coverage Agent — metrics ──────────────────────────
            coverage_data = compute_coverage(enriched_results, test_cases)
            coverage_pct = coverage_data["coverage_pct"]

            # ── Stage 7: Synthesizer Agent ─────────────────────────────────
            _set_progress(redis_client, run_id, "saving", 92, "Saving results to database...")
            pass_rate = compute_pass_rate(enriched_results)
            passed = sum(1 for r in enriched_results if r and r.get("status") == "pass")
            total = len(enriched_results)

            log_to_mlflow(
                endpoints_found=len(endpoints),
                test_cases_generated=len(test_cases),
                pass_rate=pass_rate,
                coverage_pct=coverage_pct,
                total_tests=total,
                passed=passed,
                failure_summary=failure_summary,
            )

            persist_results(
                db=db,
                run=run,
                enriched_results=enriched_results,
                pass_rate=pass_rate,
                coverage_pct=coverage_pct,
                mlflow_run_id=mlrun.info.run_id,
            )

            _set_progress(redis_client, run_id, "done", 100,
                          f"{total} tests — {pass_rate}% pass rate")

    except Exception as e:
        db.rollback()
        try:
            run = db.query(TestRun).filter(TestRun.id == run_id).first()
            if run:
                run.status = "failed"
                db.commit()
        except Exception:
            pass
        _set_progress(redis_client, run_id, "failed", 0, str(e))
    finally:
        db.close()