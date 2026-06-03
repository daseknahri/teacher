import os
import tempfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    tmpdir = tempfile.mkdtemp(prefix="teacher_progress_tests_")
    db_path = os.path.join(tmpdir, "test.db")
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["STORAGE_DIR"] = os.path.join(tmpdir, "storage")

    # Import app after env vars are set, so config binds to test paths.
    from app.database import Base, engine
    from app.main import create_app

    # The SQLAlchemy engine is a module-level singleton bound on first import, so
    # the per-test DATABASE_URL above only takes effect for the very first test.
    # Without this reset every later test would share the first test's database and
    # accumulate rows, making "list/isolation/archive" assertions order-dependent.
    # Drop and recreate the schema so each test starts from a clean, isolated state.
    Base.metadata.drop_all(bind=engine)

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
