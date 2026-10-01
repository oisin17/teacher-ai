"""Read-only browser regression probe; never offers a save action."""
import copy
import streamlit as st
from planning_quality import quality_gate, QualityFailure, protected_blocks
from lesson_progress import PLAN_FORMAT, plan_markdown
from timetable_constraints import interval


def render_probe(store, day, client):
    st.header('Read-only planning rubric diagnostic')
    st.caption('Uses a deliberately conflicting COPY. No candidate, progress or learning state is saved.')
    saved=store.load_day(day)['plan']
    if not saved or not all(l.get('phases') for l in saved['lessons']):
        st.info('First select a date with a saved rubric-checked plan.');return
    st.write('Original saved plan ID: '+saved['plan_id'])
    if st.button('Test conflicting candidate without saving'):
        context=store.planning_quality_context(day)
        bad=copy.deepcopy(saved)
        target=next((b for b in protected_blocks(context) if b[2] in ('Singing','Sport','Yard')),None)
        if not target:st.info('No protected slot available for this probe.');return
        start,end,name=target
        bad['lessons'][0]['time']=f'{start//60:02}:{start%60:02}–{end//60:02}:{end%60:02}'
        st.write(f'Deliberately moved a normal lesson into protected {name}: '+bad['lessons'][0]['time'])
        before=store.load_day(day)['plan']
        try:
            fixed=quality_gate(bad,context,client,PLAN_FORMAT)
            st.success('Pass after one targeted revision; diagnostic candidate NOT saved.')
            st.json(fixed['planning_quality'])
        except QualityFailure as error:
            st.warning(str(error));st.json(error.report)
        st.write('Previous saved plan unchanged: '+str(store.load_day(day)['plan']==before))
