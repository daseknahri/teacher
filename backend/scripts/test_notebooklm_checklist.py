from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from notebooklm import NotebookLMClient

from app.models import WorkflowUnitType
from app.services import workflow as workflow_service
from app.services.workflow_generation import (
    _build_notebooklm_checklist_prompt,
    _flatten_checklist_nodes,
    generate_unit_checklist_package,
)


MANUAL_PROMPT = """
Lis ce PDF entier comme un manuel scolaire.
Retourne uniquement une liste ordonnee de tous les titres et sous-titres visibles.
Regles:
- Garde seulement les headlines pedagogiques.
- Garde l'ordre exact du document.
- Garde la hierarchie avec indentation.
- Ignore les paragraphes, explications detaillees et metadata.
- Si un titre est coupe sur deux lignes, reconstitue-le.
Format:
- une ligne par titre
- commence chaque ligne par -
- utilise deux espaces d'indentation par niveau
""".strip()


async def run_notebooklm_prompts(pdf_path: Path, app_prompt: str) -> tuple[str, str]:
    client = await NotebookLMClient.from_storage(profile="default", timeout=90.0)
    async with client as opened:
        notebook = await opened.notebooks.create(f"Checklist test - {pdf_path.stem}")
        notebook_id = str(notebook.id)
        try:
            source = await opened.sources.add_file(notebook_id, str(pdf_path), wait=True, wait_timeout=180.0)
            source_id = str(source.id)
            manual = await opened.chat.ask(notebook_id, MANUAL_PROMPT, source_ids=[source_id])
            app = await opened.chat.ask(notebook_id, app_prompt, source_ids=[source_id])
            return (
                str(getattr(manual, "answer", "") or "").strip(),
                str(getattr(app, "answer", "") or "").strip(),
            )
        finally:
            await opened.notebooks.delete(notebook_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare direct NotebookLM checklist prompts for one PDF.")
    parser.add_argument("pdf_path", help="Absolute or relative path to the PDF")
    parser.add_argument("--title", required=True, help="Unit title to use in app prompt/package generation")
    parser.add_argument("--session-count", type=int, default=6, help="Session count for package generation")
    parser.add_argument("--unit-type", choices=[item.value for item in WorkflowUnitType], default=WorkflowUnitType.CHAPTER.value)
    parser.add_argument(
        "--output-dir",
        default=str(Path.cwd().parent / ".tmp_notebooklm_cli"),
        help="Directory where prompt/response artifacts will be written",
    )
    args = parser.parse_args()

    pdf_path = Path(args.pdf_path).expanduser().resolve()
    if not pdf_path.exists():
        raise SystemExit(f"PDF not found: {pdf_path}")

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    unit_type = WorkflowUnitType(args.unit_type)
    app_prompt = _build_notebooklm_checklist_prompt(
        unit_type=unit_type,
        title=args.title,
        source_hint="",
        session_count=args.session_count,
        outline_hint_lines=None,
    )

    manual_answer, app_answer = asyncio.run(run_notebooklm_prompts(pdf_path, app_prompt))

    source_text = workflow_service.extract_text_from_document(str(pdf_path))
    package = generate_unit_checklist_package(
        unit_type=unit_type,
        title=args.title,
        source_text=source_text,
        session_count=args.session_count,
        provider="notebooklm",
        document_path=str(pdf_path),
    )

    (output_dir / "manual_prompt.txt").write_text(MANUAL_PROMPT, encoding="utf-8")
    (output_dir / "app_prompt.txt").write_text(app_prompt, encoding="utf-8")
    (output_dir / "manual_answer.txt").write_text(manual_answer, encoding="utf-8")
    (output_dir / "app_answer.txt").write_text(app_answer, encoding="utf-8")

    print(f"PDF: {pdf_path}")
    print(f"Artifacts: {output_dir}")
    print("\n===== MANUAL RESPONSE =====\n")
    print(manual_answer)
    print("\n===== APP RESPONSE =====\n")
    print(app_answer)
    print("\n===== FULL PACKAGE =====\n")
    print("SOURCE:", package["source"])
    print("MODEL:", package["model"])
    print("ERROR:", package["error_message"])
    print("RAW RESPONSE MODE:", (package.get("raw_provider_response") or {}).get("response_mode"))
    for row in _flatten_checklist_nodes(package["items"]):
        print("-", row.get("kind"), "|", row.get("title"), "| session=", row.get("session_number"))


if __name__ == "__main__":
    main()
