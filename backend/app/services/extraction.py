from __future__ import annotations

import base64
from difflib import SequenceMatcher
import json
from pathlib import Path
import re
from statistics import mean
import unicodedata

import httpx

from ..config import OCR_LANG, OPENAI_API_KEY, OPENAI_MODEL, OPENAI_TIMEOUT_SECONDS


HEADING_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+)*)(?:\s*[-.):]\s*|\s+)(.+)$")
ROMAN_HEADING_PATTERN = re.compile(r"^\s*[ivxlcdm]+(?:\.[ivxlcdm0-9]+)*(?:\s*[-):.]?\s*)(.+)$", re.IGNORECASE)
CHAPTER_PATTERN = re.compile(r"^\s*(chapter|chapitre|title|titre|lesson|lecon)\s*[:.\-]?\s*\d*.*$", re.IGNORECASE)
SECTION_WORD_PATTERN = re.compile(r"^\s*(section|sous[- ]?section|partie|titre)\b", re.IGNORECASE)
COMMA_HEADING_PATTERN = re.compile(r"^\s*(\d+(?:[.,]\d+)+)(?:\s*[-):.]?\s*)(.+)$")
BULLET_PREFIX_PATTERN = re.compile(r"^[\s\-\*\u2022\u25aa\u25ab\u25cf\u00b7\u00b0\[\]\(\)]+")
NOISE_ONLY_PATTERN = re.compile(r"^[\W_]+$")
ACTIVITY_KEYWORDS = (
    "activity",
    "activite",
    "application",
    "exemple",
    "example",
    "propriete",
    "property",
    "methode",
    "method",
    "definition",
    "theoreme",
    "theorem",
)
EXERCISE_KEYWORDS = ("exercise", "exercice", "serie", "problem", "probleme")
MAX_LESSON_ITEMS = 90
MAX_ACTIVITY_ITEMS = 120
MAX_EXERCISE_ITEMS = 120


