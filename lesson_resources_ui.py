"""Lesson-local resource editor. AI runs only on explicit submit actions."""
import copy
import importlib
import lesson_resources
if lesson_resources.VERSION != 5:
 importlib.reload(lesson_resources)
import streamlit as st
from lesson_resources import TYPES, suggestions, generate, review, digest, checked_digest, ResourceFailure
from persistence import StorageError

MODULE_VERSION = 6


def _message(error):
 st.error(str(error))


def editor(store, client, resource, pending_key):
 rid=resource['id']; epoch=st.session_state.get('resource_epoch_'+rid,0)
 key=f'resource_{rid}_{resource["revision"]}_{epoch}'
 st.markdown('**'+resource['title']+'** · '+TYPES[resource['type']])
 st.caption('Teacher AI-created material · '+resource['planning_date'])
 with st.expander('View classroom content', expanded=True):
  st.markdown(resource['body'])
 if resource['guidance']:
  with st.expander('Teacher answers / guidance'): st.markdown(resource['guidance'])
 with st.expander('Edit resource'):
  with st.form(key+'_edit'):
   title=st.text_input('Resource title',value=resource['title'],key=key+'_title')
   body=st.text_area('Classroom content',value=resource['body'],height=230,key=key+'_body')
   guidance=st.text_area('Teacher answers / guidance (optional)',value=resource['guidance'],height=100,key=key+'_guidance')
   save=st.form_submit_button('Save changes' if resource['revision'] else 'Save resource')
  if save:
   candidate=copy.deepcopy(resource); candidate.update(title=title,body=body,guidance=guidance)
   try:
    context=store.resource_context(resource['planning_date'],resource['plan_id'],resource['lesson_id'])
    if digest(context)!=resource['context_digest']: raise StorageError('Lesson evidence changed. Regenerate before saving this draft.')
    changed=(body,guidance)!=(resource['body'],resource['guidance'])
    if changed or candidate['quality']['state']!='Pass':
     with st.spinner('Checking your edited resource...'):
      findings,metrics=review([candidate],context,candidate['source_text'],candidate['instruction'],client)
     candidate['quality']={'state':'Blocked' if findings[candidate['type']] else 'Pass','findings':findings[candidate['type']],'content_digest':digest({'body':body,'guidance':guidance}),'version':1}
     candidate['quality']['input_digest']=checked_digest(candidate)
     candidate['metrics']=dict(candidate['metrics'],edit_review=metrics)
    if candidate['quality']['state']!='Pass':
     st.session_state[pending_key][rid]=candidate; st.error('Resource not saved: '+'; '.join(candidate['quality']['findings']))
    else:
     store.save_resource(candidate,resource['revision'])
     st.session_state[pending_key].pop(rid,None)
     st.session_state['resource_notice']='Resource saved. Classroom progress unchanged.'
     st.rerun()
   except (StorageError,ResourceFailure) as e: _message(e)
 with st.expander('Copy resource text'):
  st.caption('Use the copy control in the top-right corner. Pupil content and teacher guidance are separate.')
  st.code(resource['body'],language=None)
  if resource['guidance']: st.code(resource['guidance'],language=None)
 with st.expander('Regenerate this resource'):
  instruction=st.text_input('Generation instruction',value=resource['instruction'],max_chars=300,key=key+'_instruction')
  if st.button('Regenerate resource',key=key+'_regen'):
   try:
    context=store.resource_context(resource['planning_date'],resource['plan_id'],resource['lesson_id'])
    with st.spinner('Generating and checking this resource...'):
     candidate=generate(context,[resource['type']],instruction,resource['source_text'],resource['include_answers'],client)[0]
    candidate.update(id=rid,revision=resource['revision'],created_at=resource['created_at'],title=resource['title'])
    st.session_state[pending_key][rid]=candidate
    st.session_state['resource_epoch_'+rid]=epoch+1
    st.rerun()
   except (StorageError,ResourceFailure) as e: _message(e)
 with st.expander('Resource checks / basis'):
  st.caption(resource['quality']['state']+' · '+str(resource['quality']['findings']))
  st.caption('Instruction: '+(resource['instruction'] or '(none)'))
  st.caption('Generation: '+str(resource['metrics'].get('generation_seconds',0))+'s · review: '+str(resource['metrics'].get('review_seconds',0))+'s · AI calls: '+str(resource['metrics'].get('generation_calls',0)+resource['metrics'].get('review_calls',0)))
  st.caption('Based on the exact saved lesson, linked learning/carryover, relevant profile and supplied source when present.')
  if st.button('Test stale lesson reference (read-only)',key=key+'_stale_probe'):
   try:
    before=store.list_resources(resource['planning_date'])
    store.resource_context(resource['planning_date'],resource['plan_id']+'-replaced',resource['lesson_id'])
    st.error('Unexpectedly accepted a stale reference.')
   except StorageError as error:
    st.success('Stale/replaced lesson blocked: '+str(error))
    st.caption('Saved resources unchanged: '+str(store.list_resources(resource['planning_date'])==before))
  if resource['source_text']: st.text(resource['source_text'])
  if resource.get('versions'):
   with st.expander('Earlier saved versions'):
    for old in reversed(resource['versions']):
     st.caption('Revision '+str(old['revision'])+' · '+old['updated_at']);st.code(old['body'],language=None)


