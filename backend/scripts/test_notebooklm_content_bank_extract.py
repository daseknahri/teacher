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


STRICT_CONTENT_BANK_PROMPT = """
Lis ce PDF comme une unite pedagogique complete de mathematiques.

Ta mission a 2 etapes inseparables:
1. extraire tous les contenus pedagogiques nommes du document
2. construire une sequence pedagogique ordonnee qui reutilise uniquement les noms extraits

Retourne uniquement un JSON strict avec cette forme:
{
  "unit_title": "...",
  "content_bank": [
    {
      "content_name": "nom exact visible du contenu",
      "content_type": "activity|lesson|definition|property|example|exercise|evaluation|content",
      "source_heading_path": ["grand titre", "sous-titre", "sous-section"],
      "source_order": 1,
      "exact_content": "contenu exact utile du PDF pour ce contenu, sans resume, sans ajout, sans reformulation"
    }
  ],
  "pedagogy_sequence": [
    {
      "section_title": "titre pedagogique exact le plus precis",
      "section_path": ["grand titre", "sous-titre", "sous-section"],
      "sequence_order": 1,
      "content_names": ["nom exact 1", "nom exact 2", "nom exact 3"]
    }
  ]
}

Regles obligatoires:
- Le content_bank est la source de verite.
- Chaque entree du pedagogy_sequence doit reutiliser uniquement des content_names deja presents dans content_bank.
- N'invente aucun nom.
- N'ajoute aucune activite, aucune explication, aucune synthese, aucune reformulation.
- Garde l'ordre exact du document.
- N'utilise PAS de buckets generiques comme "Activites", "Exercices", "Contenu de la lecon" comme noms de contenu s'il existe un nom plus precis visible.
- Si le PDF montre "Exercice 1" avec plusieurs sous-questions a), b), c), garde un seul content_name "Exercice 1" et mets les sous-questions dans exact_content.
- Ne cree PAS des faux noms comme "Exercice 1 : 1" ou "Exemple 1 : 2" sauf si le document les affiche vraiment comme noms separes.
- Garde les mathematiques, listes, numerotations et suites d'exercices aussi fidelement que possible.
- Ignore les rubriques meta enseignant comme objectifs, prerequis, competences, outils, gestion du temps.
- Ne retourne aucun commentaire hors JSON.
""".strip()


STRICT_CONTENT_BANK_V2_PROMPT = """
Lis ce PDF comme une unite pedagogique complete de mathematiques.

Ta mission a 2 etapes inseparables:
1. extraire tous les contenus pedagogiques exacts du document dans une banque de contenus
2. construire une sequence pedagogique ordonnee qui reutilise uniquement les identifiants de cette banque

Retourne uniquement un JSON strict avec cette forme:
{
  "unit_title": "...",
  "content_bank": [
    {
      "content_id": "S01-B01",
      "content_label": "nom exact visible du contenu, nettoye sans puce ni etoile",
      "content_type": "activity|lesson|definition|property|example|exercise|evaluation|content",
      "source_heading_path": ["rubrique exacte du document", "sous-rubrique exacte"],
      "pedagogical_section_path": ["grand titre d'apprentissage", "section exacte", "sous-section exacte si visible"],
      "source_order": 1,
      "exact_content": "contenu exact utile du PDF pour ce contenu, sans resume, sans ajout, sans reformulation"
    }
  ],
  "pedagogy_sequence": [
    {
      "section_title": "titre pedagogique exact le plus precis",
      "section_path": ["grand titre d'apprentissage", "section exacte", "sous-section exacte si visible"],
      "sequence_order": 1,
      "content_ids": ["S01-B01", "S01-B02", "S01-B03"]
    }
  ]
}

Regles obligatoires:
- content_bank est la source de verite.
- pedagogy_sequence doit reutiliser uniquement des content_ids deja presents dans content_bank.
- N'invente aucun contenu nouveau.
- N'ajoute aucune activite, aucune synthese, aucune reformulation pedagogique.
- Garde l'ordre exact du document.
- content_label doit reprendre le nom visible le plus proche, mais nettoye sans caracteres decoratifs comme "*", "-", puces ou doubles points inutiles.
- Si le document montre seulement "Règle", "Exemples", "Exercice 1", garde exactement ce label nettoye comme content_label.
- Si deux contenus partagent le meme content_label dans des sections differentes, garde le meme label mais donne des content_id differents.
- source_heading_path doit garder le chemin physique exact du document, meme s'il contient une rubrique generique comme "Activités" ou "Evaluation".
- pedagogical_section_path doit rattacher chaque contenu a la section d'apprentissage la plus precise; n'utilise PAS "Activités", "Evaluation", "Contenu de la leçon" comme chemin pedagogique principal s'il existe une section pedagogique plus precise.
- Si un exercice contient plusieurs sous-questions a), b), c), garde un seul contenu nomme, et laisse les sous-questions dans exact_content.
- Ne cree PAS de faux noms comme "Exercice 1 : 1", "Exemple 1 : 2", "Activité 1 : 1" sauf si ces noms sont visibles tels quels dans le PDF.
- Garde les mathematiques, listes, numerotations et suites d'exercices aussi fidelement que possible.
- Ignore les rubriques meta enseignant comme objectifs, prerequis, competences, outils, gestion du temps.
- Ne retourne aucun commentaire hors JSON.
""".strip()


