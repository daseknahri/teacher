from datetime import date, datetime, time
from typing import Optional

from pydantic import BaseModel, Field

from .models import (
    AttendanceStatus,
    ProgressItemType,
    UserRole,
    WorkflowChecklistItemKind,
    WorkflowUnitStatus,
    WorkflowUnitType,
)


class ClassroomCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    subject: str | None = None
    level: str | None = None
    teacher_user_id: int | None = None


class ClassroomOut(BaseModel):
    id: int
    name: str
    subject: str | None
    level: str | None
    is_archived: bool = False

    model_config = {"from_attributes": True}


class StudentOut(BaseModel):
    id: int
    class_id: int
    student_code: str
    external_id: str | None
    full_name: str
    birth_date: date | None

    model_config = {"from_attributes": True}


class SessionCreate(BaseModel):
    session_date: date
    start_time: time | None = None
    end_time: time | None = None
    note: str | None = None


class SessionOut(BaseModel):
    id: int
    class_id: int
    session_date: date
    start_time: time | None
    end_time: time | None
    note: str | None

    model_config = {"from_attributes": True}


class SessionUpdate(BaseModel):
    session_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    note: str | None = None


class AttendanceIn(BaseModel):
    student_id: int
    status: AttendanceStatus
    minutes_late: int = 0
    comment: str | None = None


class AttendanceOut(BaseModel):
    id: int
    session_id: int
    student_id: int
    status: AttendanceStatus
    minutes_late: int
    comment: str | None

    model_config = {"from_attributes": True}


class ProgressItemIn(BaseModel):
    item_type: ProgressItemType
    heading: str
    content: str | None = None
    position: int = 0


class ProgressItemOut(BaseModel):
    id: int
    session_id: int
    item_type: ProgressItemType
    heading: str
    content: str | None
    position: int

    model_config = {"from_attributes": True}


class ExtractionItemOut(BaseModel):
    item_type: ProgressItemType
    heading: str
    content: str | None = None
    position: int
    hint_id: str | None = None


class ExtractionResponse(BaseModel):
    upload_id: int
    confidence: float
    lesson_headings: list[str]
    activities: list[str]
    exercises: list[str]
    raw_text: str
    provider: str
    model: str | None = None
    fallback_reason: str | None = None
    items: list[ExtractionItemOut] = Field(default_factory=list)


class ConfirmExtractionIn(BaseModel):
    items: list[ProgressItemIn]
    mode: str = Field(default="replace", pattern="^(replace|append)$")


class ExtractionLatestOut(BaseModel):
    upload_id: int
    session_id: int
    reviewed: bool
    created_at: datetime
    confidence: float
    lesson_headings: list[str]
    activities: list[str]
    exercises: list[str]
    raw_text: str
    provider: str
    model: str | None = None
    fallback_reason: str | None = None
    items: list[ExtractionItemOut] = Field(default_factory=list)


class QuickSubmitOut(BaseModel):
    session_id: int
    class_id: int
    session_date: date
    start_time: time | None
    end_time: time | None
    absent_students: int
    lesson_headings_count: int
    activities_count: int
    exercises_count: int
    provider: str
    model: str | None = None
    fallback_reason: str | None = None


class ExamCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    exam_date: date
    max_score: float = Field(gt=0)
    weight: float = Field(default=1.0, gt=0)


class ExamOut(BaseModel):
    id: int
    class_id: int
    title: str
    exam_date: date
    max_score: float
    weight: float
    is_archived: bool = False

    model_config = {"from_attributes": True}


class ExamUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    exam_date: date | None = None
    max_score: float | None = Field(default=None, gt=0)
    weight: float | None = Field(default=None, gt=0)


class ExamResultOut(BaseModel):
    student_id: int
    student_code: str
    full_name: str
    score: float
    note: str | None
    teacher_comment: str | None


class OwnerBootstrapIn(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)


class LoginIn(BaseModel):
    email: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: str