def lesson_panel(store,client,plan,lesson,saved):
 key=f'resources_{plan["plan_id"]}_{lesson["lesson_id"]}'
 pending_key=key+'_pending'; st.session_state.setdefault(pending_key,{})
 if st.button('Create resources / saved resources',key=key+'_open'):
  st.session_state[key+'_visible']=not st.session_state.get(key+'_visible',False)
 if not st.session_state.get(key+'_visible',False): return
 with st.expander('Create resources / saved resources', expanded=True):
  if plan.get('planning_quality',{}).get('state')!='Pass':
   st.caption('New resource generation requires a saved rubric-approved plan. Historical lessons remain unchanged.');return
  more=st.checkbox('More resource options',key=key+'_more')
  options=list(TYPES) if more else suggestions(lesson)
  with st.form(key+'_generate'):
   types=st.multiselect('Resource types (up to four)',options,format_func=lambda t:TYPES[t],key=key+'_types')
   instruction=st.text_input('Optional instruction',max_chars=300,placeholder='six questions · no printing · make this easier',key=key+'_request')
   source=st.text_area('Source passage or exact task (optional; required for comprehension)',max_chars=16000,key=key+'_source',help='A book name is not source text. Paste only the relevant content. Clearly label test material.')
   answers=st.checkbox('Include teacher answers where useful',value=True,key=key+'_answers',help='Answers are useful for closed questions; discussion prompts and Art checklists need not include them.')
   submit=st.form_submit_button('Generate selected resources')
  if submit:
   try:
    context=store.resource_context(plan['planning_date'],plan['plan_id'],lesson['lesson_id'])
    with st.spinner('Generating and checking resources...'):
     candidates=generate(context,types,instruction,source,answers,client)
    st.session_state[pending_key].update({r['id']:r for r in candidates})
   except (StorageError,ResourceFailure) as e: _message(e)
  resources={r['id']:r for r in saved if r['plan_id']==plan['plan_id'] and r['lesson_id']==lesson['lesson_id']}
  resources.update(st.session_state[pending_key])
  for resource in resources.values(): editor(store,client,resource,pending_key)


def historical_panel(saved,plan):
 old=[r for r in saved if not plan or r['plan_id']!=plan['plan_id']]
 if old:
  with st.expander('Resources from earlier plans'):
   st.caption('These retain their original lesson association. Copy them here; generate new resources from the current approved lesson.')
   for r in old:
    st.markdown('**'+r['title']+'** · '+r['lesson_snapshot']['subject'])
    st.caption('Earlier plan '+r['plan_id']+' · '+r['planning_date']);st.code(r['body'],language=None)
    if r['guidance']:
     with st.expander('Teacher guidance — '+r['title']): st.code(r['guidance'],language=None)
