import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from lesson_resources import CHECK, FORMAT, TYPES, suggestions, generate, review, digest, checked_digest, ResourceFailure, validate_saved


def context():
 return {'plan_id':'p','planning_date':'2026-10-01','lesson':{'lesson_id':'l','subject':'Maths','topic':'Division','learning_intention':'Divide by two','details':'Use boards','time':'09:30–10:00'},'profile':{'class_level':'5th Class'},'learning':[],'carryover':[],'current':{},'recent_progress':[]}

def item(kind='whiteboard'):
 return dict(type=kind,title='Division questions',body='On mini-whiteboards: 12 ÷ 2; 18 ÷ 2.',guidance='6; 9.',evidence_ids=['lesson','profile'])

def client(items=None,passed=True):
 c=Mock();items=items or [item()]
 c.responses.create.side_effect=[SimpleNamespace(output_text=json.dumps({'resources':items})),SimpleNamespace(output_text=json.dumps({'checks':[dict(type=i['type'],**{'pass':passed},findings=[] if passed else ['Contradicts intention']) for i in items]}))]
 return c

class ResourceTests(unittest.TestCase):
 def test_eleven_types_and_suggestions_without_ai(self):
  self.assertEqual(len(TYPES),11)
  for subject,expected in [('Maths','whiteboard'),('Gaeilge','gaeilge'),('History','quiz'),('Art','checklist'),('English','discussion')]:
   c=context();c['lesson']['subject']=subject;self.assertIn(expected,suggestions(c['lesson']))
 def test_evidence_schema_constrains_categories(self):
  refs=FORMAT['schema']['properties']['resources']['items']['properties']['evidence_ids']['items']['enum']
  self.assertEqual(refs,['lesson','profile','learning','carryover','current','source'])
 def test_review_contract_uses_exact_type_ids_and_empty_pass_findings(self):
  self.assertEqual(CHECK['schema']['properties']['checks']['items']['properties']['type']['enum'],list(TYPES))
  c=client(); generate(context(),['whiteboard'],'','',True,c)
  prompt=c.responses.create.call_args_list[1].kwargs['input']
  self.assertIn('MUST include the literal string lesson',prompt);self.assertIn('findings=[]',prompt);self.assertIn('Do not generate or rewrite resources',prompt)
 def test_no_source_comprehension_zero_calls(self):
  c=client()
  with self.assertRaises(ResourceFailure): generate(context(),['comprehension'],'','Reading Zone',True,c)
  c.responses.create.assert_not_called()
 def test_supplied_source_comprehension(self):
  i=item('comprehension');i['evidence_ids']+=['source'];source='TEST MATERIAL: Aoife planted three seeds in a pot and watered them each morning.'
  c=client([i]);r=generate(context(),['comprehension'],'',source,True,c)[0]
  self.assertEqual(r['quality']['state'],'Pass');self.assertEqual(c.responses.create.call_count,2)
 def test_generation_is_pure_and_instruction_retained(self):
  before=context();c=client();r=generate(before,['whiteboard'],'six questions; no printing','',True,c)[0]
  self.assertEqual(before,context());self.assertEqual(r['instruction'],'six questions; no printing');self.assertEqual(r['revision'],0)
 def test_blocked_review_no_repair(self):
  c=client(passed=False);r=generate(context(),['whiteboard'],'','',True,c)[0]
  self.assertEqual(r['quality']['state'],'Blocked');self.assertEqual(c.responses.create.call_count,2)
 def test_unsupported_page_code_blocks_before_review(self):
  i=item();i['body']='Open page 42 in the programme.';c=client([i]);r=generate(context(),['whiteboard'],'','',True,c)[0]
  self.assertEqual(r['quality']['state'],'Blocked');self.assertEqual(c.responses.create.call_count,1)
 def test_differentiated_requires_three_meaningful_sections(self):
  c=client([item('differentiated')]);r=generate(context(),['differentiated'],'','',True,c)[0]
  self.assertEqual(r['quality']['state'],'Blocked');self.assertEqual(c.responses.create.call_count,1)
 def test_no_printing_conflict(self):
  i=item();i['body']='Print out the questions.';c=client([i]);r=generate(context(),['whiteboard'],'no printing','',True,c)[0]
  self.assertEqual(r['quality']['state'],'Blocked')
 def test_optional_guidance_and_batch(self):
  a=item('discussion');a['guidance']='';b=item('checklist');b['guidance']='';c=client([a,b]);rs=generate(context(),['discussion','checklist'],'','',False,c)
  self.assertEqual(len(rs),2);self.assertTrue(all(r['quality']['state']=='Pass' for r in rs));self.assertEqual(c.responses.create.call_count,2)
 def test_malformed_reviewer_blocks_without_error_body(self):
  c=client();c.responses.create.side_effect=[SimpleNamespace(output_text=json.dumps({'resources':[item()]})),RuntimeError('SECRET')]
  r=generate(context(),['whiteboard'],'','',True,c)[0];self.assertNotIn('SECRET',str(r));self.assertEqual(r['quality']['state'],'Blocked')
 def test_changed_content_or_source_invalidates_check(self):
  r=generate(context(),['whiteboard'],'','',True,client())[0];r['revision']=1;validate_saved(r)
  for field in ('body','instruction','source_text'):
   bad=copy.deepcopy(r);bad[field]+=' changed'
   with self.assertRaises(ValueError): validate_saved(bad)
 def test_title_edit_preserves_check(self):
  r=generate(context(),['whiteboard'],'','',True,client())[0];r['revision']=1;r['title']='My title';validate_saved(r)
 def test_review_edits_is_one_call(self):
  c=Mock();c.responses.create.return_value=SimpleNamespace(output_text=json.dumps({'checks':[{'type':'whiteboard','pass':True,'findings':[]}]}))
  findings,metrics=review([item()],context(),'','',c);self.assertFalse(findings['whiteboard']);self.assertEqual(c.responses.create.call_count,1)
 def test_edit_review_excludes_old_findings_and_storage_metadata(self):
  i=item();i['quality']={'findings':['OLD FAILURE']};i['versions']=[{'body':'OLD BODY'}]
  c=Mock();c.responses.create.return_value=SimpleNamespace(output_text=json.dumps({'checks':[{'type':'whiteboard','pass':True,'findings':[]}]}))
  review([i],context(),'','',c)
  prompt=c.responses.create.call_args.kwargs['input']
  self.assertNotIn('OLD FAILURE',prompt);self.assertNotIn('OLD BODY',prompt)
 def test_invalid_generation_preserves_caller(self):
  c=Mock();c.responses.create.return_value=SimpleNamespace(output_text='bad')
  with self.assertRaises(ResourceFailure): generate(context(),['whiteboard'],'','',True,c)
  self.assertEqual(c.responses.create.call_count,1)
