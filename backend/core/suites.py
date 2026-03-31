from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from backend.core.database import get_db
from backend.core.models import TestSuite
from backend.rag.parser import parse_openapi_spec
from backend.rag.retriever import index_endpoints
import uuid

router = APIRouter()

@router.post("/")
async def create_suite(
    name: str = Form(...),
    base_url: str = Form(...),
    spec_file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    raw = (await spec_file.read()).decode("utf-8")

    try:
        endpoints = parse_openapi_spec(raw)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid spec: {e}")

    if not endpoints:
        raise HTTPException(status_code=400, detail="No endpoints found in spec")

    suite = TestSuite(
        id=uuid.uuid4(),
        name=name,
        base_url=base_url,
        spec_text=raw,
    )
    db.add(suite)
    db.commit()
    db.refresh(suite)

    index_endpoints(str(suite.id), endpoints)

    return {
        "suite_id": str(suite.id),
        "name": suite.name,
        "base_url": suite.base_url,
        "endpoint_count": len(endpoints),
    }

@router.get("/{suite_id}")
def get_suite(suite_id: str, db: Session = Depends(get_db)):
    suite = db.query(TestSuite).filter(TestSuite.id == suite_id).first()
    if not suite:
        raise HTTPException(status_code=404, detail="Suite not found")
    return {
        "suite_id": str(suite.id),
        "name": suite.name,
        "base_url": suite.base_url,
        "created_at": suite.created_at,
    }