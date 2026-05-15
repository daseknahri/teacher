from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ..models import HolidayDay


FIXED_HOLIDAY_SOURCE = "morocco-fixed"
DEFAULT_ACADEMIC_HOLIDAY_SOURCE = "morocco-academic-2025-2026"
OWNER_HOLIDAY_IMPORT_SOURCE = "owner-academic-upload"

MOROCCO_FIXED_PUBLIC_HOLIDAYS: list[tuple[int, int, str]] = [
    (1, 1, "New Year's Day"),
    (1, 11, "Independence Manifesto Day"),
    (1, 14, "Amazigh New Year (Yennayer)"),
    (5, 1, "Labour Day"),
    (7, 30, "Throne Day"),
    (8, 14, "Oued Ed-Dahab Day"),
    (8, 20, "Revolution of the King and the People"),
    (8, 21, "Youth Day"),
    (11, 6, "Green March Anniversary"),
    (11, 18, "Independence Day"),
]
MOROCCO_FIXED_BY_MONTH_DAY = {(month, day): name for month, day, name in MOROCCO_FIXED_PUBLIC_HOLIDAYS}
MOROCCO_ACADEMIC_HOLIDAY_RANGES: list[tuple[date, date, str]] = [
    # School-year calendar requested for 2025-2026.
    (date(2025, 9, 4), date(2025, 9, 5), "Prophet's Birthday"),
    (date(2025, 10, 19), date(2025, 10, 26), "First Mid-Term Break"),
    (date(2025, 11, 6), date(2025, 11, 6), "Green March Anniversary"),
    (date(2025, 11, 18), date(2025, 11, 18), "Independence Day"),
    (date(2025, 12, 7), date(2025, 12, 14), "Second Mid-Term Break"),
    (date(2026, 1, 1), date(2026, 1, 1), "New Year's Day"),
    (date(2026, 1, 11), date(2026, 1, 11), "Independence Manifesto Day"),
    (date(2026, 1, 14), date(2026, 1, 14), "Amazigh New Year (Yennayer)"),
    (date(2026, 1, 25), date(2026, 2, 1), "Mid-Year School Break"),
    (date(2026, 3, 15), date(2026, 3, 22), "Third Mid-Term Break"),
    (date(2026, 3, 18), date(2026, 3, 21), "Eid al-Fitr"),
    (date(2026, 5, 1), date(2026, 5, 1), "Labour Day"),
    (date(2026, 5, 3), date(2026, 5, 10), "Fourth Mid-Term Break"),
    (date(2026, 5, 27), date(2026, 5, 29), "Eid al-Adha"),
    (date(2026, 6, 16), date(2026, 6, 16), "Islamic New Year (1 Muharram)"),
]


def _year_bounds(year: int) -> tuple[date, date]:
    return date(int(year), 1, 1), date(int(year), 12, 31)


def _iter_morocco_academic_holiday_days_for_year(year: int) -> list[tuple[date, str]]:
    year_start, year_end = _year_bounds(year)
    output: list[tuple[date, str]] = []
    for start_day, end_day, name in MOROCCO_ACADEMIC_HOLIDAY_RANGES:
        if end_day < year_start or start_day > year_end:
            continue
        cursor = max(start_day, year_start)
        stop = min(end_day, year_end)
        while cursor <= stop:
            output.append((cursor, name))
            cursor = cursor + timedelta(days=1)
    return output


def _morocco_academic_holiday_names_for_date(value: date) -> list[str]:
    names: list[str] = []
    for start_day, end_day, name in MOROCCO_ACADEMIC_HOLIDAY_RANGES:
        if start_day <= value <= end_day:
            names.append(name)
    return names


def _merge_holiday_names(existing_name: str | None, new_name: str) -> str:
    existing_parts = [part.strip() for part in str(existing_name or "").split(" / ") if part.strip()]
    if new_name not in existing_parts:
        existing_parts.append(new_name)
    return " / ".join(existing_parts) if existing_parts else new_name


def _split_holiday_parts(value: str | None) -> list[str]:
    return [part.strip() for part in str(value or "").split(" / ") if part.strip()]


def _join_holiday_parts(parts: list[str]) -> str | None:
    unique_parts: list[str] = []
    for part in parts:
        text = str(part or "").strip()
        if text and text not in unique_parts:
            unique_parts.append(text)
    return " / ".join(unique_parts) if unique_parts else None


