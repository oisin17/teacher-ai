import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from planning_quality import CATEGORIES, code_checks, quality_gate, QualityFailure, digest, evaluate_candidate
from fixtures import sample_plan


def context(day='2026-10-01'):
    return dict(planning_date=day,monthly_plan=dict(id='oct',title='October',start_date='2026-10-01',end_date='2026-10-31',plan_text='English narrative.'),
        teacher_profile={},planning_setup={},current_learning_position={'English':'Final activity unfinished; Gaeilge not taught due to assembly'},recent_progress=[],learning_items=[],carryover=[])


def candidate(c):
    p=sample_plan(c['planning_date']);p['monthly_plan']={k:c['monthly_plan'][k] for k in ('id','title','start_date','end_date')};return p


def review(findings=None, decisions=None):
    return SimpleNamespace(output_text=json.dumps(dict(checked_categories=list(CATEGORIES),findings=findings or [],carryover_decisions=decisions or [])))


class QualityTests(unittest.TestCase):
    def test_overview_cannot_schedule_a_teaching_slot_without_a_lesson(self):
        c=context(); p=candidate(c)
        p['overview'] += '\n10:00–10:30 English — procedural reading'
        self.assertIn('overview_missing_lesson',{f['code'] for f in code_checks(p,c)})
        p['overview']=p['overview'].replace('English — procedural reading','Morning meeting')
        self.assertNotIn('overview_missing_lesson',{f['code'] for f in code_checks(p,c)})

    def test_code_checks_run_before_model_and_one_repair_limit(self):
        c=context();p=candidate(c);p['lessons'][0]['phases'][0]['minutes']=50
        p['overview']=p['overview'].replace('09:30–10:00','09:30–10:10')
        client=Mock();client.responses.create.return_value=SimpleNamespace(output_text=json.dumps({k:p[k] for k in ('overview','lessons')}))
        with self.assertRaises(QualityFailure) as raised:quality_gate(p,c,client,{})
        self.assertEqual(raised.exception.report['state'],'Blocked');self.assertEqual(client.responses.create.call_count,1)
        self.assertIn('phase_duration',{f['code'] for f in raised.exception.report['findings']})
        timing = next(f for f in raised.exception.report['findings'] if f['code']=='phase_duration')
        self.assertIn('requires exactly',timing['message']); self.assertIn('supplied total:',timing['message'])

    def test_repair_pass_and_metadata(self):
        c=context();p=candidate(c);fixed=copy.deepcopy(p);p['lessons'][0]['phases'][0]['minutes']=50
        client=Mock();client.responses.create.side_effect=[SimpleNamespace(output_text=json.dumps({'lesson_0':dict(details=fixed['lessons'][0]['details'],activities=dict(phase_1='Recall rounding',phase_2='Model rounding',phase_3='Practise rounding',phase_4='Check and tidy'))})),review()]
        result=quality_gate(p,c,client,{})
        self.assertEqual(result['planning_quality']['repair_kind'],'phase_budget')
        self.assertEqual(result['planning_quality']['state'],'Pass');self.assertEqual(result['planning_quality']['extra_ai_calls'],2)
        self.assertEqual(result['planning_quality']['revision_count'],1);self.assertEqual(result['planning_quality']['context_digest'],digest(c))

    def test_modest_repair_arithmetic_is_compiled_without_another_ai_attempt(self):
        c=context();p=candidate(c);fixed=copy.deepcopy(p)
        p['lessons'][0]['phases'][0]['minutes']=50
        p['overview']=p['overview'].replace('09:30–10:00','09:30–10:10')
        fixed['lessons'][0]['phases'][1]['minutes'] += 5
        activities=[q['activity'] for q in fixed['lessons'][0]['phases']]
        client=Mock();client.responses.create.side_effect=[SimpleNamespace(output_text=json.dumps({k:fixed[k] for k in ('overview','lessons')})),review()]
        result=quality_gate(p,c,client,{})
        self.assertEqual(sum(q['minutes'] for q in result['lessons'][0]['phases']),30)
        self.assertEqual([q['activity'] for q in result['lessons'][0]['phases']],activities)
        self.assertEqual(result['planning_quality']['revision_count'],1)
        self.assertEqual(client.responses.create.call_count,2)
        self.assertEqual(len(result['planning_quality']['phase_adjustments']),1)

    def test_large_timing_discrepancies_are_not_compiled(self):
        from planning_quality import allocate_repair_minutes
        c=context();p=candidate(c);p['lessons'][0]['phases'][0]['minutes']=50
        before=copy.deepcopy(p)
        self.assertEqual(allocate_repair_minutes(p),[]);self.assertEqual(p,before)

    def test_short_slot_budget_is_exact_and_semantics_can_still_block(self):
        c=context();p=candidate(c)
        p['lessons'][0]['time']='09:30–09:45';p['overview']=p['overview'].replace('09:30–10:00','09:30–09:45')
        before=copy.deepcopy(p);client=Mock()
        patch={'lesson_0':dict(details='Board examples; support with number line; check one response.',activities=dict(phase_1='Recall known rounding',phase_2='Model and practise two examples',phase_3='Check response and tidy'))}
        f=dict(code='invalid_scope',severity='Blocked',lesson_index=0,message='A remaining semantic blocker',evidence=p['lessons'][0]['topic'])
        client.responses.create.side_effect=[SimpleNamespace(output_text=json.dumps(patch)),review([f])]
        with self.assertRaises(QualityFailure) as raised:quality_gate(p,c,client,{})
        self.assertEqual(raised.exception.report['state'],'Blocked')
        self.assertEqual(raised.exception.report['phase_adjustments'][0]['after'],[3,9,3])
        self.assertEqual(client.responses.create.call_count,2);self.assertEqual(p,before)

    def test_invalid_timing_patch_preserves_input_and_does_not_retry(self):
        c=context();p=candidate(c);p['lessons'][0]['phases'][0]['minutes']=90;before=copy.deepcopy(p)
        client=Mock();client.responses.create.return_value=SimpleNamespace(output_text='{}')
        with self.assertRaises(QualityFailure) as raised:quality_gate(p,c,client,{})
        self.assertEqual(raised.exception.report['state'],'Unchecked')
        self.assertEqual(client.responses.create.call_count,1);self.assertEqual(p,before)

    def test_first_pass_one_review_no_mutation(self):
        c=context();p=candidate(c);before=copy.deepcopy(c);client=Mock();client.responses.create.return_value=review()
        result=quality_gate(p,c,client,{})
        self.assertEqual(result['planning_quality']['extra_ai_calls'],1);self.assertEqual(c,before)

    def test_semantic_hard_blockers_are_not_downgraded(self):
        c=context();p=candidate(c)
        for code in ('unsupported_content','unfinished_contradiction','completed_repetition','broad_completion'):
            with self.subTest(code=code):
                f=dict(code=code,severity='Blocked',lesson_index=1,message='Violates teacher evidence',evidence='Final activity unfinished')
                client=Mock();client.responses.create.side_effect=[review([f]),SimpleNamespace(output_text=json.dumps({k:p[k] for k in ('overview','lessons')})),review([f])]
                with self.assertRaises(QualityFailure) as raised:quality_gate(copy.deepcopy(p),c,client,{})
                self.assertEqual(raised.exception.report['state'],'Blocked');self.assertEqual(client.responses.create.call_count,3)

    def test_nonnegotiable_codes_cannot_be_softened_by_reviewer(self):
        c=context();p=candidate(c);client=Mock()
        client.responses.create.return_value=review([dict(code='completed_repetition',severity='Revise',lesson_index=0,message='Repeats completed learning',evidence=p['lessons'][0]['topic'])])
        report,_=evaluate_candidate(p,c,client)
        self.assertEqual(report['state'],'Blocked')

    def test_legitimate_retrieval_and_carryover_deferral(self):
        c=context();c['carryover']=[dict(id='carry',state='outstanding',learning='Finish final activity')]
        p=candidate(c);p['lessons'][0]['phases'][0]['activity']='Brief retrieval of completed addition before new rounding'
        client=Mock();client.responses.create.return_value=review(decisions=[dict(id='carry',decision='deferred',reason='No English writing slot today after protected Sport; next writing lesson')])
        result=quality_gate(p,c,client,{})
        self.assertEqual(result['planning_quality']['state'],'Pass');self.assertEqual(c['carryover'][0]['state'],'outstanding')

    def test_review_schema_requires_every_outstanding_carryover_decision(self):
        c=context(); c['carryover']=[dict(id='carry',state='outstanding',learning='Finish final activity')]
        p=candidate(c); client=Mock()
        def respond(**kwargs):
            schema=kwargs['text']['format']['schema']['properties']['carryover_decisions']
            self.assertEqual(schema['required'],['carry'])
            self.assertFalse(schema['additionalProperties'])
            self.assertEqual(schema['properties']['carry']['properties']['decision']['enum'],['deferred'])
            return SimpleNamespace(output_text=json.dumps(dict(checked_categories=list(CATEGORIES),findings=[],carryover_decisions={'carry':dict(decision='deferred',reason='Protected Sport reduces available English writing time; next writing slot.')})))
        client.responses.create.side_effect=respond
        result=quality_gate(p,c,client,{})
        self.assertEqual(result['planning_quality']['state'],'Pass')
        self.assertEqual(result['planning_quality']['carryover_decisions'][0]['id'],'carry')
        self.assertEqual(c['carryover'][0]['state'],'outstanding')

    def test_unchecked_is_fail_closed(self):
        c=context();p=candidate(c)
        for output in ('bad json',json.dumps(dict(checked_categories=[],findings=[],carryover_decisions=[]))):
            client=Mock();client.responses.create.return_value=SimpleNamespace(output_text=output)
            with self.assertRaises(QualityFailure) as raised:quality_gate(p,c,client,{})
            self.assertEqual(raised.exception.report['state'],'Unchecked')

    def test_unverifiable_findings_and_missing_carryover_fail_closed(self):
        c=context();p=candidate(c);client=Mock();client.responses.create.return_value=review([dict(code='x',severity='Blocked',lesson_index=1,message='bad',evidence='invented evidence')])
        with self.assertRaises(ValueError):evaluate_candidate(p,c,client)
        c['carryover']=[dict(id='carry',state='outstanding')];client.responses.create.return_value=review()
        with self.assertRaises(ValueError):evaluate_candidate(p,c,client)

    def test_quote_wrappers_and_whitespace_preserve_evidence_verification(self):
        from planning_quality import verifiable_quote
        evidence={'source':'How to Organise\na Horse Show'}
        self.assertTrue(verifiable_quote('"How to Organise a Horse Show"',evidence))
        self.assertFalse(verifiable_quote('How to Organise a Dog Show',evidence))
        self.assertFalse(verifiable_quote('How to … Horse Show',evidence))

    def test_canonical_reference_does_not_authorise_unrelated_carryover(self):
        c=context();c['carryover']=[dict(id='carry',state='outstanding',learning='Prior final activity unfinished.')]
        p=candidate(c);p['lessons'][0]['carryover_ids']=['carry']
        f=dict(code='invalid_scope',severity='Blocked',lesson_index=0,message='Maths phases do not resume prior English task',evidence=p['lessons'][0]['topic'])
        client=Mock();client.responses.create.side_effect=[review([f],[dict(id='carry',decision='addressed',reason='Linked but unrelated phases')]),SimpleNamespace(output_text=json.dumps({k:p[k] for k in ('overview','lessons')})),review([f],[dict(id='carry',decision='addressed',reason='Still unrelated phases')])]
        with self.assertRaises(QualityFailure) as raised:quality_gate(p,c,client,{})
        self.assertEqual(raised.exception.report['state'],'Blocked')
        self.assertNotIn('Confirmed carryover reference',p['lessons'][0]['details'])
        self.assertEqual(c['carryover'][0]['state'],'outstanding')

    def test_model_evidence_references_resolve_to_original_text(self):
        c=context();p=candidate(c);client=Mock()
        def respond(**kwargs):
            packet=json.loads(kwargs['input'].split('SOURCE-REFERENCED PACKET:')[1].split('\n',1)[1])
            reference=packet['candidate']['lessons'][0]['topic']['evidence_id']
            schema=kwargs['text']['format']['schema']['properties']['findings']['items']
            self.assertIn(reference,schema['properties']['evidence_id']['enum'])
            return SimpleNamespace(output_text=json.dumps(dict(checked_categories=list(CATEGORIES),findings=[dict(code='lesson_quality',severity='Revise',lesson_index=0,message='Material quality issue',evidence_id=reference)],carryover_decisions=[])))
        client.responses.create.side_effect=respond
        report,_=evaluate_candidate(p,c,client)
        self.assertEqual(report['findings'][0]['evidence'],p['lessons'][0]['topic'])
        self.assertNotIn('evidence_id',report['findings'][0])

    def test_unknown_model_evidence_reference_fails_closed(self):
        c=context();p=candidate(c);client=Mock()
        client.responses.create.return_value=SimpleNamespace(output_text=json.dumps(dict(checked_categories=list(CATEGORIES),findings=[dict(code='lesson_quality',severity='Revise',lesson_index=0,message='Untrusted finding',evidence_id='unknown')],carryover_decisions=[])))
        with self.assertRaises(QualityFailure) as raised:quality_gate(p,c,client,{})
        self.assertEqual(raised.exception.report['state'],'Unchecked')

    def test_date_boundary_and_all_item_state_blockers(self):
        from monthly_learning import fingerprint
        c=context();p=candidate(c);p['planning_date']='2026-09-30'
        self.assertIn('monthly_date',{f['code'] for f in code_checks(p,c)})
        p=candidate(c);item=dict(id='i',monthly_plan_id='oct',archived=False,requires_clarification=False,status='Not started',fingerprint=fingerprint(c['monthly_plan']['plan_text']))
        p['lessons'][1]['monthly_item_links']=[dict(item_id='i',coverage='narrative')]
        for changes in ({},{'archived':True},{'requires_clarification':True},{'status':'Completed'},{'monthly_plan_id':'sept'},{'fingerprint':'stale'}):
            c['learning_items']=[dict(item,**changes)]
            self.assertEqual('invalid_item' in {f['code'] for f in code_checks(p,c)},bool(changes))

    def test_protected_daily_weekly_and_singing(self):
        c=context();c['teacher_profile']={'thursday_singing':True,'recurring_arrangements':'Daily\n10:45–11:00 Lunch\n11:00–11:15 Yard\n13:05–13:20 DEAR\n14:20–14:30 Pack Up\nWeekly\nFriday 11:15–11:45 Sport\nFriday afternoon Art'}
        p=candidate(c);p['overview']+='\n10:45–11:00 Lunch\n11:00–11:15 Yard\n13:05–13:20 DEAR\n13:50–14:00 Pack Up\n14:00–14:30 Singing'
        self.assertEqual(code_checks(p,c),[])
        p['lessons'][2]['time']='14:00–14:30'
        self.assertIn('protected_overlap',{f['code'] for f in code_checks(p,c)})
        c['planning_date']='2026-10-02';p=candidate(c)
        codes={f['code'] for f in code_checks(p,c)};self.assertIn('friday_art',codes);self.assertIn('protected_overlap',codes)

    def test_overlaps_and_exact_phase_total(self):
        c=context();p=candidate(c);p['lessons'][1]['time']='09:40–10:10'
        self.assertIn('lesson_overlap',{f['code'] for f in code_checks(p,c)})
        p=candidate(c);p['overview']+='\n09:40–09:50 Another lesson'
        self.assertIn('overview_overlap',{f['code'] for f in code_checks(p,c)})
        p=candidate(c);p['lessons'][0]['phases'][0]['minutes']=True
        self.assertIn('phase_duration',{f['code'] for f in code_checks(p,c)})
