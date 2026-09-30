"""Date suggestions are upload hints only. Confirmed dates control selection."""
import calendar
import re
from datetime import date

MONTH_NAMES = {
    **{name.lower(): number for number, name in enumerate(calendar.month_name) if name},
    **{name.lower(): number for number, name in enumerate(calendar.month_abbr) if name},
    "sept": 9,
}
MONTH_PATTERN = "|".join(sorted(MONTH_NAMES, key=len, reverse=True))


def iso_date(value):
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError("Invalid date")
    return value


def validate_monthly_plan(plan, allow_pending=False):
    for key in ("id", "title", "source_filename", "plan_text"):
        if not isinstance(plan.get(key), str):
            raise ValueError("Invalid monthly plan")
    if not plan["id"] or not plan["title"].strip() or not plan["plan_text"].strip():
        raise ValueError("Empty monthly plan")
    start, end = plan.get("start_date"), plan.get("end_date")
    if start is None and end is None and allow_pending:
        return plan
    if iso_date(start) > iso_date(end):
        raise ValueError("End date is before start date")
    return plan


def month_range(year, month):
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def suggest_dates(text, filename="", reference_date=None):
    """Conservative, deterministic suggestions; never used at generation time.

    Only inspect the document header for dates, not every curriculum reference.
    Ambiguous or conflicting date evidence produces no detected range.
    A month without a year is explicitly labelled as a proposed year.
    """
    reference_date = reference_date or date.today()
    header = text[:2500]
    sources = [("document heading", header), ("filename", filename.replace("_", " "))]
    candidates = []
    for source, content in sources:
        # Explicit full numerical date range (Irish day/month/year or ISO).
        token = r"(?:\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[/.]\d{1,2}[/.]\d{4})"
        matches = re.findall(rf"({token})\s*(?:to|until|–|—|-)\s*({token})", content, re.I)
        for first, last in matches:
            try:
                def parse(value):
                    parts = [int(part) for part in re.split(r"[./-]", value)]
                    return date(*parts) if len(str(parts[0])) == 4 else date(parts[2], parts[1], parts[0])
                start, end = parse(first), parse(last)
                if start <= end:
                    candidates.append((start, end, f"Suggested from {source}: {first} – {last}"))
            except ValueError:
                pass
        if matches:
            continue
        pairs = re.findall(rf"\b({MONTH_PATTERN})\b[\s,.-]+(20\d{{2}})\b", content, re.I)
        for month, year in pairs:
            start, end = month_range(int(year), MONTH_NAMES[month.lower()])
            candidates.append((start, end, f"Suggested from {source}: {month} {year}"))
    distinct = {(start, end) for start, end, _ in candidates}
    if len(distinct) == 1:
        start, end, evidence = candidates[0]
        return {"start": start, "end": end, "evidence": evidence + ". Confirm or correct before saving."}
    if len(distinct) > 1:
        return {"start": None, "end": None, "evidence": "Conflicting date suggestions. Enter and confirm the intended dates."}
    months = set(re.findall(rf"\b({MONTH_PATTERN})\b", header + " " + filename.replace("_", " "), re.I))
    month_numbers = {MONTH_NAMES[month.lower()] for month in months}
    if len(month_numbers) == 1:
        month = next(iter(month_numbers))
        start, end = month_range(reference_date.year, month)
        return {"start": start, "end": end, "evidence":
                f"Month detected, but no explicit year. {reference_date.year} is only a suggestion; confirm or correct both dates."}
    return {"start": None, "end": None, "evidence": "No unambiguous date range detected. Enter and confirm both dates."}
