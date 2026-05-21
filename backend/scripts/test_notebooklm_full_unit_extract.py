from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from notebooklm import NotebookLMClient

from app.models import WorkflowUnitType
from app.services.workflow_generation import _build_notebooklm_content_pack_prompt


REFINED_FULL_UNIT_PROMPT = """
Lis ce PDF comme une unite pedagogique complete de mathematiques.

Retourne uniquement un JSON strict avec cette forme:
{
  "unit_title": "...",
  "sections": [
    {
      "section_title": "titre exact de la section pedagogique la plus precise",
      "section_path": ["grand titre", "sous-titre exact", "sous-section exacte si visible"],
      "order_index": 1,
      "blocks": [
        {
          "kind": "activity|lesson|definition|property|example|exercise|evaluation|content",
          "title": "titre exact du bloc si visible",
          "exact_text": "texte exact utile du document pour ce bloc, sans resume et sans ajout",
          "order_index": 1
        }
      ]
    }
  ]
}

Regles obligatoires:
- Garde l'ordre exact du document.
- N'utilise PAS des sections generiques comme "Activites", "Contenu de la lecon", "Exercices" ou "Evaluation" comme section principale s'il existe une section pedagogique plus precise dans le document.
- Chaque activite, exemple, propriete ou exercice doit etre rattache a la section exacte qu'il prepare, illustre ou evalue.
- Garde les grands titres et sous-titres visibles comme chemins de section.
- Pour chaque bloc, copie le contenu utile du PDF de la maniere la plus fidele possible.
- N'ajoute aucune reformulation pedagogique, aucune synthese, aucune activite nouvelle.
- N'inclus pas les rubriques meta enseignant comme objectifs, prerequis, outils, gestion du temps, competences.
- Si une section contient plusieurs exemples ou exercices, garde-les dans l'ordre comme plusieurs blocks.
- Garde les mathematiques, les listes et les suites d'exercices aussi fidelement que possible.
- Ne retourne aucun commentaire hors JSON.
""".strip()


def _extract_json_payload(text: str) -> dict | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", raw)
    if fenced:
        raw = fenced.group(1).strip()
    else:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            raw = raw[start : end + 1]
    try:
        return json.loads(raw)
    except Exception:
        return None


def _summarize_payload(label: str, payload: dict | None) -> str:
    if not isinstance(payload, dict):
        return f"{label}: invalid JSON"
    if isinstance(payload.get("content_blocks"), list):
        rows = payload.get("content_blocks") if isinstance(payload.get("content_blocks"), list) else []
        sections: list[str] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            path = row.get("section_path") if isinstance(row.get("section_path"), list) else [row.get("section_title")]
            path_label = " > ".join(str(part or "").strip() for part in path if str(part or "").strip())
            if path_label and path_label not in sections:
                sections.append(path_label)
        lines = [f"{label}: {len(rows)} blocks / {len(sections)} unique sections"]
        lines.extend(f"- {row}" for row in sections[:12])
        return "\n".join(lines)
    sections = payload.get("sections") if isinstance(payload.get("sections"), list) else []
    lines = [f"{label}: {len(sections)} sections"]
    for row in sections[:12]:
        if not isinstance(row, dict):
            continue
        path_label = " > ".join(str(part or "").strip() for part in (row.get("section_path") or []) if str(part or "").strip())
        block_count = len(row.get("blocks") or []) if isinstance(row.get("blocks"), list) else 0
        lines.append(f"- {path_label} | blocks={block_count}")
    return "\n".join(lines)


async def _run(pdf_path: Path, *, title: str, unit_type: WorkflowUnitType, output_dir: Path) -> None:
    client = await NotebookLMClient.from_storage(profile="default", timeout=180.0)
    async with client as opened:
        notebook = await opened.notebooks.create(f"Full unit extract benchmark - {pdf_path.stem}")
        notebook_id = str(notebook.id)
        try:
            try:
                source = await opened.sources.add_file(notebook_id, str(pdf_path), wait=True, wait_timeout=240.0)
            except Exception as exc:
                (output_dir / "source_error.txt").write_text(
                    f"NotebookLM source processing failed for {pdf_path.name}\n{type(exc).__name__}: {exc}\n",
                    encoding="utf-8",
                )
                print(f"PDF: {pdf_path}")
                print(f"Artifacts: {output_dir}")
                print("")
                print(f"source_error: {type(exc).__name__}: {exc}")
                return
            source_id = str(source.id)
            current_prompt = _build_notebooklm_content_pack_prompt(unit_type=unit_type, title=title)
            current_answer = await opened.chat.ask(notebook_id, current_prompt, source_ids=[source_id])
            refined_answer = await opened.chat.ask(notebook_id, REFINED_FULL_UNIT_PROMPT, source_ids=[source_id])
            current_text = str(getattr(current_answer, "answer", "") or "").strip()
            refined_text = str(getattr(refined_answer, "answer", "") or "").strip()

            (output_dir / "current_prompt.txt").write_text(current_prompt, encoding="utf-8")
            (output_dir / "current_answer.txt").write_text(current_text, encoding="utf-8")
            (output_dir / "refined_prompt.txt").write_text(REFINED_FULL_UNIT_PROMPT, encoding="utf-8")
            (output_dir / "refined_answer.txt").write_text(refined_text, encoding="utf-8")

            current_payload = _extract_json_payload(current_text)
            refined_payload = _extract_json_payload(refined_text)
            if current_payload is not None:
                (output_dir / "current_parsed.json").write_text(
                    json.dumps(current_payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            if refined_payload is not None:
                (output_dir / "refined_parsed.json").write_text(
                    json.dumps(refined_payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

            print(f"PDF: {pdf_path}")
            print(f"Artifacts: {output_dir}")
            print("")
            print(_summarize_payload("current", current_payload))
            print("")
            print(_summarize_payload("refined", refined_payload))
        finally:
            await opened.notebooks.delete(notebook_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark current vs strict full-unit NotebookLM extraction for one PDF.")
    parser.add_argument("pdf_path", help="Path to the PDF to test.")
    parser.add_argument("--title", required=True, help="Expected unit title.")
    parser.add_argument(
        "--unit-type",
        choices=[item.value for item in WorkflowUnitType],
        default=WorkflowUnitType.CHAPTER.value,
        help="Workflow unit type. Default: chapter.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(Path.cwd() / ".tmp_notebooklm_full_unit_extract"),
        help="Directory where prompt and answer artifacts will be written.",
    )
    args = parser.parse_args()

    pdf_path = Path(args.pdf_path).expanduser().resolve()
    if not pdf_path.exists():
        raise SystemExit(f"PDF not found: {pdf_path}")

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    asyncio.run(
        _run(
            pdf_path,
            title=str(args.title or "").strip() or pdf_path.stem,
            unit_type=WorkflowUnitType(args.unit_type),
            output_dir=output_dir,
        )
    )


if __name__ == "__main__":
    main()
