import json
import sys
from types import SimpleNamespace
from importlib import import_module


def _clear_report_modules() -> None:
    for name in [
        "app.services.report",
        "app.config",
        "app.database",
        "app.models",
    ]:
        sys.modules.pop(name, None)


def test_collect_ai_session_narratives_parses_french_learning_focus_and_sections(monkeypatch):
    report = import_module("app.services.report")

    try:
        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "sessions": [
                                            {
                                                "session_id": 7,
                                                "learning_focus": [
                                                    "Introduction aux nombres rationnels",
                                                    "Comparaison de deux nombres relatifs",
                                                ],
                                                "summary": "Seance d'introduction aux nombres rationnels.",
                                                "paragraph": "La seance a permis de definir les nombres rationnels et d'expliquer leur comparaison a partir d'exemples simples.",
                                                "sections": [
                                                    {
                                                        "heading": "1. Les nombres rationnels",
                                                        "subheadings": [
                                                            "1.1 Definition",
                                                            "1.2 Exemples d'ecriture fractionnaire",
                                                        ],
                                                    }
                                                ],
                                                "admin_note": "Trace ecrite finalisee.",
                                            }
                                        ]
                                    },
                                    ensure_ascii=False,
                                )
                            }
                        }
                    ]
                }

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def post(self, *args, **kwargs):
                return FakeResponse()

        monkeypatch.setattr(report.app_config, "OPENAI_API_KEY", "test-key")
        monkeypatch.setattr(report.httpx, "Client", FakeClient)

        rows = report._collect_ai_session_narratives(
            [
                {
                    "session_id": 7,
                    "session_content": ["Definition des nombres rationnels."],
                    "confirmed_checklist_titles": ["1. Definition", "1.1 Ecriture fractionnaire"],
                    "teacher_note": "",
                }
            ]
        )

        assert 7 in rows
        assert rows[7]["paragraph"] == (
            "La seance a permis de definir les nombres rationnels et d'expliquer leur comparaison a partir d'exemples simples."
        )
    finally:
        _clear_report_modules()


def test_default_session_outline_uses_confirmed_titles_as_subheadings():
    report = import_module("app.services.report")
    try:
        outline = report._default_session_outline(
            focus_items=["Introduction aux nombres rationnels."],
            checked_titles=[
                "1. Definition des nombres rationnels",
                "2. Comparaison de deux nombres relatifs",
                "3. Lecture d'une fraction",
            ],
        )

        assert outline == [
            {
                "heading": "Introduction aux nombres rationnels",
                "subheadings": [
                    "Definition des nombres rationnels",
                    "Comparaison de deux nombres relatifs",
                    "Lecture d'une fraction",
                ],
            }
        ]
    finally:
        _clear_report_modules()


def test_merge_headlines_includes_progress_structure_rows():
    report = import_module("app.services.report")
    try:
        item_1 = SimpleNamespace(heading="1.1) Connaitre les regles d'addition et de soustraction", content=None)
        item_2 = SimpleNamespace(heading="Activity", content="1.2.1) Operations sur les nombres decimaux relatifs")

        progress_rows = []
        progress_rows.extend(report._extract_headline_candidates_from_progress_item(item_1))
        progress_rows.extend(report._extract_headline_candidates_from_progress_item(item_2))

        merged = report._merge_headline_candidates(
            ["1.1) Connaitre les regles d'addition et de soustraction"],
            progress_rows,
        )

        assert merged == [
            "1.1) Connaitre les regles d'addition et de soustraction",
            "1.2.1) Operations sur les nombres decimaux relatifs",
        ]
    finally:
        _clear_report_modules()


def test_dedupe_focus_items_against_outline_removes_duplicates():
    report = import_module("app.services.report")
    try:
        outline = [
            {
                "heading": "Utiliser l'equivalence entre deux nombres rationnels",
                "subheadings": [
                    "Comparer deux fractions",
                    "Simplification d'un nombre rationnel",
                ],
            }
        ]
        focus = [
            "Utiliser l'equivalence entre deux nombres rationnels.",
            "Comparer deux fractions.",
            "Resoudre des exercices de mise en pratique.",
        ]

        filtered = report._dedupe_focus_items_against_outline(focus, outline)
        assert filtered == ["Resoudre des exercices de mise en pratique."]
    finally:
        _clear_report_modules()


def test_focus_summary_from_outline_is_generated_when_focus_is_empty():
    report = import_module("app.services.report")
    try:
        outline = [
            {
                "heading": "Comparer deux fractions",
                "subheadings": [
                    "Simplification d'un nombre rationnel",
                ],
            }
        ]
        summary_line = report._build_focus_summary_from_outline(outline)
        lowered = summary_line.lower()
        assert "comparer deux fractions" in lowered
        assert "simplification d'un nombre rationnel" in lowered
    finally:
        _clear_report_modules()
