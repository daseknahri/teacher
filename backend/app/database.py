from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import DATABASE_URL


class Base(DeclarativeBase):
    pass


connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, future=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_schema_compatibility() -> None:
    # Keep runtime schema backwards-compatible for existing deployments without migrations.
    with engine.begin() as conn:
        inspector = inspect(conn)
        table_names = set(inspector.get_table_names())
        if "students" not in table_names:
            return
        student_columns = {col["name"] for col in inspector.get_columns("students")}
        if "external_id" not in student_columns:
            conn.execute(text("ALTER TABLE students ADD COLUMN external_id VARCHAR(64)"))
        if "birth_date" not in student_columns:
            conn.execute(text("ALTER TABLE students ADD COLUMN birth_date DATE"))
        session_columns = {col["name"] for col in inspector.get_columns("sessions")}
        if "unit_id" not in session_columns:
            conn.execute(text("ALTER TABLE sessions ADD COLUMN unit_id INTEGER"))
        if "unit_session_number" not in session_columns:
            conn.execute(text("ALTER TABLE sessions ADD COLUMN unit_session_number INTEGER"))
        user_columns = {col["name"] for col in inspector.get_columns("users")}
        if "failed_login_attempts" not in user_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN failed_login_attempts INTEGER DEFAULT 0"))
            conn.execute(text("UPDATE users SET failed_login_attempts = 0 WHERE failed_login_attempts IS NULL"))
        if "locked_until" not in user_columns:
            locked_type = "TIMESTAMP" if conn.dialect.name == "postgresql" else "DATETIME"
            conn.execute(text(f"ALTER TABLE users ADD COLUMN locked_until {locked_type}"))
        if "timetable_rule_exceptions" in table_names:
            exception_columns = {col["name"] for col in inspector.get_columns("timetable_rule_exceptions")}
            if "target_date" not in exception_columns:
                conn.execute(text("ALTER TABLE timetable_rule_exceptions ADD COLUMN target_date DATE"))
            if "target_start_time" not in exception_columns:
                time_type = "TIME" if conn.dialect.name == "postgresql" else "TIME"
                conn.execute(text(f"ALTER TABLE timetable_rule_exceptions ADD COLUMN target_start_time {time_type}"))
            if "target_end_time" not in exception_columns:
                time_type = "TIME" if conn.dialect.name == "postgresql" else "TIME"
                conn.execute(text(f"ALTER TABLE timetable_rule_exceptions ADD COLUMN target_end_time {time_type}"))
