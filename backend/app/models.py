from datetime import date, datetime, time
from enum import Enum

from sqlalchemy import JSON, Boolean, Date, DateTime, Enum as SQLEnum, Float, ForeignKey, Integer, String, Text, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class AttendanceStatus(str, Enum):
    PRESENT = "present"
    ABSENT = "absent"
    LATE = "late"
    EXCUSED = "excused"


class ProgressItemType(str, Enum):
    LESSON = "lesson"
    ACTIVITY = "activity"
    EXERCISE = "exercise"


class WorkflowUnitType(str, Enum):
    CHAPTER = "chapter"
    EXERCISE_SERIES = "exercise_series"
    EXAM = "exam"
    EXAM_CORRECTION = "exam_correction"


class WorkflowUnitStatus(str, Enum):
    ACTIVE = "active"
    CLOSED = "closed"


class WorkflowChecklistItemKind(str, Enum):
    CHAPTER = "chapter"
    SECTION = "section"
    SUBSECTION = "subsection"
    PROPERTY = "property"
    DEFINITION = "definition"
    EXAMPLE = "example"
    EXERCISE = "exercise"
    SUPERVISION = "supervision"
    CORRECTION = "correction"
    OTHER = "other"


class UserRole(str, Enum):
    OWNER = "owner"
    TEACHER = "teacher"


class HolidayDay(Base):
    __tablename__ = "holiday_days"
    __table_args__ = (
        UniqueConstraint("holiday_date", "country_code", "region", name="uq_holiday_day_country_region"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    holiday_date: Mapped[date] = mapped_column(Date, index=True)
    name: Mapped[str] = mapped_column(String(255))
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=True)
    country_code: Mapped[str] = mapped_column(String(8), index=True, default="MA")
    region: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Classroom(Base):
    __tablename__ = "classes"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    level: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    students: Mapped[list["Student"]] = relationship(back_populates="classroom", cascade="all, delete-orphan")
    sessions: Mapped[list["ClassSession"]] = relationship(back_populates="classroom", cascade="all, delete-orphan")
    timetable_rules: Mapped[list["ClassTimetableRule"]] = relationship(back_populates="classroom", cascade="all, delete-orphan")
    timetable_class_aliases: Mapped[list["TimetableClassAlias"]] = relationship(
        back_populates="classroom",
        cascade="all, delete-orphan",
    )
    timetable_versions: Mapped[list["TimetableVersion"]] = relationship(
        back_populates="classroom",
        cascade="all, delete-orphan",
    )
    exams: Mapped[list["Exam"]] = relationship(back_populates="classroom", cascade="all, delete-orphan")
    workflow_units: Mapped[list["WorkflowUnit"]] = relationship(back_populates="classroom", cascade="all, delete-orphan")
    access_entries: Mapped[list["ClassAccess"]] = relationship(back_populates="classroom", cascade="all, delete-orphan")
    archive_state: Mapped["ClassArchiveState | None"] = relationship(
        back_populates="classroom",
        cascade="all, delete-orphan",
        uselist=False,
    )


class Student(Base):
    __tablename__ = "students"
    __table_args__ = (UniqueConstraint("class_id", "student_code", name="uq_class_student_code"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), index=True)
    student_code: Mapped[str] = mapped_column(String(64), index=True)
    external_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255))
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    classroom: Mapped["Classroom"] = relationship(back_populates="students")
    attendance_records: Mapped[list["AttendanceRecord"]] = relationship(back_populates="student", cascade="all, delete-orphan")
    exam_results: Mapped[list["ExamResult"]] = relationship(back_populates="student", cascade="all, delete-orphan")


