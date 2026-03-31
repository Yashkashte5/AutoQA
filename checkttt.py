from backend.core.database import SessionLocal
from backend.core.models import TestSuite, TestRun, TestResult
from backend.rag.retriever import get_collection_size, retrieve_endpoints
from sqlalchemy import text

db = SessionLocal()

# Get latest suite
suite = db.query(TestSuite).order_by(TestSuite.created_at.desc()).first()
print(f"Latest suite: {suite.name} ({suite.id})")
print(f"Base URL: {suite.base_url}")

# Indexed count
size = get_collection_size(str(suite.id))
print(f"\nIndexed in ChromaDB: {size} endpoints")

# Get latest run for this suite
run = db.query(TestRun).filter(
    TestRun.suite_id == suite.id,
    TestRun.status == "done"
).order_by(TestRun.created_at.desc()).first()

if run:
    results = db.query(TestResult).filter(TestResult.run_id == run.id).all()
    tested = set(r.endpoint for r in results)
    print(f"Tested endpoints in last run: {len(tested)}")
    print(f"Total test cases run: {len(results)}")
    print(f"\nEndpoints tested:")
    for ep in sorted(tested):
        print(f"  {ep}")

# Retrieve all endpoints from ChromaDB to see what's there
print(f"\nAll endpoints in ChromaDB (sample via broad query):")
from backend.rag.retriever import _client, _ef
collection = _client.get_or_create_collection(
    name=f"suite_{suite.id}",
    embedding_function=_ef,
)
all_docs = collection.get()
paths = set()
for meta in all_docs.get("metadatas", []):
    path = meta.get("path", "")
    method = meta.get("method", "")
    if path and method:
        paths.add(f"{method} {path}")

print(f"Total unique method+path combos in ChromaDB: {len(paths)}")
for p in sorted(paths):
    print(f"  {p}")

db.close()