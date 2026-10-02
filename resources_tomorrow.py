"""Read-only suggestions and bounded orchestration of the existing resource engine."""
from collections import defaultdict
from datetime import date, timedelta
from time import perf_counter
from app_diagnostics import timed

from lesson_resources import suggestions, source_available, digest, generate, regenerate_resource, ResourceFailure
from persistence import StorageError

VERSION = 3


class _Meter:
    def __init__(self, client):
        self.client = client
        self.responses = self
        self.calls = 0
        self.seconds = 0.0

    def create(self, **kwargs):
        start = perf_counter()
        self.calls += 1
        try:
            return self.client.responses.create(**kwargs)
        finally:
            self.seconds += perf_counter() - start


def next_weekday(day):
    day = date.fromisoformat(day) if isinstance(day, str) else day
    day += timedelta(days=1)
    while day.weekday() > 4:
        day += timedelta(days=1)
    return day.isoformat()


def next_plan(plans, after):
    target = next_weekday(after)
    return target, next((p for p in plans if p['planning_date'] == target and p.get('planning_quality', {}).get('state') == 'Pass'), None)


def suggested_types(lesson):
    """Rank existing suggestions, never ask AI or claim an unknown carryover task."""
    options = suggestions(lesson)
    text = (lesson.get('details', '') + ' ' + str(lesson.get('phases', []))).casefold()
    preferred = []
    if lesson.get('carryover_ids'):
        preferred = ['gaeilge', 'discussion', 'exit'] if 'gaeilge' in options else ['discussion', 'exit', 'comprehension']
    elif 'whiteboard' in options:
        preferred = ['whiteboard', 'challenge' if 'challenge' in text or 'reason' in text else 'practice', 'exit']
    elif options[0] == 'checklist':
        preferred = ['checklist', 'modelling', 'discussion']
    elif options[0] == 'modelling':
        preferred = ['modelling', 'practice', 'exit']
    return [t for t in dict.fromkeys(preferred + options) if t in options][:3]


def lesson_choices(context, saved):
    lesson = context['lesson']
    choices = []
    for kind in suggested_types(lesson):
        exact = [r for r in saved if r['plan_id'] == context['plan_id'] and r['lesson_id'] == lesson['lesson_id'] and r['type'] == kind]
        current = [r for r in exact if r['context_digest'] == digest(context) and r['quality']['state'] == 'Pass']
        existing = max(current, key=lambda r: (r['updated_at'], r['revision'], r['id']), default=None)
        choices.append(dict(type=kind, existing=existing, status='Already saved — regenerate?' if existing else ('Evidence changed' if exact else 'No resource saved'), selected=False))
    # Two missing useful resources by default; comprehension always needs opt-in/source.
    missing = [c for c in choices if not c['existing'] and c['type'] != 'comprehension']
    for c in missing[:2]:
        c['selected'] = True
    return choices