class ClassTimetableRule(Base):
    __tablename__ = "class_timetable_rules"
    __table_args__ = (
        UniqueConstraint(
            "class_id",
            "weekday",
            "start_time",
            "end_time",
            "effective_from",
            "effective_to",
            "subject",
            "room",
            "group_name",
            name="uq_class_timetable_rule",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), index=True)
    teacher_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    weekday: Mapped[int] = mapped_column(Integer, index=True)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    room: Mapped[str | None] = mapped_column(String(120), nullable=True)
    group_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    effective_from: Mapped[date] = mapped_column(Date, index=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    source: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    classroom: Mapped["Classroom"] = relationship(back_populates="timetable_rules")
    exceptions: Mapped[list["TimetableRuleException"]] = relationship(
        back_populates="rule",
        cascade="all, delete-orphan",
    )


class TimetableRuleException(Base):
    __tablename__ = "timetable_rule_exceptions"
    __table_args__ = (
        UniqueConstraint("rule_id", "exception_date", "exception_type", name="uq_timetable_rule_exception"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), index=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("class_timetable_rules.id", ondelete="CASCADE"), index=True)
    exception_date: Mapped[date] = mapped_column(Date, index=True)
    exception_type: Mapped[str] = mapped_column(String(32), default="cancel", index=True)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    target_start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    target_end_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    classroom: Mapped["Classroom"] = relationship()
    rule: Mapped["ClassTimetableRule"] = relationship(back_populates="exceptions")


class TimetableClassAlias(Base):
    __tablename__ = "timetable_class_aliases"
    __table_args__ = (
        UniqueConstraint("user_id", "alias_key", name="uq_timetable_class_alias_user_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), index=True)
    alias_name: Mapped[str] = mapped_column(String(255))
    alias_key: Mapped[str] = mapped_column(String(255), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="timetable_class_aliases")
    classroom: Mapped["Classroom"] = relationship(back_populates="timetable_class_aliases")


class TimetableVersion(Base):
    __tablename__ = "timetable_versions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rules_count: Mapped[int] = mapped_column(Integer, default=0)
    exceptions_count: Mapped[int] = mapped_column(Integer, default=0)
    snapshot: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    classroom: Mapped["Classroom"] = relationship(back_populates="timetable_versions")
    created_by_user: Mapped["User | None"] = relationship(back_populates="timetable_versions_created")


class ClassSession(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), index=True)
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("workflow_units.id", ondelete="SET NULL"), index=True, nullable=True)
    unit_session_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    session_date: Mapped[date] = mapped_column(Date)
    start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    end_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    classroom: Mapped["Classroom"] = relationship(back_populates="sessions")
    unit: Mapped["WorkflowUnit | None"] = relationship(back_populates="sessions")
    attendance_records: Mapped[list["AttendanceRecord"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    uploads: Mapped[list["SessionUpload"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    progress_items: Mapped[list["ProgressItem"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    workflow_actions: Mapped[list["WorkflowSessionChecklistAction"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )
    writeup: Mapped["WorkflowSessionWriteup | None"] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        uselist=False,
    )


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"
    __table_args__ = (UniqueConstraint("session_id", "student_id", name="uq_session_student_attendance"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    status: Mapped[AttendanceStatus] = mapped_column(SQLEnum(AttendanceStatus), default=AttendanceStatus.PRESENT)
    minutes_late: Mapped[int] = mapped_column(Integer, default=0)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    session: Mapped["ClassSession"] = relationship(back_populates="attendance_records")
    student: Mapped["Student"] = relationship(back_populates="attendance_records")


class SessionUpload(Base):
    __tablename__ = "session_uploads"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    file_path: Mapped[str] = mapped_column(String(500))
    ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reviewed: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    session: Mapped["ClassSession"] = relationship(back_populates="uploads")


class ProgressItem(Base):
    __tablename__ = "progress_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    item_type: Mapped[ProgressItemType] = mapped_column(SQLEnum(ProgressItemType))
    heading: Mapped[str] = mapped_column(String(500))
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)

    session: Mapped["ClassSession"] = relationship(back_populates="progress_items")


class WorkflowUnit(Base):
    __tablename__ = "workflow_units"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), index=True)
    exam_id: Mapped[int | None] = mapped_column(ForeignKey("exams.id", ondelete="SET NULL"), index=True, nullable=True)
    unit_type: Mapped[WorkflowUnitType] = mapped_column(SQLEnum(WorkflowUnitType), index=True)
    status: Mapped[WorkflowUnitStatus] = mapped_column(SQLEnum(WorkflowUnitStatus), default=WorkflowUnitStatus.ACTIVE, index=True)
    title: Mapped[str] = mapped_column(String(255))
    planned_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    document_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    document_path: Mapped[str | None] = mapped_column(String(600), nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    classroom: Mapped["Classroom"] = relationship(back_populates="workflow_units")
    exam: Mapped["Exam | None"] = relationship(back_populates="workflow_units")
    checklist_items: Mapped[list["WorkflowChecklistItem"]] = relationship(
        back_populates="unit",
        cascade="all, delete-orphan",
        order_by="WorkflowChecklistItem.position.asc()",
    )
    sessions: Mapped[list["ClassSession"]] = relationship(back_populates="unit")
    blueprint: Mapped["WorkflowUnitBlueprint | None"] = relationship(
        back_populates="unit",
        cascade="all, delete-orphan",
        uselist=False,
    )
    materials: Mapped[list["WorkflowUnitMaterial"]] = relationship(
        back_populates="unit",
        cascade="all, delete-orphan",
        order_by="WorkflowUnitMaterial.updated_at.desc()",
    )
    assistant_artifacts: Mapped[list["WorkflowUnitAssistantArtifact"]] = relationship(
        back_populates="unit",
        cascade="all, delete-orphan",
        order_by="WorkflowUnitAssistantArtifact.updated_at.desc()",
    )


class WorkflowChecklistItem(Base):
    __tablename__ = "workflow_checklist_items"
    __table_args__ = (
        UniqueConstraint("unit_id", "parent_item_id", "position", name="uq_workflow_item_position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("workflow_units.id", ondelete="CASCADE"), index=True)
    parent_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("workflow_checklist_items.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    item_kind: Mapped[WorkflowChecklistItemKind] = mapped_column(SQLEnum(WorkflowChecklistItemKind), default=WorkflowChecklistItemKind.OTHER)
    title: Mapped[str] = mapped_column(String(500))
    teacher_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    depth: Mapped[int] = mapped_column(Integer, default=0)
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_session_id: Mapped[int | None] = mapped_column(ForeignKey("sessions.id", ondelete="SET NULL"), index=True, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    unit: Mapped["WorkflowUnit"] = relationship(back_populates="checklist_items")
    parent: Mapped["WorkflowChecklistItem | None"] = relationship(remote_side=[id], back_populates="children")
    children: Mapped[list["WorkflowChecklistItem"]] = relationship(back_populates="parent", cascade="all, delete-orphan")
    actions: Mapped[list["WorkflowSessionChecklistAction"]] = relationship(back_populates="item", cascade="all, delete-orphan")
    attachments: Mapped[list["WorkflowChecklistItemAttachment"]] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
        order_by="WorkflowChecklistItemAttachment.created_at.desc()",
    )


class WorkflowChecklistItemAttachment(Base):
    __tablename__ = "workflow_checklist_item_attachments"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("workflow_checklist_items.id", ondelete="CASCADE"), index=True)
    file_path: Mapped[str] = mapped_column(String(600))
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    item: Mapped["WorkflowChecklistItem"] = relationship(back_populates="attachments")


class WorkflowSessionChecklistAction(Base):
    __tablename__ = "workflow_session_checklist_actions"
    __table_args__ = (UniqueConstraint("session_id", "item_id", name="uq_workflow_session_item_action"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("workflow_checklist_items.id", ondelete="CASCADE"), index=True)
    checked: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    session: Mapped["ClassSession"] = relationship(back_populates="workflow_actions")
    item: Mapped["WorkflowChecklistItem"] = relationship(back_populates="actions")


class WorkflowUnitBlueprint(Base):
    __tablename__ = "workflow_unit_blueprints"
    __table_args__ = (UniqueConstraint("unit_id", name="uq_workflow_unit_blueprint_unit"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("workflow_units.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(64), default="fallback")
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="ready", index=True)
    requested_session_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    document_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_text_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    blueprint_json: Mapped[dict] = mapped_column(JSON)
    unit_map_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    content_blocks_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    raw_provider_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    unit: Mapped["WorkflowUnit"] = relationship(back_populates="blueprint")


class WorkflowUnitMaterial(Base):
    __tablename__ = "workflow_unit_materials"
    __table_args__ = (UniqueConstraint("unit_id", "material_type", name="uq_workflow_unit_material_type"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("workflow_units.id", ondelete="CASCADE"), index=True)
    material_type: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(64), default="notebooklm")
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="ready", index=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notebook_artifact_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    source_payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    content_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(600), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    raw_provider_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    unit: Mapped["WorkflowUnit"] = relationship(back_populates="materials")


class WorkflowUnitAssistantArtifact(Base):
    __tablename__ = "workflow_unit_assistant_artifacts"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("workflow_units.id", ondelete="CASCADE"), index=True)
    artifact_kind: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(64), default="notebooklm")
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    section_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    section_path_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    action: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    raw_provider_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    unit: Mapped["WorkflowUnit"] = relationship(back_populates="assistant_artifacts")


class WorkflowSessionWriteup(Base):
    __tablename__ = "workflow_session_writeups"
    __table_args__ = (UniqueConstraint("session_id", name="uq_workflow_session_writeup_session"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("workflow_units.id", ondelete="SET NULL"), index=True, nullable=True)
    provider: Mapped[str] = mapped_column(String(64), default="fallback")
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="ready", index=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    checked_item_ids_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    checked_item_titles_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    learning_focus_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    teaching_content_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    practice_items_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    teacher_note_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    raw_provider_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    session: Mapped["ClassSession"] = relationship(back_populates="writeup")
    unit: Mapped["WorkflowUnit | None"] = relationship()


class Exam(Base):
    __tablename__ = "exams"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    exam_date: Mapped[date] = mapped_column(Date)
    max_score: Mapped[float] = mapped_column(Float)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    paper_outline_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    classroom: Mapped["Classroom"] = relationship(back_populates="exams")
    workflow_units: Mapped[list["WorkflowUnit"]] = relationship(back_populates="exam")
    results: Mapped[list["ExamResult"]] = relationship(back_populates="exam", cascade="all, delete-orphan")
    archive_state: Mapped["ExamArchiveState | None"] = relationship(
        back_populates="exam",
        cascade="all, delete-orphan",
        uselist=False,
    )


class ExamResult(Base):
    __tablename__ = "exam_results"
    __table_args__ = (UniqueConstraint("exam_id", "student_id", name="uq_exam_student_result"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    score: Mapped[float] = mapped_column(Float)
    note: Mapped[str | None] = mapped_column(String(100), nullable=True)
    teacher_comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    exam: Mapped["Exam"] = relationship(back_populates="results")
    student: Mapped["Student"] = relationship(back_populates="exam_results")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(SQLEnum(UserRole))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    tokens: Mapped[list["AuthToken"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    class_access_entries: Mapped[list["ClassAccess"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    timetable_class_aliases: Mapped[list["TimetableClassAlias"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    timetable_versions_created: Mapped[list["TimetableVersion"]] = relationship(
        back_populates="created_by_user",
    )


class AuthToken(Base):
    __tablename__ = "auth_tokens"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="tokens")


class ClassAccess(Base):
    __tablename__ = "class_access"
    __table_args__ = (UniqueConstraint("class_id", "user_id", name="uq_class_access_user"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    classroom: Mapped["Classroom"] = relationship(back_populates="access_entries")
    user: Mapped["User"] = relationship(back_populates="class_access_entries")


class ClassArchiveState(Base):
    __tablename__ = "class_archive_state"
    __table_args__ = (UniqueConstraint("class_id", name="uq_class_archive_state_class"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), index=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    classroom: Mapped["Classroom"] = relationship(back_populates="archive_state")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True)
    action: Mapped[str] = mapped_column(String(120), index=True)
    entity_type: Mapped[str] = mapped_column(String(120), index=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    class_id: Mapped[int | None] = mapped_column(ForeignKey("classes.id", ondelete="SET NULL"), index=True, nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class ExportArtifact(Base):
    __tablename__ = "export_artifacts"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), index=True)
    export_type: Mapped[str] = mapped_column(String(120), index=True)
    file_name: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(String(600))
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class ExamArchiveState(Base):
    __tablename__ = "exam_archive_state"
    __table_args__ = (UniqueConstraint("exam_id", name="uq_exam_archive_state_exam"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id", ondelete="CASCADE"), index=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    exam: Mapped["Exam"] = relationship(back_populates="archive_state")


class WorkflowLeafContent(Base):
    __tablename__ = "workflow_leaf_content"
    __table_args__ = (UniqueConstraint("unit_id", "checklist_item_id", name="uq_workflow_leaf_content_unit_item"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("workflow_units.id", ondelete="CASCADE"), index=True)
    checklist_item_id: Mapped[int] = mapped_column(ForeignKey("workflow_checklist_items.id", ondelete="CASCADE"), index=True)
    item_path_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    section_path_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    provider: Mapped[str] = mapped_column(String(64), default="manual")
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    source_payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    raw_provider_response_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    teaching_goal_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    launch_activity_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    worked_example_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    practice_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    solution_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    assessment_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    teacher_notes_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_excerpt_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    unit: Mapped["WorkflowUnit"] = relationship()
    checklist_item: Mapped["WorkflowChecklistItem"] = relationship()


class WorkflowPreparedSection(Base):
    __tablename__ = "workflow_prepared_sections"
    __table_args__ = (UniqueConstraint("unit_id", "section_key", name="uq_workflow_prepared_sections_unit_key"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("workflow_units.id", ondelete="CASCADE"), index=True)
    section_key: Mapped[str] = mapped_column(String(255), index=True)
    section_title: Mapped[str] = mapped_column(String(255))
    section_path_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    source_blocks_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source_excerpt_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    latex_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str] = mapped_column(String(64), default="notebooklm")
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="indexed", index=True)
    benchmark_status: Mapped[str] = mapped_column(String(32), default="pending")
    benchmark_notes_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_provider_response_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    unit: Mapped["WorkflowUnit"] = relationship()