def _normalized(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return stripped.lower().strip()


def _contains_keyword(line: str, keywords: tuple[str, ...], *, fuzzy_min: float = 0.62) -> bool:
    for keyword in keywords:
        if keyword in line:
            return True
    tokens = re.findall(r"[a-z0-9]+", line)
    for token in tokens:
        if len(token) < 5:
            continue
        for keyword in keywords:
            if SequenceMatcher(None, token, keyword).ratio() >= fuzzy_min:
                return True
    return False


def _heuristic_extract(raw_text: str, fallback_reason: str | None = None) -> dict:
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    lessons: list[str] = []
    activities: list[str] = []
    exercises: list[str] = []

    for line in lines:
        normalized = _normalized(line)
        is_heading = _is_heading_line(line)
        if is_heading:
            lessons.append(line)
            continue
        if _contains_keyword(normalized, EXERCISE_KEYWORDS):
            exercises.append(line)
            continue
        if _contains_keyword(normalized, ACTIVITY_KEYWORDS):
            activities.append(line)

    lesson_headings, activity_rows, exercise_rows = _normalize_extraction_lists(lessons, activities, exercises)
    confidence = 0.55
    if lesson_headings:
        confidence += 0.2
    if activity_rows or exercise_rows:
        confidence += 0.2
    confidence = min(confidence, 0.95)
    return {
        "confidence": confidence,
        "lesson_headings": lesson_headings,
        "activities": activity_rows,
        "exercises": exercise_rows,
        "raw_text": raw_text,
        "provider": "heuristic",
        "model": None,
        "fallback_reason": fallback_reason,
    }


def _sanitize_result(
    payload: dict,
    raw_text: str,
    *,
    provider: str,
    model: str | None,
    fallback_reason: str | None = None,
) -> dict:
    lessons = payload.get("lesson_headings") if isinstance(payload.get("lesson_headings"), list) else []
    activities = payload.get("activities") if isinstance(payload.get("activities"), list) else []
    exercises = payload.get("exercises") if isinstance(payload.get("exercises"), list) else []

    lessons, activities, exercises = _normalize_extraction_lists(lessons, activities, exercises)

    confidence_raw = payload.get("confidence", 0.75)
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        confidence = 0.75
    confidence = max(0.0, min(confidence, 1.0))

    return {
        "confidence": confidence,
        "lesson_headings": lessons,
        "activities": activities,
        "exercises": exercises,
        "raw_text": raw_text,
        "provider": provider,
        "model": model,
        "fallback_reason": fallback_reason,
    }


def _json_object_from_text(text: str) -> dict | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        chunk = text[start : end + 1]
        try:
            return json.loads(chunk)
        except Exception:
            return None
    return None


def _mime_from_suffix(suffix: str) -> str:
    ext = suffix.lower()
    if ext in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if ext == ".png":
        return "image/png"
    if ext == ".webp":
        return "image/webp"
    if ext == ".bmp":
        return "image/bmp"
    return "application/octet-stream"


def _openai_extract(raw_text: str, image_path: str | None = None) -> tuple[dict | None, str | None]:
    if not OPENAI_API_KEY:
        return None, "openai_api_key_not_set"

    system_prompt = (
        "You are an expert college-level (middle-school) mathematics teacher and curriculum tracker. "
        "Extract structured progress from classroom screenshots/notes in French or English. "
        "Return STRICT JSON only with exactly these keys: confidence, lesson_headings, activities, exercises. "
        "Rules: "
        "1) lesson_headings: chapter/section headings only (examples: Chapitre 2, 1, 1.1, 2.3, Titre...). "
        "Accept compact OCR styles like '1.Developpement' or missing spaces/punctuation. "
        "2) activities: full content lines for Propriete, Exemple(s), Application, Activite, Methode, Definition. "
        "3) exercises: full content lines for Exercice/Exercise even when inside chapter content. "
        "4) Keep the original wording from input, preserve order, remove duplicates. "
        "5) Do not invent missing content. "
        "6) confidence must be a number in [0,1]."
    )
    user_text = (
        "Extract the classroom math progress for attendance/reporting. Return JSON only.\n\n"
        f"Raw text:\n{raw_text.strip() if raw_text.strip() else '(empty)'}"
    )

    system_message = {"role": "system", "content": system_prompt}
    messages: list[dict] = [system_message]
    use_image = bool(image_path and Path(image_path).exists())
    if use_image:
        try:
            image_bytes = Path(image_path).read_bytes()
            mime = _mime_from_suffix(Path(image_path).suffix)
            data_url = f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            )
        except Exception:
            use_image = False
            messages.append({"role": "user", "content": user_text})
    else:
        messages.append({"role": "user", "content": user_text})

    payload = {
        "model": OPENAI_MODEL,
        "messages": messages,
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}

    data: dict | None = None
    try:
        with httpx.Client(timeout=OPENAI_TIMEOUT_SECONDS) as client:
            response = client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError:
        # Retry without forcing JSON response_format; some model deployments reject it.
        payload_no_json_mode = {
            "model": OPENAI_MODEL,
            "messages": messages,
            "temperature": 0.0,
        }
        try:
            with httpx.Client(timeout=OPENAI_TIMEOUT_SECONDS) as client:
                response = client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers=headers,
                    json=payload_no_json_mode,
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as retry_exc:
            # Last retry: if image request failed and OCR text exists, try text-only mode.
            if use_image and raw_text.strip():
                text_only_messages = [system_message, {"role": "user", "content": user_text}]
                payload_text_only = {
                    "model": OPENAI_MODEL,
                    "messages": text_only_messages,
                    "temperature": 0.0,
                }
                try:
                    with httpx.Client(timeout=OPENAI_TIMEOUT_SECONDS) as client:
                        response = client.post(
                            "https://api.openai.com/v1/chat/completions",
                            headers=headers,
                            json=payload_text_only,
                        )
                        response.raise_for_status()
                        data = response.json()
                except httpx.HTTPStatusError as text_retry_exc:
                    detail = _openai_error_details(text_retry_exc.response)
                    return None, f"openai_request_failed:http_{text_retry_exc.response.status_code}:{detail}"
                except Exception as text_retry_exc:
                    return None, f"openai_request_failed:{type(text_retry_exc).__name__}"
            else:
                detail = _openai_error_details(retry_exc.response)
                return None, f"openai_request_failed:http_{retry_exc.response.status_code}:{detail}"
        except Exception as retry_exc:
            return None, f"openai_request_failed:{type(retry_exc).__name__}"
    except Exception as exc:
        return None, f"openai_request_failed:{type(exc).__name__}"

    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    if isinstance(content, list):
        text_chunks = []
        for chunk in content:
            if isinstance(chunk, dict):
                maybe_text = chunk.get("text")
                if isinstance(maybe_text, str):
                    text_chunks.append(maybe_text)
        content = "\n".join(text_chunks)
    parsed = _json_object_from_text(content)
    if not isinstance(parsed, dict):
        return None, "openai_invalid_json_response"
    return _sanitize_result(parsed, raw_text, provider="openai", model=OPENAI_MODEL), None