def _holiday_year_filters(years: set[int]):
    filters = []
    for year in sorted({int(value) for value in years if value is not None}):
        year_start, year_end = _year_bounds(year)
        filters.append(and_(HolidayDay.holiday_date >= year_start, HolidayDay.holiday_date <= year_end))
    return filters


def _upsert_holiday_row(
    db: Session,
    *,
    existing_by_date: dict[date, HolidayDay],
    holiday_date: date,
    name: str,
    source: str,
    is_blocked: bool = True,
    overwrite_is_blocked: bool = False,
    inserted: list[HolidayDay],
) -> None:
    existing = existing_by_date.get(holiday_date)
    if existing is not None:
        source_parts = _split_holiday_parts(existing.source)
        seed_source = source in {FIXED_HOLIDAY_SOURCE, DEFAULT_ACADEMIC_HOLIDAY_SOURCE}
        if not (seed_source and OWNER_HOLIDAY_IMPORT_SOURCE in source_parts):
            existing.name = _merge_holiday_names(existing.name, name)
        if overwrite_is_blocked:
            existing.is_blocked = bool(is_blocked)
        if source not in source_parts:
            source_parts.append(source)
        existing.source = _join_holiday_parts(source_parts) or source
        return
    row = HolidayDay(
        holiday_date=holiday_date,
        name=name,
        is_blocked=bool(is_blocked),
        country_code="MA",
        region=None,
        source=source,
    )
    db.add(row)
    inserted.append(row)
    existing_by_date[holiday_date] = row


def seed_morocco_fixed_holidays(db: Session, year: int) -> list[HolidayDay]:
    year_start, year_end = _year_bounds(year)
    existing_rows = db.scalars(
        select(HolidayDay).where(
            HolidayDay.country_code == "MA",
            HolidayDay.region.is_(None),
            HolidayDay.holiday_date >= year_start,
            HolidayDay.holiday_date <= year_end,
        )
    ).all()
    existing_by_date = {row.holiday_date: row for row in existing_rows}

    inserted: list[HolidayDay] = []
    for month, day, name in MOROCCO_FIXED_PUBLIC_HOLIDAYS:
        holiday_date = date(int(year), int(month), int(day))
        _upsert_holiday_row(
            db,
            existing_by_date=existing_by_date,
            holiday_date=holiday_date,
            name=name,
            source=FIXED_HOLIDAY_SOURCE,
            inserted=inserted,
        )

    if inserted:
        db.flush()
    return inserted


def seed_morocco_academic_holidays(db: Session, year: int) -> list[HolidayDay]:
    year_start, year_end = _year_bounds(year)
    existing_rows = db.scalars(
        select(HolidayDay).where(
            HolidayDay.country_code == "MA",
            HolidayDay.region.is_(None),
            HolidayDay.holiday_date >= year_start,
            HolidayDay.holiday_date <= year_end,
        )
    ).all()
    existing_by_date = {row.holiday_date: row for row in existing_rows}

    inserted: list[HolidayDay] = []
    for holiday_date, name in _iter_morocco_academic_holiday_days_for_year(year):
        _upsert_holiday_row(
            db,
            existing_by_date=existing_by_date,
            holiday_date=holiday_date,
            name=name,
            source=DEFAULT_ACADEMIC_HOLIDAY_SOURCE,
            inserted=inserted,
        )

    if inserted:
        db.flush()
    return inserted


def seed_morocco_school_holidays(db: Session, year: int) -> list[HolidayDay]:
    return seed_morocco_academic_holidays(db, year)


def list_holidays_for_year(db: Session, year: int, country_code: str = "MA") -> list[HolidayDay]:
    code = str(country_code or "MA").strip().upper() or "MA"
    if code == "MA":
        seed_morocco_fixed_holidays(db, year)
        seed_morocco_academic_holidays(db, year)

    year_start, year_end = _year_bounds(year)
    return db.scalars(
        select(HolidayDay)
        .where(
            HolidayDay.country_code == code,
            HolidayDay.holiday_date >= year_start,
            HolidayDay.holiday_date <= year_end,
        )
        .order_by(HolidayDay.holiday_date.asc(), HolidayDay.id.asc())
    ).all()


