import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


TEST_ROOT = Path(tempfile.mkdtemp(prefix="teacher_progress_tests_"))
TEST_DB_PATH = TEST_ROOT / "test.db"
TEST_STORAGE_DIR = TEST_ROOT / "storage"

# These must be set before test modules import application services. The app
# config loads backend/.env at import time, and local secrets should never make
# unit tests call external providers or reuse the developer database.
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"
os.environ["STORAGE_DIR"] = str(TEST_STORAGE_DIR)
os.environ["OPENAI_API_KEY"] = ""
os.environ["UNIT_PLANNER_PROVIDER"] = "fallback"
os.environ["SESSION_WRITER_PROVIDER"] = "fallback"
os.environ["NOTEBOOKLM_HOME"] = str(TEST_ROOT / "notebooklm")
os.environ["NOTEBOOKLM_AUTH_PATH"] = ""


@pytest.fixture()
def client():
    from app.database import Base, engine, ensure_schema_compatibility
    from app.main import create_app

    engine.dispose()
    Base.metadata.drop_all(bind=engine)
    TEST_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

    app = create_app()
    ensure_schema_compatibility()
    with TestClient(app) as test_client:
        yield test_client
    engine.dispose()