class UserCreate(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)
    role: UserRole = UserRole.TEACHER


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    failed_login_attempts: int = 0
    locked_until: datetime | None = None

    model_config = {"from_attributes": True}


class UserStatusUpdateIn(BaseModel):
    is_active: bool


class PasswordResetIn(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class InviteSendIn(BaseModel):
    temporary_password: str | None = Field(default=None, min_length=8, max_length=128)
    app_url: str | None = Field(default=None, max_length=500)


class InviteSendOut(BaseModel):
    sent: bool
    to_email: str
    app_url: str
    included_temporary_password: bool


class AuditLogOut(BaseModel):
    id: int
    user_id: int | None
    action: str
    entity_type: str
    entity_id: int | None
    class_id: int | None
    details: dict | None
    created_at: str


class ExportArtifactOut(BaseModel):
    id: int
    class_id: int
    export_type: str
    file_name: str
    file_size: int
    created_by_user_id: int | None
    created_at: str


class HolidayDayOut(BaseModel):
    id: int
    holiday_date: date
    name: str
    is_blocked: bool
    country_code: str
    region: str | None = None
    source: str | None = None

    model_config = {"from_attributes": True}


class HolidayDayUpdateIn(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    is_blocked: bool | None = None


class TimetableImportRowOut(BaseModel):
    row_index: int
    teacher_key: str | None = None
    class_name: str | None = None
    subject: str | None = None
    weekday: int | None = None
    weekday_label: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    room: str | None = None
    group: str | None = None
    is_valid: bool
    issues: list[str] = Field(default_factory=list)


class TimetableImportPreviewOut(BaseModel):
    total_rows: int
    valid_rows: int
    invalid_rows: int
    rows: list[TimetableImportRowOut] = Field(default_factory=list)


class TimetableRuleOut(BaseModel):
    id: int
    class_id: int
    teacher_key: str | None = None
    subject: str | None = None
    weekday: int
    weekday_label: str | None = None
    start_time: str
    end_time: str
    room: str | None = None
    group: str | None = None
    effective_from: date
    effective_to: date | None = None
    source: str | None = None


class TimetableClassAliasOut(BaseModel):
    id: int
    class_id: int
    class_name: str
    alias_name: str
    alias_key: str


class TimetableClassAliasUpdateIn(BaseModel):
    class_id: int = Field(gt=0)


class TimetableClassAliasBulkSaveIn(BaseModel):
    mappings: dict[str, int] = Field(default_factory=dict)


class TimetableClassAliasBulkSaveOut(BaseModel):
    saved_count: int
    skipped_count: int
    rows: list[TimetableClassAliasOut] = Field(default_factory=list)


class TimetableRuleExceptionCreateIn(BaseModel):
    rule_id: int = Field(gt=0)
    exception_date: date
    exception_type: str = Field(default="cancel", pattern="^(cancel|move)$")
    target_date: date | None = None
    target_start_time: time | None = None
    target_end_time: time | None = None
    allow_overlap: bool = False
    note: str | None = None


class TimetableRuleExceptionUpdateIn(BaseModel):
    exception_date: date | None = None
    target_date: date | None = None
    target_start_time: time | None = None
    target_end_time: time | None = None
    allow_overlap: bool | None = None
    note: str | None = None


class TimetableRuleExceptionOut(BaseModel):
    id: int
    class_id: int
    rule_id: int
    exception_date: date
    exception_type: str
    target_date: date | None = None
    target_start_time: time | None = None
    target_end_time: time | None = None
    note: str | None = None
    created_at: datetime


class TimetableImportApplyRowOut(BaseModel):
    row_index: int
    class_name: str | None = None
    class_id: int | None = None
    action: str
    issues: list[str] = Field(default_factory=list)


class TimetableImportApplyOut(BaseModel):
    mode: str
    effective_from: date
    effective_to: date | None = None
    total_rows: int
    valid_rows: int
    invalid_rows: int
    planned_apply_rows: int
    applied_rows: int
    skipped_duplicate_rows: int
    skipped_unresolved_rows: int
    created_classes_count: int
    unresolved_class_names: list[str] = Field(default_factory=list)
    rows: list[TimetableImportApplyRowOut] = Field(default_factory=list)


class ClassSetupStudentIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    student_code: str | None = Field(default=None, max_length=64)
    external_id: str | None = Field(default=None, max_length=64)
    birth_date: date | None = None


class ClassSetupTimetableRowIn(BaseModel):
    weekday: int = Field(ge=1, le=7)
    start_time: time
    end_time: time
    subject: str | None = Field(default=None, max_length=255)
    room: str | None = Field(default=None, max_length=120)
    group: str | None = Field(default=None, max_length=120)
    teacher_key: str | None = Field(default=None, max_length=255)


class ClassSetupInitIn(BaseModel):
    class_id: int | None = Field(default=None, gt=0)
    class_name: str | None = Field(default=None, min_length=1, max_length=255)
    subject: str | None = Field(default=None, max_length=255)
    level: str | None = Field(default=None, max_length=120)
    student_mode: str = Field(default="append_new", pattern="^(append_new|replace_all|ignore)$")
    students: list[ClassSetupStudentIn] = Field(default_factory=list)
    timetable_mode: str = Field(default="replace_future_from_date", pattern="^(append_new_slots|replace_future_from_date|ignore)$")
    effective_from: date | None = None
    effective_to: date | None = None
    timetable_rows: list[ClassSetupTimetableRowIn] = Field(default_factory=list)


class ClassSetupInitOut(BaseModel):
    class_id: int
    class_name: str
    created_class: bool = False
    students_created: int = 0
    students_updated: int = 0
    students_skipped: int = 0
    students_total: int = 0
    timetable_total_rows: int = 0
    timetable_applied_rows: int = 0
    timetable_skipped_duplicates: int = 0
    timetable_replaced_existing_count: int = 0
    effective_from: date | None = None
    effective_to: date | None = None


class TimetableVersionCreateIn(BaseModel):
    label: str | None = Field(default=None, max_length=160)
    source: str | None = Field(default=None, max_length=64)


class TimetableVersionRuleOut(BaseModel):
    weekday: int
    weekday_label: str | None = None
    start_time: str
    end_time: str
    subject: str | None = None
    room: str | None = None
    group: str | None = None
    teacher_key: str | None = None
    effective_from: date
    effective_to: date | None = None
    source: str | None = None


class TimetableVersionExceptionOut(BaseModel):
    exception_date: date
    exception_type: str
    target_date: date | None = None
    target_start_time: time | None = None
    target_end_time: time | None = None
    note: str | None = None
    rule: TimetableVersionRuleOut


class TimetableVersionOut(BaseModel):
    id: int
    class_id: int
    label: str | None = None
    source: str | None = None
    is_active: bool = False
    rules_count: int = 0
    exceptions_count: int = 0
    created_by_user_id: int | None = None
    activated_at: datetime | None = None
    created_at: datetime


class TimetableVersionDetailOut(TimetableVersionOut):
    rules: list[TimetableVersionRuleOut] = Field(default_factory=list)
    exceptions: list[TimetableVersionExceptionOut] = Field(default_factory=list)


class TimetableVersionCompareOut(BaseModel):
    version_id: int
    class_id: int
    snapshot_rules_count: int = 0
    snapshot_exceptions_count: int = 0
    current_rules_count: int = 0
    current_exceptions_count: int = 0
    snapshot_only_rules_count: int = 0
    current_only_rules_count: int = 0
    snapshot_only_exceptions_count: int = 0
    current_only_exceptions_count: int = 0
    snapshot_only_rules: list[TimetableVersionRuleOut] = Field(default_factory=list)
    current_only_rules: list[TimetableVersionRuleOut] = Field(default_factory=list)
    snapshot_only_exceptions: list[TimetableVersionExceptionOut] = Field(default_factory=list)
    current_only_exceptions: list[TimetableVersionExceptionOut] = Field(default_factory=list)


class TimetableVersionRestoreOut(BaseModel):
    version_id: int
    class_id: int
    restored_rules_count: int
    restored_exceptions_count: int
    removed_rules_count: int
    removed_exceptions_count: int
    active_version_id: int


class WorkflowSessionStartIn(BaseModel):
    absent_student_ids: list[int] = Field(default_factory=list)


class WorkflowCalendarSessionCreateIn(BaseModel):
    session_date: date
    start_time: time | None = None
    end_time: time | None = None
    note: str | None = None
    unit_id: int | None = None
    absent_student_ids: list[int] = Field(default_factory=list)
    allow_on_holiday: bool = False


class WorkflowCalendarSlotActionIn(BaseModel):
    action: str = Field(pattern="^(new_unit_session|continue_unit_session)$")
    session_date: date
    start_time: time | None = None
    end_time: time | None = None
    note: str | None = None
    absent_student_ids: list[int] = Field(default_factory=list)
    checked_item_ids: list[int] = Field(default_factory=list)
    unit_id: int | None = None
    unit_type: WorkflowUnitType | None = None
    unit_title: str | None = None
    planned_hours: float | None = None
    source_text: str | None = None
    allow_on_holiday: bool = False


class WorkflowSessionEndIn(BaseModel):
    session_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    absent_student_ids: list[int] | None = None
    note: str | None = None


class WorkflowSessionEnsureNextOut(BaseModel):
    created: bool = False
    reason: str | None = None
    session: Optional["WorkflowSessionOut"] = None


class WorkflowSessionConfirmIn(BaseModel):
    auto_close_unit: bool = True
    create_progress_items: bool = True
    generate_session_writeup: bool = False


class WorkflowToggleItemIn(BaseModel):
    checked: bool


class WorkflowChecklistItemCreateIn(BaseModel):
    title: str
    item_kind: WorkflowChecklistItemKind = WorkflowChecklistItemKind.OTHER
    parent_item_id: int | None = None


class WorkflowChecklistItemUpdateIn(BaseModel):
    title: str | None = None
    item_kind: WorkflowChecklistItemKind | None = None


class WorkflowChecklistReorderItemIn(BaseModel):
    id: int
    parent_item_id: int | None = None
    position: int = 0


class WorkflowChecklistReorderIn(BaseModel):
    items: list[WorkflowChecklistReorderItemIn] = Field(default_factory=list, min_length=1)


class WorkflowChecklistItemOut(BaseModel):
    id: int
    unit_id: int
    parent_item_id: int | None
    item_kind: WorkflowChecklistItemKind
    title: str
    position: int
    depth: int
    is_completed: bool
    completed_session_id: int | None
    completed_at: datetime | None
    children: list["WorkflowChecklistItemOut"] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class WorkflowUnitOut(BaseModel):
    id: int
    class_id: int
    exam_id: int | None = None
    unit_type: WorkflowUnitType
    status: WorkflowUnitStatus
    title: str
    planned_hours: float | None
    document_name: str | None
    created_at: datetime
    closed_at: datetime | None
    progress_total: int = 0
    progress_done: int = 0
    extraction_source: str | None = None
    extraction_model: str | None = None
    extraction_status: str | None = None
    extraction_error: str | None = None
    extraction_reviewed: bool = True
    extraction_reviewed_at: datetime | None = None
    checklist: list[WorkflowChecklistItemOut] = Field(default_factory=list)


class WorkflowExamLinkedUnitCreateIn(BaseModel):
    unit_type: WorkflowUnitType
    title: str | None = Field(default=None, max_length=255)


class WorkflowExamLinkedUnitCreateOut(BaseModel):
    created: bool = True
    unit: WorkflowUnitOut


class WorkflowUnitDeleteOut(BaseModel):
    deleted_unit_id: int
    deleted_sessions_count: int = 0
    deleted_upload_files_count: int = 0
    deleted_document_file: bool = False


class WorkflowSessionOut(BaseModel):
    id: int
    class_id: int
    unit_id: int | None
    unit_session_number: int | None = None
    session_date: date
    start_time: time | None
    end_time: time | None
    note: str | None
    absent_count: int = 0
    absent_student_ids: list[int] = Field(default_factory=list)
    checked_items_count: int = 0
    checked_item_ids: list[int] = Field(default_factory=list)
    checked_item_paths: list[list[str]] = Field(default_factory=list)
    checked_section_paths: list[list[str]] = Field(default_factory=list)
    has_saved_writeup: bool = False

    model_config = {"from_attributes": True}


class WorkflowUnitBlueprintOut(BaseModel):
    id: int
    unit_id: int
    provider: str
    model: str | None = None
    status: str
    requested_session_count: int | None = None
    document_hash: str | None = None
    source_text_excerpt: str | None = None
    blueprint_json: dict
    unit_map_json: dict | None = None
    content_blocks_json: list[dict] | None = None
    raw_provider_response: dict | None = None
    error_message: str | None = None
    reviewed: bool = False
    reviewed_at: datetime | None = None
    reviewed_by_user_id: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WorkflowSessionWriteupOut(BaseModel):
    id: int
    session_id: int
    unit_id: int | None = None
    provider: str
    model: str | None = None
    status: str
    title: str | None = None
    checked_item_ids: list[int] = Field(default_factory=list)
    checked_item_titles: list[str] = Field(default_factory=list)
    learning_focus: list[str] = Field(default_factory=list)
    teaching_content: list[str] = Field(default_factory=list)
    practice_items: list[str] = Field(default_factory=list)
    teacher_note_snapshot: str | None = None
    source_payload: dict | None = None
    raw_provider_response: dict | None = None
    error_message: str | None = None
    approved: bool = True
    created_at: datetime
    updated_at: datetime


class WorkflowSessionWriteupGenerateIn(BaseModel):
    regenerate: bool = True


class WorkflowSessionWriteupImportAssistantIn(BaseModel):
    artifact_id: int


class WorkflowSessionWriteupUpdateIn(BaseModel):
    title: str | None = None
    learning_focus: list[str] | None = None
    teaching_content: list[str] | None = None
    practice_items: list[str] | None = None
    approved: bool | None = None


class WorkflowUnitExtractionReviewIn(BaseModel):
    reviewed: bool = True


class WorkflowUnitAssistantIn(BaseModel):
    section_title: str | None = None
    section_path: list[str] | None = None
    action: str | None = None
    teacher_request: str | None = None


class WorkflowUnitAssistantOut(BaseModel):
    provider: str
    requested_provider: str
    model: str | None = None
    status: str
    section_title: str | None = None
    section_path: list[str] = Field(default_factory=list)
    action: str | None = None
    title: str | None = None
    answer_rows: list[str] = Field(default_factory=list)
    suggested_followups: list[str] = Field(default_factory=list)
    source_payload: dict | None = None
    raw_provider_response: dict | None = None
    error_message: str | None = None


class WorkflowUnitAssistantArtifactSaveIn(BaseModel):
    artifact_kind: str = Field(pattern="^(teacher_notes|guided_practice|quick_quiz_draft)$")
    provider: str = "notebooklm"
    model: str | None = None
    section_title: str | None = None
    section_path: list[str] | None = None
    action: str | None = None
    title: str | None = None
    answer_rows: list[str] = Field(default_factory=list)
    suggested_followups: list[str] = Field(default_factory=list)
    source_payload: dict | None = None
    raw_provider_response: dict | None = None


class WorkflowUnitAssistantArtifactOut(BaseModel):
    id: int
    unit_id: int
    artifact_kind: str
    provider: str
    model: str | None = None
    section_title: str | None = None
    section_path: list[str] = Field(default_factory=list)
    action: str | None = None
    title: str | None = None
    content_markdown: str | None = None
    source_payload: dict | None = None
    raw_provider_response: dict | None = None
    created_by_user_id: int | None = None
    created_at: datetime
    updated_at: datetime


class WorkflowUnitMaterialGenerateIn(BaseModel):
    material_type: str = Field(
        default="study_guide",
        pattern="^(study_guide|formative_quiz|mastery_quiz_hard|revision_flashcards|presenter_slides|detailed_slides|concept_infographic|teacher_prep_audio)$",
    )


class WorkflowUnitMaterialOut(BaseModel):
    id: int
    unit_id: int
    material_type: str
    provider: str
    model: str | None = None
    status: str
    title: str | None = None
    notebook_artifact_id: str | None = None
    source_payload: dict | None = None
    content_markdown: str | None = None
    file_name: str | None = None
    file_content_type: str | None = None
    raw_provider_response: dict | None = None
    error_message: str | None = None
    created_by_user_id: int | None = None
    created_at: datetime
    updated_at: datetime


class WorkflowSessionConfirmOut(BaseModel):
    session: WorkflowSessionOut
    checked_items_count: int = 0
    progress_items_created: int = 0
    unit_closed: bool = False
    unit_id: int | None = None
    remaining_items_count: int = 0
    writeup_generated: bool = False


class WorkflowCalendarEventOut(BaseModel):
    session_id: int
    class_id: int
    unit_id: int | None
    unit_session_number: int | None = None
    unit_title: str | None
    unit_type: WorkflowUnitType | None
    session_date: date
    start_time: time | None
    end_time: time | None
    absent_count: int
    absent_student_ids: list[int] = Field(default_factory=list)
    checked_items_count: int
    checked_items: list[str] = Field(default_factory=list)
    checked_item_ids: list[int] = Field(default_factory=list)
    checked_item_paths: list[list[str]] = Field(default_factory=list)
    checked_section_paths: list[list[str]] = Field(default_factory=list)
    note: str | None = None


class WorkflowWorkspaceOut(BaseModel):
    class_id: int
    active_unit: WorkflowUnitOut | None = None
    closed_units: list[WorkflowUnitOut] = Field(default_factory=list)
    active_session: WorkflowSessionOut | None = None
    recent_sessions: list[WorkflowSessionOut] = Field(default_factory=list)


class WorkflowCalendarSlotActionOut(BaseModel):
    unit: WorkflowUnitOut | None = None
    session: WorkflowSessionOut


class WorkflowCalendarAutoPlanIn(BaseModel):
    action: str = Field(pattern="^(load_week_plan|plan_unit)$")
    week_start: date | None = None
    start_date: date | None = None
    session_count: int | None = Field(default=None, ge=1, le=120)
    dry_run: bool = False
    skip_blocked_holidays: bool = True
    max_search_days: int | None = Field(default=None, ge=28, le=730)
    plan_mode: str | None = Field(default=None, pattern="^(new_unit|continue_unit)$")
    unit_type: WorkflowUnitType | None = None
    unit_title: str | None = None
    planned_hours: float | None = None
    source_text: str | None = None


class WorkflowCalendarPlannedSlotOut(BaseModel):
    session_date: date
    start_time: time | None = None
    end_time: time | None = None
    note: str | None = None
    subject: str | None = None
    room: str | None = None
    group_name: str | None = None
    moved_from_date: date | None = None


class WorkflowCalendarAutoPlanOut(BaseModel):
    action: str
    requested_count: int
    planned_count: int = 0
    created_count: int
    failed_count: int = 0
    search_end_date: date | None = None
    skipped_holiday_count: int = 0
    skipped_existing_count: int = 0
    skipped_exception_count: int = 0
    skipped_duplicate_count: int = 0
    target_unit_id: int | None = None
    target_unit_title: str | None = None
    planned_slots: list[WorkflowCalendarPlannedSlotOut] = Field(default_factory=list)
    created_sessions: list[WorkflowSessionOut] = Field(default_factory=list)


WorkflowChecklistItemOut.model_rebuild()
WorkflowSessionEnsureNextOut.model_rebuild()


class WorkflowLeafContentSummaryOut(BaseModel):
    id: int
    checklist_item_id: int
    status: str
    reviewed: bool = False
    updated_at: datetime
    provider: str

    model_config = {"from_attributes": True}


class WorkflowLeafContentOut(BaseModel):
    id: int
    unit_id: int
    checklist_item_id: int
    item_path_json: list | None = None
    section_path_json: list | None = None
    provider: str
    model: str | None = None
    status: str
    reviewed: bool = False
    reviewed_at: datetime | None = None
    reviewed_by_user_id: int | None = None
    teaching_goal_md: str | None = None
    launch_activity_md: str | None = None
    explanation_md: str | None = None
    worked_example_md: str | None = None
    practice_md: str | None = None
    solution_md: str | None = None
    assessment_md: str | None = None
    teacher_notes_md: str | None = None
    source_excerpt_md: str | None = None
    source_payload_json: dict | None = None
    raw_provider_response_json: dict | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WorkflowLeafContentUpsertIn(BaseModel):
    item_path: list[str] | None = None
    section_path: list[str] | None = None
    provider: str | None = None
    model: str | None = None
    status: str | None = None
    teaching_goal_md: str | None = None
    launch_activity_md: str | None = None
    explanation_md: str | None = None
    worked_example_md: str | None = None
    practice_md: str | None = None
    solution_md: str | None = None
    assessment_md: str | None = None
    teacher_notes_md: str | None = None
    source_excerpt_md: str | None = None
    source_payload: dict | None = None
    raw_provider_response: dict | None = None


class WorkflowLeafContentGenerateIn(BaseModel):
    provider: str | None = None
    regenerate: bool = True
    merge_strategy: str = "fill_missing"


class WorkflowLeafContentGenerateOut(BaseModel):
    requested_provider: str
    provider: str
    status: str
    leaf_content: WorkflowLeafContentOut


class WorkflowSectionLessonRequestIn(BaseModel):
    section_path: list[str] = Field(default_factory=list)
    item_path: list[str] = Field(default_factory=list)
    item_title: str | None = None


class WorkflowSectionLessonBlockOut(BaseModel):
    title: str | None = None
    kind: str
    kind_label: str
    teaching_phase: str | None = None
    content_md: str
    content_source: str


class WorkflowSectionLessonOut(BaseModel):
    section_title: str
    section_path_json: list[str] = Field(default_factory=list)
    item_path_json: list[str] = Field(default_factory=list)
    item_title: str | None = None
    source_block_count: int = 0
    source_blocks: list[WorkflowSectionLessonBlockOut] = Field(default_factory=list)
    source_excerpt_md: str | None = None


class WorkflowPreparedSectionPrepareIn(BaseModel):
    section_path: list[str] = Field(default_factory=list)


class WorkflowPreparedSectionSummaryOut(BaseModel):
    id: int
    unit_id: int
    section_key: str
    section_title: str
    section_path_json: list[str] = Field(default_factory=list)
    order_index: int = 0
    status: str
    benchmark_status: str = "pending"
    error_message: str | None = None
    source_block_count: int = 0
    provider: str
    updated_at: datetime

    model_config = {"from_attributes": True}


class WorkflowPreparedSectionOut(BaseModel):
    id: int
    unit_id: int
    section_key: str
    section_title: str
    section_path_json: list[str] = Field(default_factory=list)
    order_index: int = 0
    source_blocks_json: list[WorkflowSectionLessonBlockOut] = Field(default_factory=list)
    source_excerpt_md: str | None = None
    latex_source: str | None = None
    provider: str
    model: str | None = None
    status: str
    benchmark_status: str = "pending"
    benchmark_notes_md: str | None = None
    raw_provider_response_json: dict | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


