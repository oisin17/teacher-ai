import unittest
from carryover import retain_explicit_links


class CarryoverLinks(unittest.TestCase):
    def test_same_subject_without_explicit_prior_task_has_no_completion_link(self):
        plan = {'lessons': [{'subject': 'Gaeilge', 'details': 'Practise October food vocabulary.', 'carryover_ids': ['missed']}]}
        retain_explicit_links(plan, [{'id': 'missed', 'learning': 'Resume missed September lesson'}])
        self.assertEqual(plan['lessons'][0]['carryover_ids'], [])

    def test_explicit_prior_task_retains_only_known_link(self):
        plan = {'lessons': [{'details': 'Carryover: Finish final activity. Identify where pupils stopped, then finish that task.', 'carryover_ids': ['english', 'unknown']}]}
        retain_explicit_links(plan, [{'id': 'english', 'learning': 'Finish final activity'}])
        self.assertEqual(plan['lessons'][0]['carryover_ids'], ['english'])
