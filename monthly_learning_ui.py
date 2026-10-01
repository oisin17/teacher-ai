"""Optional item review and exception-only daily outcomes."""
MODULE_VERSION = 4
import json
from uuid import uuid4
import streamlit as st
from monthly_learning import TYPES, STATUSES, fingerprint


def extract_items(client, monthly):
    # AI chooses a source line; the app copies that line verbatim. This avoids
    # hallucinated quotations and fragile punctuation/whitespace reproduction.
    lines = [line for line in monthly['plan_text'].splitlines() if line.strip()]
    schema = {'type': 'json_schema', 'name': 'monthly_learning_suggestions', 'strict': True,
        'schema': {'type': 'object', 'additionalProperties': False,
            'properties': {'items': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
                'properties': {'subject': {'type': 'string', 'enum': ['English', 'Gaeilge', 'Maths', 'History', 'Geography', 'Science', 'Music', 'Drama', 'Visual Arts', 'PE', 'SPHE', 'Religion', 'Other']}, 'description': {'type': 'string'},
                    'type': {'type': 'string', 'enum': list(TYPES)}, 'source_index': {'type': 'integer'}},
                'required': ['subject', 'description', 'type', 'source_index']}}}, 'required': ['items']}}
    response = client.responses.create(model='gpt-5.4-mini', text={'format': schema}, input=(
        'Extract independently trackable learning items from this monthly plan. Subject MUST be the actual curriculum subject (English, History, etc.), NEVER a strand, topic, skill or heading like Vocabulary, Money or The Great Irish Famine. '
        'CRITICAL GRANULARITY: one separately checkable learning result per item. Never bundle a whole subject/topic section into one item. Split distinct objectives and activities even when they share a topic. For example, Famine causes/events, effects, push/pull factors, analysing immigrant letters, writing an immigrant letter, and creating/presenting a project need separate items when supplied. Procedural writing and morphology are English items, not subject names. Deduplicate an objective with its matching activity, but do not merge different activities into one broad summary. Do not create a duplicate overarching topic item when its discrete items already cover it. '
        'Use type discrete for a finite task, recurring for repeated practice, broad for ongoing objectives. '
        'Do not infer past progress. Set source_index to the numbered original document line that explicitly supports this item. '
        'Keep descriptions concise; cover all subjects. No invented pages or tasks.\n' +
        '\n'.join(f'{n}: {line}' for n, line in enumerate(lines))))
    items = json.loads(response.output_text)['items']
    if not isinstance(items, list) or not 1 <= len(items) <= 250:
        raise ValueError('Invalid extraction')
    result = []
    for i in items:
        index = i['source_index']
        if not isinstance(index, int) or not 0 <= index < len(lines) or i['type'] not in TYPES:
            raise ValueError('Unverifiable source')
        result.append({k: v for k, v in i.items() if k != 'source_index'} | {
            'source': lines[index], 'id': uuid4().hex, 'monthly_plan_id': monthly['id'],
            'fingerprint': fingerprint(monthly['plan_text']), 'archived': False})
    return result