def extract_structured_progress(raw_text: str, image_path: str | None = None) -> dict:
    """
    Extraction priority:
    1) OpenAI extraction when OPENAI_API_KEY is configured.
    2) Deterministic heuristic fallback.
    """
    ai_result, error = _openai_extract(raw_text, image_path=image_path)
    if ai_result is not None:
        has_items = bool(ai_result.get("lesson_headings") or ai_result.get("activities") or ai_result.get("exercises"))
        if has_items:
            ai_result = _augment_openai_with_heuristic(ai_result, raw_text)
            return ai_result
        if raw_text.strip():
            return _heuristic_extract(raw_text, fallback_reason="openai_empty_result")
        return ai_result
    return _heuristic_extract(raw_text, fallback_reason=error)


def resolve_raw_text(file_path: str, provided_raw_text: str | None) -> str:
    """
    Resolve OCR text from:
    1) explicitly provided text,
    2) pytesseract OCR when installed,
    3) empty string as a safe fallback.
    """
    if provided_raw_text and provided_raw_text.strip():
        return provided_raw_text.strip()

    file = Path(file_path)
    if not file.exists():
        return ""

    try:
        from PIL import Image
        import pytesseract
    except Exception:
        return ""

    best_text = ""
    best_score = -1.0
    seen_texts: set[str] = set()
    psm_configs = ["--psm 6", "--psm 4"]
    lang_options = [OCR_LANG]
    if OCR_LANG != "eng":
        lang_options.append("eng")
    if OCR_LANG != "fra+eng":
        lang_options.append("fra+eng")
    try:
        with Image.open(file) as image:
            variants = _build_ocr_variants(image)
    except Exception:
        return ""
    if not variants:
        return ""

    for variant in variants:
        for lang in lang_options:
            for config in psm_configs:
                text, avg_conf = _ocr_text_with_confidence(
                    pytesseract,
                    variant,
                    lang=lang,
                    config=config,
                )
                cleaned = text.strip()
                if not cleaned:
                    continue
                dedupe_key = _normalized(cleaned)
                if dedupe_key in seen_texts:
                    continue
                seen_texts.add(dedupe_key)
                score = _score_ocr_candidate(cleaned, avg_conf=avg_conf)
                if score > best_score:
                    best_score = score
                    best_text = cleaned

    if best_text:
        return best_text
    return ""


def _openai_error_details(response: httpx.Response) -> str:
    try:
        data = response.json()
        error = data.get("error", {})
        message = error.get("message")
        code = error.get("code")
        pieces = [piece for piece in [code, message] if piece]
        if pieces:
            return "_".join(str(piece).replace(" ", "_") for piece in pieces)
    except Exception:
        pass
    return "request_failed"


