# AutoQA

Agentic API Testing Platform: upload an OpenAPI spec and AutoQA generates tests, executes them in parallel, classifies failures, and tracks everything in MLflow.

Repository: https://github.com/Yashkashte5/AutoQA

![Python](https://img.shields.io/badge/python-3.11-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-green)
![Celery](https://img.shields.io/badge/Celery-workers-brightgreen)
![MLflow](https://img.shields.io/badge/MLflow-tracking-blue)

## Demo

![AutoQA Demo](demo/demo.gif)

## What It Does

Given a base URL + OpenAPI spec, AutoQA performs this pipeline:

1. Parses and indexes the spec (RAG-ready endpoint docs)
2. Retrieves endpoints via agentic retrieval loop
3. Generates tests with a hybrid strategy:
   - Deterministic baseline for simple endpoints
   - LLM generation for complex endpoints
4. Validates generated cases against spec-defined status codes
5. Executes tests in parallel via Celery workers
6. Classifies failures deterministically and adds AI suggestions
7. Generates an AI health summary and logs metrics in MLflow
8. Displays run results in the React dashboard

## Current Architecture

### Core Services

- Backend API: FastAPI
- Queue/Workers: RabbitMQ + Celery
- Cache/Progress: Redis
- Database: PostgreSQL
- Experiment Tracking: MLflow
- Vector Store: ChromaDB
- Frontend: React + Vite

### Agent Flow

- Spec Reader: endpoint retrieval
- Test Generator: hybrid deterministic + LLM generation
- Coverage Agent: dedup + coverage metrics
- Bug Reporter: deterministic category/severity + AI suggestions + summary
- Synthesizer: persist results and log MLflow metrics

## Workflow

### End-to-End Pipeline

1. Suite creation
  - User uploads OpenAPI spec + base URL
  - Spec is parsed and endpoint chunks are indexed in ChromaDB

2. Run orchestration
  - Supervisor creates a run and updates progress state in Redis
  - Spec Reader retrieves testable endpoints using multi-query retrieval

3. Test generation
  - Simple endpoints use deterministic baseline generation
  - Complex endpoints use LLM generation with adaptive backoff
  - All generated cases go through strict validation and normalization

4. Coverage shaping
  - Dedup keeps one success + one negative variant per method/endpoint

5. Parallel execution
  - Celery workers execute HTTP requests in parallel via RabbitMQ
  - Results include status, code, latency, and failure reason

6. Failure intelligence
  - Deterministic rule classification sets category/severity
  - AI suggestions are generated in batch and sanitized
  - AI summary is generated for run-level health view

7. Persistence and analytics
  - Enriched results saved in PostgreSQL
  - Run metrics and failure breakdown logged to MLflow

### Agent Responsibilities

| Agent | File | Responsibility |
|---|---|---|
| Supervisor | backend/agents/supervisor.py | Orchestrates full pipeline, manages stage progress, coordinates worker execution and persistence |
| Spec Reader | backend/agents/spec_reader.py | Retrieves endpoint candidates from indexed spec documents |
| Test Generator | backend/agents/test_generator.py | Hybrid test generation, JSON recovery, retry/backoff, deterministic fallback cases |
| Validator | backend/agents/validator.py | Enforces case schema, endpoint validity, and spec-constrained expected statuses |
| Coverage Agent | backend/agents/coverage.py | Deduplicates test cases and computes endpoint coverage metrics |
| Bug Reporter | backend/agents/bug_reporter.py | Deterministic category/severity classification, AI suggestions, and AI run summary |
| Synthesizer | backend/agents/synthesizer.py | Computes pass rate, logs MLflow metrics, persists run results |

## Project Structure

```text
AutoQA/
├── backend/
│   ├── agents/
│   │   ├── supervisor.py
│   │   ├── spec_reader.py
│   │   ├── test_generator.py
│   │   ├── validator.py
│   │   ├── coverage.py
│   │   ├── bug_reporter.py
│   │   └── synthesizer.py
│   ├── rag/
│   │   ├── parser.py
│   │   ├── retriever.py
│   │   └── grader.py
│   ├── workers/
│   │   ├── celery_app.py
│   │   └── tasks.py
│   └── core/
│       ├── main.py
│       ├── suites.py
│       ├── runs.py
│       ├── models.py
│       ├── database.py
│       └── config.py
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   ├── components/
│   │   └── api.js
│   ├── package.json
│   └── vite.config.js
├── infra/
│   └── docker-compose.yml
├── requirements.txt
└── README.md
```

## Key Improvements Implemented

### Correctness

- `expected_status` is constrained to spec responses only
- Path-only endpoint normalization is enforced
- Invalid templated endpoints (`{id}` unresolved) are dropped
- Generated test cases are validated before execution

### Stability

- Defensive JSON parsing for LLM output
- Retry with stricter prompt on malformed JSON
- Deterministic spec-based fallback generation when needed
- Safe handling when `expected_status is None`

### Performance

- Hybrid generation reduces unnecessary LLM calls
- Adaptive pacing/backoff for LLM calls
- HTTP connection pooling in workers
- Batch suggestion generation for failure explanations
- Threaded Celery workers for real parallelism on Windows

### Reporting

- Deterministic failure categories:
  - `server_error` (critical for 5xx)
  - `unexpected_status` (medium for non-404 4xx)
  - `not_found` (low for 404)
  - `timeout` (low for timeout failures)
- AI suggestions are sanitized to avoid backend-internal hallucinations
- AI run summary is included in results flow

## Demo Results

Run target: `https://httpbin.org`

- Endpoints found: 49
- Total tests: 40
- Passed: 26
- Failed: 14
- Pass rate: 65.0%
- Coverage: 100%
- Duration: ~3.2 min

Failure breakdown:

- `server_error`: 7
- `unexpected_status`: 6
- `not_found`: 1

This runtime is substantially improved from earlier ~7-8 minute runs while preserving endpoint-level coverage.

## API Endpoints

- `POST /suites/` create suite (upload spec)
- `POST /runs/{suite_id}` trigger run
- `GET /runs/{run_id}/progress` poll progress
- `GET /runs/{run_id}` get run overview
- `GET /runs/{run_id}/results` get detailed results
- `GET /health` health check

Swagger docs: `http://localhost:8000/docs`

## Environment Variables

Create `.env` in project root with required keys:

```env
GROQ_API_KEY=
POSTGRES_URL=
REDIS_URL=
RABBITMQ_URL=
MLFLOW_TRACKING_URI=
```

## Local Setup (Windows)

Clone repository:

```powershell
git clone https://github.com/Yashkashte5/AutoQA.git
cd AutoQA
```

Install dependencies:

```powershell
pip install -r requirements.txt
```

Start backend:

```powershell
uvicorn backend.core.main:app --reload
```

Start worker (recommended):

```powershell
celery -A backend.workers.celery_app worker --loglevel=info --pool=threads --concurrency=12
```

Start frontend:

```powershell
cd frontend
npm install
npm run dev
```

Open UI: `http://localhost:5173`
Open MLflow: `http://localhost:5000`


## Future Scope

### 1. Agentic UI Testing

- Convert API + flow intent into browser journeys
- Multi-agent Playwright/Cypress generation and execution
- DOM + screenshot based failure triage
- Visual regression and accessibility agents

### 2. Self-Healing QA Agents

- Auto-detect flaky tests
- Retry with context-aware mutation
- Update failing selectors/inputs intelligently

### 3. PR-Aware Test Intelligence

- Diff OpenAPI/schema changes
- Regenerate only impacted tests
- Risk scoring and release gates

### 4. Security-Focused Agents

- Auth and token-flow validation
- Abuse-case payload generation
- Rate-limit and policy validation

### 5. Cost and Latency Optimization

- Spec hash caching of validated test sets
- Adaptive modes: smoke / standard / deep
- Dynamic complexity routing for LLM usage