REFINED_SECTION_PROMPT = """
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
    fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", raw, re.IGNORECASE)
    if fenced:
        raw = fenced.group(1).strip()
    else:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            raw = raw[start : end + 1]
    raw = "".join(ch for ch in raw if ord(ch) >= 32 or ch in "\n\r\t")
    try:
        return json.loads(raw)
    except Exception:
        return None


def _summarize_payload(label: str, payload: dict | None) -> str:
    if not isinstance(payload, dict):
        return f"{label}: invalid JSON"
    if isinstance(payload.get("content_blocks"), list):
        rows = payload.get("content_blocks") if isinstance(payload.get("content_blocks"), list) else []
        section_labels: list[str] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            path = row.get("section_path") if isinstance(row.get("section_path"), list) else [row.get("section_title")]
            text = " > ".join(str(part or "").strip() for part in path if str(part or "").strip())
            if text and text not in section_labels:
                section_labels.append(text)
        lines = [f"{label}: old content_blocks shape | blocks={len(rows)} | sections={len(section_labels)}"]
        lines.extend(f"- {row}" for row in section_labels[:10])
        return "\n".join(lines)
    if isinstance(payload.get("sections"), list):
        rows = payload.get("sections") if isinstance(payload.get("sections"), list) else []
        lines = [f"{label}: sections={len(rows)}"]
        for row in rows[:10]:
            if not isinstance(row, dict):
                continue
            path = " > ".join(str(part or "").strip() for part in (row.get("section_path") or []) if str(part or "").strip())
            block_count = len(row.get("blocks") or []) if isinstance(row.get("blocks"), list) else 0
            lines.append(f"- {path} | blocks={block_count}")
        return "\n".join(lines)
    if isinstance(payload.get("content_bank"), list) and isinstance(payload.get("pedagogy_sequence"), list):
        bank = payload.get("content_bank") if isinstance(payload.get("content_bank"), list) else []
        sequence = payload.get("pedagogy_sequence") if isinstance(payload.get("pedagogy_sequence"), list) else []
        lines = [f"{label}: content_bank={len(bank)} | pedagogy_sections={len(sequence)}"]
        for row in sequence[:10]:
            if not isinstance(row, dict):
                continue
            path = " > ".join(str(part or "").strip() for part in (row.get("section_path") or []) if str(part or "").strip())
            refs = row.get("content_ids") if isinstance(row.get("content_ids"), list) else (
                row.get("content_names") if isinstance(row.get("content_names"), list) else []
            )
            lines.append(f"- {path} | refs={len(refs)}")
        return "\n".join(lines)
    return f"{label}: unknown JSON shape"


async def _run(pdf_path: Path, *, title: str, unit_type: WorkflowUnitType, output_dir: Path) -> None:
    client = await NotebookLMClient.from_storage(profile="default", timeout=180.0)
    async with client as opened:
        notebook = await opened.notebooks.create(f"Content bank benchmark - {pdf_path.stem}")
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
            section_answer = await opened.chat.ask(notebook_id, REFINED_SECTION_PROMPT, source_ids=[source_id])
            bank_answer = await opened.chat.ask(notebook_id, STRICT_CONTENT_BANK_PROMPT, source_ids=[source_id])
            bank_v2_answer = await opened.chat.ask(notebook_id, STRICT_CONTENT_BANK_V2_PROMPT, source_ids=[source_id])

            answers = {
                "current": (current_prompt, str(getattr(current_answer, "answer", "") or "").strip()),
                "section": (REFINED_SECTION_PROMPT, str(getattr(section_answer, "answer", "") or "").strip()),
                "content_bank": (STRICT_CONTENT_BANK_PROMPT, str(getattr(bank_answer, "answer", "") or "").strip()),
                "content_bank_v2": (STRICT_CONTENT_BANK_V2_PROMPT, str(getattr(bank_v2_answer, "answer", "") or "").strip()),
            }

            for name, (prompt, answer) in answers.items():
                (output_dir / f"{name}_prompt.txt").write_text(prompt, encoding="utf-8")
                (output_dir / f"{name}_answer.txt").write_text(answer, encoding="utf-8")
                payload = _extract_json_payload(answer)
                if payload is not None:
                    (output_dir / f"{name}_parsed.json").write_text(
                        json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )

            print(f"PDF: {pdf_path}")
            print(f"Artifacts: {output_dir}")
            print("")
            for name, (_prompt, answer) in answers.items():
                payload = _extract_json_payload(answer)
                print(_summarize_payload(name, payload))
                print("")
        finally:
            await opened.notebooks.delete(notebook_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark NotebookLM extraction prompts for raw content bank and pedagogy sequence.")
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
        default=str(Path.cwd() / ".tmp_notebooklm_content_bank_extract"),
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
