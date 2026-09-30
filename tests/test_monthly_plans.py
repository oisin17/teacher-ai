import unittest
from datetime import date
from monthly_plans import suggest_dates

class SuggestionTests(unittest.TestCase):
    def test_month_year_and_leap_year(self):
        result = suggest_dates('February 2028 Monthly Plan')
        self.assertEqual(result['start'], date(2028, 2, 1))
        self.assertEqual(result['end'], date(2028, 2, 29))

    def test_conflicts_unknown_and_missing_year(self):
        self.assertIsNone(suggest_dates('September 2026', 'October_2026.docx')['start'])
        self.assertIsNone(suggest_dates('Curriculum plan')['start'])
        self.assertIn('only a suggestion', suggest_dates('September', reference_date=date(2027, 1, 1))['evidence'])

    def test_explicit_date_range(self):
        result = suggest_dates('School plan: 01/09/2026 to 30/09/2026')
        self.assertEqual(result['start'], date(2026, 9, 1))
        self.assertEqual(result['end'], date(2026, 9, 30))
