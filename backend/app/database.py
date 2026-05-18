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
        datetime_type = "TIMESTAMP" if conn.dialect.name == "postgresql" else "DATETIME"
        time_type = "TIME"
        float_type = "DOUBLE PRECISION" if conn.dialect.name == "postgresql" else "FLOAT"
        json_type = "JSONB" if conn.dialect.name == "postgresql" else "JSON"
        checklist_kind_default = "OTHER" if conn.dialect.name == "postgresql" else "other"
        column_cache: dict[str, set[str]] = {}

        def _columns(table_name: str) -> set[str]:
            if table_name not in column_cache:
                column_cache[table_name] = {col["name"] for col in inspector.get_columns(table_name)}
            return column_cache[table_name]

        def _ensure_column(table_name: str, column_name: str, ddl: str) -> None:
            if table_name not in table_names:
                return
            columns = _columns(table_name)
            if column_name in columns:
                return
            conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}"))
            columns.add(column_name)

        if "students" not in table_names:
            return
        student_columns = _columns("students")
        if "external_id" not in student_columns:
            conn.execute(text("ALTER TABLE students ADD COLUMN external_id VARCHAR(64)"))
        if "birth_date" not in student_columns:
            conn.execute(text("ALTER TABLE students ADD COLUMN birth_date DATE"))
        session_columns = _columns("sessions")
        if "unit_id" not in session_columns:
            conn.execute(text("ALTER TABLE sessions ADD COLUMN unit_id INTEGER"))
        if "unit_session_number" not in session_columns:
            conn.execute(text("ALTER TABLE sessions ADD COLUMN unit_session_number INTEGER"))
        user_columns = _columns("users")
        if "failed_login_attempts" not in user_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN failed_login_attempts INTEGER DEFAULT 0"))
            conn.execute(text("UPDATE users SET failed_login_attempts = 0 WHERE failed_login_attempts IS NULL"))
        if "locked_until" not in user_columns:
            conn.execute(text(f"ALTER TABLE users ADD COLUMN locked_until {datetime_type}"))
        if "timetable_rule_exceptions" in table_names:
            exception_columns = _columns("timetable_rule_exceptions")
            if "target_date" not in exception_columns:
                conn.execute(text("ALTER TABLE timetable_rule_exceptions ADD COLUMN target_date DATE"))
            if "target_start_time" not in exception_columns:
                conn.execute(text(f"ALTER TABLE timetable_rule_exceptions ADD COLUMN target_start_time {time_type}"))
            if "target_end_time" not in exception_columns:
                conn.execute(text(f"ALTER TABLE timetable_rule_exceptions ADD COLUMN target_end_time {time_type}"))

        _ensure_column("workflow_units", "planned_hours", f"{float_type} NULL")
        _ensure_column("workflow_units", "document_name", "VARCHAR(255) NULL")
        _ensure_column("workflow_units", "document_path", "VARCHAR(600) NULL")
        _ensure_column("workflow_units", "order_index", "INTEGER DEFAULT 0")
        _ensure_column("workflow_units", "created_by_user_id", "INTEGER NULL")
        _ensure_column("workflow_units", "closed_at", f"{datetime_type} NULL")
        if "workflow_units" in table_names:
            conn.execute(text("UPDATE workflow_units SET order_index = 0 WHERE order_index IS NULL"))

        _ensure_column("workflow_checklist_items", "parent_item_id", "INTEGER NULL")
        _ensure_column("workflow_checklist_items", "item_kind", f"VARCHAR(32) DEFAULT '{checklist_kind_default}'")
        _ensure_column("workflow_checklist_items", "position", "INTEGER DEFAULT 0")
        _ensure_column("workflow_checklist_items", "depth", "INTEGER DEFAULT 0")
        _ensure_column("workflow_checklist_items", "is_completed", "BOOLEAN DEFAULT FALSE")
        _ensure_column("workflow_checklist_items", "completed_session_id", "INTEGER NULL")
        _ensure_column("workflow_checklist_items", "completed_at", f"{datetime_type} NULL")
        _ensure_column("workflow_checklist_items", "created_at", f"{datetime_type} NULL")
        if "workflow_checklist_items" in table_names:
            conn.execute(
                text(f"UPDATE workflow_checklist_items SET item_kind = '{checklist_kind_default}' WHERE item_kind IS NULL")
            )
            conn.execute(text("UPDATE workflow_checklist_items SET position = 0 WHERE position IS NULL"))
            conn.execute(text("UPDATE workflow_checklist_items SET depth = 0 WHERE depth IS NULL"))
            conn.execute(text("UPDATE workflow_checklist_items SET is_completed = FALSE WHERE is_completed IS NULL"))

        _ensure_column("workflow_session_checklist_actions", "checked", "BOOLEAN DEFAULT TRUE")
        _ensure_column("workflow_session_checklist_actions", "created_at", f"{datetime_type} NULL")
        _ensure_column("workflow_session_checklist_actions", "updated_at", f"{datetime_type} NULL")
        if "workflow_session_checklist_actions" in table_names:
            conn.execute(text("UPDATE workflow_session_checklist_actions SET checked = TRUE WHERE checked IS NULL"))

        _ensure_column("workflow_unit_blueprints", "provider", "VARCHAR(64) DEFAULT 'fallback'")
        _ensure_column("workflow_unit_blueprints", "model", "VARCHAR(128) NULL")
        _ensure_column("workflow_unit_blueprints", "status", "VARCHAR(32) DEFAULT 'ready'")
        _ensure_column("workflow_unit_blueprints", "requested_session_count", "INTEGER NULL")
        _ensure_column("workflow_unit_blueprints", "document_hash", "VARCHAR(64) NULL")
        _ensure_column("workflow_unit_blueprints", "source_text_excerpt", "TEXT NULL")
        _ensure_column("workflow_unit_blueprints", "blueprint_json", f"{json_type} NULL")
        _ensure_column("workflow_unit_blueprints", "unit_map_json", f"{json_type} NULL")
        _ensure_column("workflow_unit_blueprints", "content_blocks_json", f"{json_type} NULL")
        _ensure_column("workflow_unit_blueprints", "raw_provider_response", f"{json_type} NULL")
        _ensure_column("workflow_unit_blueprints", "error_message", "TEXT NULL")
        _ensure_column("workflow_unit_blueprints", "reviewed", "BOOLEAN DEFAULT FALSE")
        _ensure_column("workflow_unit_blueprints", "reviewed_at", f"{datetime_type} NULL")
        _ensure_column("workflow_unit_blueprints", "reviewed_by_user_id", "INTEGER NULL")
        _ensure_column("workflow_unit_blueprints", "updated_at", f"{datetime_type} NULL")
        if "workflow_unit_blueprints" in table_names:
            conn.execute(text("UPDATE workflow_unit_blueprints SET reviewed = TRUE WHERE reviewed IS NULL"))

        _ensure_column("workflow_session_writeups", "unit_id", "INTEGER NULL")
        _ensure_column("workflow_session_writeups", "provider", "VARCHAR(64) DEFAULT 'fallback'")
        _ensure_column("workflow_session_writeups", "model", "VARCHAR(128) NULL")
        _ensure_column("workflow_session_writeups", "status", "VARCHAR(32) DEFAULT 'ready'")
        _ensure_column("workflow_session_writeups", "title", "VARCHAR(255) NULL")
        _ensure_column("workflow_session_writeups", "checked_item_ids_json", f"{json_type} NULL")
        _ensure_column("workflow_session_writeups", "checked_item_titles_json", f"{json_type} NULL")
        _ensure_column("workflow_session_writeups", "learning_focus_json", f"{json_type} NULL")
        _ensure_column("workflow_session_writeups", "teaching_content_json", f"{json_type} NULL")
        _ensure_column("workflow_session_writeups", "practice_items_json", f"{json_type} NULL")
        _ensure_column("workflow_session_writeups", "teacher_note_snapshot", "TEXT NULL")
        _ensure_column("workflow_session_writeups", "source_payload_json", f"{json_type} NULL")
        _ensure_column("workflow_session_writeups", "raw_provider_response", f"{json_type} NULL")
        _ensure_column("workflow_session_writeups", "error_message", "TEXT NULL")
        _ensure_column("workflow_session_writeups", "approved", "BOOLEAN DEFAULT TRUE")
        _ensure_column("workflow_session_writeups", "updated_at", f"{datetime_type} NULL")
        if "workflow_session_writeups" in table_names:
            conn.execute(text("UPDATE workflow_session_writeups SET provider = 'fallback' WHERE provider IS NULL"))
            conn.execute(text("UPDATE workflow_session_writeups SET status = 'ready' WHERE status IS NULL"))
            conn.execute(text("UPDATE workflow_session_writeups SET approved = TRUE WHERE approved IS NULL"))

        _ensure_column("workflow_unit_materials", "provider", "VARCHAR(64) DEFAULT 'notebooklm'")
        _ensure_column("workflow_unit_materials", "model", "VARCHAR(128) NULL")
        _ensure_column("workflow_unit_materials", "status", "VARCHAR(32) DEFAULT 'ready'")
        _ensure_column("workflow_unit_materials", "title", "VARCHAR(255) NULL")
        _ensure_column("workflow_unit_materials", "notebook_artifact_id", "VARCHAR(128) NULL")
        _ensure_column("workflow_unit_materials", "source_payload_json", f"{json_type} NULL")
        _ensure_column("workflow_unit_materials", "content_markdown", "TEXT NULL")
        _ensure_column("workflow_unit_materials", "file_path", "VARCHAR(600) NULL")
        _ensure_column("workflow_unit_materials", "file_name", "VARCHAR(255) NULL")
        _ensure_column("workflow_unit_materials", "file_content_type", "VARCHAR(128) NULL")
        _ensure_column("workflow_unit_materials", "raw_provider_response", f"{json_type} NULL")
        _ensure_column("workflow_unit_materials", "error_message", "TEXT NULL")
        _ensure_column("workflow_unit_materials", "created_by_user_id", "INTEGER NULL")
        _ensure_column("workflow_unit_materials", "created_at", f"{datetime_type} NULL")
        _ensure_column("workflow_unit_materials", "updated_at", f"{datetime_type} NULL")
        if "workflow_unit_materials" in table_names:
            conn.execute(text("UPDATE workflow_unit_materials SET provider = 'notebooklm' WHERE provider IS NULL"))
            conn.execute(text("UPDATE workflow_unit_materials SET status = 'ready' WHERE status IS NULL"))
