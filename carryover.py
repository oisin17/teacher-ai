"""Small teacher-confirmed carryover records; suggestions are never outcomes."""
from lesson_progress import school_date

SUGGESTION_FORMAT = {"type": "json_schema", "name": "carryover_suggestions", "strict": True,
    "schema": {"type": "object", "additionalProperties": False,
        "properties": {"items": {"type": "array", "items": {"type": "object", "additionalProperties": False,
            "properties": {k: {"type": "string"} for k in ("subject", "learning", "evidence")},
            "required": ["subject", "learning", "evidence"]}}}, "required": ["items"]}}


def validate_item(item):
    for key in ("id", "period_id", "subject", "learning", "evidence", "created_date", "state"):
        if not isinstance(item.get(key), str):
            raise ValueError("Invalid carryover item")
    if not all(item[key].strip() for key in ("id", "period_id", "subject", "learning")):
        raise ValueError("Empty carryover item")
    if len(item["learning"]) > 300 or len(item["evidence"]) > 1500:
        raise ValueError("Carryover text too long")
    school_date(item["created_date"])
    if item["state"] not in ("outstanding", "completed", "removed"):
        raise ValueError("Invalid carryover state")
    return item


def before_date(position, cutoff):
    # Generated CLP evidence can include later lessons when browsing back.
    return {key: "\n".join(line for line in str(value).splitlines()
            if not (line.startswith("- 20") and line[2:12] > cutoff))
            for key, value in position.items()}


def retain_explicit_links(plan, items):
    """A subject match alone cannot attach a completion control to new learning."""
    known = {item["id"]: item for item in items}
    for lesson in plan["lessons"]:
        lesson["carryover_ids"] = [id for id in lesson.get("carryover_ids", [])
            if id in known and known[id]["learning"].casefold() in lesson["details"].casefold()]
    return plan
