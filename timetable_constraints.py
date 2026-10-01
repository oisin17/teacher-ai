"""Protect teacher-confirmed external Thursday Singing independently of coverage."""
import re
from datetime import date

CONSTRAINT_VERSION = 2

TIME_RANGE = re.compile(r'(\d{1,2}):([0-5]\d)\s*[–—-]\s*(\d{1,2}):([0-5]\d)')


def singing_day(profile, school_date):
    return bool(profile.get('thursday_singing')) and date.fromisoformat(school_date).weekday() == 3


def interval(text):
    match = TIME_RANGE.search(text.replace('*', '').replace('`', ''))
    if not match:
        raise ValueError('A protected Thursday requires explicit lesson times.')
    h1, m1, h2, m2 = map(int, match.groups())
    start, end = h1 * 60 + m1, h2 * 60 + m2
    if h1 > 23 or h2 > 23 or end <= start:
        raise ValueError('Invalid timetable interval')
    return start, end


def validate_protected_plan(plan, profile):
    if not singing_day(profile, plan['planning_date']):
        return plan
    for lesson in plan['lessons']:
        start, end = interval(lesson['time'])
        if end > 830:
            raise ValueError('Normal teaching must finish by 13:50 for pack-up before external Singing.')
    singing = tidy = False
    for line in plan['overview'].splitlines():
        if not TIME_RANGE.search(line.replace('*', '').replace('`', '')):
            continue
        start, end = interval(line)
        external = 'singing' in line.casefold() and start == 840 and end == 870
        singing |= external
        tidy |= bool(re.search(r'pack|tidy', line, re.I)) and start == 830 and end == 840
        if end > 840 and not external:
            raise ValueError('Only external Singing can occupy 14:00–14:30.')
    if not singing or not tidy:
        raise ValueError('Include pack-up before 14:00 and protected Singing 14:00–14:30.')
    return plan
