import unittest
from timetable_constraints import validate_protected_plan


class SingingConstraints(unittest.TestCase):
    def plan(self, day='2026-10-01', time='13:20–13:50'):
        return {'planning_date': day, 'overview': '13:20–13:50 Writing\n13:50–14:00 Pack up / tidy up\n14:00–14:30 Singing — external teacher', 'lessons': [{'time': time}]}

    def test_thursday_singing_and_early_packup(self):
        p = self.plan()
        self.assertIs(validate_protected_plan(p, {'thursday_singing': True}), p)

    def test_overlapping_lesson_or_routine_is_rejected(self):
        for time in ('13:20–14:05', '14:00–14:20', '14:20–14:30'):
            with self.subTest(time=time), self.assertRaises(ValueError):
                validate_protected_plan(self.plan(time=time), {'thursday_singing': True})
        p = self.plan()
        p['overview'] += '\n14:20–14:30 Pack up'
        with self.assertRaises(ValueError):
            validate_protected_plan(p, {'thursday_singing': True})

    def test_missing_singing_or_packup_rejected(self):
        for overview in ('13:50–14:00 Pack up', '14:00–14:30 Singing'):
            p = self.plan()
            p['overview'] = overview
            with self.assertRaises(ValueError):
                validate_protected_plan(p, {'thursday_singing': True})

    def test_other_days_or_disabled_constraint_unchanged(self):
        for day, enabled in [('2026-10-02', True), ('2026-10-01', False)]:
            p = self.plan(day, '14:00–14:20')
            self.assertIs(validate_protected_plan(p, {'thursday_singing': enabled}), p)