@timed('resource.batch_preparation_and_execution')
def run_batches(store, client, plan, requests, batch_instruction='', on_result=None):
    """Each new-resource lesson group uses one generation and one review.

    Existing resources take the same individual regeneration path as V1. No writes,
    retries, repair, or reassociation. Return every available result independently.
    """
    started = perf_counter()
    client = _Meter(client)
    result = dict(resources=[], blocked=[], failures=[], calls=0, ai_seconds=0.0, elapsed_seconds=0.0)
    groups = defaultdict(list)
    lessons = {l['lesson_id']: l for l in plan['lessons']}
    seen = set()
    for request in requests:
        lid, kind = request['lesson_id'], request['type']
        if (lid, kind) in seen:
            continue
        seen.add((lid, kind))
        instruction = request.get('override', '').strip() or batch_instruction.strip() or (request.get('existing') or {}).get('instruction', '')
        source = request.get('source', '')
        existing = request.get('existing')
        if existing:
            source = existing['source_text']
        if kind == 'comprehension' and not source_available(source):
            result['blocked'].append(dict(lesson_id=lid, type=kind, reason='Comprehension requires a relevant supplied source passage. No AI call made.'))
            continue
        if lid not in lessons or kind not in suggestions(lessons[lid]):
            result['blocked'].append(dict(lesson_id=lid, type=kind, reason='Selection does not belong to this lesson.'))
            continue
        if len(instruction) > 300 or len(source) > 16000:
            result['blocked'].append(dict(lesson_id=lid, type=kind, reason='Instruction or source is too long.'))
            continue
        if existing and (existing['plan_id'], existing['lesson_id'], existing['planning_date'], existing['type']) != (plan['plan_id'], lid, plan['planning_date'], kind):
            result['blocked'].append(dict(lesson_id=lid, type=kind, reason='Resource belongs to a different lesson.'))
            continue
        # Regeneration stays individual, even if another selected type has identical inputs.
        group_key = (lid, instruction, source, existing['include_answers'] if existing else request.get('answers', True), existing['id'] if existing else '')
        groups[group_key].append(request)
    for (lid, instruction, source, answers, existing_id), group in groups.items():
        try:
            context = store.resource_context(plan['planning_date'], plan['plan_id'], lid)
            existing = group[0].get('existing')
            if existing:
                resources = [regenerate_resource(existing, context, instruction, client)]
            else:
                resources = generate(context, [r['type'] for r in group], instruction, source, answers, client)
            for resource in resources:
                request = next(r for r in group if r['type'] == resource['type'])
                resource['instruction_context'] = dict(batch=batch_instruction, override=request.get('override', ''), effective=instruction, origin='resources_for_tomorrow')
            result['resources'].extend(resources)
            if on_result:
                on_result(resources)
        except ResourceFailure as error:
            result['failures'].append(dict(lesson_id=lid, reason=str(error)))
        except StorageError as error:
            result['failures'].append(dict(lesson_id=lid, reason=str(error)))
    result['calls'] = client.calls
    result['ai_seconds'] = round(client.seconds, 2)
    result['elapsed_seconds'] = round(perf_counter() - started, 2)
    return result


def probe_mixed_review(store, client, plan):
    """Explicit acceptance probe: copied real resources, intentionally wrong answer.

    No draft or outcome is saved. The UI exposes this only in read-only probe mode.
    """
    import copy
    from lesson_resources import review
    before = store.list_resources(plan['planning_date'])
    for lesson in plan['lessons']:
        if lesson['subject'].casefold() not in ('maths', 'mathematics'):
            continue
        context = store.resource_context(plan['planning_date'], plan['plan_id'], lesson['lesson_id'])
        exact = [r for r in before if r['plan_id'] == plan['plan_id'] and r['lesson_id'] == lesson['lesson_id'] and r['context_digest'] == digest(context)]
        whiteboard = next((r for r in exact if r['type'] == 'whiteboard'), None)
        sibling = next((r for r in exact if r['type'] == 'differentiated' and not r['source_text']), None) or next((r for r in exact if r['type'] != 'whiteboard' and not r['source_text']), None)
        if whiteboard and sibling:
            bad = copy.deepcopy(whiteboard)
            bad.update(body='Calculate 12 ÷ 2 on your mini-whiteboard.', guidance='The answer is 99.')
            findings, metrics = review([bad, sibling], context, '', 'no printing', client)
            stale = dict(whiteboard, context_digest='changed-for-read-only-probe')
            old = dict(whiteboard, plan_id='replaced-for-read-only-probe')
            stale_status = next(c['status'] for c in lesson_choices(context, [stale]) if c['type'] == 'whiteboard')
            old_status = next(c['status'] for c in lesson_choices(context, [old]) if c['type'] == 'whiteboard')
            try:
                store.resource_context(plan['planning_date'], plan['plan_id']+'-replaced', lesson['lesson_id'])
                replaced_blocked = False
            except StorageError:
                replaced_blocked = True
            return dict(invalid_resource_blocked=bool(findings['whiteboard']), sibling_passed=not findings[sibling['type']], findings=findings, metrics=metrics, evidence_changed_status=stale_status, earlier_plan_status=old_status, replaced_lesson_blocked=replaced_blocked, saved_resources_unchanged=before == store.list_resources(plan['planning_date']))
    raise ResourceFailure('This read-only probe needs two existing current Maths resources of different types, including whiteboard.')
