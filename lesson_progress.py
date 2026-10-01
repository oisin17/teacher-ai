"""Small, explicit lesson snapshots and conservative learning evidence for V1."""
import copy
import json
from datetime import date
from uuid import uuid4

STATUSES = ("Completed", "Partially completed", "Not taught")
POSITION_KEYS = ("Maths", "English", "Gaeilge", "SESE", "Other")
EVIDENCE_MARKER = "\n\nRecorded lesson progress (newest first; teacher notes take precedence):\n"
LESSON_FIELDS = ("lesson_id", "time", "subject", "topic", "learning_intention", "details")

# One generation supplies the visible lessons AND the progress snapshots.
# We never ask a second model to guess lessons from free-form markdown.
PLAN_FORMAT = {
    "type": "json_schema", "name": "teacher_day_plan", "strict": True,
    "schema": {
        "type": "object", "additionalProperties": False,
        "properties": {
            "overview": {"type": "string"},
            "lessons": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "properties": {"phases": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {"minutes": {"type": "integer"}, "activity": {"type": "string"}}, "required": ["minutes", "activity"]}}, **{key: {"type": "string"} for key in LESSON_FIELDS if key != "lesson_id"}, "carryover_ids": {"type": "array", "items": {"type": "string"}},
                "monthly_item_links": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {"item_id": {"type": "string"}, "coverage": {"type": "string"}}, "required": ["item_id", "coverage"]}}},
                "required": [key for key in LESSON_FIELDS if key != "lesson_id"] + ["carryover_ids", "monthly_item_links", "phases"],
            }},
        }, "required": ["overview", "lessons"],
    },
}


