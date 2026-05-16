from io import BytesIO
import json
import os
import sys
from tempfile import NamedTemporaryFile
import types
import uuid

from openpyxl import Workbook, load_workbook
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


def _build_roster_file(rows: list[tuple[str, str]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(("student_code", "full_name"))
    for row in rows:
        sheet.append(row)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def _build_exam_file(rows: list[tuple[str, str, float, str, str]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(("student_code", "full_name", "score", "note", "teacher_comment"))
    for row in rows:
        sheet.append(row)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def _build_notescc_exam_file(rows: list[tuple[str, str, float]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "NotesCC"
    for idx, (code, name, score) in enumerate(rows, start=18):
        sheet.cell(idx, 3).value = code
        sheet.cell(idx, 4).value = name
        sheet.cell(idx, 7).value = score
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def _build_notescc_list_file(rows: list[tuple[str, str, str, str]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "NotesCC"
    sheet.cell(16, 2).value = "ID"
    sheet.cell(16, 3).value = "student_code"
    sheet.cell(16, 4).value = "name"
    sheet.cell(16, 6).value = "birth_date"
    for idx, (external_id, code, name, birth_date) in enumerate(rows, start=18):
        sheet.cell(idx, 2).value = external_id
        sheet.cell(idx, 3).value = code
        sheet.cell(idx, 4).value = name
        sheet.cell(idx, 6).value = birth_date
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def _build_exam_list_file(rows: list[tuple[str, str, str, float, float, float, float]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(("id", "name", "birth_date", "note_1", "note_2", "note_3", "note"))
    for row in rows:
        sheet.append(row)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def _build_holiday_file(headers: tuple[str, ...], rows: list[tuple]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "holiday_import"
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def _build_pdf_file(lines: list[str]) -> bytes:
    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=A4)
    _, page_height = A4
    y = page_height - 48
    for line in lines:
        pdf.drawString(42, y, line)
        y -= 18
        if y < 48:
            pdf.showPage()
            y = page_height - 48
    pdf.save()
    return output.getvalue()


def _build_timetable_csv(rows: list[tuple[str, str, str, str, str, str, str, str]]) -> bytes:
    lines = ["teacher_key,class_name,subject,weekday,start_time,end_time,room,group"]
    for row in rows:
        lines.append(",".join(row))
    return ("\n".join(lines) + "\n").encode("utf-8")


def _build_timetable_ics(events: list[dict]) -> bytes:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Teacher Progress//Tests//EN",
    ]
    for event in events:
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"SUMMARY:{event.get('summary', '')}",
                f"DTSTART:{event.get('dtstart', '')}",
                f"DTEND:{event.get('dtend', '')}",
            ]
        )
        if event.get("rrule"):
            lines.append(f"RRULE:{event.get('rrule')}")
        if event.get("location"):
            lines.append(f"LOCATION:{event.get('location')}")
        if event.get("description"):
            lines.append(f"DESCRIPTION:{event.get('description')}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def _flatten_checklist(nodes: list[dict]) -> list[dict]:
    output: list[dict] = []
    for node in nodes:
        output.append(node)
        output.extend(_flatten_checklist(node.get("children", [])))
    return output


def _auth_headers(client) -> dict[str, str]:
    owner_payload = {"email": "owner@app.local", "password": "OwnerPass123", "full_name": "Owner"}
    bootstrap_resp = client.post("/auth/bootstrap-owner", json=owner_payload)
    assert bootstrap_resp.status_code in (201, 400)
    login_resp = client.post("/auth/login", json={"email": owner_payload["email"], "password": owner_payload["password"]})
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _login_headers(client, email: str, password: str) -> dict[str, str]:
    login_resp = client.post("/auth/login", json={"email": email, "password": password})
    assert login_resp.status_code == 200
    return {"Authorization": f"Bearer {login_resp.json()['access_token']}"}


def _create_teacher_and_login(client, owner_headers: dict[str, str]) -> tuple[int, dict[str, str]]:
    email = f"teacher_{uuid.uuid4().hex[:8]}@app.local"
    password = "TeacherPass123"
    create_resp = client.post(
        "/auth/users",
        headers=owner_headers,
        json={"email": email, "password": password, "full_name": "Teacher", "role": "teacher"},
    )
    assert create_resp.status_code == 201
    teacher_id = create_resp.json()["id"]
    login_resp = client.post("/auth/login", json={"email": email, "password": password})
    assert login_resp.status_code == 200
    return teacher_id, {"Authorization": f"Bearer {login_resp.json()['access_token']}"}


def test_heuristic_extract_supports_compact_numbered_and_french_keywords():
    from app.services.extraction import _heuristic_extract

    raw_text = (
        "Chapitre2: Calcul litteral - Identites remarquables\n"
        "1.Developpement par la distributivite\n"
        "Propriete: Developper un produit.\n"
        "Exemples: Calculs de demonstration.\n"
        "Application: Developper et simplifier.\n"
        "2.Developpement a l'aide des identites remarquables\n"
        "Exercice 1: Resoudre l'equation.\n"
    )
    extracted = _heuristic_extract(raw_text)
    assert any(item.startswith("Chapitre2") for item in extracted["lesson_headings"])
    assert "1.Developpement par la distributivite" in extracted["lesson_headings"]
    assert any("2.Developpement" in item for item in extracted["lesson_headings"])
    assert len(extracted["activities"]) >= 2
    assert len(extracted["exercises"]) >= 1


def test_extract_structured_progress_falls_back_when_openai_returns_empty(monkeypatch):
    from app.services import extraction

    def fake_openai(raw_text, image_path=None):
        return (
            {
                "confidence": 0.92,
                "lesson_headings": [],
                "activities": [],
                "exercises": [],
                "raw_text": raw_text,
                "provider": "openai",
                "model": "gpt-fake",
                "fallback_reason": None,
            },
            None,
        )

    monkeypatch.setattr(extraction, "_openai_extract", fake_openai)
    parsed = extraction.extract_structured_progress(
        "1.Developpement par la distributivite\nExercice 1: factoriser"
    )
    assert parsed["provider"] == "heuristic"
    assert parsed["fallback_reason"] == "openai_empty_result"
    assert parsed["lesson_headings"]
    assert parsed["exercises"]


def test_resolve_raw_text_uses_best_ocr_candidate(monkeypatch):
    from PIL import Image
    from app.services import extraction

    with NamedTemporaryFile(suffix=".png", delete=False) as temp:
        temp_path = temp.name
    try:
        image = Image.new("RGB", (120, 40), color="white")
        image.save(temp_path)

        fake_module = types.SimpleNamespace()
        fake_module.Output = types.SimpleNamespace(DICT="dict")

        def fake_image_to_string(_image, lang=None, config=""):
            if config == "--psm 4":
                return "1.Developpement par la distributivite\nExercice 1: factoriser"
            return "blurry noise"

        def fake_image_to_data(_image, lang=None, config="", output_type=None):
            if config == "--psm 4":
                return {"conf": ["88", "84"], "text": ["1.Developpement", "Exercice"]}
            return {"conf": ["12"], "text": ["noise"]}

        fake_module.image_to_string = fake_image_to_string
        fake_module.image_to_data = fake_image_to_data
        monkeypatch.setitem(sys.modules, "pytesseract", fake_module)

        text = extraction.resolve_raw_text(temp_path, None)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

    assert "1.Developpement" in text
    assert "Exercice 1" in text


def test_sanitize_result_reclassifies_and_cleans_lines():
    from app.services.extraction import _sanitize_result

    parsed = _sanitize_result(
        {
            "confidence": 0.8,
            "lesson_headings": ["  1.2 Equations  ", "• Exercice 2 page 44"],
            "activities": ["\u25aa Propriete: distributivite"],
            "exercises": [],
        },
        "raw",
        provider="openai",
        model="gpt-fake",
    )
    assert "1.2 Equations" in parsed["lesson_headings"]
    assert any("Exercice 2 page 44" in row for row in parsed["exercises"])
    assert any("Propriete: distributivite" in row for row in parsed["activities"])


def test_extract_structured_progress_augments_openai_with_heuristic(monkeypatch):
    from app.services import extraction

    def fake_openai(raw_text, image_path=None):
        return (
            {
                "confidence": 0.61,
                "lesson_headings": ["Chapitre 2: Calcul litteral"],
                "activities": [],
                "exercises": [],
                "raw_text": raw_text,
                "provider": "openai",
                "model": "gpt-fake",
                "fallback_reason": None,
            },
            None,
        )

    monkeypatch.setattr(extraction, "_openai_extract", fake_openai)
    raw_text = (
        "1.1 Developpement par la distributivite\n"
        "Propriete: k(a+b)=ka+kb\n"
        "Exercice 1: simplifier\n"
    )
    parsed = extraction.extract_structured_progress(raw_text)
    assert parsed["provider"] == "openai"
    assert any("1.1" in row for row in parsed["lesson_headings"])
    assert any("Propriete" in row for row in parsed["activities"])
    assert any("Exercice 1" in row for row in parsed["exercises"])
    assert parsed["fallback_reason"] == "openai_augmented_with_heuristic"


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_workflow_unit_session_lifecycle(client):
    headers = _auth_headers(client)
    class_resp = client.post("/classes", json={"name": "Workflow 2APIC", "subject": "Math", "level": "2APIC"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = class_resp.json()["id"]

    roster = _build_roster_file([("STD001", "Alice"), ("STD002", "Bob")])
    import_resp = client.post(
        f"/classes/{class_id}/students/import",
        headers=headers,
        files={"file": ("students.xlsx", roster, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert import_resp.status_code == 200
    students = client.get(f"/classes/{class_id}/students", headers=headers).json()
    assert len(students) == 2

    source_text_lines = [
        "Chapitre 1: Calcul litteral",
        "1.1 Developpement",
        "Propriete: distributivite",
        "Exemples: simplifier",
        "2. Identites remarquables",
        "Definition: (a+b)^2",
    ]
    source_pdf = _build_pdf_file(source_text_lines)
    start_unit_resp = client.post(
        f"/workflow/classes/{class_id}/units/start",
        headers=headers,
        data={"unit_type": "chapter", "title": "Chapitre 1", "planned_hours": "6"},
        files={"file": ("chapter.pdf", source_pdf, "application/pdf")},
    )
    assert start_unit_resp.status_code == 201
    unit = start_unit_resp.json()
    assert unit["status"] == "active"
    assert unit["unit_type"] == "chapter"
    assert unit["progress_total"] >= 1

    workspace_resp = client.get(f"/workflow/classes/{class_id}", headers=headers)
    assert workspace_resp.status_code == 200
    workspace = workspace_resp.json()
    assert workspace["active_unit"]["id"] == unit["id"]
    assert workspace["active_session"] is None

    parent_item_id = workspace["active_unit"]["checklist"][0]["id"]
    add_item_resp = client.post(
        f"/workflow/classes/{class_id}/units/{unit['id']}/items",
        headers=headers,
        json={"title": "3.1 Revision guidee", "item_kind": "exercise", "parent_item_id": parent_item_id},
    )
    assert add_item_resp.status_code == 201
    added_item = add_item_resp.json()
    assert added_item["unit_id"] == unit["id"]
    assert added_item["title"] == "3.1 Revision guidee"
    assert added_item["item_kind"] == "exercise"
    assert added_item["parent_item_id"] == parent_item_id

    update_item_resp = client.put(
        f"/workflow/classes/{class_id}/units/{unit['id']}/items/{added_item['id']}",
        headers=headers,
        json={"title": "3.1 Revision guidee (updated)", "item_kind": "example"},
    )
    assert update_item_resp.status_code == 200
    updated_item = update_item_resp.json()
    assert updated_item["title"] == "3.1 Revision guidee (updated)"
    assert updated_item["item_kind"] == "example"

    delete_item_resp = client.delete(
        f"/workflow/classes/{class_id}/units/{unit['id']}/items/{added_item['id']}",
        headers=headers,
    )
    assert delete_item_resp.status_code == 200
    assert delete_item_resp.json()["deleted"] is True

    absent_ids = [students[0]["id"]]
    start_session_resp = client.post(
        f"/workflow/classes/{class_id}/sessions/start",
        headers=headers,
        json={"absent_student_ids": absent_ids},
    )
    assert start_session_resp.status_code == 201
    session = start_session_resp.json()
    session_id = session["id"]
    assert session["absent_count"] == 1
    assert sorted(session["absent_student_ids"]) == sorted(absent_ids)
    assert session["unit_session_number"] == 1

    item_id = workspace["active_unit"]["checklist"][0]["id"]
    toggle_resp = client.post(
        f"/workflow/classes/{class_id}/sessions/{session_id}/items/{item_id}/toggle",
        headers=headers,
        json={"checked": True},
    )
    assert toggle_resp.status_code == 200
    assert toggle_resp.json()["is_completed"] is True

    # Forward-only checklist flow: unchecking is blocked even while session is open.
    toggle_uncheck_open_resp = client.post(
        f"/workflow/classes/{class_id}/sessions/{session_id}/items/{item_id}/toggle",
        headers=headers,
        json={"checked": False},
    )
    assert toggle_uncheck_open_resp.status_code == 409

    end_session_resp = client.post(
        f"/workflow/classes/{class_id}/sessions/{session_id}/end",
        headers=headers,
        json={
            "session_date": "2026-03-03",
            "start_time": "08:00:00",
            "end_time": "10:00:00",
            "absent_student_ids": absent_ids,
            "note": "Session complete",
        },
    )
    assert end_session_resp.status_code == 200
    assert end_session_resp.json()["end_time"] == "10:00:00"

    toggle_closed_resp = client.post(
        f"/workflow/classes/{class_id}/sessions/{session_id}/items/{item_id}/toggle",
        headers=headers,
        json={"checked": False},
    )
    assert toggle_closed_resp.status_code == 409

    keep_end_time_resp = client.post(
        f"/workflow/classes/{class_id}/sessions/{session_id}/end",
        headers=headers,
        json={"note": "Session note only update"},
    )
    assert keep_end_time_resp.status_code == 200
    assert keep_end_time_resp.json()["end_time"] == "10:00:00"

    # Past sessions remain editable.
    edit_past_resp = client.post(
        f"/workflow/classes/{class_id}/sessions/{session_id}/end",
        headers=headers,
        json={"note": "Session edited after save", "end_time": "10:30:00"},
    )
    assert edit_past_resp.status_code == 200
    assert edit_past_resp.json()["end_time"] == "10:30:00"

    # Multiple sessions on same day are allowed.
    second_session_resp = client.post(
        f"/workflow/classes/{class_id}/sessions/start",
        headers=headers,
        json={"absent_student_ids": []},
    )
    assert second_session_resp.status_code == 201
    assert second_session_resp.json()["unit_session_number"] == 2

    unit_sessions_resp = client.get(f"/workflow/units/{unit['id']}/sessions", headers=headers)
    assert unit_sessions_resp.status_code == 200
    unit_sessions = unit_sessions_resp.json()
    assert len(unit_sessions) >= 2
    assert unit_sessions[0]["unit_id"] == unit["id"]
    assert unit_sessions[0]["unit_session_number"] == 1
    assert unit_sessions[1]["unit_session_number"] == 2
    assert unit_sessions[1]["end_time"] is None

    calendar_resp = client.get(f"/workflow/classes/{class_id}/calendar", headers=headers)
    assert calendar_resp.status_code == 200
    events = calendar_resp.json()
    assert len(events) >= 1
    assert events[0]["class_id"] == class_id
    session_event = next((row for row in events if row["session_id"] == session_id), None)
    assert session_event is not None
    assert sorted(session_event["absent_student_ids"]) == sorted(absent_ids)
    assert session_event["unit_session_number"] == 1
    calendar_export_resp = client.get(f"/workflow/classes/{class_id}/calendar/export.xlsx", headers=headers)
    assert calendar_export_resp.status_code == 200
    assert (
        calendar_export_resp.headers["content-type"]
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    export_workbook = load_workbook(filename=BytesIO(calendar_export_resp.content), data_only=True)
    export_sheet = export_workbook.active
    assert export_sheet.cell(1, 1).value == "session_id"
    assert export_sheet.cell(1, 2).value == "session_date"
    assert export_sheet.max_row >= 2
    export_session_ids = {
        int(value)
        for value in [export_sheet.cell(row, 1).value for row in range(2, export_sheet.max_row + 1)]
        if value is not None
    }
    assert session_id in export_session_ids
    calendar_pdf_resp = client.get(
        f"/workflow/classes/{class_id}/calendar/export.pdf?date_from=2026-01-01&date_to=2026-12-31",
        headers=headers,
    )
    assert calendar_pdf_resp.status_code == 200
    assert calendar_pdf_resp.headers["content-type"] == "application/pdf"
    assert len(calendar_pdf_resp.content or b"") > 100

    close_unit_resp = client.post(f"/workflow/classes/{class_id}/units/{unit['id']}/close", headers=headers)
    assert close_unit_resp.status_code == 409  # second session still open

    # End second session then close unit.
    second_id = second_session_resp.json()["id"]
    close_open_resp = client.post(
        f"/workflow/classes/{class_id}/sessions/{second_id}/end",
        headers=headers,
        json={"end_time": "23:59:00"},
    )
    assert close_open_resp.status_code == 200
    close_unit_resp = client.post(f"/workflow/classes/{class_id}/units/{unit['id']}/close", headers=headers)
    assert close_unit_resp.status_code == 200
    assert close_unit_resp.json()["status"] == "closed"
    close_unit_again_resp = client.post(f"/workflow/classes/{class_id}/units/{unit['id']}/close", headers=headers)
    assert close_unit_again_resp.status_code == 409

    exam_correction_resp = client.post(
        f"/workflow/classes/{class_id}/units/start",
        headers=headers,
        data={"unit_type": "exam_correction", "title": "Correction CC1"},
    )
    assert exam_correction_resp.status_code == 201
    assert exam_correction_resp.json()["unit_type"] == "exam_correction"


def test_workflow_calendar_session_create_with_unit_and_absences(client):
    headers = _auth_headers(client)
    class_resp = client.post("/classes", json={"name": "Workflow Calendar Create", "subject": "Math"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = class_resp.json()["id"]

    roster = _build_roster_file([("STD110", "Mina"), ("STD111", "Hakim")])
    import_resp = client.post(
        f"/classes/{class_id}/students/import",
        headers=headers,
        files={"file": ("students.xlsx", roster, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert import_resp.status_code == 200
    students = client.get(f"/classes/{class_id}/students", headers=headers).json()
    assert len(students) == 2

    start_unit_resp = client.post(
        f"/workflow/classes/{class_id}/units/start",
        headers=headers,
        data={"unit_type": "chapter", "title": "Calendar Unit", "source_text": "Chapter seed"},
    )
    assert start_unit_resp.status_code == 201
    unit_id = int(start_unit_resp.json()["id"])

    absent_id = int(students[0]["id"])
    create_resp = client.post(
        f"/workflow/classes/{class_id}/sessions",
        headers=headers,
        json={
            "session_date": "2026-03-04",
            "start_time": "09:00:00",
            "end_time": "10:30:00",
            "note": "Calendar block",
            "unit_id": unit_id,
            "absent_student_ids": [absent_id],
        },
    )
    assert create_resp.status_code == 201
    session_payload = create_resp.json()
    session_id = int(session_payload["id"])
    assert session_payload["unit_id"] == unit_id
    assert session_payload["absent_count"] == 1
    assert sorted(session_payload["absent_student_ids"]) == [absent_id]
    assert session_payload["unit_session_number"] == 1

    detail_resp = client.get(f"/sessions/{session_id}", headers=headers)
    assert detail_resp.status_code == 200
    attendance = detail_resp.json()["attendance"]
    assert len(attendance) == 2
    absent_rows = [row for row in attendance if row["status"] == "absent"]
    assert len(absent_rows) == 1
    assert int(absent_rows[0]["student_id"]) == absent_id

    calendar_resp = client.get(f"/workflow/classes/{class_id}/calendar", headers=headers)
    assert calendar_resp.status_code == 200
    created_event = next((row for row in calendar_resp.json() if int(row["session_id"]) == session_id), None)
    assert created_event is not None
    assert int(created_event["unit_id"]) == unit_id
    assert created_event["unit_title"] == "Calendar Unit"
    assert sorted(created_event["absent_student_ids"]) == [absent_id]
    assert created_event["unit_session_number"] == 1

    invalid_unit_resp = client.post(
        f"/workflow/classes/{class_id}/sessions",
        headers=headers,
        json={"session_date": "2026-03-05", "unit_id": 999999},
    )
    assert invalid_unit_resp.status_code == 404

    invalid_absent_resp = client.post(
        f"/workflow/classes/{class_id}/sessions",
        headers=headers,
        json={"session_date": "2026-03-05", "absent_student_ids": [999999]},
    )
    assert invalid_absent_resp.status_code == 400
    assert "Unknown student ids" in str(invalid_absent_resp.json()["detail"])


def test_workflow_slot_actions_create_new_unit_and_continue(client):
    headers = _auth_headers(client)
    class_resp = client.post("/classes", json={"name": "Workflow Slot Actions", "subject": "Math"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = class_resp.json()["id"]

    roster = _build_roster_file([("STD210", "Sara"), ("STD211", "Nabil")])
    import_resp = client.post(
        f"/classes/{class_id}/students/import",
        headers=headers,
        files={"file": ("students.xlsx", roster, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert import_resp.status_code == 200

    new_unit_resp = client.post(
        f"/workflow/classes/{class_id}/slot-actions",
        headers=headers,
        json={
            "action": "new_unit_session",
            "session_date": "2026-03-04",
            "start_time": "08:00:00",
            "end_time": "09:00:00",
            "note": "First session from slot",
            "unit_type": "chapter",
            "unit_title": "Slot Unit",
            "planned_hours": 4,
            "source_text": "Chapter slot seed",
        },
    )
    assert new_unit_resp.status_code == 201
    new_unit_payload = new_unit_resp.json()
    assert new_unit_payload["unit"] is not None
    assert new_unit_payload["unit"]["title"] == "Slot Unit"
    assert new_unit_payload["session"]["unit_id"] == new_unit_payload["unit"]["id"]
    assert new_unit_payload["session"]["unit_session_number"] == 1
    checklist_rows = _flatten_checklist(new_unit_payload["unit"].get("checklist") or [])
    first_check_id = int(checklist_rows[0]["id"]) if checklist_rows else None

    continue_resp = client.post(
        f"/workflow/classes/{class_id}/slot-actions",
        headers=headers,
        json={
            "action": "continue_unit_session",
            "session_date": "2026-03-05",
            "start_time": "08:00:00",
            "end_time": "09:00:00",
            "unit_id": new_unit_payload["unit"]["id"],
            "checked_item_ids": [first_check_id] if first_check_id is not None else [],
        },
    )
    assert continue_resp.status_code == 201
    continue_payload = continue_resp.json()
    assert continue_payload["unit"] is None
    assert continue_payload["session"]["unit_id"] == new_unit_payload["unit"]["id"]
    assert continue_payload["session"]["unit_session_number"] == 2
    if first_check_id is not None:
        assert int(continue_payload["session"]["checked_items_count"]) >= 1
        workspace_resp = client.get(f"/workflow/classes/{class_id}", headers=headers)
        assert workspace_resp.status_code == 200
        workspace_payload = workspace_resp.json()
        assert workspace_payload.get("active_unit") is not None
        assert int(workspace_payload["active_unit"]["progress_done"]) >= 1

    invalid_new_unit_resp = client.post(
        f"/workflow/classes/{class_id}/slot-actions",
        headers=headers,
        json={
            "action": "new_unit_session",
            "session_date": "2026-03-06",
            "start_time": "08:00:00",
            "end_time": "09:00:00",
            "unit_title": "Missing type",
        },
    )
    assert invalid_new_unit_resp.status_code == 400


def test_workflow_auto_plan_week_and_unit(client):
    headers = _auth_headers(client)
    class_name = f"AUTO-PLAN-{uuid.uuid4().hex[:6]}"
    class_resp = client.post("/classes", json={"name": class_name, "subject": "Math"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = int(class_resp.json()["id"])

    roster = _build_roster_file([("STD500", "A"), ("STD501", "B")])
    import_resp = client.post(
        f"/classes/{class_id}/students/import",
        headers=headers,
        files={"file": ("students.xlsx", roster, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert import_resp.status_code == 200

    csv_content = _build_timetable_csv(
        [
            ("owner@school.edu", class_name, "Math", "Monday", "08:00", "09:00", "R12", "G1"),
            ("owner@school.edu", class_name, "Math", "Wednesday", "10:00", "11:00", "R12", "G1"),
        ]
    )
    apply_resp = client.post(
        "/workflow/timetable/import/apply",
        headers=headers,
        data={
            "mode": "append_new_slots",
            "effective_from": "2026-09-01",
            "create_missing_classes": "false",
        },
        files={"file": ("emploi.csv", csv_content, "text/csv")},
    )
    assert apply_resp.status_code == 200
    assert int(apply_resp.json()["applied_rows"]) >= 2

    existing_resp = client.post(
        f"/workflow/classes/{class_id}/sessions",
        headers=headers,
        json={
            "session_date": "2026-09-07",
            "start_time": "08:00:00",
            "end_time": "09:00:00",
            "note": "Existing manual session",
        },
    )
    assert existing_resp.status_code == 201

    week_plan_resp = client.post(
        f"/workflow/classes/{class_id}/auto-plan",
        headers=headers,
        json={
            "action": "load_week_plan",
            "week_start": "2026-09-07",
        },
    )
    assert week_plan_resp.status_code == 200
    week_payload = week_plan_resp.json()
    assert week_payload["action"] == "load_week_plan"
    assert int(week_payload["created_count"]) >= 1
    assert int(week_payload["skipped_existing_count"]) >= 1
    assert all(row["unit_id"] is None for row in (week_payload.get("created_sessions") or []))

    plan_unit_resp = client.post(
        f"/workflow/classes/{class_id}/auto-plan",
        headers=headers,
        json={
            "action": "plan_unit",
            "plan_mode": "new_unit",
            "start_date": "2026-09-08",
            "session_count": 3,
            "unit_type": "chapter",
            "unit_title": "Auto Planned Unit",
            "source_text": "Auto Planned Unit",
        },
    )
    assert plan_unit_resp.status_code == 200
    unit_payload = plan_unit_resp.json()
    assert unit_payload["action"] == "plan_unit"
    assert int(unit_payload["requested_count"]) == 3
    assert int(unit_payload["created_count"]) >= 1
    assert unit_payload["target_unit_id"] is not None
    created_rows = unit_payload.get("created_sessions") or []
    assert len(created_rows) == int(unit_payload["created_count"])
    assert all(int(row["unit_id"]) == int(unit_payload["target_unit_id"]) for row in created_rows)
    unit_numbers = [int(row["unit_session_number"]) for row in created_rows if row.get("unit_session_number") is not None]
    assert unit_numbers == sorted(unit_numbers)


def test_workflow_auto_plan_unit_skips_holidays_and_jumps_forward(client):
    headers = _auth_headers(client)
    class_name = f"AUTO-PLAN-HOL-{uuid.uuid4().hex[:6]}"
    class_resp = client.post("/classes", json={"name": class_name, "subject": "Math"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = int(class_resp.json()["id"])

    roster = _build_roster_file([("STD900", "A"), ("STD901", "B")])
    import_resp = client.post(
        f"/classes/{class_id}/students/import",
        headers=headers,
        files={"file": ("students.xlsx", roster, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert import_resp.status_code == 200

    csv_content = _build_timetable_csv(
        [
            ("owner@school.edu", class_name, "Math", "Wednesday", "08:00", "09:00", "R12", "G1"),
        ]
    )
    apply_resp = client.post(
        "/workflow/timetable/import/apply",
        headers=headers,
        data={
            "mode": "append_new_slots",
            "effective_from": "2026-09-01",
            "create_missing_classes": "false",
        },
        files={"file": ("emploi.csv", csv_content, "text/csv")},
    )
    assert apply_resp.status_code == 200
    assert int(apply_resp.json()["applied_rows"]) >= 1

    auto_plan_resp = client.post(
        f"/workflow/classes/{class_id}/auto-plan",
        headers=headers,
        json={
            "action": "plan_unit",
            "plan_mode": "new_unit",
            "start_date": "2026-11-16",
            "session_count": 2,
            "unit_type": "exercise_series",
            "unit_title": "Series Auto Holiday",
            "source_text": "Series Auto Holiday",
        },
    )
    assert auto_plan_resp.status_code == 200
    payload = auto_plan_resp.json()
    assert int(payload["created_count"]) == 2
    assert int(payload["failed_count"]) == 0
    assert int(payload["skipped_holiday_count"]) >= 1
    created_dates = [str(row["session_date"]) for row in (payload.get("created_sessions") or [])]
    assert "2026-11-18" not in created_dates
    assert "2026-11-25" in created_dates
    assert "2026-12-02" in created_dates


def test_workflow_auto_plan_unit_dry_run_preview_does_not_create_data(client):
    headers = _auth_headers(client)
    class_name = f"AUTO-PLAN-DRY-{uuid.uuid4().hex[:6]}"
    class_resp = client.post("/classes", json={"name": class_name, "subject": "Math"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = int(class_resp.json()["id"])

    roster = _build_roster_file([("STD910", "A"), ("STD911", "B")])
    import_resp = client.post(
        f"/classes/{class_id}/students/import",
        headers=headers,
        files={"file": ("students.xlsx", roster, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert import_resp.status_code == 200

    csv_content = _build_timetable_csv(
        [
            ("owner@school.edu", class_name, "Math", "Monday", "08:00", "09:00", "R12", "G1"),
            ("owner@school.edu", class_name, "Math", "Wednesday", "10:00", "11:00", "R12", "G1"),
        ]
    )
    apply_resp = client.post(
        "/workflow/timetable/import/apply",
        headers=headers,
        data={
            "mode": "append_new_slots",
            "effective_from": "2026-09-01",
            "create_missing_classes": "false",
        },
        files={"file": ("emploi.csv", csv_content, "text/csv")},
    )
    assert apply_resp.status_code == 200
    assert int(apply_resp.json()["applied_rows"]) >= 2

    preview_resp = client.post(
        f"/workflow/classes/{class_id}/auto-plan",
        headers=headers,
        json={
            "action": "plan_unit",
            "dry_run": True,
            "plan_mode": "new_unit",
            "start_date": "2026-09-07",
            "session_count": 3,
            "unit_type": "exercise_series",
            "unit_title": "Dry Run Series",
            "source_text": "Dry Run Series",
        },
    )
    assert preview_resp.status_code == 200
    preview_payload = preview_resp.json()
    assert preview_payload["action"] == "plan_unit"
    assert preview_payload["created_count"] == 0
    assert int(preview_payload["planned_count"]) >= 1
    assert len(preview_payload.get("planned_slots") or []) == int(preview_payload["planned_count"])
    assert preview_payload["target_unit_id"] is None
    assert preview_payload["target_unit_title"] == "Dry Run Series"

    workspace_resp = client.get(f"/workflow/classes/{class_id}", headers=headers)
    assert workspace_resp.status_code == 200
    assert workspace_resp.json().get("active_unit") is None

    calendar_resp = client.get(f"/workflow/classes/{class_id}/calendar", headers=headers)
    assert calendar_resp.status_code == 200
    assert len(calendar_resp.json()) == 0


def test_workflow_auto_plan_new_unit_dry_run_respects_active_unit_conflict(client):
    headers = _auth_headers(client)
    class_name = f"AUTO-PLAN-CONFLICT-{uuid.uuid4().hex[:6]}"
    class_resp = client.post("/classes", json={"name": class_name, "subject": "Math"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = int(class_resp.json()["id"])

    roster = _build_roster_file([("STD920", "A"), ("STD921", "B")])
    import_resp = client.post(
        f"/classes/{class_id}/students/import",
        headers=headers,
        files={"file": ("students.xlsx", roster, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert import_resp.status_code == 200

    first_unit_resp = client.post(
        f"/workflow/classes/{class_id}/units/start",
        headers=headers,
        data={
            "unit_type": "exam",
            "title": "Existing Active Unit",
        },
    )
    assert first_unit_resp.status_code == 201

    dry_run_resp = client.post(
        f"/workflow/classes/{class_id}/auto-plan",
        headers=headers,
        json={
            "action": "plan_unit",
            "dry_run": True,
            "plan_mode": "new_unit",
            "start_date": "2026-09-07",
            "session_count": 2,
            "unit_type": "exercise_series",
            "unit_title": "Should Conflict",
            "source_text": "Should Conflict",
        },
    )
    assert dry_run_resp.status_code == 409
    assert "active unit already exists" in str(dry_run_resp.json()["detail"]).lower()


def test_workflow_class_setup_creates_class_students_and_timetable(client):
    headers = _auth_headers(client)
    setup_resp = client.post(
        "/workflow/class-setup",
        headers=headers,
        json={
            "class_name": f"SETUP-INIT-{uuid.uuid4().hex[:6]}",
            "subject": "Math",
            "level": "2BAC",
            "student_mode": "append_new",
            "students": [
                {"full_name": "Sara Zahra"},
                {"student_code": "STD900", "full_name": "Nabil Idrissi"},
            ],
            "timetable_mode": "replace_future_from_date",
            "effective_from": "2026-09-01",
            "timetable_rows": [
                {
                    "weekday": 1,
                    "start_time": "08:00:00",
                    "end_time": "09:00:00",
                    "subject": "Algebra",
                    "room": "R12",
                    "group": "A",
                },
                {
                    "weekday": 3,
                    "start_time": "10:00:00",
                    "end_time": "11:00:00",
                    "subject": "Geometry",
                    "room": "R12",
                    "group": "A",
                },
            ],
        },
    )
    assert setup_resp.status_code == 200
    payload = setup_resp.json()
    class_id = int(payload["class_id"])
    assert payload["created_class"] is True
    assert int(payload["students_created"]) == 2
    assert int(payload["students_total"]) == 2
    assert int(payload["timetable_applied_rows"]) == 2

    students_resp = client.get(f"/classes/{class_id}/students", headers=headers)
    assert students_resp.status_code == 200
    students = students_resp.json()
    assert len(students) == 2
    assert any(str(row["student_code"]).startswith("AUTO") for row in students)
    assert any(str(row["student_code"]) == "STD900" for row in students)

    rules_resp = client.get(f"/workflow/classes/{class_id}/timetable-rules", headers=headers)
    assert rules_resp.status_code == 200
    rules = rules_resp.json()
    assert len(rules) == 2
    assert all(str(row.get("source") or "") == "class-setup-form" for row in rules)


def test_workflow_class_setup_resubmits_timetable_on_existing_class(client):
    headers = _auth_headers(client)
    class_resp = client.post("/classes", json={"name": f"SETUP-RESUBMIT-{uuid.uuid4().hex[:6]}", "subject": "Math"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = int(class_resp.json()["id"])

    first_setup_resp = client.post(
        "/workflow/class-setup",
        headers=headers,
        json={
            "class_id": class_id,
            "student_mode": "ignore",
            "timetable_mode": "replace_future_from_date",
            "effective_from": "2026-09-01",
            "timetable_rows": [
                {
                    "weekday": 1,
                    "start_time": "08:00:00",
                    "end_time": "09:00:00",
                    "subject": "Algebra",
                    "room": "R10",
                    "group": "A",
                }
            ],
        },
    )
    assert first_setup_resp.status_code == 200
    assert int(first_setup_resp.json()["timetable_applied_rows"]) == 1

    second_setup_resp = client.post(
        "/workflow/class-setup",
        headers=headers,
        json={
            "class_id": class_id,
            "student_mode": "ignore",
            "timetable_mode": "replace_future_from_date",
            "effective_from": "2026-10-01",
            "timetable_rows": [
                {
                    "weekday": 4,
                    "start_time": "14:00:00",
                    "end_time": "15:00:00",
                    "subject": "Functions",
                    "room": "R10",
                    "group": "A",
                }
            ],
        },
    )
    assert second_setup_resp.status_code == 200
    second_payload = second_setup_resp.json()
    assert int(second_payload["timetable_applied_rows"]) == 1
    assert int(second_payload["timetable_replaced_existing_count"]) >= 1

    rules_resp = client.get(f"/workflow/classes/{class_id}/timetable-rules", headers=headers)
    assert rules_resp.status_code == 200
    rules = rules_resp.json()
    assert len(rules) == 2
    first_rule = next((row for row in rules if row["effective_from"] == "2026-09-01"), None)
    latest_rule = next((row for row in rules if row["effective_from"] == "2026-10-01"), None)
    assert first_rule is not None
    assert latest_rule is not None
    assert first_rule["effective_to"] == "2026-09-30"
    assert latest_rule["effective_to"] is None


def test_workflow_auto_setup_from_document_creates_sessions_and_checks_progress(client):
    headers = _auth_headers(client)
    class_name = f"DOC-AUTO-SETUP-{uuid.uuid4().hex[:6]}"
    class_resp = client.post("/classes", json={"name": class_name, "subject": "Math"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = int(class_resp.json()["id"])

    roster = _build_roster_file([("STD501", "Lina"), ("STD502", "Ayoub")])
    import_resp = client.post(
        f"/classes/{class_id}/students/import",
        headers=headers,
        files={"file": ("students.xlsx", roster, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert import_resp.status_code == 200

    csv_content = _build_timetable_csv(
        [
            ("owner@school.edu", class_name, "Math", "Monday", "08:00", "09:00", "R20", "A"),
            ("owner@school.edu", class_name, "Math", "Wednesday", "08:00", "09:00", "R20", "A"),
        ]
    )
    apply_resp = client.post(
        "/workflow/timetable/import/apply",
        headers=headers,
        data={
            "mode": "append_new_slots",
            "effective_from": "2026-09-01",
            "create_missing_classes": "false",
        },
        files={"file": ("emploi.csv", csv_content, "text/csv")},
    )
    assert apply_resp.status_code == 200
    assert int(apply_resp.json()["applied_rows"]) >= 2

    auto_setup_resp = client.post(
        f"/workflow/classes/{class_id}/auto-setup-from-doc",
        headers=headers,
        data={
            "unit_type": "chapter",
            "unit_title": "Fractions and Operations",
            "source_text": "Chapter Fractions\nDefinition of fraction\nEquivalent fractions\nSimplify fractions\nExercises",
            "start_date": "2026-09-07",
            "session_count": "2",
            "auto_check_items": "true",
        },
    )
    assert auto_setup_resp.status_code == 200
    payload = auto_setup_resp.json()
    assert payload["action"] == "plan_document_unit"
    assert int(payload["created_count"]) == 2
    assert int(payload["target_unit_id"]) > 0
    assert len(payload.get("created_sessions") or []) == 2
    assert sum(int(row.get("checked_items_count") or 0) for row in payload["created_sessions"]) >= 1

    workspace_resp = client.get(f"/workflow/classes/{class_id}", headers=headers)
    assert workspace_resp.status_code == 200
    workspace_payload = workspace_resp.json()
    active_unit = workspace_payload.get("active_unit")
    assert active_unit is not None
    assert int(active_unit.get("progress_done") or 0) >= 1


def test_workflow_auto_setup_from_document_fills_empty_sessions_with_exercises(client):
    headers = _auth_headers(client)
    class_name = f"DOC-AUTO-FILL-{uuid.uuid4().hex[:6]}"
    class_resp = client.post("/classes", json={"name": class_name, "subject": "Math"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = int(class_resp.json()["id"])

    roster = _build_roster_file([("STD601", "Sara"), ("STD602", "Yassine")])
    import_resp = client.post(
        f"/classes/{class_id}/students/import",
        headers=headers,
        files={"file": ("students.xlsx", roster, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert import_resp.status_code == 200

    csv_content = _build_timetable_csv(
        [
            ("owner@school.edu", class_name, "Math", "Monday", "08:00", "09:00", "R30", "A"),
            ("owner@school.edu", class_name, "Math", "Wednesday", "08:00", "09:00", "R30", "A"),
        ]
    )
    apply_resp = client.post(
        "/workflow/timetable/import/apply",
        headers=headers,
        data={
            "mode": "append_new_slots",
            "effective_from": "2026-09-01",
            "create_missing_classes": "false",
        },
        files={"file": ("emploi.csv", csv_content, "text/csv")},
    )
    assert apply_resp.status_code == 200
    assert int(apply_resp.json()["applied_rows"]) >= 2

    auto_setup_resp = client.post(
        f"/workflow/classes/{class_id}/auto-setup-from-doc",
        headers=headers,
        data={
            "unit_type": "chapter",
            "unit_title": "Very short chapter",
            "source_text": "Chapter tiny content",
            "start_date": "2026-09-07",
            "session_count": "4",
            "auto_check_items": "true",
        },
    )
    assert auto_setup_resp.status_code == 200
    payload = auto_setup_resp.json()
    assert payload["action"] == "plan_document_unit"
    assert int(payload["created_count"]) == 4
    created_sessions = payload.get("created_sessions") or []
    assert len(created_sessions) == 4
    assert all(int(row.get("checked_items_count") or 0) >= 1 for row in created_sessions)


def test_timetable_version_snapshot_compare_restore(client):
    headers = _auth_headers(client)
    class_name = f"TT-VERSION-{uuid.uuid4().hex[:6]}"
    class_resp = client.post("/classes", json={"name": class_name, "subject": "Math"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = int(class_resp.json()["id"])

    initial_csv = _build_timetable_csv(
        [
            ("owner@school.edu", class_name, "Math", "Monday", "08:00", "09:00", "R12", "G1"),
        ]
    )
    initial_apply_resp = client.post(
        "/workflow/timetable/import/apply",
        headers=headers,
        data={
            "mode": "append_new_slots",
            "effective_from": "2026-09-01",
            "create_missing_classes": "false",
        },
        files={"file": ("initial.csv", initial_csv, "text/csv")},
    )
    assert initial_apply_resp.status_code == 200
    assert int(initial_apply_resp.json()["applied_rows"]) >= 1

    snapshot_resp = client.post(
        f"/workflow/classes/{class_id}/timetable-versions",
        headers=headers,
        json={"label": "Baseline Snapshot", "source": "test"},
    )
    assert snapshot_resp.status_code == 201
    snapshot_payload = snapshot_resp.json()
    version_id = int(snapshot_payload["id"])
    assert snapshot_payload["is_active"] is True
    assert int(snapshot_payload["rules_count"]) >= 1

    replacement_csv = _build_timetable_csv(
        [
            ("owner@school.edu", class_name, "Math", "Tuesday", "10:00", "11:00", "R14", "G1"),
        ]
    )
    replace_apply_resp = client.post(
        "/workflow/timetable/import/apply",
        headers=headers,
        data={
            "mode": "replace_future_from_date",
            "effective_from": "2026-09-01",
            "create_missing_classes": "false",
        },
        files={"file": ("replacement.csv", replacement_csv, "text/csv")},
    )
    assert replace_apply_resp.status_code == 200
    assert int(replace_apply_resp.json()["applied_rows"]) >= 1

    compare_resp = client.get(
        f"/workflow/classes/{class_id}/timetable-versions/{version_id}/compare-current",
        headers=headers,
    )
    assert compare_resp.status_code == 200
    compare_payload = compare_resp.json()
    assert int(compare_payload["snapshot_only_rules_count"]) >= 1
    assert int(compare_payload["current_only_rules_count"]) >= 1

    restore_resp = client.post(
        f"/workflow/classes/{class_id}/timetable-versions/{version_id}/restore",
        headers=headers,
    )
    assert restore_resp.status_code == 200
    restore_payload = restore_resp.json()
    assert int(restore_payload["active_version_id"]) == version_id
    assert int(restore_payload["restored_rules_count"]) >= 1

    rules_resp = client.get(f"/workflow/classes/{class_id}/timetable-rules", headers=headers)
    assert rules_resp.status_code == 200
    restored_rules = rules_resp.json()
    assert any(int(row["weekday"]) == 1 and row["start_time"] == "08:00:00" for row in restored_rules)

    versions_resp = client.get(f"/workflow/classes/{class_id}/timetable-versions", headers=headers)
    assert versions_resp.status_code == 200
    versions_payload = versions_resp.json()
    active_versions = [row for row in versions_payload if row.get("is_active")]
    assert len(active_versions) == 1
    assert int(active_versions[0]["id"]) == version_id


def test_morocco_holidays_list_and_block_session_creation(client):
    headers = _auth_headers(client)
    class_resp = client.post("/classes", json={"name": "Holiday Block Class", "subject": "Math"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = class_resp.json()["id"]

    holidays_resp = client.get("/workflow/holidays", headers=headers, params={"year": 2026, "country_code": "MA"})
    assert holidays_resp.status_code == 200
    holidays_rows = holidays_resp.json()
    assert len(holidays_rows) >= 1
    independence_row = next((row for row in holidays_rows if row["holiday_date"] == "2026-11-18"), None)
    assert independence_row is not None
    assert independence_row["is_blocked"] is True

    blocked_generic_resp = client.post(
        f"/classes/{class_id}/sessions",
        headers=headers,
        json={"session_date": "2026-11-18", "start_time": "08:00:00", "end_time": "09:00:00"},
    )
    assert blocked_generic_resp.status_code == 409

    blocked_workflow_resp = client.post(
        f"/workflow/classes/{class_id}/sessions",
        headers=headers,
        json={"session_date": "2026-11-18", "start_time": "08:00:00", "end_time": "09:00:00"},
    )
    assert blocked_workflow_resp.status_code == 409

    override_workflow_resp = client.post(
        f"/workflow/classes/{class_id}/sessions",
        headers=headers,
        json={
            "session_date": "2026-11-18",
            "start_time": "08:00:00",
            "end_time": "09:00:00",
            "allow_on_holiday": True,
        },
    )
    assert override_workflow_resp.status_code == 201

    unblocked_resp = client.patch(
        f"/workflow/holidays/{independence_row['id']}",
        headers=headers,
        json={"is_blocked": False},
    )
    assert unblocked_resp.status_code == 200
    assert unblocked_resp.json()["is_blocked"] is False

    allowed_generic_resp = client.post(
        f"/classes/{class_id}/sessions",
        headers=headers,
        json={"session_date": "2026-11-18", "start_time": "10:00:00", "end_time": "11:00:00"},
    )
    assert allowed_generic_resp.status_code == 201


def test_morocco_academic_holidays_seed_exact_2025_2026_calendar(client):
    headers = _auth_headers(client)

    holidays_2025_resp = client.get("/workflow/holidays", headers=headers, params={"year": 2025, "country_code": "MA"})
    assert holidays_2025_resp.status_code == 200
    holidays_2025 = holidays_2025_resp.json()
    assert len(holidays_2025) == 28
    by_date_2025 = {row["holiday_date"]: row for row in holidays_2025}
    assert by_date_2025["2025-09-04"]["name"] == "Prophet's Birthday"
    assert by_date_2025["2025-10-19"]["name"] == "First Mid-Term Break"
    assert by_date_2025["2025-11-06"]["name"] == "Green March Anniversary"
    assert by_date_2025["2025-12-14"]["name"] == "Second Mid-Term Break"

    holidays_2026_resp = client.get("/workflow/holidays", headers=headers, params={"year": 2026, "country_code": "MA"})
    assert holidays_2026_resp.status_code == 200
    holidays_2026 = holidays_2026_resp.json()
    assert len(holidays_2026) == 38
    by_date_2026 = {row["holiday_date"]: row for row in holidays_2026}
    assert by_date_2026["2026-01-14"]["name"] == "Amazigh New Year (Yennayer)"
    assert by_date_2026["2026-03-18"]["name"] == "Third Mid-Term Break / Eid al-Fitr"
    assert by_date_2026["2026-05-27"]["name"] == "Eid al-Adha"
    assert by_date_2026["2026-06-16"]["name"] == "Islamic New Year (1 Muharram)"


def test_owner_can_download_holiday_template(client):
    headers = _auth_headers(client)

    response = client.get("/workflow/holidays/template.xlsx", headers=headers)
    assert response.status_code == 200
    assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in response.headers["content-type"]

    workbook = load_workbook(filename=BytesIO(response.content), data_only=True)
    assert "holiday_import" in workbook.sheetnames
    sheet = workbook["holiday_import"]
    header = [cell.value for cell in sheet[1]]
    assert header[:4] == ["holiday", "start_date", "end_date", "is_blocked"]
    first_row = [sheet.cell(2, idx).value for idx in range(1, 5)]
    assert first_row == ["Prophet's Birthday", "2025-09-04", "2025-09-05", True]


def test_owner_can_export_current_holidays_excel(client):
    headers = _auth_headers(client)

    response = client.get(
        "/workflow/holidays/export.xlsx",
        headers=headers,
        params={"year": 2026, "country_code": "MA"},
    )
    assert response.status_code == 200
    workbook = load_workbook(filename=BytesIO(response.content), data_only=True)
    assert "holiday_export" in workbook.sheetnames
    sheet = workbook["holiday_export"]
    header = [cell.value for cell in sheet[1]]
    assert header == ["holiday", "start_date", "end_date", "number_of_days", "is_blocked", "source"]
    rows = list(sheet.iter_rows(min_row=2, values_only=True))
    assert ("Mid-Year School Break", "2026-01-25", "2026-02-01", 8, True, "morocco-academic-2025-2026") in rows
    assert ("New Year's Day", "2026-01-01", "2026-01-01", 1, True, "morocco-fixed / morocco-academic-2025-2026") in rows


def test_owner_holiday_import_adds_to_standard_calendar_and_preserves_existing_custom_rows(client):
    headers = _auth_headers(client)

    first_import = _build_holiday_file(
        ("holiday", "dates", "number_of_days", "is_blocked"),
        [
            ("Green March Day", "November 6, 2025", 1, True),
        ],
    )

    first_import_resp = client.post(
        "/workflow/holidays/import",
        headers=headers,
        files={"file": ("holidays.xlsx", first_import, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert first_import_resp.status_code == 200
    first_payload = first_import_resp.json()
    assert first_payload["rows"] == 1
    assert first_payload["holiday_dates"] == 1
    assert first_payload["years"] == [2025]

    holidays_2025_resp = client.get("/workflow/holidays", headers=headers, params={"year": 2025, "country_code": "MA"})
    assert holidays_2025_resp.status_code == 200
    holidays_2025 = holidays_2025_resp.json()
    green_march_row = next((row for row in holidays_2025 if row["holiday_date"] == "2025-11-06"), None)
    prophet_row = next((row for row in holidays_2025 if row["holiday_date"] == "2025-09-04"), None)
    assert green_march_row is not None
    assert green_march_row["name"] == "Green March Day"
    assert "morocco-fixed" in str(green_march_row["source"] or "")
    assert "owner-academic-upload" in str(green_march_row["source"] or "")
    assert prophet_row is not None
    assert prophet_row["name"] == "Prophet's Birthday"

    second_import = _build_holiday_file(
        ("holiday", "start_date", "end_date", "is_blocked"),
        [
            ("School Open House", "2025-10-02", "2025-10-02", True),
        ],
    )
    second_import_resp = client.post(
        "/workflow/holidays/import",
        headers=headers,
        files={"file": ("holidays-update.xlsx", second_import, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert second_import_resp.status_code == 200
    second_payload = second_import_resp.json()
    assert second_payload["rows"] == 1
    assert second_payload["holiday_dates"] == 1
    assert second_payload["years"] == [2025]

    refreshed_2025_resp = client.get("/workflow/holidays", headers=headers, params={"year": 2025, "country_code": "MA"})
    assert refreshed_2025_resp.status_code == 200
    refreshed_2025 = refreshed_2025_resp.json()
    refreshed_green_march_row = next((row for row in refreshed_2025 if row["holiday_date"] == "2025-11-06"), None)
    open_house_row = next((row for row in refreshed_2025 if row["holiday_date"] == "2025-10-02"), None)
    assert refreshed_green_march_row is not None
    assert refreshed_green_march_row["name"] == "Green March Day"
    assert open_house_row is not None
    assert open_house_row["name"] == "School Open House"
    assert open_house_row["source"] == "owner-academic-upload"

    patch_resp = client.patch(
        f"/workflow/holidays/{open_house_row['id']}",
        headers=headers,
        json={"is_blocked": False},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["is_blocked"] is False

    final_2025_resp = client.get("/workflow/holidays", headers=headers, params={"year": 2025, "country_code": "MA"})
    assert final_2025_resp.status_code == 200
    final_2025 = final_2025_resp.json()
    final_open_house_row = next((row for row in final_2025 if row["holiday_date"] == "2025-10-02"), None)
    assert final_open_house_row is not None
    assert final_open_house_row["is_blocked"] is False


def test_workflow_unit_start_persists_blueprint(client):
    headers = _auth_headers(client)
    class_resp = client.post("/classes", json={"name": "Blueprint Class", "subject": "Math"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = class_resp.json()["id"]

    unit_resp = client.post(
        f"/workflow/classes/{class_id}/units/start",
        headers=headers,
        data={
            "unit_type": "chapter",
            "title": "Factorisation",
            "source_text": (
                "1.3 Factorisation\n"
                "1.3.2 Factorisation a l'aide des identites remarquables\n"
                "Propriete: Utiliser les identites remarquables.\n"
                "Exemple: Factoriser une expression simple.\n"
            ),
        },
    )
    assert unit_resp.status_code == 201
    unit_id = unit_resp.json()["id"]

    blueprint_resp = client.get(f"/workflow/classes/{class_id}/units/{unit_id}/blueprint", headers=headers)
    assert blueprint_resp.status_code == 200
    blueprint = blueprint_resp.json()
    assert blueprint["unit_id"] == unit_id
    assert blueprint["status"] == "ready"
    assert blueprint["blueprint_json"]["unit_title"] == "Factorisation"
    assert isinstance(blueprint["blueprint_json"]["items"], list)
    assert len(blueprint["blueprint_json"]["items"]) >= 1


def test_workflow_confirm_can_generate_saved_session_writeup(client):
    headers = _auth_headers(client)
    class_resp = client.post("/classes", json={"name": "Writeup Class", "subject": "Math"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = class_resp.json()["id"]

    roster_content = _build_roster_file([("A1", "Student One")])
    roster_resp = client.post(
        f"/classes/{class_id}/students/import",
        headers=headers,
        files={"file": ("roster.xlsx", roster_content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert roster_resp.status_code == 200

    unit_resp = client.post(
        f"/workflow/classes/{class_id}/units/start",
        headers=headers,
        data={
            "unit_type": "chapter",
            "title": "Identites remarquables",
            "source_text": (
                "1. Identites remarquables\n"
                "1.1 Somme et difference\n"
                "Propriete: Reconnaitre une identite remarquable.\n"
                "Exemple: a2-b2.\n"
                "Application: Exercices de factorisation.\n"
            ),
        },
    )
    assert unit_resp.status_code == 201

    start_session_resp = client.post(
        f"/workflow/classes/{class_id}/sessions/start",
        headers=headers,
        json={"absent_student_ids": []},
    )
    assert start_session_resp.status_code == 201
    session_id = start_session_resp.json()["id"]

    confirm_resp = client.post(
        f"/workflow/classes/{class_id}/sessions/{session_id}/confirm",
        headers=headers,
        json={"generate_session_writeup": True},
    )
    assert confirm_resp.status_code == 200
    confirm_payload = confirm_resp.json()
    assert confirm_payload["writeup_generated"] is True
    assert confirm_payload["session"]["has_saved_writeup"] is True

    writeup_resp = client.get(
        f"/workflow/classes/{class_id}/sessions/{session_id}/writeup",
        headers=headers,
    )
    assert writeup_resp.status_code == 200
    writeup = writeup_resp.json()
    assert writeup["status"] == "ready"
    assert writeup["provider"] in {"fallback", "openai"}
    assert len(writeup["learning_focus"]) >= 1
    assert len(writeup["teaching_content"]) >= 1
    assert len(writeup["practice_items"]) >= 1


def test_workflow_blueprint_records_requested_provider_when_falling_back(client, monkeypatch):
    from app import config as app_config

    monkeypatch.setattr(app_config, "UNIT_PLANNER_PROVIDER", "notebooklm")
    headers = _auth_headers(client)
    class_resp = client.post("/classes", json={"name": "Blueprint Provider Class", "subject": "Math"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = class_resp.json()["id"]

    unit_resp = client.post(
        f"/workflow/classes/{class_id}/units/start",
        headers=headers,
        data={
            "unit_type": "chapter",
            "title": "Calcul litteral",
            "source_text": "1. Developpement\n1.1 Distributivite\nPropriete: k(a+b)=ka+kb\n",
        },
    )
    assert unit_resp.status_code == 201
    unit_id = unit_resp.json()["id"]

    blueprint_resp = client.get(f"/workflow/classes/{class_id}/units/{unit_id}/blueprint", headers=headers)
    assert blueprint_resp.status_code == 200
    blueprint = blueprint_resp.json()
    assert blueprint["provider"] == "fallback"
    assert blueprint["raw_provider_response"]["requested_provider"] == "notebooklm"
    assert blueprint["raw_provider_response"]["error_message"] == "notebooklm_client_unavailable"


def test_workflow_writeup_records_requested_provider_when_falling_back(client, monkeypatch):
    from app import config as app_config

    monkeypatch.setattr(app_config, "SESSION_WRITER_PROVIDER", "notebooklm")
    headers = _auth_headers(client)
    class_resp = client.post("/classes", json={"name": "Writeup Provider Class", "subject": "Math"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = class_resp.json()["id"]

    roster_content = _build_roster_file([("A1", "Student One")])
    roster_resp = client.post(
        f"/classes/{class_id}/students/import",
        headers=headers,
        files={"file": ("roster.xlsx", roster_content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert roster_resp.status_code == 200

    unit_resp = client.post(
        f"/workflow/classes/{class_id}/units/start",
        headers=headers,
        data={
            "unit_type": "chapter",
            "title": "Factorisation",
            "source_text": "1. Factorisation\n1.1 Mise en facteur commun\nApplication: Exercices de base\n",
        },
    )
    assert unit_resp.status_code == 201

    start_session_resp = client.post(
        f"/workflow/classes/{class_id}/sessions/start",
        headers=headers,
        json={"absent_student_ids": []},
    )
    assert start_session_resp.status_code == 201
    session_id = start_session_resp.json()["id"]

    writeup_resp = client.post(
        f"/workflow/classes/{class_id}/sessions/{session_id}/writeup/generate",
        headers=headers,
        json={"regenerate": True},
    )
    assert writeup_resp.status_code == 200
    writeup = writeup_resp.json()
    assert writeup["provider"] == "fallback"
    assert writeup["source_payload"]["requested_provider"] == "notebooklm"
    assert writeup["source_payload"]["provider_used"] == "fallback"


def test_workflow_writeup_can_be_edited_after_generation(client):
    headers = _auth_headers(client)
    class_resp = client.post("/classes", json={"name": "Writeup Edit Class", "subject": "Math"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = class_resp.json()["id"]

    roster_content = _build_roster_file([("A1", "Student One")])
    roster_resp = client.post(
        f"/classes/{class_id}/students/import",
        headers=headers,
        files={"file": ("roster.xlsx", roster_content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert roster_resp.status_code == 200

    unit_resp = client.post(
        f"/workflow/classes/{class_id}/units/start",
        headers=headers,
        data={
            "unit_type": "chapter",
            "title": "Theoreme de Pythagore",
            "source_text": "1. Theoreme de Pythagore\n1.1 Enonce\nExemple: Triangle rectangle\nApplication: Exercices directs\n",
        },
    )
    assert unit_resp.status_code == 201

    start_session_resp = client.post(
        f"/workflow/classes/{class_id}/sessions/start",
        headers=headers,
        json={"absent_student_ids": []},
    )
    assert start_session_resp.status_code == 201
    session_id = start_session_resp.json()["id"]

    generate_resp = client.post(
        f"/workflow/classes/{class_id}/sessions/{session_id}/writeup/generate",
        headers=headers,
        json={"regenerate": True},
    )
    assert generate_resp.status_code == 200

    update_resp = client.patch(
        f"/workflow/classes/{class_id}/sessions/{session_id}/writeup",
        headers=headers,
        json={
            "title": "Seance 1 - Pythagore en triangle rectangle",
            "learning_focus": ["Enoncer le theoreme", "Identifier le cote oppose a l'angle droit"],
            "teaching_content": [
                "La seance a introduit le theoreme de Pythagore dans le cas du triangle rectangle.",
                "Les eleves ont applique la relation a des exemples simples avant un entrainement guide.",
            ],
            "practice_items": ["Exercices directs sur le calcul d'une longueur"],
            "approved": False,
        },
    )
    assert update_resp.status_code == 200
    updated = update_resp.json()
    assert updated["title"] == "Seance 1 - Pythagore en triangle rectangle"
    assert updated["learning_focus"][0] == "Enoncer le theoreme"
    assert updated["practice_items"] == ["Exercices directs sur le calcul d'une longueur"]
    assert updated["approved"] is False


def test_owner_can_read_notebooklm_status(client):
    headers = _auth_headers(client)
    resp = client.get('/ops/notebooklm/status', headers=headers)
    assert resp.status_code == 200
    payload = resp.json()
    assert "installed" in payload
    assert "ready" in payload
    assert "auth_path" in payload
    assert "profile" in payload


def test_owner_can_upload_and_clear_notebooklm_auth_file(client, monkeypatch, tmp_path):
    import app.routers.ops as ops_router

    auth_path = tmp_path / "notebooklm" / "profiles" / "default" / "storage_state.json"
    monkeypatch.setattr(ops_router, "NOTEBOOKLM_AUTH_PATH", str(auth_path))
    headers = _auth_headers(client)

    upload_resp = client.post(
        '/ops/notebooklm/auth/upload',
        headers=headers,
        files={"file": ("storage_state.json", b'{"cookies": [], "origins": []}', "application/json")},
    )
    assert upload_resp.status_code == 200
    payload = upload_resp.json()
    assert payload["auth_file_exists"] is True
    assert payload["auth_file_valid"] is True
    assert auth_path.exists() is True

    clear_resp = client.post('/ops/notebooklm/auth/clear', headers=headers)
    assert clear_resp.status_code == 200
    cleared = clear_resp.json()
    assert cleared["auth_file_exists"] is False
    assert auth_path.exists() is False


def test_checklist_postprocess_splits_verbose_extraction_items():
    from app.models import WorkflowUnitType
    from app.services import workflow_generation

    raw_items = [
        {
            "title": "introduction-aux-nombres-rationnels-cours-ma",
            "kind": "chapter",
            "children": [
                {
                    "title": (
                        "Chapitre1:Introduction des nombres rationnels Nombre rationnel 1: "
                        "Définition Un nombre rationnel est un nombre qui peut s'exprimer sous la forme "
                        "du quotient de deux nombres entiers. 2.Exemples les nombres 7-3 et 7/3. "
                        "3.Remarques: Tout nombre entier relatif est un nombre rationnel."
                    ),
                    "kind": "example",
                    "children": [],
                }
            ],
        }
    ]

    normalized = workflow_generation._postprocess_checklist_items(
        raw_items,
        unit_type=WorkflowUnitType.CHAPTER,
        unit_title="introduction-aux-nombres-rationnels-cours-ma",
    )

    assert normalized
    titles = [str(item["title"]) for item in normalized]
    assert titles[0] != "introduction-aux-nombres-rationnels-cours-ma"
    assert any("Definition" in title for title in titles)
    assert any("Exemples" in title for title in titles)
    assert any("Remarques" in title for title in titles)
    assert all(len(title) <= 120 for title in titles)


def test_notebooklm_prompt_omits_noisy_source_hint_when_pdf_is_attached():
    from app.models import WorkflowUnitType
    from app.services import workflow_generation

    prompt = workflow_generation._build_notebooklm_checklist_prompt(
        unit_type=WorkflowUnitType.CHAPTER,
        title="Nombres rationnels",
        source_hint="",
        session_count=6,
    )

    assert "Indice textuel de secours" not in prompt
    assert "jamais des paragraphes complets" in prompt
    assert "moins de 90 caracteres" in prompt


def test_unit_creation_replaces_slug_title_with_first_meaningful_generated_heading(client, monkeypatch):
    import app.routers.workflow as workflow_router

    headers = _auth_headers(client)
    class_resp = client.post("/classes", json={"name": "Slug Title Class", "subject": "Math"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = class_resp.json()["id"]

    monkeypatch.setattr(
        workflow_router,
        "generate_unit_checklist",
        lambda **kwargs: {
            "source": "notebooklm",
            "requested_provider": "notebooklm",
            "model": "notebooklm-py",
            "status": "ready",
            "items": [
                {
                    "title": "Chapitre 1: Introduction des nombres rationnels",
                    "kind": "chapter",
                    "children": [
                        {"title": "Definition - Nombre rationnel", "kind": "definition", "children": []},
                    ],
                }
            ],
            "raw_provider_response": {"answer": "{}"},
            "error_message": None,
            "provider_context": None,
        },
    )

    unit_resp = client.post(
        f"/workflow/classes/{class_id}/units/start",
        headers=headers,
        data={
            "unit_type": "chapter",
            "title": "introduction-aux-nombres-rationnels-cours-ma",
            "source_text": "dummy source",
        },
    )

    assert unit_resp.status_code == 201
    payload = unit_resp.json()
    assert payload["title"] == "Chapitre 1: Introduction des nombres rationnels"


def test_workflow_notebooklm_provider_persists_context_and_writeup(client, monkeypatch):
    from app import config as app_config
    from app.services import workflow_generation

    monkeypatch.setattr(app_config, "UNIT_PLANNER_PROVIDER", "notebooklm")
    monkeypatch.setattr(app_config, "SESSION_WRITER_PROVIDER", "notebooklm")

    monkeypatch.setattr(
        workflow_generation,
        "_notebooklm_generate_checklist",
        lambda **kwargs: (
            [
                {
                    "title": "1. Factorisation",
                    "kind": "chapter",
                    "children": [
                        {"title": "1.1 Mise en facteur commun", "kind": "section", "children": [], "session_number": 1},
                        {"title": "1.2 Exercices d'application", "kind": "exercise", "children": [], "session_number": 2},
                    ],
                }
            ],
            {
                "provider": "notebooklm",
                "notebook_id": "nb-unit-1",
                "source_ids": ["src-1"],
                "notebook_title": "Teacher Progress - Factorisation",
            },
            {"answer": "{\"items\": []}"},
            None,
        ),
    )
    monkeypatch.setattr(
        workflow_generation,
        "_notebooklm_generate_session_writeup",
        lambda **kwargs: {
            "provider": "notebooklm",
            "requested_provider": "notebooklm",
            "model": "notebooklm-py",
            "status": "ready",
            "title": "Seance 1 - Mise en facteur commun",
            "checked_item_ids": kwargs["checked_item_ids"],
            "checked_item_titles": kwargs["checked_item_titles"],
            "learning_focus": ["Reconnaître un facteur commun."],
            "teaching_content": ["La seance a introduit la mise en facteur commun avec des exemples progressifs."],
            "practice_items": ["Exercices d'application sur des expressions algebriques."],
            "teacher_note_snapshot": kwargs["note_text"] or None,
            "raw_provider_response": {"answer": "{\"title\":\"ok\"}"},
            "error_message": None,
        },
    )

    headers = _auth_headers(client)
    class_resp = client.post("/classes", json={"name": "NotebookLM Class", "subject": "Math"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = class_resp.json()["id"]

    roster_content = _build_roster_file([("A1", "Student One")])
    roster_resp = client.post(
        f"/classes/{class_id}/students/import",
        headers=headers,
        files={"file": ("roster.xlsx", roster_content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert roster_resp.status_code == 200

    unit_resp = client.post(
        f"/workflow/classes/{class_id}/units/start",
        headers=headers,
        data={
            "unit_type": "chapter",
            "title": "Factorisation",
            "source_text": "1. Factorisation\n1.1 Mise en facteur commun\n1.2 Exercices d'application\n",
        },
    )
    assert unit_resp.status_code == 201
    unit_id = unit_resp.json()["id"]

    blueprint_resp = client.get(f"/workflow/classes/{class_id}/units/{unit_id}/blueprint", headers=headers)
    assert blueprint_resp.status_code == 200
    blueprint = blueprint_resp.json()
    assert blueprint["provider"] == "notebooklm"
    assert blueprint["blueprint_json"]["provider_context"]["notebook_id"] == "nb-unit-1"

    start_session_resp = client.post(
        f"/workflow/classes/{class_id}/sessions/start",
        headers=headers,
        json={"absent_student_ids": []},
    )
    assert start_session_resp.status_code == 201
    session_id = start_session_resp.json()["id"]

    writeup_resp = client.post(
        f"/workflow/classes/{class_id}/sessions/{session_id}/writeup/generate",
        headers=headers,
        json={"regenerate": True},
    )
    assert writeup_resp.status_code == 200
    writeup = writeup_resp.json()
    assert writeup["provider"] == "notebooklm"
    assert writeup["title"] == "Seance 1 - Mise en facteur commun"
    assert writeup["learning_focus"] == ["Reconnaître un facteur commun."]


def test_timetable_import_preview_csv(client):
    headers = _auth_headers(client)
    csv_content = _build_timetable_csv(
        [
            ("owner@school.edu", "2APIC-1", "Math", "Monday", "08:00", "09:00", "R12", "G1"),
            ("owner@school.edu", "2APIC-2", "Math", "Friday", "10:30", "09:30", "R15", "G2"),
        ]
    )

    preview_resp = client.post(
        "/workflow/timetable/import/preview",
        headers=headers,
        files={"file": ("emploi.csv", csv_content, "text/csv")},
    )
    assert preview_resp.status_code == 200
    payload = preview_resp.json()
    assert payload["total_rows"] == 2
    assert payload["valid_rows"] == 1
    assert payload["invalid_rows"] == 1
    assert len(payload["rows"]) == 2
    assert payload["rows"][0]["is_valid"] is True
    assert payload["rows"][0]["weekday"] == 1
    assert payload["rows"][0]["start_time"] == "08:00:00"
    assert payload["rows"][1]["is_valid"] is False
    assert any("end_time" in issue for issue in payload["rows"][1]["issues"])


def test_timetable_import_preview_ics(client):
    headers = _auth_headers(client)
    ics_content = _build_timetable_ics(
        [
            {
                "summary": "2APIC-1 | Math",
                "dtstart": "20260907T080000",
                "dtend": "20260907T090000",
                "rrule": "FREQ=WEEKLY;BYDAY=MO,WE",
                "location": "R12",
                "description": "Group:G1",
            },
            {
                "summary": "2APIC-2 | Physics",
                "dtstart": "20260908T110000",
                "dtend": "20260908T103000",
                "location": "R15",
            },
        ]
    )

    preview_resp = client.post(
        "/workflow/timetable/import/preview",
        headers=headers,
        files={"file": ("emploi.ics", ics_content, "text/calendar")},
    )
    assert preview_resp.status_code == 200
    payload = preview_resp.json()
    assert payload["total_rows"] == 3
    assert payload["valid_rows"] == 2
    assert payload["invalid_rows"] == 1
    assert payload["rows"][0]["class_name"] == "2APIC-1"
    assert payload["rows"][0]["subject"] == "Math"
    assert payload["rows"][0]["weekday"] == 1
    assert payload["rows"][0]["room"] == "R12"
    assert payload["rows"][0]["group"] == "G1"
    assert payload["rows"][1]["weekday"] == 3
    assert payload["rows"][2]["is_valid"] is False
    assert any("end_time" in issue for issue in payload["rows"][2]["issues"])


def test_timetable_import_apply_append_and_replace(client):
    headers = _auth_headers(client)
    existing_class_resp = client.post(
        "/classes",
        json={"name": "2APIC-1", "subject": "Math"},
        headers=headers,
    )
    assert existing_class_resp.status_code == 201
    existing_class_id = existing_class_resp.json()["id"]

    csv_content = _build_timetable_csv(
        [
            ("owner@school.edu", "2APIC-1", "Math", "Monday", "08:00", "09:00", "R12", "G1"),
            ("owner@school.edu", "2APIC-2", "Math", "Tuesday", "10:00", "11:00", "R15", "G2"),
        ]
    )

    dry_run_resp = client.post(
        "/workflow/timetable/import/apply",
        headers=headers,
        data={
            "mode": "dry_run_only",
            "effective_from": "2026-09-01",
            "create_missing_classes": "false",
        },
        files={"file": ("emploi.csv", csv_content, "text/csv")},
    )
    assert dry_run_resp.status_code == 200
    dry_run_payload = dry_run_resp.json()
    assert dry_run_payload["planned_apply_rows"] == 1
    assert dry_run_payload["applied_rows"] == 0
    assert "2APIC-2" in dry_run_payload["unresolved_class_names"]

    append_resp = client.post(
        "/workflow/timetable/import/apply",
        headers=headers,
        data={
            "mode": "append_new_slots",
            "effective_from": "2026-09-01",
            "create_missing_classes": "true",
        },
        files={"file": ("emploi.csv", csv_content, "text/csv")},
    )
    assert append_resp.status_code == 200
    append_payload = append_resp.json()
    assert append_payload["applied_rows"] == 2
    assert append_payload["created_classes_count"] == 1

    append_again_resp = client.post(
        "/workflow/timetable/import/apply",
        headers=headers,
        data={
            "mode": "append_new_slots",
            "effective_from": "2026-09-01",
            "create_missing_classes": "false",
        },
        files={"file": ("emploi.csv", csv_content, "text/csv")},
    )
    assert append_again_resp.status_code == 200
    append_again_payload = append_again_resp.json()
    assert append_again_payload["applied_rows"] == 0
    assert append_again_payload["skipped_duplicate_rows"] == 2

    rules_existing_resp = client.get(f"/workflow/classes/{existing_class_id}/timetable-rules", headers=headers)
    assert rules_existing_resp.status_code == 200
    rules_existing = rules_existing_resp.json()
    assert len(rules_existing) == 1
    assert rules_existing[0]["start_time"] == "08:00:00"

    classes_resp = client.get("/classes", headers=headers)
    assert classes_resp.status_code == 200
    created_class = next((row for row in classes_resp.json() if row["name"] == "2APIC-2"), None)
    assert created_class is not None
    created_class_id = int(created_class["id"])

    replace_csv = _build_timetable_csv(
        [
            ("owner@school.edu", "2APIC-1", "Math", "Monday", "11:00", "12:00", "R12", "G1"),
        ]
    )
    replace_resp = client.post(
        "/workflow/timetable/import/apply",
        headers=headers,
        data={
            "mode": "replace_future_from_date",
            "effective_from": "2026-09-01",
            "create_missing_classes": "false",
        },
        files={"file": ("emploi-replace.csv", replace_csv, "text/csv")},
    )
    assert replace_resp.status_code == 200
    assert replace_resp.json()["applied_rows"] == 1

    rules_existing_after_resp = client.get(f"/workflow/classes/{existing_class_id}/timetable-rules", headers=headers)
    assert rules_existing_after_resp.status_code == 200
    rules_existing_after = rules_existing_after_resp.json()
    assert len(rules_existing_after) == 1
    assert rules_existing_after[0]["start_time"] == "11:00:00"

    rules_created_resp = client.get(f"/workflow/classes/{created_class_id}/timetable-rules", headers=headers)
    assert rules_created_resp.status_code == 200
    rules_created = rules_created_resp.json()
    assert len(rules_created) == 1


def test_timetable_import_apply_ics(client):
    headers = _auth_headers(client)
    class_resp = client.post(
        "/classes",
        json={"name": "2APIC-1", "subject": "Math"},
        headers=headers,
    )
    assert class_resp.status_code == 201
    class_id = int(class_resp.json()["id"])

    ics_content = _build_timetable_ics(
        [
            {
                "summary": "2APIC-1 | Math",
                "dtstart": "20260907T080000",
                "dtend": "20260907T090000",
                "rrule": "FREQ=WEEKLY;BYDAY=MO",
                "location": "R12",
                "description": "Group:G1",
            },
        ]
    )

    apply_resp = client.post(
        "/workflow/timetable/import/apply",
        headers=headers,
        data={
            "mode": "append_new_slots",
            "effective_from": "2026-09-01",
            "create_missing_classes": "false",
        },
        files={"file": ("emploi.ics", ics_content, "text/calendar")},
    )
    assert apply_resp.status_code == 200
    payload = apply_resp.json()
    assert payload["applied_rows"] == 1
    assert payload["unresolved_class_names"] == []

    rules_resp = client.get(f"/workflow/classes/{class_id}/timetable-rules", headers=headers)
    assert rules_resp.status_code == 200
    rules = rules_resp.json()
    assert len(rules) == 1
    assert rules[0]["weekday"] == 1
    assert rules[0]["start_time"] == "08:00:00"
    assert rules[0]["end_time"] == "09:00:00"


def test_timetable_rule_exception_create_list_delete(client):
    headers = _auth_headers(client)
    class_name = f"2APIC-EXC-{uuid.uuid4().hex[:6]}"
    class_resp = client.post(
        "/classes",
        json={"name": class_name, "subject": "Math"},
        headers=headers,
    )
    assert class_resp.status_code == 201
    class_id = int(class_resp.json()["id"])

    csv_content = _build_timetable_csv(
        [
            ("owner@school.edu", class_name, "Math", "Monday", "08:00", "09:00", "R12", "G1"),
        ]
    )
    apply_resp = client.post(
        "/workflow/timetable/import/apply",
        headers=headers,
        data={
            "mode": "append_new_slots",
            "effective_from": "2026-09-01",
            "create_missing_classes": "false",
        },
        files={"file": ("emploi.csv", csv_content, "text/csv")},
    )
    assert apply_resp.status_code == 200
    assert apply_resp.json()["applied_rows"] == 1

    rules_resp = client.get(f"/workflow/classes/{class_id}/timetable-rules", headers=headers)
    assert rules_resp.status_code == 200
    rules = rules_resp.json()
    assert len(rules) == 1
    rule_id = int(rules[0]["id"])

    create_exception_resp = client.post(
        f"/workflow/classes/{class_id}/timetable-exceptions",
        headers=headers,
        json={
            "rule_id": rule_id,
            "exception_date": "2026-09-07",
            "exception_type": "cancel",
            "note": "Teacher absent",
        },
    )
    assert create_exception_resp.status_code == 201
    exception_row = create_exception_resp.json()
    assert int(exception_row["class_id"]) == class_id
    assert int(exception_row["rule_id"]) == rule_id
    assert exception_row["exception_type"] == "cancel"
    assert exception_row["exception_date"] == "2026-09-07"

    create_duplicate_resp = client.post(
        f"/workflow/classes/{class_id}/timetable-exceptions",
        headers=headers,
        json={
            "rule_id": rule_id,
            "exception_date": "2026-09-07",
            "exception_type": "cancel",
            "note": "Updated note",
        },
    )
    assert create_duplicate_resp.status_code == 201
    duplicate_row = create_duplicate_resp.json()
    assert int(duplicate_row["id"]) == int(exception_row["id"])
    assert duplicate_row["note"] == "Updated note"

    update_cancel_resp = client.patch(
        f"/workflow/timetable-exceptions/{exception_row['id']}",
        headers=headers,
        json={
            "exception_date": "2026-09-14",
            "note": "Updated by patch",
        },
    )
    assert update_cancel_resp.status_code == 200
    updated_cancel_row = update_cancel_resp.json()
    assert updated_cancel_row["exception_date"] == "2026-09-14"
    assert updated_cancel_row["note"] == "Updated by patch"

    list_resp = client.get(
        f"/workflow/classes/{class_id}/timetable-exceptions?date_from=2026-09-01&date_to=2026-09-30",
        headers=headers,
    )
    assert list_resp.status_code == 200
    rows = list_resp.json()
    assert len(rows) == 1
    assert int(rows[0]["id"]) == int(exception_row["id"])

    existing_session_resp = client.post(
        f"/workflow/classes/{class_id}/sessions",
        headers=headers,
        json={
            "session_date": "2026-09-10",
            "start_time": "12:00:00",
            "end_time": "13:00:00",
            "note": "Existing real session",
        },
    )
    assert existing_session_resp.status_code == 201

    move_exception_resp = client.post(
        f"/workflow/classes/{class_id}/timetable-exceptions",
        headers=headers,
        json={
            "rule_id": rule_id,
            "exception_date": "2026-10-05",
            "exception_type": "move",
            "target_date": "2026-09-08",
            "target_start_time": "10:00:00",
            "target_end_time": "11:00:00",
            "note": "Shifted to Tuesday",
        },
    )
    assert move_exception_resp.status_code == 201
    move_row = move_exception_resp.json()
    assert move_row["exception_type"] == "move"
    assert move_row["target_date"] == "2026-09-08"
    assert move_row["target_start_time"] == "10:00:00"
    assert move_row["target_end_time"] == "11:00:00"

    move_list_resp = client.get(
        f"/workflow/classes/{class_id}/timetable-exceptions?date_from=2026-09-08&date_to=2026-09-08",
        headers=headers,
    )
    assert move_list_resp.status_code == 200
    move_rows = move_list_resp.json()
    assert len(move_rows) == 1
    assert int(move_rows[0]["id"]) == int(move_row["id"])

    create_overlap_blocked_resp = client.post(
        f"/workflow/classes/{class_id}/timetable-exceptions",
        headers=headers,
        json={
            "rule_id": rule_id,
            "exception_date": "2026-10-12",
            "exception_type": "move",
            "target_date": "2026-09-10",
            "target_start_time": "12:00:00",
            "target_end_time": "13:00:00",
            "note": "Should be blocked without override",
        },
    )
    assert create_overlap_blocked_resp.status_code == 409
    assert "allow_overlap=true" in str(create_overlap_blocked_resp.json().get("detail", ""))

    create_overlap_allowed_resp = client.post(
        f"/workflow/classes/{class_id}/timetable-exceptions",
        headers=headers,
        json={
            "rule_id": rule_id,
            "exception_date": "2026-10-12",
            "exception_type": "move",
            "target_date": "2026-09-10",
            "target_start_time": "12:00:00",
            "target_end_time": "13:00:00",
            "allow_overlap": True,
            "note": "Allowed with explicit override",
        },
    )
    assert create_overlap_allowed_resp.status_code == 201
    overlap_move_row = create_overlap_allowed_resp.json()
    assert overlap_move_row["target_date"] == "2026-09-10"
    assert overlap_move_row["target_start_time"] == "12:00:00"

    update_overlap_note_only_resp = client.patch(
        f"/workflow/timetable-exceptions/{overlap_move_row['id']}",
        headers=headers,
        json={
            "note": "Note-only patch should not require override",
        },
    )
    assert update_overlap_note_only_resp.status_code == 200
    assert update_overlap_note_only_resp.json()["note"] == "Note-only patch should not require override"

    update_move_blocked_resp = client.patch(
        f"/workflow/timetable-exceptions/{move_row['id']}",
        headers=headers,
        json={
            "target_date": "2026-09-10",
            "target_start_time": "12:00:00",
            "target_end_time": "13:00:00",
            "note": "Should fail without override",
        },
    )
    assert update_move_blocked_resp.status_code == 409
    assert "allow_overlap=true" in str(update_move_blocked_resp.json().get("detail", ""))

    update_move_resp = client.patch(
        f"/workflow/timetable-exceptions/{move_row['id']}",
        headers=headers,
        json={
            "target_date": "2026-09-10",
            "target_start_time": "12:00:00",
            "target_end_time": "13:00:00",
            "allow_overlap": True,
            "note": "Patched move",
        },
    )
    assert update_move_resp.status_code == 200
    updated_move_row = update_move_resp.json()
    assert updated_move_row["target_date"] == "2026-09-10"
    assert updated_move_row["target_start_time"] == "12:00:00"
    assert updated_move_row["target_end_time"] == "13:00:00"
    assert updated_move_row["note"] == "Patched move"

    delete_resp = client.delete(f"/workflow/timetable-exceptions/{exception_row['id']}", headers=headers)
    assert delete_resp.status_code == 204
    delete_move_resp = client.delete(f"/workflow/timetable-exceptions/{move_row['id']}", headers=headers)
    assert delete_move_resp.status_code == 204
    delete_overlap_move_resp = client.delete(f"/workflow/timetable-exceptions/{overlap_move_row['id']}", headers=headers)
    assert delete_overlap_move_resp.status_code == 204

    list_after_delete = client.get(f"/workflow/classes/{class_id}/timetable-exceptions", headers=headers)
    assert list_after_delete.status_code == 200
    assert list_after_delete.json() == []


def test_timetable_import_apply_with_class_mappings(client):
    headers = _auth_headers(client)
    class_resp = client.post(
        "/classes",
        json={"name": "2APIC-1", "subject": "Math"},
        headers=headers,
    )
    assert class_resp.status_code == 201
    class_id = int(class_resp.json()["id"])

    csv_content = _build_timetable_csv(
        [
            ("owner@school.edu", "2APIC-LEGACY", "Math", "Monday", "08:00", "09:00", "R12", "G1"),
        ]
    )
    mapping_payload = json.dumps({"2APIC-LEGACY": class_id})

    dry_run_resp = client.post(
        "/workflow/timetable/import/apply",
        headers=headers,
        data={
            "mode": "dry_run_only",
            "effective_from": "2026-09-01",
            "create_missing_classes": "false",
            "class_mappings_json": mapping_payload,
        },
        files={"file": ("emploi.csv", csv_content, "text/csv")},
    )
    assert dry_run_resp.status_code == 200
    dry_run_payload = dry_run_resp.json()
    assert dry_run_payload["planned_apply_rows"] == 1
    assert dry_run_payload["applied_rows"] == 0
    assert dry_run_payload["unresolved_class_names"] == []
    assert any(
        row["action"] == "dry_run_ready" and int(row.get("class_id") or 0) == class_id
        for row in dry_run_payload["rows"]
    )

    append_resp = client.post(
        "/workflow/timetable/import/apply",
        headers=headers,
        data={
            "mode": "append_new_slots",
            "effective_from": "2026-09-01",
            "create_missing_classes": "false",
            "class_mappings_json": mapping_payload,
        },
        files={"file": ("emploi.csv", csv_content, "text/csv")},
    )
    assert append_resp.status_code == 200
    append_payload = append_resp.json()
    assert append_payload["applied_rows"] == 1
    assert append_payload["unresolved_class_names"] == []

    rules_resp = client.get(f"/workflow/classes/{class_id}/timetable-rules", headers=headers)
    assert rules_resp.status_code == 200
    rows = rules_resp.json()
    assert len(rows) == 1
    assert rows[0]["start_time"] == "08:00:00"


def test_timetable_import_saved_class_aliases_reused_and_manageable(client):
    headers = _auth_headers(client)
    class_resp = client.post(
        "/classes",
        json={"name": "2APIC-1", "subject": "Math"},
        headers=headers,
    )
    assert class_resp.status_code == 201
    class_id = int(class_resp.json()["id"])
    class_resp_2 = client.post(
        "/classes",
        json={"name": "2APIC-2", "subject": "Math"},
        headers=headers,
    )
    assert class_resp_2.status_code == 201
    class_id_2 = int(class_resp_2.json()["id"])

    csv_content = _build_timetable_csv(
        [
            ("owner@school.edu", "2APIC LEGACY", "Math", "Monday", "08:00", "09:00", "R12", "G1"),
        ]
    )
    mapping_payload = json.dumps({"2APIC LEGACY": class_id})

    apply_resp = client.post(
        "/workflow/timetable/import/apply",
        headers=headers,
        data={
            "mode": "append_new_slots",
            "effective_from": "2026-09-01",
            "create_missing_classes": "false",
            "class_mappings_json": mapping_payload,
            "save_class_mappings": "true",
        },
        files={"file": ("emploi.csv", csv_content, "text/csv")},
    )
    assert apply_resp.status_code == 200
    assert apply_resp.json()["applied_rows"] == 1

    list_resp = client.get("/workflow/timetable/class-mappings", headers=headers)
    assert list_resp.status_code == 200
    rows = list_resp.json()
    target_row = next((row for row in rows if str(row.get("alias_name")) == "2APIC LEGACY"), None)
    assert target_row is not None
    assert int(target_row["class_id"]) == class_id
    mapping_id = int(target_row["id"])

    update_resp = client.patch(
        f"/workflow/timetable/class-mappings/{mapping_id}",
        headers=headers,
        json={"class_id": class_id_2},
    )
    assert update_resp.status_code == 200
    update_payload = update_resp.json()
    assert int(update_payload["id"]) == mapping_id
    assert int(update_payload["class_id"]) == class_id_2

    dry_run_resp = client.post(
        "/workflow/timetable/import/apply",
        headers=headers,
        data={
            "mode": "dry_run_only",
            "effective_from": "2026-10-01",
            "create_missing_classes": "false",
        },
        files={"file": ("emploi.csv", csv_content, "text/csv")},
    )
    assert dry_run_resp.status_code == 200
    dry_run_payload = dry_run_resp.json()
    assert dry_run_payload["unresolved_class_names"] == []
    assert dry_run_payload["planned_apply_rows"] == 1
    assert any(
        row["action"] == "dry_run_ready" and int(row.get("class_id") or 0) == class_id_2
        for row in dry_run_payload["rows"]
    )

    delete_resp = client.delete(f"/workflow/timetable/class-mappings/{mapping_id}", headers=headers)
    assert delete_resp.status_code == 204

    list_after_delete = client.get("/workflow/timetable/class-mappings", headers=headers)
    assert list_after_delete.status_code == 200
    assert all(int(row["id"]) != mapping_id for row in list_after_delete.json())


def test_timetable_class_mapping_bulk_save(client):
    headers = _auth_headers(client)
    class_1_resp = client.post("/classes", json={"name": "2APIC-1", "subject": "Math"}, headers=headers)
    assert class_1_resp.status_code == 201
    class_1_id = int(class_1_resp.json()["id"])
    class_2_resp = client.post("/classes", json={"name": "2APIC-2", "subject": "Math"}, headers=headers)
    assert class_2_resp.status_code == 201
    class_2_id = int(class_2_resp.json()["id"])

    bulk_save_resp = client.post(
        "/workflow/timetable/class-mappings/bulk-save",
        headers=headers,
        json={
            "mappings": {
                "2APIC LEGACY": class_1_id,
                "   ": class_1_id,
            },
        },
    )
    assert bulk_save_resp.status_code == 200
    bulk_save_payload = bulk_save_resp.json()
    assert bulk_save_payload["saved_count"] == 1
    assert bulk_save_payload["skipped_count"] == 1
    assert len(bulk_save_payload["rows"]) == 1
    assert int(bulk_save_payload["rows"][0]["class_id"]) == class_1_id

    bulk_update_resp = client.post(
        "/workflow/timetable/class-mappings/bulk-save",
        headers=headers,
        json={
            "mappings": {
                "2APIC LEGACY": class_2_id,
            },
        },
    )
    assert bulk_update_resp.status_code == 200
    bulk_update_payload = bulk_update_resp.json()
    assert bulk_update_payload["saved_count"] == 1
    assert int(bulk_update_payload["rows"][0]["class_id"]) == class_2_id

    csv_content = _build_timetable_csv(
        [
            ("owner@school.edu", "2APIC LEGACY", "Math", "Monday", "08:00", "09:00", "R12", "G1"),
        ]
    )
    dry_run_resp = client.post(
        "/workflow/timetable/import/apply",
        headers=headers,
        data={
            "mode": "dry_run_only",
            "effective_from": "2026-10-01",
            "create_missing_classes": "false",
        },
        files={"file": ("emploi.csv", csv_content, "text/csv")},
    )
    assert dry_run_resp.status_code == 200
    dry_run_payload = dry_run_resp.json()
    assert dry_run_payload["unresolved_class_names"] == []
    assert any(
        row["action"] == "dry_run_ready" and int(row.get("class_id") or 0) == class_2_id
        for row in dry_run_payload["rows"]
    )


def test_timetable_import_apply_supports_effective_to_window(client):
    headers = _auth_headers(client)
    class_resp = client.post(
        "/classes",
        json={"name": "2APIC-Window", "subject": "Math"},
        headers=headers,
    )
    assert class_resp.status_code == 201
    class_id = int(class_resp.json()["id"])

    csv_content = _build_timetable_csv(
        [
            ("owner@school.edu", "2APIC-Window", "Math", "Monday", "08:00", "09:00", "R12", "G1"),
        ]
    )

    apply_resp = client.post(
        "/workflow/timetable/import/apply",
        headers=headers,
        data={
            "mode": "append_new_slots",
            "effective_from": "2026-09-01",
            "effective_to": "2026-12-31",
            "create_missing_classes": "false",
        },
        files={"file": ("emploi.csv", csv_content, "text/csv")},
    )
    assert apply_resp.status_code == 200
    payload = apply_resp.json()
    assert payload["applied_rows"] == 1
    assert payload["effective_to"] == "2026-12-31"

    rules_resp = client.get(f"/workflow/classes/{class_id}/timetable-rules", headers=headers)
    assert rules_resp.status_code == 200
    rows = rules_resp.json()
    assert len(rows) == 1
    assert rows[0]["effective_from"] == "2026-09-01"
    assert rows[0]["effective_to"] == "2026-12-31"

    invalid_window_resp = client.post(
        "/workflow/timetable/import/apply",
        headers=headers,
        data={
            "mode": "append_new_slots",
            "effective_from": "2026-09-01",
            "effective_to": "2026-08-31",
            "create_missing_classes": "false",
        },
        files={"file": ("emploi.csv", csv_content, "text/csv")},
    )
    assert invalid_window_resp.status_code == 400


def test_workflow_checklist_reorder_supports_reparent_and_reposition(client):
    headers = _auth_headers(client)
    class_resp = client.post("/classes", json={"name": "Workflow Reorder 2APIC", "subject": "Math"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = class_resp.json()["id"]

    start_unit_resp = client.post(
        f"/workflow/classes/{class_id}/units/start",
        headers=headers,
        data={"unit_type": "chapter", "title": "Reorder Unit", "source_text": "Chapter reorder seed"},
    )
    assert start_unit_resp.status_code == 201
    unit = start_unit_resp.json()

    root_a_resp = client.post(
        f"/workflow/classes/{class_id}/units/{unit['id']}/items",
        headers=headers,
        json={"title": "Root A", "item_kind": "chapter", "parent_item_id": None},
    )
    assert root_a_resp.status_code == 201
    root_a_id = root_a_resp.json()["id"]

    root_b_resp = client.post(
        f"/workflow/classes/{class_id}/units/{unit['id']}/items",
        headers=headers,
        json={"title": "Root B", "item_kind": "chapter", "parent_item_id": None},
    )
    assert root_b_resp.status_code == 201
    root_b_id = root_b_resp.json()["id"]

    child_resp = client.post(
        f"/workflow/classes/{class_id}/units/{unit['id']}/items",
        headers=headers,
        json={"title": "Child A1", "item_kind": "exercise", "parent_item_id": root_a_id},
    )
    assert child_resp.status_code == 201
    child_id = child_resp.json()["id"]

    workspace_resp = client.get(f"/workflow/classes/{class_id}", headers=headers)
    assert workspace_resp.status_code == 200
    flat_before = _flatten_checklist(workspace_resp.json()["active_unit"]["checklist"])
    rows_by_id = {
        int(item["id"]): {
            "id": int(item["id"]),
            "parent_item_id": item.get("parent_item_id"),
            "position": int(item.get("position", 0)),
        }
        for item in flat_before
    }

    rows_by_id[root_b_id]["position"] = 0
    rows_by_id[root_a_id]["position"] = 1
    rows_by_id[child_id]["parent_item_id"] = root_b_id
    rows_by_id[child_id]["position"] = 0

    reorder_resp = client.post(
        f"/workflow/classes/{class_id}/units/{unit['id']}/items/reorder",
        headers=headers,
        json={"items": list(rows_by_id.values())},
    )
    assert reorder_resp.status_code == 200
    assert reorder_resp.json()["updated"] >= len(rows_by_id)
    assert reorder_resp.json()["moved"] >= 1

    workspace_after = client.get(f"/workflow/classes/{class_id}", headers=headers)
    assert workspace_after.status_code == 200
    active_unit = workspace_after.json()["active_unit"]
    flat_after = _flatten_checklist(active_unit["checklist"])
    by_id = {int(item["id"]): item for item in flat_after}
    assert int(by_id[child_id]["parent_item_id"]) == root_b_id

    roots = [row for row in active_unit["checklist"] if row.get("parent_item_id") is None]
    root_ids = [int(row["id"]) for row in roots]
    assert root_ids.index(root_b_id) < root_ids.index(root_a_id)
    root_b_children = [int(row["id"]) for row in by_id[root_b_id].get("children", [])]
    assert child_id in root_b_children


def test_workflow_parent_toggle_checks_children_and_calendar(client):
    headers = _auth_headers(client)
    class_resp = client.post("/classes", json={"name": "Workflow Cascade 2APIC", "subject": "Math"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = class_resp.json()["id"]
    roster = _build_roster_file([("STD001", "Alice"), ("STD002", "Bob")])
    import_resp = client.post(
        f"/classes/{class_id}/students/import",
        headers=headers,
        files={"file": ("students.xlsx", roster, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert import_resp.status_code == 200

    start_unit_resp = client.post(
        f"/workflow/classes/{class_id}/units/start",
        headers=headers,
        data={"unit_type": "chapter", "title": "Cascade Unit", "source_text": "Seed lesson"},
    )
    assert start_unit_resp.status_code == 201
    unit = start_unit_resp.json()

    parent_resp = client.post(
        f"/workflow/classes/{class_id}/units/{unit['id']}/items",
        headers=headers,
        json={"title": "Parent topic", "item_kind": "chapter", "parent_item_id": None},
    )
    assert parent_resp.status_code == 201
    parent_id = parent_resp.json()["id"]

    child_resp = client.post(
        f"/workflow/classes/{class_id}/units/{unit['id']}/items",
        headers=headers,
        json={"title": "Child practice", "item_kind": "exercise", "parent_item_id": parent_id},
    )
    assert child_resp.status_code == 201
    child_id = child_resp.json()["id"]

    start_session_resp = client.post(
        f"/workflow/classes/{class_id}/sessions/start",
        headers=headers,
        json={"absent_student_ids": []},
    )
    assert start_session_resp.status_code == 201
    session_id = start_session_resp.json()["id"]

    toggle_resp = client.post(
        f"/workflow/classes/{class_id}/sessions/{session_id}/items/{parent_id}/toggle",
        headers=headers,
        json={"checked": True},
    )
    assert toggle_resp.status_code == 200
    assert toggle_resp.json()["is_completed"] is True

    workspace_resp = client.get(f"/workflow/classes/{class_id}", headers=headers)
    assert workspace_resp.status_code == 200
    flat = _flatten_checklist(workspace_resp.json()["active_unit"]["checklist"])
    by_id = {int(row["id"]): row for row in flat}
    assert by_id[parent_id]["is_completed"] is True
    assert by_id[child_id]["is_completed"] is True

    end_resp = client.post(
        f"/workflow/classes/{class_id}/sessions/{session_id}/end",
        headers=headers,
        json={"end_time": "10:00:00"},
    )
    assert end_resp.status_code == 200

    calendar_resp = client.get(f"/workflow/classes/{class_id}/calendar", headers=headers)
    assert calendar_resp.status_code == 200
    event = next((row for row in calendar_resp.json() if row["session_id"] == session_id), None)
    assert event is not None
    checked_items = [str(value or "") for value in event.get("checked_items", [])]
    checked_text = " | ".join(checked_items).lower()
    assert event.get("checked_items_count", 0) >= 2
    assert "parent topic" in checked_text
    assert "child practice" in checked_text


def test_workflow_end_session_rejects_end_before_start(client):
    headers = _auth_headers(client)
    class_resp = client.post("/classes", json={"name": "Workflow End Time Validation", "subject": "Math"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = class_resp.json()["id"]

    roster = _build_roster_file([("STD001", "Alice")])
    import_resp = client.post(
        f"/classes/{class_id}/students/import",
        headers=headers,
        files={"file": ("students.xlsx", roster, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert import_resp.status_code == 200

    unit_resp = client.post(
        f"/workflow/classes/{class_id}/units/start",
        headers=headers,
        data={"unit_type": "chapter", "title": "Time Validation Unit", "source_text": "chapter seed"},
    )
    assert unit_resp.status_code == 201

    session_resp = client.post(
        f"/workflow/classes/{class_id}/sessions/start",
        headers=headers,
        json={"absent_student_ids": []},
    )
    assert session_resp.status_code == 201
    session_id = session_resp.json()["id"]

    invalid_end_resp = client.post(
        f"/workflow/classes/{class_id}/sessions/{session_id}/end",
        headers=headers,
        json={"start_time": "10:00:00", "end_time": "09:00:00"},
    )
    assert invalid_end_resp.status_code == 400
    assert "end_time must be greater than or equal to start_time" in str(invalid_end_resp.json().get("detail", ""))


def test_workflow_end_with_attendance_only_keeps_session_open(client):
    headers = _auth_headers(client)
    class_resp = client.post("/classes", json={"name": "Workflow Attendance Update Open Session", "subject": "Math"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = class_resp.json()["id"]

    roster = _build_roster_file([("STD001", "Alice"), ("STD002", "Bob")])
    import_resp = client.post(
        f"/classes/{class_id}/students/import",
        headers=headers,
        files={"file": ("students.xlsx", roster, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert import_resp.status_code == 200
    students = client.get(f"/classes/{class_id}/students", headers=headers).json()
    absent_id = students[0]["id"]

    unit_resp = client.post(
        f"/workflow/classes/{class_id}/units/start",
        headers=headers,
        data={"unit_type": "chapter", "title": "Attendance Update Unit", "source_text": "chapter seed"},
    )
    assert unit_resp.status_code == 201

    session_resp = client.post(
        f"/workflow/classes/{class_id}/sessions/start",
        headers=headers,
        json={"absent_student_ids": []},
    )
    assert session_resp.status_code == 201
    session_id = session_resp.json()["id"]

    attendance_only_resp = client.post(
        f"/workflow/classes/{class_id}/sessions/{session_id}/end",
        headers=headers,
        json={"absent_student_ids": [absent_id]},
    )
    assert attendance_only_resp.status_code == 200
    assert attendance_only_resp.json()["end_time"] is None
    assert attendance_only_resp.json()["absent_count"] == 1

    workspace_resp = client.get(f"/workflow/classes/{class_id}", headers=headers)
    assert workspace_resp.status_code == 200
    active_session = workspace_resp.json().get("active_session")
    assert active_session is not None
    assert int(active_session["id"]) == session_id

    close_resp = client.post(
        f"/workflow/classes/{class_id}/sessions/{session_id}/end",
        headers=headers,
        json={},
    )
    assert close_resp.status_code == 200
    assert close_resp.json()["end_time"] is not None


def test_workflow_start_unit_accepts_source_text_without_pdf(client):
    headers = _auth_headers(client)
    class_resp = client.post("/classes", json={"name": "Workflow Manual 2APIC", "subject": "Math"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = class_resp.json()["id"]

    start_unit_resp = client.post(
        f"/workflow/classes/{class_id}/units/start",
        headers=headers,
        data={
            "unit_type": "chapter",
            "title": "Chapitre 3",
            "source_text": "Chapitre 3\n1.1 Fractions\nDefinition: fraction equivalente",
        },
    )
    assert start_unit_resp.status_code == 201
    unit = start_unit_resp.json()
    assert unit["unit_type"] == "chapter"
    assert unit["progress_total"] >= 1
    assert unit["checklist"]


def test_workflow_start_unit_rejects_blank_title_and_non_positive_planned_hours(client):
    headers = _auth_headers(client)
    class_resp = client.post("/classes", json={"name": "Workflow Validation Unit Start", "subject": "Math"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = class_resp.json()["id"]

    blank_title_resp = client.post(
        f"/workflow/classes/{class_id}/units/start",
        headers=headers,
        data={
            "unit_type": "chapter",
            "title": "   ",
            "source_text": "chapter seed",
        },
    )
    assert blank_title_resp.status_code == 400
    assert "Unit title is required" in str(blank_title_resp.json().get("detail", ""))

    invalid_hours_resp = client.post(
        f"/workflow/classes/{class_id}/units/start",
        headers=headers,
        data={
            "unit_type": "chapter",
            "title": "Chapitre Validation",
            "source_text": "chapter seed",
            "planned_hours": "0",
        },
    )
    assert invalid_hours_resp.status_code == 400
    assert "planned_hours must be greater than zero" in str(invalid_hours_resp.json().get("detail", ""))


def test_workflow_start_unit_from_pdf_generates_todo_tree(client, monkeypatch):
    from app.services import workflow as workflow_service

    monkeypatch.setattr(workflow_service, "OPENAI_API_KEY", "")
    monkeypatch.setattr(
        workflow_service,
        "_ocr_pdf_pages",
        lambda _source, *, max_pages: [
            "Chapitre 2 : Calcul litteral - Identites remarquables",
            "1. Developpement",
            "1.1 Developpement par la distributivite",
            "Propriete : k(a+b)=ka+kb",
            "Exemple : developper des expressions",
            "2. Identites remarquables",
            "2.1 (a+b)^2",
        ],
    )
    headers = _auth_headers(client)
    class_resp = client.post("/classes", json={"name": "Workflow PDF 2APIC", "subject": "Math"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = class_resp.json()["id"]

    pdf_bytes = _build_pdf_file(
        [
            "Chapitre 2 : Calcul litteral - Identites remarquables",
            "1. Developpement",
            "1.1 Developpement par la distributivite",
            "Propriete : k(a+b)=ka+kb",
            "Exemple : developper des expressions",
            "2. Identites remarquables",
            "2.1 (a+b)^2",
        ]
    )
    start_unit_resp = client.post(
        f"/workflow/classes/{class_id}/units/start",
        headers=headers,
        data={"unit_type": "chapter", "title": "Chapitre 2", "planned_hours": "6"},
        files={"file": ("chapter.pdf", pdf_bytes, "application/pdf")},
    )
    assert start_unit_resp.status_code == 201
    unit = start_unit_resp.json()
    assert unit["unit_type"] == "chapter"
    assert unit["progress_total"] >= 4
    checklist = unit["checklist"]
    assert checklist

    def flatten(nodes):
        output = []
        for node in nodes:
            output.append(node)
            output.extend(flatten(node.get("children", [])))
        return output

    flat = flatten(checklist)
    titles = [str(node.get("title", "")).lower() for node in flat]
    assert any("chapitre 2" in title for title in titles)
    assert any("1.1" in title or "distributivite" in title for title in titles)
    assert any(int(node.get("depth", 0)) > 0 for node in flat)


def test_workflow_start_unit_rejects_non_pdf_document(client):
    headers = _auth_headers(client)
    class_resp = client.post("/classes", json={"name": "Workflow PDF Strict", "subject": "Math"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = class_resp.json()["id"]

    text_content = b"Chapitre 1\n1.1 Developpement"
    start_unit_resp = client.post(
        f"/workflow/classes/{class_id}/units/start",
        headers=headers,
        data={"unit_type": "chapter", "title": "Chapitre 1"},
        files={"file": ("chapter.txt", text_content, "text/plain")},
    )
    assert start_unit_resp.status_code == 400
    assert "Only PDF documents are supported" in str(start_unit_resp.json().get("detail", ""))


def test_workflow_reopen_closed_unit_flow(client):
    headers = _auth_headers(client)
    class_resp = client.post("/classes", json={"name": "Workflow Reopen Flow", "subject": "Math"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = class_resp.json()["id"]

    unit_resp = client.post(
        f"/workflow/classes/{class_id}/units/start",
        headers=headers,
        data={
            "unit_type": "chapter",
            "title": "Reopen Unit",
            "source_text": "chapter seed",
        },
    )
    assert unit_resp.status_code == 201
    first_unit_id = unit_resp.json()["id"]

    close_resp = client.post(f"/workflow/classes/{class_id}/units/{first_unit_id}/close", headers=headers)
    assert close_resp.status_code == 200

    reopen_resp = client.post(f"/workflow/classes/{class_id}/units/{first_unit_id}/reopen", headers=headers)
    assert reopen_resp.status_code == 200
    reopened = reopen_resp.json()
    assert reopened["status"] == "active"
    assert reopened["closed_at"] is None

    workspace_resp = client.get(f"/workflow/classes/{class_id}", headers=headers)
    assert workspace_resp.status_code == 200
    assert int(workspace_resp.json()["active_unit"]["id"]) == first_unit_id

    reopen_again_resp = client.post(f"/workflow/classes/{class_id}/units/{first_unit_id}/reopen", headers=headers)
    assert reopen_again_resp.status_code == 409

    close_again_resp = client.post(f"/workflow/classes/{class_id}/units/{first_unit_id}/close", headers=headers)
    assert close_again_resp.status_code == 200

    second_unit_resp = client.post(
        f"/workflow/classes/{class_id}/units/start",
        headers=headers,
        data={
            "unit_type": "chapter",
            "title": "Active Other Unit",
            "source_text": "chapter seed 2",
        },
    )
    assert second_unit_resp.status_code == 201

    reopen_blocked_resp = client.post(f"/workflow/classes/{class_id}/units/{first_unit_id}/reopen", headers=headers)
    assert reopen_blocked_resp.status_code == 409
    assert "active unit already exists" in str(reopen_blocked_resp.json().get("detail", "")).lower()


def test_workflow_delete_unit_deletes_linked_sessions(client):
    headers = _auth_headers(client)
    class_resp = client.post("/classes", json={"name": "Workflow Delete Unit", "subject": "Math"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = class_resp.json()["id"]

    unit_resp = client.post(
        f"/workflow/classes/{class_id}/units/start",
        headers=headers,
        data={
            "unit_type": "chapter",
            "title": "Delete Me Unit",
            "source_text": "chapter seed",
        },
    )
    assert unit_resp.status_code == 201
    unit_id = int(unit_resp.json()["id"])

    first_session_resp = client.post(
        f"/workflow/classes/{class_id}/sessions",
        headers=headers,
        json={
            "session_date": "2026-03-03",
            "start_time": "08:00:00",
            "end_time": "09:00:00",
            "unit_id": unit_id,
            "absent_student_ids": [],
        },
    )
    assert first_session_resp.status_code == 201
    first_session_id = int(first_session_resp.json()["id"])

    second_session_resp = client.post(
        f"/workflow/classes/{class_id}/sessions",
        headers=headers,
        json={
            "session_date": "2026-03-04",
            "start_time": "08:00:00",
            "unit_id": unit_id,
            "absent_student_ids": [],
        },
    )
    assert second_session_resp.status_code == 201
    second_session_id = int(second_session_resp.json()["id"])

    unit_sessions_before = client.get(f"/workflow/units/{unit_id}/sessions", headers=headers)
    assert unit_sessions_before.status_code == 200
    assert len(unit_sessions_before.json()) >= 2

    delete_unit_resp = client.delete(f"/workflow/classes/{class_id}/units/{unit_id}", headers=headers)
    assert delete_unit_resp.status_code == 200
    delete_payload = delete_unit_resp.json()
    assert int(delete_payload["deleted_unit_id"]) == unit_id
    assert int(delete_payload["deleted_sessions_count"]) >= 2

    workspace_resp = client.get(f"/workflow/classes/{class_id}", headers=headers)
    assert workspace_resp.status_code == 200
    workspace = workspace_resp.json()
    assert workspace.get("active_unit") is None
    assert workspace.get("active_session") is None

    unit_sessions_after = client.get(f"/workflow/units/{unit_id}/sessions", headers=headers)
    assert unit_sessions_after.status_code == 404

    first_session_detail = client.get(f"/sessions/{first_session_id}", headers=headers)
    assert first_session_detail.status_code == 404
    second_session_detail = client.get(f"/sessions/{second_session_id}", headers=headers)
    assert second_session_detail.status_code == 404

    calendar_resp = client.get(f"/workflow/classes/{class_id}/calendar", headers=headers)
    assert calendar_resp.status_code == 200
    assert not any(int(row.get("unit_id") or 0) == unit_id for row in calendar_resp.json())


def test_classes_students_sessions_and_extraction(client):
    headers = _auth_headers(client)
    class_resp = client.post("/classes", json={"name": "2APIC-3", "subject": "Math", "level": "2APIC"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = class_resp.json()["id"]

    roster = _build_roster_file([("STD001", "Alice"), ("STD002", "Bob")])
    import_resp = client.post(
        f"/classes/{class_id}/students/import",
        headers=headers,
        files={"file": ("students.xlsx", roster, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert import_resp.status_code == 200
    assert import_resp.json()["created"] == 2

    students = client.get(f"/classes/{class_id}/students", headers=headers).json()
    assert len(students) == 2

    session_resp = client.post(
        f"/classes/{class_id}/sessions",
        headers=headers,
        json={"session_date": "2026-03-02", "start_time": "08:00:00", "end_time": "09:00:00", "note": "chapter progress"},
    )
    assert session_resp.status_code == 201
    session_id = session_resp.json()["id"]

    attendance_payload = [
        {"student_id": students[0]["id"], "status": "present", "minutes_late": 0},
        {"student_id": students[1]["id"], "status": "late", "minutes_late": 10},
    ]
    attendance_resp = client.put(f"/sessions/{session_id}/attendance", json=attendance_payload, headers=headers)
    assert attendance_resp.status_code == 200
    assert len(attendance_resp.json()) == 2
    attendance_summary_resp = client.get(f"/classes/{class_id}/attendance-summary", headers=headers)
    assert attendance_summary_resp.status_code == 200
    assert attendance_summary_resp.json()["total_sessions"] == 1
    student_profile_resp = client.get(f"/classes/{class_id}/students/{students[0]['id']}/profile", headers=headers)
    assert student_profile_resp.status_code == 200
    profile = student_profile_resp.json()
    assert profile["student"]["student_code"] == students[0]["student_code"]
    assert profile["attendance"]["total_rows"] == 1
    student_profile_pdf_resp = client.get(
        f"/classes/{class_id}/students/{students[0]['id']}/reports/profile.pdf",
        headers=headers,
    )
    assert student_profile_pdf_resp.status_code == 200
    assert student_profile_pdf_resp.content.startswith(b"%PDF")
    dashboard_resp = client.get(f"/classes/{class_id}/dashboard", headers=headers)
    assert dashboard_resp.status_code == 200
    assert dashboard_resp.json()["counts"]["students"] == 2
    assert "attendance_trend" in dashboard_resp.json()
    assert "extraction_metrics" in dashboard_resp.json()
    assert "exam_trend" in dashboard_resp.json()

    upload_resp = client.post(
        f"/sessions/{session_id}/uploads",
        headers=headers,
        files={"file": ("board.jpg", b"fake-image", "image/jpeg")},
        data={"raw_text": "1 Algebra\n1.1 Equations\nActivity: Solve by substitution\nExercise 1 page 20"},
    )
    assert upload_resp.status_code == 201
    extraction = upload_resp.json()
    assert extraction["lesson_headings"] == ["1 Algebra", "1.1 Equations"]
    assert len(extraction["activities"]) == 1
    assert len(extraction["exercises"]) == 1
    assert extraction["provider"] in {"heuristic", "openai"}

    confirm_payload = {
        "items": [
            {"item_type": "lesson", "heading": "1 Algebra", "position": 1},
            {"item_type": "lesson", "heading": "1.1 Equations", "position": 2},
            {
                "item_type": "activity",
                "heading": "Activity: Solve by substitution",
                "content": "Activity: Solve by substitution",
                "position": 3,
            },
            {
                "item_type": "exercise",
                "heading": "Exercise 1 page 20",
                "content": "Exercise 1 page 20",
                "position": 4,
            },
        ]
    }
    confirm_resp = client.post(f"/sessions/{session_id}/confirm-extraction", json=confirm_payload, headers=headers)
    assert confirm_resp.status_code == 200
    assert len(confirm_resp.json()) == 4

    class_audit_resp = client.get(f"/classes/{class_id}/audit-logs", headers=headers)
    assert class_audit_resp.status_code == 200
    extraction_entries = [row for row in class_audit_resp.json()["items"] if row["action"] == "extraction.confirm"]
    assert extraction_entries
    extraction_details = extraction_entries[0]["details"] or {}
    assert "before_items" in extraction_details
    assert "after_items" in extraction_details

    update_resp = client.put(
        f"/sessions/{session_id}",
        headers=headers,
        json={"note": "updated chapter progress"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["note"] == "updated chapter progress"

    session_detail_resp = client.get(f"/sessions/{session_id}", headers=headers)
    assert session_detail_resp.status_code == 200
    session_detail = session_detail_resp.json()
    assert session_detail["session"]["note"] == "updated chapter progress"
    assert len(session_detail["attendance"]) == 2
    assert len(session_detail["progress_items"]) == 4

    timeline_resp = client.get(f"/classes/{class_id}/timeline", headers=headers)
    assert timeline_resp.status_code == 200
    assert timeline_resp.json()["sessions"][0]["session_id"] == session_id
    timeline_filtered_resp = client.get(
        f"/classes/{class_id}/timeline?note_query=updated&has_progress=true",
        headers=headers,
    )
    assert timeline_filtered_resp.status_code == 200
    assert len(timeline_filtered_resp.json()["sessions"]) == 1
    timeline_reviewed_resp = client.get(
        f"/classes/{class_id}/timeline?has_reviewed_upload=true",
        headers=headers,
    )
    assert timeline_reviewed_resp.status_code == 200
    assert len(timeline_reviewed_resp.json()["sessions"]) == 1

    attendance_csv_resp = client.get(f"/classes/{class_id}/attendance-export.csv", headers=headers)
    assert attendance_csv_resp.status_code == 200
    assert "text/csv" in attendance_csv_resp.headers["content-type"]
    text = attendance_csv_resp.text
    assert "session_date,session_id,student_code,full_name,status,minutes_late,comment" in text
    assert "STD001" in text

    dashboard_after_extraction = client.get(f"/classes/{class_id}/dashboard", headers=headers)
    assert dashboard_after_extraction.status_code == 200
    metrics = dashboard_after_extraction.json()["extraction_metrics"]
    assert metrics["sample_size"] >= 1
    assert isinstance(metrics["average_confidence"], float)


def test_quick_submit_session_flow(client):
    headers = _auth_headers(client)
    class_resp = client.post("/classes", json={"name": "Quick Submit Class", "subject": "Math"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = class_resp.json()["id"]

    roster = _build_roster_file([("STD701", "Meryem"), ("STD702", "Omar")])
    import_resp = client.post(
        f"/classes/{class_id}/students/import",
        headers=headers,
        files={"file": ("students.xlsx", roster, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert import_resp.status_code == 200

    students = client.get(f"/classes/{class_id}/students", headers=headers).json()
    absent_id = students[0]["id"]
    quick_submit_resp = client.post(
        f"/classes/{class_id}/quick-submit",
        headers=headers,
        files={"file": ("board.jpg", b"fake-image", "image/jpeg")},
        data={
            "absent_student_ids": f"[{absent_id}]",
            "raw_text": "1 Geometry\n1.1 Triangles\nActivity: classify triangles\nExercise 1 page 44",
        },
    )
    assert quick_submit_resp.status_code == 201
    payload = quick_submit_resp.json()
    assert payload["class_id"] == class_id
    assert payload["absent_students"] == 1
    assert payload["lesson_headings_count"] == 2
    assert payload["activities_count"] == 1
    assert payload["exercises_count"] == 1
    assert payload["provider"] in {"heuristic", "openai"}

    session_id = payload["session_id"]
    detail_resp = client.get(f"/sessions/{session_id}", headers=headers)
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert len(detail["attendance"]) == 2
    absent_rows = [row for row in detail["attendance"] if row["status"] == "absent"]
    present_rows = [row for row in detail["attendance"] if row["status"] == "present"]
    assert len(absent_rows) == 1
    assert len(present_rows) == 1
    assert len(detail["progress_items"]) == 4
    assert len(detail["uploads"]) == 1
    assert detail["uploads"][0]["reviewed"] is True


def test_confirm_extraction_append_mode_keeps_existing_progress(client):
    headers = _auth_headers(client)
    class_resp = client.post("/classes", json={"name": "Append Mode Class"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = class_resp.json()["id"]

    session_resp = client.post(
        f"/classes/{class_id}/sessions",
        headers=headers,
        json={"session_date": "2026-03-02"},
    )
    assert session_resp.status_code == 201
    session_id = session_resp.json()["id"]

    replace_resp = client.post(
        f"/sessions/{session_id}/confirm-extraction",
        headers=headers,
        json={"items": [{"item_type": "lesson", "heading": "Intro", "position": 99}]},
    )
    assert replace_resp.status_code == 200
    replace_rows = replace_resp.json()
    assert [row["heading"] for row in replace_rows] == ["Intro"]
    assert [row["position"] for row in replace_rows] == [1]

    append_resp = client.post(
        f"/sessions/{session_id}/confirm-extraction",
        headers=headers,
        json={
            "mode": "append",
            "items": [
                {
                    "item_type": "activity",
                    "heading": "Activity",
                    "content": "Warm up",
                    "position": 20,
                },
                {
                    "item_type": "exercise",
                    "heading": "Exercise",
                    "content": "Page 44",
                    "position": 10,
                },
            ],
        },
    )
    assert append_resp.status_code == 200
    append_rows = append_resp.json()
    assert [row["heading"] for row in append_rows] == ["Intro", "Exercise", "Activity"]
    assert [row["position"] for row in append_rows] == [1, 2, 3]

    detail_resp = client.get(f"/sessions/{session_id}", headers=headers)
    assert detail_resp.status_code == 200
    assert len(detail_resp.json()["progress_items"]) == 3

    audit_resp = client.get(f"/classes/{class_id}/audit-logs", headers=headers)
    assert audit_resp.status_code == 200
    extraction_entries = [row for row in audit_resp.json()["items"] if row["action"] == "extraction.confirm"]
    assert extraction_entries
    assert any((entry.get("details") or {}).get("mode") == "append" for entry in extraction_entries)


def test_get_latest_session_upload_returns_normalized_items(client):
    headers = _auth_headers(client)
    class_resp = client.post("/classes", json={"name": "Latest Upload Class", "subject": "Math"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = class_resp.json()["id"]

    session_resp = client.post(
        f"/classes/{class_id}/sessions",
        headers=headers,
        json={"session_date": "2026-03-02", "start_time": "08:00:00", "end_time": "09:00:00"},
    )
    assert session_resp.status_code == 201
    session_id = session_resp.json()["id"]

    latest_missing_resp = client.get(f"/sessions/{session_id}/uploads/latest", headers=headers)
    assert latest_missing_resp.status_code == 404

    upload_resp = client.post(
        f"/sessions/{session_id}/uploads",
        headers=headers,
        files={"file": ("board.jpg", b"fake-image", "image/jpeg")},
        data={"raw_text": "1 Algebra\nActivity: Solve quickly\nExercise 1 page 20"},
    )
    assert upload_resp.status_code == 201
    upload_payload = upload_resp.json()
    assert upload_payload["items"]
    upload_hint_ids = [str(row.get("hint_id") or "") for row in upload_payload["items"]]
    assert all(hint.startswith("ex_") for hint in upload_hint_ids)
    assert len(upload_hint_ids) == len(set(upload_hint_ids))

    latest_resp = client.get(f"/sessions/{session_id}/uploads/latest", headers=headers)
    assert latest_resp.status_code == 200
    latest_payload = latest_resp.json()
    assert latest_payload["upload_id"] == upload_payload["upload_id"]
    assert latest_payload["session_id"] == session_id
    assert latest_payload["reviewed"] is False
    assert latest_payload["items"]
    assert latest_payload["items"][0]["item_type"] == "lesson"
    assert latest_payload["items"][0]["position"] == 1
    latest_hint_ids = [str(row.get("hint_id") or "") for row in latest_payload["items"]]
    assert latest_hint_ids == upload_hint_ids

    confirm_resp = client.post(
        f"/sessions/{session_id}/confirm-extraction",
        headers=headers,
        json={"items": latest_payload["items"]},
    )
    assert confirm_resp.status_code == 200
    assert len(confirm_resp.json()) >= 1

    latest_after_confirm_resp = client.get(f"/sessions/{session_id}/uploads/latest", headers=headers)
    assert latest_after_confirm_resp.status_code == 200
    assert latest_after_confirm_resp.json()["reviewed"] is True


def test_quick_submit_rejects_unknown_absent_student(client):
    headers = _auth_headers(client)
    class_resp = client.post("/classes", json={"name": "Quick Submit Validation"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = class_resp.json()["id"]

    roster = _build_roster_file([("STD801", "Yasmin")])
    import_resp = client.post(
        f"/classes/{class_id}/students/import",
        headers=headers,
        files={"file": ("students.xlsx", roster, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert import_resp.status_code == 200

    invalid_absent_resp = client.post(
        f"/classes/{class_id}/quick-submit",
        headers=headers,
        files={"file": ("board.jpg", b"fake-image", "image/jpeg")},
        data={
            "absent_student_ids": "[999999]",
            "raw_text": "1 Numbers",
        },
    )
    assert invalid_absent_resp.status_code == 400
    assert "Unknown student ids" in str(invalid_absent_resp.json()["detail"])


def test_class_archive_restore_and_write_lock(client):
    headers = _auth_headers(client)
    class_resp = client.post("/classes", json={"name": "Archive Class", "subject": "Math"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = class_resp.json()["id"]

    list_before = client.get("/classes", headers=headers)
    assert list_before.status_code == 200
    assert any(item["id"] == class_id for item in list_before.json())

    archive_resp = client.post(f"/classes/{class_id}/archive", headers=headers)
    assert archive_resp.status_code == 200
    assert archive_resp.json()["is_archived"] is True

    list_after_archive = client.get("/classes", headers=headers)
    assert list_after_archive.status_code == 200
    assert all(item["id"] != class_id for item in list_after_archive.json())

    list_with_archived = client.get("/classes?include_archived=true", headers=headers)
    assert list_with_archived.status_code == 200
    archived_row = next(item for item in list_with_archived.json() if item["id"] == class_id)
    assert archived_row["is_archived"] is True

    blocked_session_resp = client.post(
        f"/classes/{class_id}/sessions",
        headers=headers,
        json={"session_date": "2026-03-02"},
    )
    assert blocked_session_resp.status_code == 409

    restore_resp = client.post(f"/classes/{class_id}/restore", headers=headers)
    assert restore_resp.status_code == 200
    assert restore_resp.json()["is_archived"] is False

    create_session_after_restore = client.post(
        f"/classes/{class_id}/sessions",
        headers=headers,
        json={"session_date": "2026-03-02"},
    )
    assert create_session_after_restore.status_code == 201


def test_exam_excel_flow_and_exports(client):
    headers = _auth_headers(client)
    class_resp = client.post("/classes", json={"name": "2APIC-3"}, headers=headers)
    class_id = class_resp.json()["id"]
    roster = _build_roster_file([("STD010", "Nora"), ("STD011", "Youssef")])
    client.post(
        f"/classes/{class_id}/students/import",
        headers=headers,
        files={"file": ("students.xlsx", roster, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    exam_resp = client.post(
        f"/classes/{class_id}/exams",
        headers=headers,
        json={"title": "CC1", "exam_date": "2026-03-02", "max_score": 20, "weight": 1},
    )
    assert exam_resp.status_code == 201
    exam_id = exam_resp.json()["id"]

    template_resp = client.get(f"/exams/{exam_id}/template", headers=headers)
    assert template_resp.status_code == 200
    workbook = load_workbook(filename=BytesIO(template_resp.content), data_only=True)
    sheet = workbook.active
    assert sheet.max_row == 3

    results_file = _build_exam_file(
        [
            ("STD010", "Nora", 18, "A", "Good"),
            ("STD011", "Youssef", 16.5, "B+", "Can improve speed"),
        ]
    )
    import_resp = client.post(
        f"/exams/{exam_id}/results/import",
        headers=headers,
        files={"file": ("results.xlsx", results_file, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert import_resp.status_code == 200
    assert import_resp.json()["imported"] == 2

    results_resp = client.get(f"/exams/{exam_id}/results", headers=headers)
    assert results_resp.status_code == 200
    assert len(results_resp.json()) == 2
    results_csv_resp = client.get(f"/exams/{exam_id}/results.csv", headers=headers)
    assert results_csv_resp.status_code == 200
    assert "text/csv" in results_csv_resp.headers["content-type"]
    assert "student_code,full_name,score,max_score,note,teacher_comment" in results_csv_resp.text
    assert "STD010" in results_csv_resp.text
    results_xlsx_resp = client.get(f"/exams/{exam_id}/results.xlsx", headers=headers)
    assert results_xlsx_resp.status_code == 200
    export_wb = load_workbook(filename=BytesIO(results_xlsx_resp.content), data_only=True)
    export_sheet = export_wb.active
    assert export_sheet.cell(1, 1).value == "student_code"
    assert export_sheet.cell(2, 1).value == "STD010"
    students = client.get(f"/classes/{class_id}/students", headers=headers).json()
    nora = next(student for student in students if student["student_code"] == "STD010")
    nora_profile = client.get(f"/classes/{class_id}/students/{nora['id']}/profile", headers=headers)
    assert nora_profile.status_code == 200
    assert nora_profile.json()["exams"]["count"] == 1
    assert float(nora_profile.json()["exams"]["results"][0]["score"]) == 18.0
    exam_summary_resp = client.get(f"/classes/{class_id}/exam-summary", headers=headers)
    assert exam_summary_resp.status_code == 200
    assert exam_summary_resp.json()["exams"][0]["average_score"] == 17.25
    exam_dashboard = client.get(f"/classes/{class_id}/dashboard", headers=headers)
    assert exam_dashboard.status_code == 200
    assert len(exam_dashboard.json()["exam_trend"]) >= 1

    export_excel_resp = client.get(f"/classes/{class_id}/reports/official-notes.xlsx", headers=headers)
    assert export_excel_resp.status_code == 200
    export_pdf_resp = client.get(f"/classes/{class_id}/reports/full.pdf", headers=headers)
    assert export_pdf_resp.status_code == 200
    assert export_pdf_resp.content.startswith(b"%PDF")


def test_import_students_from_notescc_list_format(client):
    headers = _auth_headers(client)
    class_resp = client.post("/classes", json={"name": "NotesCC List Class"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = class_resp.json()["id"]

    roster = _build_notescc_list_file(
        [
            ("10934196", "A161027646", "Ismail", "23-03-2011"),
            ("10851611", "A166022053", "Adam", "28-08-2010"),
        ]
    )
    import_resp = client.post(
        f"/classes/{class_id}/students/import",
        headers=headers,
        files={"file": ("list_notescc.xlsx", roster, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert import_resp.status_code == 200
    assert import_resp.json()["created"] == 2

    students = client.get(f"/classes/{class_id}/students", headers=headers).json()
    assert len(students) == 2
    ismail = next(row for row in students if row["student_code"] == "A161027646")
    assert ismail["external_id"] == "10934196"
    assert ismail["birth_date"] == "2011-03-23"


def test_exam_import_from_id_name_birthdate_notes_layout(client):
    headers = _auth_headers(client)
    class_resp = client.post("/classes", json={"name": "Exam Notes Layout"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = class_resp.json()["id"]

    roster = _build_notescc_list_file(
        [
            ("2001", "STD2001", "Sara", "14-08-2012"),
            ("2002", "STD2002", "Omar", "01-03-2012"),
        ]
    )
    import_resp = client.post(
        f"/classes/{class_id}/students/import",
        headers=headers,
        files={"file": ("students_layout.xlsx", roster, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert import_resp.status_code == 200

    exam_resp = client.post(
        f"/classes/{class_id}/exams",
        headers=headers,
        json={"title": "CC Layout", "exam_date": "2026-03-09", "max_score": 20, "weight": 1},
    )
    assert exam_resp.status_code == 201
    exam_id = exam_resp.json()["id"]

    results_file = _build_exam_list_file(
        [
            ("STD2001", "Sara", "2012-08-14", 12, 14, 16, 15.5),
            ("STD2002", "Omar", "2012-03-01", 10, 11, 13, 12.0),
        ]
    )
    import_exam_resp = client.post(
        f"/exams/{exam_id}/results/import",
        headers=headers,
        files={"file": ("results_layout.xlsx", results_file, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert import_exam_resp.status_code == 200
    assert import_exam_resp.json()["imported"] == 2

    results_resp = client.get(f"/exams/{exam_id}/results", headers=headers)
    assert results_resp.status_code == 200
    result_map = {row["student_code"]: float(row["score"]) for row in results_resp.json()}
    assert result_map["STD2001"] == 15.5
    assert result_map["STD2002"] == 12.0


def test_exam_update_archive_restore(client):
    headers = _auth_headers(client)
    class_resp = client.post("/classes", json={"name": "Exam Archive Class"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = class_resp.json()["id"]

    roster = _build_roster_file([("STD300", "Rita"), ("STD301", "Amine")])
    roster_resp = client.post(
        f"/classes/{class_id}/students/import",
        headers=headers,
        files={"file": ("students.xlsx", roster, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert roster_resp.status_code == 200

    exam_resp = client.post(
        f"/classes/{class_id}/exams",
        headers=headers,
        json={"title": "CC-Archive", "exam_date": "2026-03-05", "max_score": 20, "weight": 1},
    )
    assert exam_resp.status_code == 201
    exam_id = exam_resp.json()["id"]

    update_resp = client.put(
        f"/exams/{exam_id}",
        headers=headers,
        json={"title": "CC-Archive-Updated", "max_score": 25, "weight": 2},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["title"] == "CC-Archive-Updated"
    assert float(update_resp.json()["max_score"]) == 25.0
    assert float(update_resp.json()["weight"]) == 2.0

    archive_resp = client.post(f"/exams/{exam_id}/archive", headers=headers)
    assert archive_resp.status_code == 200
    assert archive_resp.json()["is_archived"] is True

    list_default = client.get(f"/classes/{class_id}/exams", headers=headers)
    assert list_default.status_code == 200
    assert all(exam["id"] != exam_id for exam in list_default.json())

    list_all = client.get(f"/classes/{class_id}/exams?include_archived=true", headers=headers)
    assert list_all.status_code == 200
    archived_row = next(exam for exam in list_all.json() if exam["id"] == exam_id)
    assert archived_row["is_archived"] is True

    results_file = _build_exam_file(
        [
            ("STD300", "Rita", 18, "A", ""),
            ("STD301", "Amine", 19, "A+", ""),
        ]
    )
    import_blocked_resp = client.post(
        f"/exams/{exam_id}/results/import",
        headers=headers,
        files={"file": ("results.xlsx", results_file, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert import_blocked_resp.status_code == 409

    restore_resp = client.post(f"/exams/{exam_id}/restore", headers=headers)
    assert restore_resp.status_code == 200
    assert restore_resp.json()["is_archived"] is False

    import_ok_resp = client.post(
        f"/exams/{exam_id}/results/import",
        headers=headers,
        files={"file": ("results.xlsx", results_file, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert import_ok_resp.status_code == 200
    assert import_ok_resp.json()["imported"] == 2


def test_import_notescc_exam_format_and_template_export(client):
    headers = _auth_headers(client)
    class_resp = client.post("/classes", json={"name": "2APIC-3", "subject": "Math"}, headers=headers)
    class_id = class_resp.json()["id"]
    roster = _build_roster_file([("STD100", "Amina"), ("STD101", "Salim")])
    client.post(
        f"/classes/{class_id}/students/import",
        headers=headers,
        files={"file": ("students.xlsx", roster, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    exam_resp = client.post(
        f"/classes/{class_id}/exams",
        headers=headers,
        json={"title": "CC1", "exam_date": "2026-03-03", "max_score": 20, "weight": 1},
    )
    exam_id = exam_resp.json()["id"]

    notescc_file = _build_notescc_exam_file([("STD100", "Amina", 14), ("STD101", "Salim", 17.5)])
    import_resp = client.post(
        f"/exams/{exam_id}/results/import",
        headers=headers,
        files={"file": ("notescc.xlsx", notescc_file, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert import_resp.status_code == 200
    assert import_resp.json()["imported"] == 2

    template_wb = Workbook()
    template_sheet = template_wb.active
    template_sheet.title = "NotesCC"
    with NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        template_wb.save(tmp.name)
        template_path = tmp.name
    os.environ["PRINCIPAL_EXPORT_TEMPLATE"] = template_path
    try:
        notescc_template_resp = client.get(f"/exams/{exam_id}/template?format=notescc", headers=headers)
        assert notescc_template_resp.status_code == 200
        notescc_wb = load_workbook(filename=BytesIO(notescc_template_resp.content), data_only=True)
        assert "NotesCC" in notescc_wb.sheetnames

        export_resp = client.get(f"/classes/{class_id}/reports/official-notes.xlsx", headers=headers)
        assert export_resp.status_code == 200
        out_wb = load_workbook(filename=BytesIO(export_resp.content), data_only=True)
        out_sheet = out_wb["NotesCC"]
        assert out_sheet["I9"].value == "2APIC-3"
        assert out_sheet["O11"].value == "Math"
        # Row ordering is by student full name asc -> Amina first.
        assert out_sheet.cell(18, 3).value == "STD100"
        assert float(out_sheet.cell(18, 7).value) == 14.0
    finally:
        os.environ.pop("PRINCIPAL_EXPORT_TEMPLATE", None)
        try:
            os.remove(template_path)
        except OSError:
            pass


def test_export_history_and_audit_logs(client):
    headers = _auth_headers(client)
    class_resp = client.post("/classes", json={"name": "Audit Export Class", "subject": "Math"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = class_resp.json()["id"]

    roster = _build_roster_file([("STD200", "Ilyas"), ("STD201", "Nisrine")])
    import_resp = client.post(
        f"/classes/{class_id}/students/import",
        headers=headers,
        files={"file": ("students.xlsx", roster, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert import_resp.status_code == 200

    exam_resp = client.post(
        f"/classes/{class_id}/exams",
        headers=headers,
        json={"title": "CC-Audit", "exam_date": "2026-03-04", "max_score": 20, "weight": 1},
    )
    assert exam_resp.status_code == 201
    exam_id = exam_resp.json()["id"]

    results_file = _build_exam_file(
        [
            ("STD200", "Ilyas", 13.5, "C+", ""),
            ("STD201", "Nisrine", 17.0, "A-", ""),
        ]
    )
    import_exam_resp = client.post(
        f"/exams/{exam_id}/results/import",
        headers=headers,
        files={"file": ("results.xlsx", results_file, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert import_exam_resp.status_code == 200

    pdf_export = client.get(f"/classes/{class_id}/reports/full.pdf", headers=headers)
    assert pdf_export.status_code == 200
    assert pdf_export.content.startswith(b"%PDF")
    notes_export = client.get(f"/classes/{class_id}/reports/official-notes.xlsx", headers=headers)
    assert notes_export.status_code == 200

    history_resp = client.get(f"/classes/{class_id}/exports/history", headers=headers)
    assert history_resp.status_code == 200
    history = history_resp.json()["items"]
    assert len(history) >= 2
    first_id = history[0]["id"]
    assert any(item["export_type"] == "class_full_pdf" for item in history)
    assert any(item["export_type"] == "official_notes_xlsx" for item in history)

    download_resp = client.get(f"/exports/{first_id}/download", headers=headers)
    assert download_resp.status_code == 200

    class_audit_resp = client.get(f"/classes/{class_id}/audit-logs", headers=headers)
    assert class_audit_resp.status_code == 200
    actions = [item["action"] for item in class_audit_resp.json()["items"]]
    assert "report.export" in actions
    assert "students.import" in actions

    owner_audit_resp = client.get("/audit/logs?action=report.export", headers=headers)
    assert owner_audit_resp.status_code == 200
    assert owner_audit_resp.json()["count"] >= 1


def test_masked_export_privacy_mode(client):
    headers = _auth_headers(client)
    class_resp = client.post("/classes", json={"name": "Privacy Class", "subject": "Math"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = class_resp.json()["id"]

    roster = _build_roster_file([("STD500", "Alice Privacy"), ("STD501", "Bob Privacy")])
    import_resp = client.post(
        f"/classes/{class_id}/students/import",
        headers=headers,
        files={"file": ("students.xlsx", roster, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert import_resp.status_code == 200

    students = client.get(f"/classes/{class_id}/students", headers=headers).json()
    session_resp = client.post(
        f"/classes/{class_id}/sessions",
        headers=headers,
        json={"session_date": "2026-03-08", "note": "privacy test"},
    )
    assert session_resp.status_code == 201
    session_id = session_resp.json()["id"]

    attendance_payload = [
        {"student_id": students[0]["id"], "status": "present", "minutes_late": 0, "comment": "present"},
        {"student_id": students[1]["id"], "status": "absent", "minutes_late": 0, "comment": "absent"},
    ]
    attendance_resp = client.put(f"/sessions/{session_id}/attendance", json=attendance_payload, headers=headers)
    assert attendance_resp.status_code == 200

    masked_csv = client.get(f"/classes/{class_id}/attendance-export.csv?mask_personal_data=true", headers=headers)
    assert masked_csv.status_code == 200
    assert "Alice Privacy" not in masked_csv.text
    assert "Bob Privacy" not in masked_csv.text
    assert "STD500" not in masked_csv.text
    assert "STD501" not in masked_csv.text
    assert "ANON001" in masked_csv.text or "ANON002" in masked_csv.text

    exam_resp = client.post(
        f"/classes/{class_id}/exams",
        headers=headers,
        json={"title": "CC-Privacy", "exam_date": "2026-03-08", "max_score": 20, "weight": 1},
    )
    assert exam_resp.status_code == 201
    exam_id = exam_resp.json()["id"]
    results_file = _build_exam_file(
        [
            ("STD500", "Alice Privacy", 14, "B", ""),
            ("STD501", "Bob Privacy", 16, "A", ""),
        ]
    )
    import_exam_resp = client.post(
        f"/exams/{exam_id}/results/import",
        headers=headers,
        files={"file": ("results.xlsx", results_file, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert import_exam_resp.status_code == 200

    masked_notes = client.get(f"/classes/{class_id}/reports/official-notes.xlsx?mask_personal_data=true", headers=headers)
    assert masked_notes.status_code == 200
    wb = load_workbook(filename=BytesIO(masked_notes.content), data_only=True)
    if "NotesCC" in wb.sheetnames:
        sheet = wb["NotesCC"]
        assert str(sheet.cell(18, 3).value).startswith("ANON")
        assert str(sheet.cell(18, 4).value).startswith("Student")
    else:
        sheet = wb.active
        assert str(sheet.cell(3, 1).value).startswith("ANON")
        assert str(sheet.cell(3, 2).value).startswith("Student")

    history_resp = client.get(f"/classes/{class_id}/exports/history", headers=headers)
    assert history_resp.status_code == 200
    export_types = {item["export_type"] for item in history_resp.json()["items"]}
    assert "official_notes_xlsx_masked" in export_types


def test_upload_validation_rejects_invalid_file_types(client):
    headers = _auth_headers(client)
    class_resp = client.post("/classes", json={"name": "Upload Validation"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = class_resp.json()["id"]

    invalid_roster_resp = client.post(
        f"/classes/{class_id}/students/import",
        headers=headers,
        files={"file": ("students.txt", b"not-an-excel", "text/plain")},
    )
    assert invalid_roster_resp.status_code == 400

    roster = _build_roster_file([("STD900", "Sara")])
    roster_resp = client.post(
        f"/classes/{class_id}/students/import",
        headers=headers,
        files={"file": ("students.xlsx", roster, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert roster_resp.status_code == 200

    session_resp = client.post(
        f"/classes/{class_id}/sessions",
        headers=headers,
        json={"session_date": "2026-03-06"},
    )
    assert session_resp.status_code == 201
    session_id = session_resp.json()["id"]

    invalid_image_resp = client.post(
        f"/sessions/{session_id}/uploads",
        headers=headers,
        files={"file": ("board.txt", b"plain text", "text/plain")},
        data={"raw_text": "1 Algebra"},
    )
    assert invalid_image_resp.status_code == 400

    exam_resp = client.post(
        f"/classes/{class_id}/exams",
        headers=headers,
        json={"title": "CC-Upload", "exam_date": "2026-03-06", "max_score": 20, "weight": 1},
    )
    assert exam_resp.status_code == 201
    exam_id = exam_resp.json()["id"]

    invalid_exam_import_resp = client.post(
        f"/exams/{exam_id}/results/import",
        headers=headers,
        files={"file": ("results.csv", b"code,score", "text/csv")},
    )
    assert invalid_exam_import_resp.status_code == 400


def test_owner_audit_csv_and_teacher_forbidden(client):
    owner_headers = _auth_headers(client)
    _ = client.post("/classes", json={"name": "Owner Audit Class"}, headers=owner_headers)

    owner_csv = client.get("/audit/logs.csv?limit=20", headers=owner_headers)
    assert owner_csv.status_code == 200
    assert "text/csv" in owner_csv.headers["content-type"]
    assert "id,created_at,user_id,action,entity_type,entity_id,class_id,details" in owner_csv.text

    owner_future_json = client.get("/audit/logs?date_from=2100-01-01&limit=20", headers=owner_headers)
    assert owner_future_json.status_code == 200
    assert owner_future_json.json()["count"] == 0

    owner_future_csv = client.get("/audit/logs.csv?date_from=2100-01-01&limit=20", headers=owner_headers)
    assert owner_future_csv.status_code == 200
    csv_lines = [line for line in owner_future_csv.text.strip().splitlines() if line.strip()]
    assert len(csv_lines) == 1
    assert csv_lines[0].startswith("id,created_at,user_id,action,entity_type,entity_id,class_id,details")

    _, teacher_headers = _create_teacher_and_login(client, owner_headers)
    teacher_json_forbidden = client.get("/audit/logs", headers=teacher_headers)
    assert teacher_json_forbidden.status_code == 403
    teacher_csv_forbidden = client.get("/audit/logs.csv", headers=teacher_headers)
    assert teacher_csv_forbidden.status_code == 403


def test_owner_ops_status_and_teacher_forbidden(client):
    owner_headers = _auth_headers(client)
    owner_resp = client.get("/ops/status", headers=owner_headers)
    assert owner_resp.status_code == 200
    payload = owner_resp.json()
    assert payload["status"] == "ok"
    assert "uptime_seconds" in payload
    assert "storage" in payload
    assert "backups" in payload
    assert "alerts" in payload
    assert "enabled" in payload["alerts"]

    _, teacher_headers = _create_teacher_and_login(client, owner_headers)
    teacher_resp = client.get("/ops/status", headers=teacher_headers)
    assert teacher_resp.status_code == 403


def test_rate_limiting_upload_and_export(client):
    from app import config as app_config
    from app.services.rate_limit import reset_rate_limits

    headers = _auth_headers(client)
    class_resp = client.post("/classes", json={"name": "Rate Limit Class"}, headers=headers)
    assert class_resp.status_code == 201
    class_id = class_resp.json()["id"]

    roster = _build_roster_file([("STD950", "Nawal")])
    roster_resp = client.post(
        f"/classes/{class_id}/students/import",
        headers=headers,
        files={"file": ("students.xlsx", roster, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert roster_resp.status_code == 200

    session_resp = client.post(
        f"/classes/{class_id}/sessions",
        headers=headers,
        json={"session_date": "2026-03-07"},
    )
    assert session_resp.status_code == 201
    session_id = session_resp.json()["id"]

    old_upload_count = app_config.UPLOAD_RATE_LIMIT_COUNT
    old_upload_window = app_config.UPLOAD_RATE_LIMIT_WINDOW_SECONDS
    old_export_count = app_config.EXPORT_RATE_LIMIT_COUNT
    old_export_window = app_config.EXPORT_RATE_LIMIT_WINDOW_SECONDS
    try:
        app_config.UPLOAD_RATE_LIMIT_COUNT = 2
        app_config.UPLOAD_RATE_LIMIT_WINDOW_SECONDS = 60
        reset_rate_limits()

        upload1 = client.post(
            f"/sessions/{session_id}/uploads",
            headers=headers,
            files={"file": ("board.jpg", b"fake-image", "image/jpeg")},
            data={"raw_text": "1 Algebra"},
        )
        assert upload1.status_code == 201
        upload2 = client.post(
            f"/sessions/{session_id}/uploads",
            headers=headers,
            files={"file": ("board.jpg", b"fake-image", "image/jpeg")},
            data={"raw_text": "1 Algebra"},
        )
        assert upload2.status_code == 201
        upload3 = client.post(
            f"/sessions/{session_id}/uploads",
            headers=headers,
            files={"file": ("board.jpg", b"fake-image", "image/jpeg")},
            data={"raw_text": "1 Algebra"},
        )
        assert upload3.status_code == 429

        app_config.EXPORT_RATE_LIMIT_COUNT = 1
        app_config.EXPORT_RATE_LIMIT_WINDOW_SECONDS = 60
        reset_rate_limits()
        export1 = client.get(f"/classes/{class_id}/attendance-export.csv", headers=headers)
        assert export1.status_code == 200
        export2 = client.get(f"/classes/{class_id}/attendance-export.csv", headers=headers)
        assert export2.status_code == 429
    finally:
        app_config.UPLOAD_RATE_LIMIT_COUNT = old_upload_count
        app_config.UPLOAD_RATE_LIMIT_WINDOW_SECONDS = old_upload_window
        app_config.EXPORT_RATE_LIMIT_COUNT = old_export_count
        app_config.EXPORT_RATE_LIMIT_WINDOW_SECONDS = old_export_window
        reset_rate_limits()


def test_requires_authentication(client):
    unauthorized = client.get("/classes")
    assert unauthorized.status_code == 401


def test_auth_refresh_rotates_token(client):
    old_headers = _auth_headers(client)
    old_token = old_headers["Authorization"].split(" ", maxsplit=1)[1]
    old_headers = {"Authorization": f"Bearer {old_token}"}

    refresh_resp = client.post("/auth/refresh", headers=old_headers)
    assert refresh_resp.status_code == 200
    new_token = refresh_resp.json()["access_token"]
    assert new_token != old_token

    old_me = client.get("/auth/me", headers=old_headers)
    assert old_me.status_code == 401
    new_me = client.get("/auth/me", headers={"Authorization": f"Bearer {new_token}"})
    assert new_me.status_code == 200


def test_login_lockout_and_owner_unlock(client):
    from app import config as app_config

    owner_headers = _auth_headers(client)
    email = f"locked_{uuid.uuid4().hex[:8]}@app.local"
    password = "TeacherPass123"
    create_resp = client.post(
        "/auth/users",
        headers=owner_headers,
        json={"email": email, "password": password, "full_name": "Lockout Teacher", "role": "teacher"},
    )
    assert create_resp.status_code == 201
    teacher_id = create_resp.json()["id"]

    old_max = app_config.MAX_FAILED_LOGIN_ATTEMPTS
    old_minutes = app_config.LOGIN_LOCKOUT_MINUTES
    try:
        app_config.MAX_FAILED_LOGIN_ATTEMPTS = 2
        app_config.LOGIN_LOCKOUT_MINUTES = 5

        bad1 = client.post("/auth/login", json={"email": email, "password": "wrong-1"})
        assert bad1.status_code == 401
        bad2 = client.post("/auth/login", json={"email": email, "password": "wrong-2"})
        assert bad2.status_code == 401

        locked_login = client.post("/auth/login", json={"email": email, "password": password})
        assert locked_login.status_code == 423

        users_resp = client.get("/auth/users", headers=owner_headers)
        assert users_resp.status_code == 200
        locked_row = next(row for row in users_resp.json() if row["id"] == teacher_id)
        assert locked_row["locked_until"] is not None

        unlock_resp = client.post(f"/auth/users/{teacher_id}/unlock", headers=owner_headers)
        assert unlock_resp.status_code == 200
        assert unlock_resp.json()["locked_until"] is None
        assert int(unlock_resp.json()["failed_login_attempts"]) == 0

        ok_login = client.post("/auth/login", json={"email": email, "password": password})
        assert ok_login.status_code == 200
        assert "access_token" in ok_login.json()
    finally:
        app_config.MAX_FAILED_LOGIN_ATTEMPTS = old_max
        app_config.LOGIN_LOCKOUT_MINUTES = old_minutes


def test_teacher_class_isolation_and_assignment(client):
    owner_headers = _auth_headers(client)
    teacher_id, teacher_headers = _create_teacher_and_login(client, owner_headers)

    owner_class_resp = client.post("/classes", headers=owner_headers, json={"name": "Owner Class"})
    assert owner_class_resp.status_code == 201
    owner_class_id = owner_class_resp.json()["id"]

    teacher_list_before = client.get("/classes", headers=teacher_headers)
    assert teacher_list_before.status_code == 200
    assert all(row["id"] != owner_class_id for row in teacher_list_before.json())

    forbidden_get = client.get(f"/classes/{owner_class_id}", headers=teacher_headers)
    assert forbidden_get.status_code == 403

    assigned_class_resp = client.post(
        "/classes",
        headers=owner_headers,
        json={"name": "Assigned Class", "teacher_user_id": teacher_id},
    )
    assert assigned_class_resp.status_code == 201
    assigned_class_id = assigned_class_resp.json()["id"]

    teacher_list_after = client.get("/classes", headers=teacher_headers)
    assert teacher_list_after.status_code == 200
    ids_after = {row["id"] for row in teacher_list_after.json()}
    assert assigned_class_id in ids_after
    assert owner_class_id not in ids_after

    owner_view_teacher_classes = client.get(f"/classes/by-teacher/{teacher_id}", headers=owner_headers)
    assert owner_view_teacher_classes.status_code == 200
    owner_view_ids = {row["id"] for row in owner_view_teacher_classes.json()}
    assert assigned_class_id in owner_view_ids
    assert owner_class_id not in owner_view_ids

    owner_overview = client.get("/classes/owner-overview", headers=owner_headers)
    assert owner_overview.status_code == 200
    overview_payload = owner_overview.json()
    assert overview_payload["counts"]["teachers"] >= 1
    teacher_overview_rows = [row for row in overview_payload["teachers"] if row["teacher_id"] == teacher_id]
    assert teacher_overview_rows
    assert teacher_overview_rows[0]["assigned_classes"] >= 1

    teacher_forbidden_owner_view = client.get(f"/classes/by-teacher/{teacher_id}", headers=teacher_headers)
    assert teacher_forbidden_owner_view.status_code == 403
    teacher_forbidden_owner_overview = client.get("/classes/owner-overview", headers=teacher_headers)
    assert teacher_forbidden_owner_overview.status_code == 403

    assign_resp = client.post(f"/classes/{owner_class_id}/assign-teacher/{teacher_id}", headers=owner_headers)
    assert assign_resp.status_code == 204

    class_teachers_owner = client.get(f"/classes/{owner_class_id}/teachers", headers=owner_headers)
    assert class_teachers_owner.status_code == 200
    teacher_ids = {row["id"] for row in class_teachers_owner.json()}
    assert teacher_id in teacher_ids

    class_teachers_teacher_forbidden = client.get(f"/classes/{owner_class_id}/teachers", headers=teacher_headers)
    assert class_teachers_teacher_forbidden.status_code == 403

    teacher_get_after_assign = client.get(f"/classes/{owner_class_id}", headers=teacher_headers)
    assert teacher_get_after_assign.status_code == 200

    unassign_resp = client.delete(f"/classes/{owner_class_id}/assign-teacher/{teacher_id}", headers=owner_headers)
    assert unassign_resp.status_code == 204

    owner_view_after_unassign = client.get(f"/classes/by-teacher/{teacher_id}", headers=owner_headers)
    assert owner_view_after_unassign.status_code == 200
    owner_view_after_ids = {row["id"] for row in owner_view_after_unassign.json()}
    assert assigned_class_id in owner_view_after_ids
    assert owner_class_id not in owner_view_after_ids

    teacher_get_after_unassign = client.get(f"/classes/{owner_class_id}", headers=teacher_headers)
    assert teacher_get_after_unassign.status_code == 403


def test_owner_teacher_status_reset_and_password_change(client):
    owner_headers = _auth_headers(client)
    owner_me = client.get("/auth/me", headers=owner_headers)
    assert owner_me.status_code == 200
    owner_id = owner_me.json()["id"]

    deactivate_owner_resp = client.patch(
        f"/auth/users/{owner_id}/status",
        headers=owner_headers,
        json={"is_active": False},
    )
    assert deactivate_owner_resp.status_code == 400

    email = f"teacher_{uuid.uuid4().hex[:8]}@app.local"
    password = "TeacherPass123"
    create_resp = client.post(
        "/auth/users",
        headers=owner_headers,
        json={"email": email, "password": password, "full_name": "Teacher Status", "role": "teacher"},
    )
    assert create_resp.status_code == 201
    teacher_id = create_resp.json()["id"]

    teacher_headers = _login_headers(client, email, password)
    me_resp = client.get("/auth/me", headers=teacher_headers)
    assert me_resp.status_code == 200

    deactivate_resp = client.patch(
        f"/auth/users/{teacher_id}/status",
        headers=owner_headers,
        json={"is_active": False},
    )
    assert deactivate_resp.status_code == 200
    assert deactivate_resp.json()["is_active"] is False

    stale_token_resp = client.get("/auth/me", headers=teacher_headers)
    assert stale_token_resp.status_code == 401
    inactive_login_resp = client.post("/auth/login", json={"email": email, "password": password})
    assert inactive_login_resp.status_code == 403

    reactivate_resp = client.patch(
        f"/auth/users/{teacher_id}/status",
        headers=owner_headers,
        json={"is_active": True},
    )
    assert reactivate_resp.status_code == 200
    assert reactivate_resp.json()["is_active"] is True
    _ = _login_headers(client, email, password)

    reset_resp = client.post(
        f"/auth/users/{teacher_id}/reset-password",
        headers=owner_headers,
        json={"new_password": "TeacherPass456"},
    )
    assert reset_resp.status_code == 200
    old_login_after_reset = client.post("/auth/login", json={"email": email, "password": password})
    assert old_login_after_reset.status_code == 401

    teacher_headers_new = _login_headers(client, email, "TeacherPass456")
    change_password_resp = client.post(
        "/auth/change-password",
        headers=teacher_headers_new,
        json={"current_password": "TeacherPass456", "new_password": "TeacherPass789"},
    )
    assert change_password_resp.status_code == 200

    stale_after_change = client.get("/auth/me", headers=teacher_headers_new)
    assert stale_after_change.status_code == 401
    final_login = client.post("/auth/login", json={"email": email, "password": "TeacherPass789"})
    assert final_login.status_code == 200


def test_owner_send_invite_requires_smtp_config(client):
    owner_headers = _auth_headers(client)
    create_resp = client.post(
        "/auth/users",
        headers=owner_headers,
        json={
            "email": f"teacher_{uuid.uuid4().hex[:8]}@app.local",
            "password": "TeacherPass123",
            "full_name": "Invite Teacher",
            "role": "teacher",
        },
    )
    assert create_resp.status_code == 201
    teacher_id = create_resp.json()["id"]

    invite_resp = client.post(
        f"/auth/users/{teacher_id}/send-invite",
        headers=owner_headers,
        json={"temporary_password": "TeacherPass123", "app_url": "http://127.0.0.1:8000/app"},
    )
    assert invite_resp.status_code == 400
    assert "SMTP is not configured." in str(invite_resp.json()["detail"])


def test_owner_send_invite_success_with_mocked_mailer(client, monkeypatch):
    owner_headers = _auth_headers(client)
    create_resp = client.post(
        "/auth/users",
        headers=owner_headers,
        json={
            "email": f"teacher_{uuid.uuid4().hex[:8]}@app.local",
            "password": "TeacherPass123",
            "full_name": "Invite Teacher",
            "role": "teacher",
        },
    )
    assert create_resp.status_code == 201
    teacher_id = create_resp.json()["id"]
    teacher_email = create_resp.json()["email"]

    sent_payload: dict[str, str] = {}

    def fake_send_email(*, to_email: str, subject: str, body_text: str) -> None:
        sent_payload["to_email"] = to_email
        sent_payload["subject"] = subject
        sent_payload["body_text"] = body_text

    monkeypatch.setattr("app.routers.auth.smtp_is_configured", lambda: True)
    monkeypatch.setattr("app.routers.auth.send_email", fake_send_email)

    invite_resp = client.post(
        f"/auth/users/{teacher_id}/send-invite",
        headers=owner_headers,
        json={"temporary_password": "TeacherPass123", "app_url": "http://127.0.0.1:8000/app"},
    )
    assert invite_resp.status_code == 200
    payload = invite_resp.json()
    assert payload["sent"] is True
    assert payload["to_email"] == teacher_email
    assert payload["app_url"] == "http://127.0.0.1:8000/app"
    assert payload["included_temporary_password"] is True
    assert sent_payload["to_email"] == teacher_email
    assert "Teacher Platform Login Details" in sent_payload["subject"]
    assert "Temporary password: TeacherPass123" in sent_payload["body_text"]
