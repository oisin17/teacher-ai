"""Teacher-confirmed monthly learning, with immutable references and event replay."""
import hashlib
import json
from uuid import uuid4
from datetime import date

STATUSES = ('Not started', 'In progress', 'Completed')
TYPES = ('discrete', 'recurring', 'broad')
MARKER = '\n\nConfirmed Monthly Plan item evidence:\n'


def fingerprint(text):
    return hashlib.sha256(text.encode()).hexdigest()


def validate_item(item):
    for key in ('id', 'monthly_plan_id', 'subject', 'description', 'source', 'fingerprint'):
        if not isinstance(item.get(key), str) or not item[key].strip():
            raise ValueError('Incomplete learning item')
    if item.get('type') not in TYPES or not isinstance(item.get('archived'), bool):
        raise ValueError('Invalid learning item type/state')
    if item.get('sources') and (not isinstance(item['sources'], list) or any(not isinstance(q, str) for q in item['sources'])):
        raise ValueError('Invalid source passages')
    if len(item['description']) > 1000 or len(item['source']) > 6000:
        raise ValueError('Learning item is too long')


def validate_update(update):
    if update.get('status') not in STATUSES:
        raise ValueError('Invalid item status')
    for key in ('item_id', 'evidence', 'remaining'):
        if not isinstance(update.get(key), str):
            raise ValueError('Invalid item evidence')
    if len(update['remaining']) > 1000 or len(update['evidence']) > 2000:
        raise ValueError('Item evidence too long')
    if update['status'] == 'Completed' and update['remaining'].strip():
        raise ValueError('Completed items cannot have remaining work')
    if update['status'] == 'Completed' and update.get('confirmed_complete') is not True:
        raise ValueError('Whole-item completion needs explicit confirmation')


def project(items, updates):
    result = {i['id']: {**i, 'status': 'Not started', 'remaining': '', 'evidence': ''} for i in items}
    for event in sorted(updates, key=lambda x: (x['date'], x['order'], x['id'])):
        if event['item_id'] not in result:
            raise ValueError('Unknown item update')
        item = result[event['item_id']]
        # Untaught and ambiguous evidence never undo previous completion.
        if event.get('manual') or event['status'] == 'Completed' or item['status'] != 'Completed':
            item.update({k: event[k] for k in ('status', 'remaining', 'evidence')})
            item['last_date'] = event['date']
    return list(result.values())