def find_blocked_holiday(db: Session, holiday_date: date, country_code: str = "MA") -> HolidayDay | None:
    code = str(country_code or "MA").strip().upper() or "MA"
    explicit = db.scalar(
        select(HolidayDay)
        .where(
            HolidayDay.country_code == code,
            HolidayDay.holiday_date == holiday_date,
            HolidayDay.region.is_(None),
        )
        .order_by(HolidayDay.id.desc())
    )
    if explicit is not None:
        return explicit if explicit.is_blocked else None

    if code == "MA":
        fixed_name = MOROCCO_FIXED_BY_MONTH_DAY.get((holiday_date.month, holiday_date.day))
        academic_names = _morocco_academic_holiday_names_for_date(holiday_date)
        names = []
        if fixed_name:
            names.append(fixed_name)
        names.extend(name for name in academic_names if name not in names)
        if names:
            return HolidayDay(
                holiday_date=holiday_date,
                name=" / ".join(names),
                is_blocked=True,
                country_code="MA",
                region=None,
                source=f"{FIXED_HOLIDAY_SOURCE} / {DEFAULT_ACADEMIC_HOLIDAY_SOURCE}" if fixed_name and academic_names else (
                    FIXED_HOLIDAY_SOURCE if fixed_name else DEFAULT_ACADEMIC_HOLIDAY_SOURCE
                ),
            )
    return None


def upsert_owner_uploaded_holidays(
    db: Session,
    *,
    rows: list[dict],
    country_code: str = "MA",
) -> dict:
    code = str(country_code or "MA").strip().upper() or "MA"
    if code != "MA":
        raise ValueError("Holiday import currently supports Morocco (MA) only.")

    expanded_by_date: dict[date, dict] = {}
    affected_years: set[int] = set()
    row_count = 0

    for row in rows:
        row_count += 1
        name = str(row.get("name") or "").strip()
        start_day = row.get("start_date")
        end_day = row.get("end_date") or start_day
        blocked = bool(row.get("is_blocked", True))
        if not name or start_day is None or end_day is None:
            continue
        cursor = start_day
        while cursor <= end_day:
            bucket = expanded_by_date.setdefault(
                cursor,
                {"names": [], "is_blocked": False},
            )
            if name not in bucket["names"]:
                bucket["names"].append(name)
            bucket["is_blocked"] = bool(bucket["is_blocked"] or blocked)
            affected_years.add(cursor.year)
            cursor = cursor + timedelta(days=1)

    if not expanded_by_date:
        return {"rows": 0, "holiday_dates": 0, "years": [], "created": 0, "updated": 0}

    for year in sorted(affected_years):
        seed_morocco_fixed_holidays(db, year)
        seed_morocco_academic_holidays(db, year)

    year_filters = _holiday_year_filters(affected_years)
    existing_rows = db.scalars(
        select(HolidayDay).where(
            HolidayDay.country_code == code,
            HolidayDay.region.is_(None),
            or_(*year_filters),
        )
    ).all()
    existing_by_date = {row.holiday_date: row for row in existing_rows}

    created = 0
    updated = 0
    for holiday_date, payload in sorted(expanded_by_date.items()):
        merged_name = _join_holiday_parts(list(payload["names"])) or "Holiday"
        is_blocked = bool(payload["is_blocked"])
        existing = existing_by_date.get(holiday_date)
        if existing is None:
            row = HolidayDay(
                holiday_date=holiday_date,
                name=merged_name,
                is_blocked=is_blocked,
                country_code=code,
                region=None,
                source=OWNER_HOLIDAY_IMPORT_SOURCE,
            )
            db.add(row)
            existing_by_date[holiday_date] = row
            created += 1
            continue

        existing.name = merged_name
        existing.is_blocked = is_blocked
        source_parts = _split_holiday_parts(existing.source)
        if OWNER_HOLIDAY_IMPORT_SOURCE not in source_parts:
            source_parts.append(OWNER_HOLIDAY_IMPORT_SOURCE)
        existing.source = _join_holiday_parts(source_parts) or OWNER_HOLIDAY_IMPORT_SOURCE
        updated += 1

    db.flush()
    return {
        "rows": row_count,
        "holiday_dates": len(expanded_by_date),
        "years": sorted(affected_years),
        "created": created,
        "updated": updated,
    }