def review_items(store, client, monthly, call):
    st.subheader('Monthly learning progress')
    saved = call(store.list_learning_items, monthly['id'])
    for subject in sorted({i['subject'] for i in saved if not i['archived']}):
        items = [i for i in saved if i['subject'] == subject and not i['archived']]
        st.write(f"**{subject}** — " + ' · '.join(f"{sum(i['status'] == status for i in items)} {status.lower()}" for status in reversed(STATUSES)))
    key = 'learning_review_' + monthly['id'] + fingerprint(monthly['plan_text'])[:12] + fingerprint(json.dumps(saved, sort_keys=True))[:12]
    changed_document = any(i['fingerprint'] != fingerprint(monthly['plan_text']) and not i['archived'] for i in saved)
    if changed_document:
        st.warning('This document changed. Archive affected old items and review new suggestions; historical lesson references remain intact.')
    if not saved or changed_document:
        st.caption('Suggest learning items once, then review and save. Original document text stays intact. No past completion is inferred.')
        if st.button('Suggest learning items', key=key + '_extract'):
            try:
                with st.spinner('Reading Monthly Plan learning items…'):
                    st.session_state[key] = [{**i, 'archived': True} for i in saved] + extract_items(client, monthly)
            except Exception:
                st.error('Extraction could not be verified. Your saved plan is unchanged; try again.')
    if saved and key not in st.session_state:
        st.session_state[key] = saved
    if key not in st.session_state:
        return
    drafts = st.session_state[key]
    with st.expander('Review / edit learning items', expanded=not saved):
        with st.form(key + '_form'):
            edited = []
            for item in drafts:
                with st.expander(f"{item['subject']} — {item['description']} ({item.get('status', 'Not started')})"):
                    st.caption('Source: ' + item['source'])
                    subject = st.text_input('Subject', value=item['subject'], key=key + item['id'] + 'subject')
                    description = st.text_area('Learning item', value=item['description'], max_chars=1000, key=key + item['id'] + 'desc')
                    kind = st.selectbox('Item type', TYPES, index=TYPES.index(item['type']), key=key + item['id'] + 'type')
                    archived = st.checkbox('Archived (uncheck to restore)', value=item['archived'], key=key + item['id'] + 'archive')
                    split = st.text_area('Split into new items (optional; one per line)', key=key + item['id'] + 'split', help='Archives this item; new items receive new IDs and start Not started.')
                    edited.append({**item, 'subject': subject, 'description': description, 'type': kind, 'archived': archived or bool(split.strip())})
                    for line in split.splitlines():
                        if line.strip():
                            edited.append({**item, 'id': uuid4().hex, 'revision': 0, 'split_from': item['id'], 'description': line.strip(), 'archived': False})
            active = [i for i in drafts if not i['archived']]
            merge = st.multiselect('Merge duplicate / overlapping items', [i['id'] for i in active], format_func=lambda id: next(i['subject'] + ' — ' + i['description'] for i in active if i['id'] == id), key=key + '_merge')
            merged_description = st.text_input('Merged item description', key=key + '_merged_text')
            save = st.form_submit_button('Save learning items', type='primary')
        if save:
            if merge:
                selected = [i for i in edited if i['id'] in merge]
                if len(selected) < 2 or len({i['subject'] for i in selected}) != 1 or not merged_description.strip():
                    st.error('Choose at least two items in the same subject and describe the merged learning.')
                    return
                for i in edited:
                    if i['id'] in merge:
                        i['archived'] = True
                # Retain all original quotations in provenance; contiguous source is the primary quotation.
                first = selected[0]
                edited.append({**first, 'id': uuid4().hex, 'revision': 0, 'description': merged_description.strip(), 'archived': False, 'type': 'broad' if any(i['type'] != 'discrete' for i in selected) else 'discrete', 'merged_from': merge, 'sources': [i['source'] for i in selected]})
            call(store.save_learning_items, monthly, edited)
            st.session_state.pop(key, None)
            st.success('Learning items saved. Split/merged replacements need their own confirmed evidence; historical IDs are retained.')
            st.rerun()
    if saved:
        with st.expander('Correct an item status or remaining learning'):
            selected_id = st.selectbox('Item to correct', [i['id'] for i in saved], format_func=lambda id: next(i['subject'] + ' — ' + i['description'] for i in saved if i['id'] == id), key=key + '_correct')
            item = next(i for i in saved if i['id'] == selected_id)
            with st.form(key + selected_id + '_correction'):
                status = st.selectbox('Item status', STATUSES, index=STATUSES.index(item['status']))
                remaining = st.text_area('Remaining learning', value=item['remaining'], max_chars=1000)
                evidence = st.text_input('Teacher correction / evidence', value=item['evidence'], max_chars=2000)
                confirm = st.checkbox('I confirm the whole item is completed')
                submit = st.form_submit_button('Save item correction')
            if submit:
                call(store.correct_learning_item, selected_id, status, remaining, evidence, confirm)
                st.session_state.pop(key, None)
                st.rerun()