class LearningStore:
    @staticmethod
    def _learning_raw(connection):
        return [json.loads(r[0]) for r in connection.execute('SELECT item_data FROM monthly_learning_items ORDER BY id').fetchall()]

    @staticmethod
    def _learning_events(connection):
        return [json.loads(r[0]) for r in connection.execute('SELECT update_data FROM monthly_item_updates ORDER BY id').fetchall()]

    @staticmethod
    def _learning(connection, as_of=None):
        events = LearningStore._learning_events(connection)
        if as_of:
            events = [e for e in events if e['date'] <= as_of]
        return project(LearningStore._learning_raw(connection), events)

    def list_learning_items(self, monthly_id=None, as_of=None):
        with self._connection() as connection:
            return [i for i in self._learning(connection, as_of) if monthly_id is None or i['monthly_plan_id'] == monthly_id]

    def save_learning_items(self, monthly, items):
        from persistence import StorageError
        try:
            if not items or len(items) > 250 or len({i['id'] for i in items}) != len(items):
                raise ValueError('Invalid item list')
            for i in items:
                validate_item(i)
                if i['monthly_plan_id'] != monthly['id'] or (not i['archived'] and (i['fingerprint'] != fingerprint(monthly['plan_text']) or i['source'] not in monthly['plan_text'] or any(q not in monthly['plan_text'] for q in i.get('sources', [])))):
                    raise ValueError('Items must retain a quoted document source')
        except (KeyError, ValueError, TypeError):
            raise StorageError('Review valid learning items and quoted source passages before saving.') from None
        with self._connection() as connection:
            self._lock(connection)
            current = next((p for p in self._monthly(connection) if p['id'] == monthly['id']), None)
            if current != monthly:
                raise StorageError('The Monthly Plan changed. Refresh before reviewing items.')
            existing = {i['id']: i for i in self._learning_raw(connection)}
            previous_progress = {i['id']: i for i in self._learning(connection)}
            for i in items:
                parents = i.get('merged_from', []) or ([i['split_from']] if i.get('split_from') else [])
                catalogue = {**existing, **{x['id']: x for x in items}}
                if any(id not in catalogue or catalogue[id]['monthly_plan_id'] != monthly['id'] for id in parents):
                    raise StorageError('Invalid split or merge source.')
                old = existing.get(i['id'])
                if old and old.get('revision', 0) != i.get('revision', 0):
                    raise StorageError('Learning items changed in another session. Refresh before editing.')
                if old and (old['monthly_plan_id'] != i['monthly_plan_id'] or old['fingerprint'] != i['fingerprint']):
                    raise StorageError('A referenced item cannot be silently replaced. Archive it and create a new item.')
                i = {k: v for k, v in i.items() if k not in ('status', 'remaining', 'evidence', 'last_date')}
                i['revision'] = i.get('revision', 0) + 1
                connection.execute('INSERT INTO monthly_learning_items (id, item_data) VALUES (%s, %s) ON CONFLICT (id) DO UPDATE SET item_data = EXCLUDED.item_data', (i['id'], json.dumps(i, ensure_ascii=False)))
                if i.get('merged_from') and not old and all(id in previous_progress for id in parents):
                    unfinished = [previous_progress[id] for id in parents if previous_progress[id]['status'] != 'Completed']
                    if any(previous_progress[id]['status'] != 'Not started' for id in parents):
                        event = dict(id=uuid4().hex, item_id=i['id'], status='In progress', remaining='; '.join(x['remaining'] or x['description'] for x in unfinished)[:1000] or 'Merged scope needs teacher confirmation', evidence='Merged item; preserved prior evidence: ' + '; '.join(previous_progress[id]['evidence'] for id in parents)[:1500], manual=True, date=date.today().isoformat(), order=max([e['order'] for e in self._learning_events(connection)] + [0]) + 1)
                        connection.execute('INSERT INTO monthly_item_updates (id, update_data) VALUES (%s, %s)', (event['id'], json.dumps(event)))
                    linked = [json.loads(r[0]) for r in connection.execute('SELECT item_data FROM carryover_items ORDER BY id').fetchall() if json.loads(r[0]).get('monthly_item_id') in parents]
                    for n, carry in enumerate(linked):
                        if n == 0:
                            carry['monthly_item_id'] = i['id']
                        else:
                            carry['state'] = 'removed'
                        connection.execute('UPDATE carryover_items SET item_data = %s WHERE id = %s', (json.dumps(carry), carry['id']))

            self._project_position(connection)

    def correct_learning_item(self, item_id, status, remaining, evidence, confirmed):
        from persistence import StorageError
        from datetime import date
        event = dict(id=uuid4().hex, item_id=item_id, status=status, remaining=remaining, evidence=evidence, confirmed_complete=confirmed, manual=True, date=date.today().isoformat())
        try:
            validate_update(event)
        except (ValueError, TypeError):
            raise StorageError('Confirm completion or specify valid remaining learning.') from None
        with self._connection() as connection:
            self._lock(connection)
            if item_id not in {i['id'] for i in self._learning_raw(connection)}:
                raise StorageError('Unknown learning item. Refresh.')
            event['order'] = max([e['order'] for e in self._learning_events(connection)] + [0]) + 1
            connection.execute('INSERT INTO monthly_item_updates (id, update_data) VALUES (%s, %s)', (event['id'], json.dumps(event)))
            self._project_position(connection)

    def _save_item_progress(self, connection, record_id, planning_date, lessons):
        from persistence import StorageError
        known = {i['id']: i for i in self._learning_raw(connection)}
        events = self._learning_events(connection)
        for e in events:
            if e.get('record_id') == record_id:
                connection.execute('DELETE FROM monthly_item_updates WHERE id = %s', (e['id'],))
        order = max([e['order'] for e in events] + [0]) + 1
        for lesson in lessons:
            links = {link['item_id'] for link in lesson.get('monthly_item_links', [])}
            # A teacher explicitly closing linked carryover closes its same item.
            carry = {i['id']: i for i in self._carryover(connection)}
            carry_finished = {carry[id]['monthly_item_id'] for id in lesson.get('completed_carryover_ids', []) if id in carry and carry[id].get('monthly_item_id')}
            links |= carry_finished
            accepted = {u['item_id']: u for u in lesson.get('item_updates', [])}
            if len(accepted) != len(lesson.get('item_updates', [])) or set(accepted) - links:
                raise StorageError('Invalid item progress links.')
            for item_id in links:
                if item_id not in known:
                    raise StorageError('Unknown linked learning item.')
                update = accepted.get(item_id)
                if item_id in carry_finished:
                    update = dict(item_id=item_id, status='Completed', remaining='', evidence=lesson['note'] or 'Teacher explicitly confirmed linked carryover finished', confirmed_complete=True)
                if update:
                    try:
                        validate_update(update)
                        if update['status'] == 'Completed' and lesson['status'] == 'Not taught':
                            raise ValueError('Untaught lesson cannot finish learning')
                    except (ValueError, TypeError):
                        raise StorageError('Review and explicitly confirm item outcomes before saving.') from None
                elif lesson['status'] == 'Not taught':
                    continue
                else:
                    update = dict(item_id=item_id, status='In progress', remaining=lesson['note'] or 'Exact remaining scope is not yet confirmed.', evidence=lesson['note'] or lesson['learning_intention'])
                event = {**update, 'id': uuid4().hex, 'date': planning_date, 'order': order, 'record_id': record_id, 'lesson_id': lesson['lesson_id'], 'manual': False}
                connection.execute('INSERT INTO monthly_item_updates (id, update_data) VALUES (%s, %s)', (event['id'], json.dumps(event, ensure_ascii=False)))

    def link_carryover_item(self, carry_id, item_id):
        """Explicit teacher link; never infer a connection from a shared subject."""
        from persistence import StorageError
        with self._connection() as connection:
            self._lock(connection)
            row = connection.execute('SELECT item_data FROM carryover_items WHERE id = %s', (carry_id,)).fetchone()
            learning = next((i for i in self._learning(connection) if i['id'] == item_id and not i['archived']), None)
            if not row or not learning:
                raise StorageError('Choose a saved active learning item.')
            carry = json.loads(row[0])
            if any(i.get('monthly_item_id') == item_id and i['id'] != carry_id and i['state'] != 'removed' for i in self._carryover(connection)):
                raise StorageError('This learning already has a carryover entry.')
            carry['monthly_item_id'] = item_id
            carry['state'] = 'outstanding' if learning['status'] != 'Completed' else 'completed'
            connection.execute('UPDATE carryover_items SET item_data = %s WHERE id = %s', (json.dumps(carry), carry_id))
