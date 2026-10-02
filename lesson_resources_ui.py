"""Lesson-local resource editor. AI runs only on explicit submit actions."""
import copy
import importlib
import lesson_resources
if lesson_resources.VERSION != 6:
 importlib.reload(lesson_resources)
import streamlit as st
from lesson_resources import TYPES, suggestions, generate, regenerate_resource, review, digest, checked_digest, ResourceFailure
from persistence import StorageError

MODULE_VERSION = 8


def _message(error):
 st.error(str(error))


def _remember_inputs(widget_key, draft_key):
 st.session_state.setdefault('resource_edit_drafts',{})[draft_key]={field:st.session_state[widget_key+'_'+field] for field in ('title','body','guidance')}


def _remember_tomorrow(key):
 st.session_state.setdefault('tomorrow_inputs',{})[key]=st.session_state[key]


def _tomorrow_input(function, label, key, default, **kwargs):
 st.session_state.setdefault(key,st.session_state.setdefault('tomorrow_inputs',{}).get(key,default))
 return function(label,key=key,on_change=_remember_tomorrow,args=(key,),**kwargs)


def _mark_tomorrow_start(prefix):
 from time import perf_counter
 st.session_state[prefix+'_started']=perf_counter()


def editor(store, client, resource, pending_key, view='lesson'):
 rid=resource['id']; epoch=st.session_state.get('resource_epoch_'+rid,0)
 draft_key=f'resource_{rid}_{resource["revision"]}_{epoch}'
 key=draft_key+'_'+view
 values=st.session_state.setdefault('resource_edit_drafts',{}).get(draft_key,resource)
 st.markdown('**'+resource['title']+'** · '+TYPES[resource['type']])
 st.caption('Teacher AI-created material · '+resource['planning_date'])
 with st.expander('View classroom content', expanded=True):
  st.markdown(resource['body'])
 if resource['guidance']:
  with st.expander('Teacher answers / guidance'): st.markdown(resource['guidance'])
 with st.expander('Edit resource'):
  # Non-widget draft state survives widget cleanup on navigation. No AI while editing.
  for field in ('title','body','guidance'):
   st.session_state.setdefault(key+'_'+field,values[field])
  title=st.text_input('Resource title',key=key+'_title',on_change=_remember_inputs,args=(key,draft_key))
  body=st.text_area('Classroom content',height=230,key=key+'_body',on_change=_remember_inputs,args=(key,draft_key))
  guidance=st.text_area('Teacher answers / guidance (optional)',height=100,key=key+'_guidance',on_change=_remember_inputs,args=(key,draft_key))
  save=st.button('Save changes' if resource['revision'] else 'Save resource',key=key+'_save')
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
     st.session_state['resource_edit_drafts'].pop(draft_key,None)
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
     candidate=regenerate_resource(resource,context,instruction,client)
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


