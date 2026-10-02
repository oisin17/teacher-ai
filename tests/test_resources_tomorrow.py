import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from lesson_resources import digest
from resources_tomorrow import next_weekday, next_plan, suggested_types, lesson_choices, run_batches
from test_lesson_resources import context, item


def fake_client(fail_type=None, fail_generation_lesson=None):
    client = Mock()
    def response(**kwargs):
        packet = json.loads(kwargs['input'].rsplit('\n', 1)[-1])
        if kwargs['text']['format']['name'] == 'lesson_resource_batch':
            if packet['context']['lesson']['lesson_id'] == fail_generation_lesson:
                raise RuntimeError('test failure')
            return SimpleNamespace(output_text=json.dumps({'resources': [item(t) for t in packet['selected_types']]}))
        return SimpleNamespace(output_text=json.dumps({'checks': [dict(type=r['type'], **{'pass': r['type'] != fail_type}, findings=['Incorrect answer'] if r['type'] == fail_type else []) for r in packet['resources']]}))
    client.responses.create.side_effect = response
    return client


class TomorrowTests(unittest.TestCase):
    def setUp(self):
        self.context = context()
        self.plan = dict(plan_id='p', planning_date='2026-10-01', planning_quality={'state':'Pass'}, lessons=[self.context['lesson']])
        self.store = Mock()
        self.store.resource_context.return_value = self.context

    def request(self, kind='whiteboard', **kwargs):
        return dict(lesson_id='l', type=kind, **kwargs)

    def test_weekdays_friday_and_weekends(self):
        for day, expected in [('2026-10-01','2026-10-02'),('2026-10-02','2026-10-05'),('2026-10-03','2026-10-05'),('2026-10-04','2026-10-05')]:
            self.assertEqual(next_weekday(day), expected)

    def test_missing_plan_does_not_skip_and_legacy_is_not_approved(self):
        tuesday = dict(self.plan, planning_date='2026-10-06')
        legacy = dict(self.plan, planning_date='2026-10-05', planning_quality={})
        self.assertEqual(next_plan([tuesday,legacy], '2026-10-02'), ('2026-10-05',None))

    def test_exact_next_day_approved_plan(self):
        self.assertEqual(next_plan([self.plan], '2026-09-30'), ('2026-10-01', self.plan))

    def test_suggestions_without_ai_and_bounded(self):
        for subject in ('Maths','English','Gaeilge','History','Art'):
            lesson=dict(self.context['lesson'],subject=subject)
            self.assertTrue(1 <= len(suggested_types(lesson)) <= 3)
        self.assertEqual(suggested_types(dict(self.context['lesson'],phases=[{'activity':'reason and explain'}]))[:2], ['whiteboard','challenge'])

    def resource(self):
        r=run_batches(self.store,fake_client(),self.plan,[self.request()])['resources'][0]
        r['revision']=1
        return r

    def test_current_saved_not_selected_and_old_parent_not_matched(self):
        r=self.resource()
        choices=lesson_choices(self.context,[r])
        self.assertEqual(choices[0]['status'],'Already saved — regenerate?')
        self.assertFalse(choices[0]['selected'])
        old=dict(r,plan_id='old')
        self.assertEqual(lesson_choices(self.context,[old])[0]['status'],'No resource saved')

    def test_evidence_changed_is_distinct(self):
        r=self.resource();changed=copy.deepcopy(self.context);changed['profile']['class_level']='6th Class'
        choice=lesson_choices(changed,[r])[0]
        self.assertEqual(choice['status'],'Evidence changed');self.assertIsNone(choice['existing'])

    def test_source_block_does_not_stop_good_batch(self):
        self.context['lesson']['subject']='English'
        c=fake_client();r=run_batches(self.store,c,self.plan,[self.request('discussion'),self.request('comprehension')])
        self.assertEqual(r['calls'],2);self.assertEqual(len(r['resources']),1);self.assertEqual(len(r['blocked']),1)
        self.assertEqual(r['resources'][0]['quality']['state'],'Pass')

    def test_one_review_failure_keeps_passing_sibling_two_calls(self):
        r=run_batches(self.store,fake_client(fail_type='practice'),self.plan,[self.request(),self.request('practice')])
        self.assertEqual(r['calls'],2)
        self.assertEqual([x['quality']['state'] for x in r['resources']],['Pass','Blocked'])

    def test_failed_lesson_does_not_stop_next_and_calls_are_measured(self):
        lesson=dict(self.context['lesson'],lesson_id='l2');self.plan['lessons'].append(lesson)
        self.store.resource_context.side_effect=lambda day,p,l: dict(self.context,lesson=self.plan['lessons'][0 if l=='l' else 1])
        r=run_batches(self.store,fake_client(fail_generation_lesson='l'),self.plan,[self.request(),dict(lesson_id='l2',type='whiteboard')])
        self.assertEqual(r['calls'],3);self.assertEqual(len(r['failures']),1);self.assertEqual(r['resources'][0]['lesson_id'],'l2')

    def test_no_printing_retained_and_individual_override_splits(self):
        c=fake_client();r=run_batches(self.store,c,self.plan,[self.request(),self.request('practice',override='six questions; no printing')],'no printing')
        self.assertEqual(r['calls'],4)
        self.assertEqual([x['instruction'] for x in r['resources']],['no printing','six questions; no printing'])
        self.assertEqual(r['resources'][1]['instruction_context']['batch'],'no printing')
        self.assertEqual(r['resources'][1]['instruction_context']['override'],'six questions; no printing')

    def test_selected_saved_regenerates_same_id_and_original_is_unchanged(self):
        old=self.resource();before=copy.deepcopy(old)
        r=run_batches(self.store,fake_client(),self.plan,[self.request(existing=old)],'keep short')['resources'][0]
        self.assertEqual((r['id'],r['revision'],r['created_at']), (old['id'],old['revision'],old['created_at']))
        self.assertEqual(old,before);self.store.save_resource.assert_not_called()

    def test_exact_parent_guard_and_stale_context(self):
        old=self.resource();old['plan_id']='other'
        r=run_batches(self.store,fake_client(),self.plan,[self.request(existing=old)])
        self.assertEqual(r['calls'],0);self.assertEqual(len(r['blocked']),1)
        self.store.resource_context.side_effect=__import__('persistence').StorageError('Replaced')
        r=run_batches(self.store,fake_client(),self.plan,[self.request()])
        self.assertEqual(r['calls'],0);self.assertEqual(len(r['failures']),1)

    def test_no_writes_and_input_immutability_and_progressive_results(self):
        before=copy.deepcopy(self.plan);collected=[]
        r=run_batches(self.store,fake_client(),self.plan,[self.request(),self.request('practice')],on_result=collected.extend)
        self.assertEqual(self.plan,before);self.assertEqual(collected,r['resources'])
        self.assertEqual(self.store.method_calls,[unittest.mock.call.resource_context('2026-10-01','p','l')])
        self.assertGreaterEqual(r['elapsed_seconds'],r['ai_seconds']-0.01)

    def test_read_only_mixed_probe_checks_stale_guard_without_writes(self):
        from resources_tomorrow import probe_mixed_review
        from persistence import StorageError
        rs=run_batches(self.store,fake_client(),self.plan,[self.request(),self.request('practice')])['resources']
        self.store.list_resources.return_value=rs
        self.store.resource_context.side_effect=lambda day,p,l: self.context if p=='p' else (_ for _ in ()).throw(StorageError('Replaced'))
        before=copy.deepcopy(rs)
        result=probe_mixed_review(self.store,fake_client(fail_type='whiteboard'),self.plan)
        self.assertTrue(result['invalid_resource_blocked']);self.assertTrue(result['sibling_passed'])
        self.assertTrue(result['replaced_lesson_blocked']);self.assertTrue(result['saved_resources_unchanged'])
        self.assertEqual(result['evidence_changed_status'],'Evidence changed')
        self.assertEqual(result['earlier_plan_status'],'No resource saved')
        self.assertEqual(rs,before);self.store.save_resource.assert_not_called()

    def test_year_and_leap_boundaries(self):
        self.assertEqual(next_weekday('2027-12-31'), '2028-01-03')
        self.assertEqual(next_weekday('2028-02-28'), '2028-02-29')
        self.assertEqual(next_weekday('2028-02-29'), '2028-03-01')

    def test_malformed_generation_group_does_not_stop_next_lesson(self):
        lesson=dict(self.context['lesson'],lesson_id='l2');self.plan['lessons'].append(lesson)
        self.store.resource_context.side_effect=lambda day,p,l: dict(self.context,lesson=self.plan['lessons'][0 if l=='l' else 1])
        c=fake_client();original=c.responses.create.side_effect
        def response(**kwargs):
            packet=json.loads(kwargs['input'].rsplit('\n',1)[-1])
            if kwargs['text']['format']['name']=='lesson_resource_batch' and packet['context']['lesson']['lesson_id']=='l':
                return SimpleNamespace(output_text=json.dumps({'resources':[dict(item(),body=['malformed'])]}))
            return original(**kwargs)
        c.responses.create.side_effect=response
        r=run_batches(self.store,c,self.plan,[self.request(),dict(lesson_id='l2',type='whiteboard')])
        self.assertEqual(r['calls'],3);self.assertEqual(len(r['failures']),1)
        self.assertEqual(r['resources'][0]['lesson_id'],'l2');self.store.save_resource.assert_not_called()