def item_inputs(lesson, prefix, items):
    updates = []
    existing = {u['item_id']: u for u in lesson.get('item_updates', [])}
    for link in lesson.get('monthly_item_links', []):
        item = items.get(link['item_id'])
        if not item:
            continue
        with st.expander(f"Monthly item: {item['description']} · {item['status']}"):
            st.caption(f"{item['type']} · Lesson addresses: {link['coverage']}")
            st.caption('Default: taught work becomes In progress; Not taught changes nothing. Change only exceptions. Save accepts these item outcomes.')
            key = prefix + lesson['lesson_id'] + item['id']
            old = existing.get(item['id'], {})
            pending = st.session_state.pop(key + '_pending', None)
            if pending:
                st.session_state[key + '_outcome'] = pending['status']
                st.session_state[key + '_remaining'] = pending['remaining']
                st.session_state[key + '_complete'] = False
                st.caption('AI suggestion — review and accept by saving. Whole-item completion still requires your explicit checkbox.')
            options = ['Use conservative lesson outcome'] + list(STATUSES)
            chosen = st.selectbox('Item outcome', options, index=options.index(old.get('status', options[0])), key=key + '_outcome')
            remaining = st.text_input('Specific unfinished aspect (optional)', value=old.get('remaining', ''), max_chars=1000, key=key + '_remaining')
            confirm = st.checkbox('Whole item completed — explicitly confirm', value=old.get('confirmed_complete', False), key=key + '_complete')
            if chosen != options[0]:
                updates.append(dict(item_id=item['id'], status=chosen, remaining=remaining, evidence=lesson.get('note', ''), confirmed_complete=confirm))
            elif remaining:
                updates.append(dict(item_id=item['id'], status='In progress', remaining=remaining, evidence=lesson.get('note', ''), confirmed_complete=False))
    return updates


def suggest_outcomes(client, lessons, items):
    linked = {link['item_id'] for lesson in lessons for link in lesson.get('monthly_item_links', [])}
    source = [i for i in items.values() if i['id'] in linked]
    response = client.responses.create(model='gpt-5.4-mini', input=(
        'Suggest Monthly Plan item outcomes from teacher lesson notes. Notes are authoritative. '
        'Return JSON only {"updates":[{"lesson_id":"...","item_id":"...","status":"In progress", "remaining":"exact unfinished aspect", "evidence":"exact teacher note quotation"}]}. '
        'Only use the exact linked IDs. Completed requires clear note evidence that the ENTIRE discrete item is finished; '
        'broad/recurring objectives remain In progress unless teacher explicitly says the whole objective is finished. '
        'Partial lessons can complete some items if explicitly supported but retain the exact unfinished aspect for others. '
        'Not taught adds no outcome. Do not invent stopping points, downgrade existing completed work, or infer completion from lesson status alone. '
        'When ambiguous, suggest In progress with uncertainty. These are suggestions for teacher acceptance only.\n'
        f'ITEMS: {source}\nLESSONS: {lessons}'))
    proposals = json.loads(response.output_text)['updates']
    if not isinstance(proposals, list):
        raise ValueError('Invalid suggestions')
    by_lesson = {l['lesson_id']: l for l in lessons}
    result = {}
    for u in proposals:
        lesson = by_lesson[u['lesson_id']]
        if u['item_id'] not in {l['item_id'] for l in lesson.get('monthly_item_links', [])} or u['status'] not in STATUSES or not isinstance(u['remaining'], str) or not u['evidence'] or u['evidence'] not in lesson['note'] or lesson['status'] == 'Not taught':
            raise ValueError('Unsupported suggestion')
        u['confirmed_complete'] = False
        result.setdefault(u['lesson_id'], []).append(u)
    return result