def tomorrow_panel(store, client, after):
 from resources_tomorrow import next_plan, lesson_choices, run_batches
 from time import perf_counter
 plans=store.approved_resource_plans()
 target,plan=next_plan(plans,after)
 with st.expander('Resources for Tomorrow'):
  st.caption('Next weekday after your selected planning date: '+str(after)+'. Weekends move to Monday; holidays are not inferred.')
  choose=_tomorrow_input(st.checkbox,'Choose another saved day','tomorrow_choose',False)
  if choose and plans:
   days=[p['planning_date'] for p in plans]
   remembered=st.session_state.setdefault('tomorrow_inputs',{}).get('tomorrow_day',days[-1])
   st.session_state.setdefault('tomorrow_day',remembered if remembered in days else days[-1])
   selected=st.selectbox('Approved saved day',days,key='tomorrow_day',on_change=_remember_tomorrow,args=('tomorrow_day',))
   plan=next(p for p in plans if p['planning_date']==selected);target=selected
  if not plan:
   st.info('No approved saved plan is available for '+target+'. No later day has been selected automatically.');return
  from datetime import date
  st.subheader(('Selected day — ' if choose else 'Tomorrow — ')+date.fromisoformat(target).strftime('%A %d %B'))
  st.caption('Review generated drafts and save each useful resource separately. Classroom progress is unchanged.')
  saved=store.list_resources(target)
  try: contexts=store.resource_day_contexts(target,plan['plan_id'])
  except StorageError as error:
   _message(error);return
  prefix='tomorrow_'+plan['plan_id']
  requests=[]
  batch_instruction=_tomorrow_input(st.text_input,'Whole-batch instruction',prefix+'_instruction','',max_chars=300,placeholder='no printing · keep everything short')
  for lesson in plan['lessons']:
   lid=lesson['lesson_id'];key=f'resources_{plan["plan_id"]}_{lid}';pending_key=key+'_pending'
   st.session_state.setdefault(pending_key,{})
   with st.expander(lesson['subject']+' — '+lesson['topic']):
    try:
     context=contexts[lid]
     choices=lesson_choices(context,saved)
    except StorageError as error:
     _message(error);continue
    selected=[]
    for choice in choices:
     kind=choice['type'];label=TYPES[kind]+' · '+choice['status']
     identity=(choice['existing']['id']+'_'+str(choice['existing']['revision'])) if choice['existing'] else context['plan_id']+'_'+digest(context)
     if _tomorrow_input(st.checkbox,label,prefix+'_'+lid+'_'+kind+'_'+identity,choice['selected']): selected.append(choice)
    with st.expander('Lesson options'):
     source=_tomorrow_input(st.text_area,'Source passage for '+lesson['subject'],prefix+'_'+lid+'_source','',max_chars=16000,help='Paste relevant supplied text for comprehension. A programme name is insufficient.')
     overrides={}
     for choice in choices:
      kind=choice['type']
      overrides[kind]=_tomorrow_input(st.text_input,'Instruction override — '+TYPES[kind],prefix+'_'+lid+'_'+kind+'_override','',max_chars=300,help='If entered, replaces the whole-batch instruction for this resource. Include any constraints you want to retain.')
    for choice in selected:
     requests.append(dict(lesson_id=lid,type=choice['type'],existing=choice['existing'],source=source,override=overrides[choice['type']],answers=True))
    changed=[r for r in saved if r['plan_id']==plan['plan_id'] and r['lesson_id']==lid and r['context_digest']!=digest(context)]
    if changed: st.caption(str(len(changed))+' saved resource(s) have changed evidence. Originals are preserved.')
    exact=[r for r in saved if r['plan_id']==plan['plan_id'] and r['lesson_id']==lid]
    if exact and st.checkbox('Show saved resources — '+lesson['subject'],key=prefix+'_'+lid+'_saved'):
     for resource in exact:
      if resource in changed:
       st.caption('Evidence changed — '+resource['title']);st.code(resource['body'],language=None)
      elif resource['id'] not in st.session_state[pending_key]:
       editor(store,client,resource,pending_key,view='tomorrow_saved')
  submitted=st.button('Generate tomorrow resources',key=prefix+'_generate',disabled=not requests,on_click=_mark_tomorrow_start,args=(prefix,))
  if submitted:
   start=perf_counter()
   progress=st.empty()
   def keep(resources):
    for resource in resources:
     pending=f'resources_{plan["plan_id"]}_{resource["lesson_id"]}_pending'
     st.session_state.setdefault(pending,{})[resource['id']]=resource
     st.session_state['resource_epoch_'+resource['id']]=st.session_state.get('resource_epoch_'+resource['id'],0)+1
    progress.info('Checked: '+resources[0]['lesson_snapshot']['subject']+' — '+', '.join(TYPES[r['type']] for r in resources))
   with st.spinner('Generating and checking selected lesson batches...'):
    result=run_batches(store,client,plan,requests,batch_instruction,on_result=keep)
   result['action_elapsed_seconds']=round(perf_counter()-start,2)
   st.session_state[prefix+'_result']=result
  result=st.session_state.get(prefix+'_result')
  if result:
   st.caption(f"Latest batch: {result['calls']} AI calls · AI-only {result['ai_seconds']}s · generation action {result['action_elapsed_seconds']}s (before final page rendering).")
   for issue in result['blocked']+result['failures']: st.warning(issue['reason'])
  for lesson in plan['lessons']:
   pending=f'resources_{plan["plan_id"]}_{lesson["lesson_id"]}_pending'
   for resource in st.session_state.get(pending,{}).values():
    editor(store,client,resource,pending,view='tomorrow')
  historical_panel(saved,plan)
  if st.query_params.get('resources_probe')=='read-only':
   if st.button('Test mixed resource review (read-only)',key=prefix+'_probe'):
    from resources_tomorrow import probe_mixed_review
    try:
     probe=probe_mixed_review(store,client,plan)
     st.session_state[prefix+'_probe_result']=probe
    except (StorageError,ResourceFailure) as error: _message(error)
   if prefix+'_probe_result' in st.session_state:
    st.json(st.session_state[prefix+'_probe_result'])
  if result:
   if submitted: result['end_to_end_seconds']=round(perf_counter()-st.session_state[prefix+'_started'],2)
   if 'end_to_end_seconds' in result:
    st.caption(f"Total preparation time: {result['end_to_end_seconds']}s from Generate to completed result rendering, including app/database work; browser network/paint excluded.")
