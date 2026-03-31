from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.core.database import Base, engine
from backend.core import suites
from backend.core import suites, runs


Base.metadata.create_all(bind=engine)

app = FastAPI(title="AutoQA", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(suites.router, prefix="/suites", tags=["suites"])
app.include_router(runs.router, prefix="/runs", tags=["runs"])
@app.get("/health")
def health():
    return {"status": "ok"}