def school_date(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError("Invalid school date")
    return value


def validate_lessons(lessons, progress=False):
    if not isinstance(lessons, list) or not 1 <= len(lessons) <= 30:
        raise ValueError("Expected individual teaching lessons")
    ids = set()
    for lesson in lessons:
        if not isinstance(lesson, dict):
            raise ValueError("Invalid lesson")
        for field in LESSON_FIELDS:
            if not isinstance(lesson.get(field), str) or not lesson[field].strip():
                raise ValueError("Incomplete lesson snapshot")
        if lesson["lesson_id"] in ids:
            raise ValueError("Duplicate lesson")
        ids.add(lesson["lesson_id"])
        for key in ("carryover_ids", "completed_carryover_ids"):
            values = lesson.get(key, [])
            if not isinstance(values, list) or any(not isinstance(v, str) or not v for v in values) or len(set(values)) != len(values):
                raise ValueError("Invalid carryover links")
        links = lesson.get('monthly_item_links', [])
        if not isinstance(links, list) or any(not isinstance(link, dict) or not isinstance(link.get('item_id'), str) or not isinstance(link.get('coverage'), str) or not link['coverage'].strip() for link in links) or len({link['item_id'] for link in links}) != len(links):
            raise ValueError('Invalid Monthly Plan learning links')
        if 'phases' in lesson:
            phases = lesson['phases']
            if not isinstance(phases, list) or not phases or any(not isinstance(p, dict) or type(p.get('minutes')) is not int or p['minutes'] <= 0 or not isinstance(p.get('activity'), str) or not p['activity'].strip() for p in phases):
                raise ValueError('Invalid structured phases')
        if progress:
            if any(id not in lesson.get("carryover_ids", []) for id in lesson.get("completed_carryover_ids", [])):
                raise ValueError("Unlinked carryover completion")
            if lesson.get("completed_carryover_ids") and lesson.get("status") != "Completed":
                raise ValueError("Partial or not-taught cannot finish carryover")
            if lesson.get("status") not in STATUSES:
                raise ValueError("Choose a status for every lesson")
            if not isinstance(lesson.get("note"), str) or len(lesson["note"]) > 300:
                raise ValueError("Lesson notes must be at most 300 characters")
    return lessons


def parse_generated_plan(output, planning_date):
    value = json.loads(output)
    if not isinstance(value, dict) or not isinstance(value.get("overview"), str):
        raise ValueError("Invalid plan")
    lessons = value.get("lessons")
    if not isinstance(lessons, list):
        raise ValueError("Invalid lesson list")
    for lesson in lessons:
        if not isinstance(lesson, dict):
            raise ValueError("Invalid lesson")
        lesson["lesson_id"] = uuid4().hex
    validate_lessons(lessons)
    return {"plan_id": uuid4().hex, "planning_date": school_date(planning_date),
            "overview": value["overview"], "lessons": lessons}


def validate_plan(plan):
    if not isinstance(plan, dict) or not isinstance(plan.get("plan_id"), str) or not plan["plan_id"]:
        raise ValueError("Invalid saved plan")
    school_date(plan["planning_date"])
    if not isinstance(plan.get("overview"), str):
        raise ValueError("Invalid overview")
    validate_lessons(plan["lessons"])
    return plan


def phase_markdown(lesson):
    if not lesson.get('phases'):
        return ''
    return '**Phases:**\n' + '\n'.join(f"- **{p['minutes']} min:** {p['activity']}" for p in lesson['phases']) + '\n\n'


def plan_markdown(plan):
    return plan["overview"] + "\n\n" + "\n\n".join(
        f"### {lesson['time']} — {lesson['subject']}: {lesson['topic']}\n\n"
        f"**Learning intention:** {lesson['learning_intention']}\n\n" + phase_markdown(lesson) + lesson['details']
        for lesson in plan["lessons"]
    )


def overall_status(lessons):
    statuses = {lesson["status"] for lesson in lessons}
    return next(iter(statuses)) if len(statuses) == 1 else "Partially completed"


def subject_bucket(subject):
    normal = subject.casefold().strip()
    if normal in ("maths", "math", "mathematics", "matamaitic"):
        return "Maths"
    if normal in ("english", "literacy", "béarla", "reading", "writing", "spelling", "phonics", "morphology"):
        return "English"
    if normal in ("gaeilge", "irish"):
        return "Gaeilge"
    if normal in ("sese", "science", "history", "geography", "eolaíocht", "stair", "tíreolaíocht"):
        return "SESE"
    return "Other"


def project_learning_position(existing, history):
    """Record facts, not model guesses; recalculates safely after date corrections.

    Keep the teacher's context before the generated evidence section. Replace
    that section from durable history, so retries/corrections cannot duplicate
    or retain obsolete outcomes. Notes are quoted verbatim, including any
    correction contradicting the selected status or original intention.
    """
    result = copy.deepcopy(existing)
    evidence = {key: [] for key in POSITION_KEYS}
    for row in sorted(history, key=lambda item: (item["planning_date"], item["id"]), reverse=True):
        for lesson in row.get("lessons", []):
            status = lesson["status"]
            outcome = {
                "Completed": "Specific lesson recorded completed; progress to the next evidence-supported learning. This does not establish completion of the wider topic/unit.",
                "Partially completed": "Partially completed; unfinished learning remains outstanding. The exact stopping point is unknown unless the teacher note specifies it.",
                "Not taught": "Not taught; this planned learning remains outstanding. Do not infer pupil difficulty.",
            }[status]
            note = f" Teacher note (authoritative): {lesson['note']}" if lesson["note"] else ""
            evidence[subject_bucket(lesson["subject"])].append(
                f"- {row['planning_date']} | {lesson['subject']} — {lesson['topic']}. "
                f"Planned learning: {lesson['learning_intention']} {outcome}{note}"
            )
    for key in POSITION_KEYS:
        baseline = str(existing.get(key, "")).split(EVIDENCE_MARKER, 1)[0]
        result[key] = baseline + (EVIDENCE_MARKER + "\n".join(evidence[key]) if evidence[key] else "")
    return result