def _unique_ordered(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for raw in items:
        value = str(raw).strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(value)
    return output


def _build_ocr_variants(image) -> list:
    try:
        from PIL import ImageFilter, ImageOps
    except Exception:
        return [image.copy()]

    base = image.convert("RGB")
    width, height = base.size
    if max(width, height) < 1300:
        base = base.resize((max(1, width * 2), max(1, height * 2)))

    gray = ImageOps.grayscale(base)
    gray_auto = ImageOps.autocontrast(gray)
    sharp = ImageOps.autocontrast(gray.filter(ImageFilter.SHARPEN))
    binary = gray_auto.point(lambda pixel: 255 if pixel > 165 else 0)
    invert = ImageOps.invert(gray_auto)

    return [base, gray_auto, sharp, binary, invert]


def _ocr_text_with_confidence(pytesseract_module, image, *, lang: str, config: str) -> tuple[str, float | None]:
    try:
        text = pytesseract_module.image_to_string(image, lang=lang, config=config) or ""
    except Exception:
        return "", None

    avg_conf: float | None = None
    try:
        output_const = getattr(getattr(pytesseract_module, "Output", None), "DICT", "dict")
        data = pytesseract_module.image_to_data(
            image,
            lang=lang,
            config=config,
            output_type=output_const,
        )
        conf_values: list[float] = []
        for raw in data.get("conf", []):
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if value >= 0:
                conf_values.append(value)
        if conf_values:
            avg_conf = float(mean(conf_values))
    except Exception:
        avg_conf = None
    return text, avg_conf


def _score_ocr_candidate(text: str, *, avg_conf: float | None) -> float:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    heading_hits = 0
    keyword_hits = 0
    for line in lines[:160]:
        normalized = _normalized(line)
        if _is_heading_line(line):
            heading_hits += 1
        if _contains_keyword(
            normalized,
            EXERCISE_KEYWORDS + ACTIVITY_KEYWORDS,
        ):
            keyword_hits += 1

    length_score = min(len(text), 4000) * 0.08
    line_score = min(len(lines), 120) * 2.0
    heading_score = heading_hits * 30.0
    keyword_score = keyword_hits * 10.0
    conf_score = (avg_conf or 0.0) * 1.4
    return length_score + line_score + heading_score + keyword_score + conf_score


def _clean_item(value: str) -> str:
    line = str(value or "").replace("\x00", " ").strip()
    if not line:
        return ""
    line = BULLET_PREFIX_PATTERN.sub("", line)
    line = re.sub(r"\s+", " ", line).strip()
    return line


def _is_noise_line(line: str) -> bool:
    normalized = _normalized(line)
    if not normalized:
        return True
    if len(normalized) < 2:
        return True
    if NOISE_ONLY_PATTERN.match(normalized):
        return True
    if re.fullmatch(r"\d+", normalized):
        return True
    return False


def _is_heading_line(line: str) -> bool:
    normalized = _normalized(line)
    if _is_noise_line(normalized):
        return False
    return bool(
        HEADING_PATTERN.match(line)
        or COMMA_HEADING_PATTERN.match(line)
        or ROMAN_HEADING_PATTERN.match(line)
        or CHAPTER_PATTERN.match(normalized)
        or SECTION_WORD_PATTERN.match(normalized)
    )


def _classify_line(line: str, default_bucket: str) -> str:
    normalized = _normalized(line)
    if _contains_keyword(normalized, EXERCISE_KEYWORDS):
        return "exercises"
    if _is_heading_line(line):
        return "lesson_headings"
    if _contains_keyword(normalized, ACTIVITY_KEYWORDS):
        return "activities"
    return default_bucket


def _normalize_extraction_lists(
    lessons: list[str],
    activities: list[str],
    exercises: list[str],
) -> tuple[list[str], list[str], list[str]]:
    buckets = {"lesson_headings": [], "activities": [], "exercises": []}
    seen_norm: set[str] = set()
    ordered = (
        [("lesson_headings", value) for value in lessons]
        + [("activities", value) for value in activities]
        + [("exercises", value) for value in exercises]
    )
    for default_bucket, raw in ordered:
        cleaned = _clean_item(str(raw))
        if not cleaned or _is_noise_line(cleaned):
            continue
        bucket = _classify_line(cleaned, default_bucket)
        key = _normalized(cleaned)
        if key in seen_norm:
            continue
        seen_norm.add(key)
        buckets[bucket].append(cleaned)
    return (
        buckets["lesson_headings"][:MAX_LESSON_ITEMS],
        buckets["activities"][:MAX_ACTIVITY_ITEMS],
        buckets["exercises"][:MAX_EXERCISE_ITEMS],
    )


def _merge_unique(existing: list[str], fallback: list[str], *, limit: int) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in [*existing, *fallback]:
        cleaned = _clean_item(value)
        key = _normalized(cleaned)
        if not cleaned or key in seen:
            continue
        seen.add(key)
        output.append(cleaned)
        if len(output) >= limit:
            break
    return output


def _augment_openai_with_heuristic(ai_result: dict, raw_text: str) -> dict:
    if not raw_text.strip():
        return ai_result
    heuristic = _heuristic_extract(raw_text, fallback_reason=None)
    ai_lessons = list(ai_result.get("lesson_headings") or [])
    ai_activities = list(ai_result.get("activities") or [])
    ai_exercises = list(ai_result.get("exercises") or [])
    merged_lessons = _merge_unique(ai_lessons, heuristic.get("lesson_headings", []), limit=MAX_LESSON_ITEMS)
    merged_activities = _merge_unique(ai_activities, heuristic.get("activities", []), limit=MAX_ACTIVITY_ITEMS)
    merged_exercises = _merge_unique(ai_exercises, heuristic.get("exercises", []), limit=MAX_EXERCISE_ITEMS)
    normalized_lessons, normalized_activities, normalized_exercises = _normalize_extraction_lists(
        merged_lessons,
        merged_activities,
        merged_exercises,
    )
    added = (
        len(normalized_lessons) > len(ai_lessons)
        or len(normalized_activities) > len(ai_activities)
        or len(normalized_exercises) > len(ai_exercises)
    )
    ai_result["lesson_headings"] = normalized_lessons
    ai_result["activities"] = normalized_activities
    ai_result["exercises"] = normalized_exercises
    if added:
        ai_result["fallback_reason"] = ai_result.get("fallback_reason") or "openai_augmented_with_heuristic"
        heuristic_conf = float(heuristic.get("confidence") or 0.0)
        ai_conf = float(ai_result.get("confidence") or 0.0)
        blended = min(0.97, max(ai_conf, (ai_conf * 0.8) + (heuristic_conf * 0.2)))
        ai_result["confidence"] = max(0.0, min(blended, 1.0))
    return ai_result
