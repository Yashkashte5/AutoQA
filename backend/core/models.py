from sqlalchemy import Column, String, Integer, Float, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid
from backend.core.database import Base

class TestSuite(Base):
    __tablename__ = "test_suites"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    base_url = Column(String, nullable=False)
    spec_text = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

class TestRun(Base):
    __tablename__ = "test_runs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    suite_id = Column(UUID(as_uuid=True), ForeignKey("test_suites.id"))
    status = Column(String, default="pending")
    pass_rate = Column(Float, nullable=True)
    coverage_pct = Column(Float, nullable=True)
    mlflow_run_id = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

class TestResult(Base):
    __tablename__ = "test_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("test_runs.id"))
    endpoint = Column(String)
    method = Column(String)
    status = Column(String)
    status_code = Column(Integer, nullable=True)
    latency_ms = Column(Float, nullable=True)
    failure_reason = Column(Text, nullable=True)
    category = Column(String, nullable=True)
    severity = Column(String, nullable=True)
    suggestion = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())