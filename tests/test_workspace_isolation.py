"""Real PostgreSQL 16 migration/RLS rehearsal, never a production connection."""
import copy
import json
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch, Mock
from urllib.parse import urlparse
from uuid import uuid4

import psycopg
from persistence import Store, StorageError
from workspace_scope import WorkspaceScope, bind_session_scope, ScopedSessionState
from workspace_backup import checksum, wrap_backup
from workspace_migration import CLASS_TABLES, migrate, inventory
from legacy_storage_admin import LegacyStore
from fixtures import sample_plan, outcomes


class ScopeUnitTests(unittest.TestCase):
    def test_missing_or_invalid_scope_has_no_default(self):
        with self.assertRaises(StorageError): Store('unused', None)
        with self.assertRaises(StorageError): WorkspaceScope(None, None)

    def test_session_scope_namespaces_and_clears_drafts_downloads(self):
        raw={}; st=SimpleNamespace(session_state=raw)
        a=WorkspaceScope(str(uuid4()),str(uuid4())); b=WorkspaceScope(str(uuid4()),str(uuid4()))
        bind_session_scope(raw,a); state=ScopedSessionState(st)
        state['resource_edit_drafts']={'text':'unsaved'};state['cutover_backup']='private'
        self.assertTrue(all(k.startswith(a.namespace) for k in raw if k!='_authorized_scope'))
        bind_session_scope(raw,a);self.assertEqual(state['cutover_backup'],'private')
        bind_session_scope(raw,b);self.assertNotIn('cutover_backup',state)
        self.assertEqual(raw,{'_authorized_scope':b.namespace})

    def test_lock_identity_is_stable_and_workspace_specific(self):
        a=WorkspaceScope(str(uuid4()),str(uuid4()))
        self.assertEqual(a.lock_key,WorkspaceScope(str(uuid4()),a.workspace_id).lock_key)
        self.assertNotEqual(a.lock_key,WorkspaceScope(a.user_id,str(uuid4())).lock_key)


@unittest.skipUnless(os.environ.get('TEST_WORKSPACE_DATABASE_URL'), 'Requires isolated PostgreSQL 16')
class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.admin_url=os.environ['TEST_WORKSPACE_DATABASE_URL']
        parsed=urlparse(self.admin_url)
        if parsed.hostname not in ('localhost','127.0.0.1') or parsed.path!='/test_teacher_ai':
            raise RuntimeError('Only isolated localhost test_teacher_ai is accepted')
        self.real_connect=psycopg.connect
        with self.real_connect(self.admin_url) as c:
            self.assertTrue(c.execute('SHOW server_version').fetchone()[0].startswith('16.'))
            c.execute('DROP SCHEMA public CASCADE; CREATE SCHEMA public')
            if not c.execute("SELECT 1 FROM pg_roles WHERE rolname='teacher_runtime'").fetchone():
                c.execute("CREATE ROLE teacher_runtime LOGIN PASSWORD 'isolated_test_only' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS")
        self.runtime_url=parsed._replace(netloc=f'teacher_runtime:isolated_test_only@{parsed.hostname}:{parsed.port or 5432}').geturl()
        # TLS-disabled localhost test service only; production remains TLS require.
        def connect(url,**kwargs):
            kwargs['sslmode']='disable'
            return self.real_connect(url,**kwargs)
        self.connect_patch=patch('persistence.psycopg.connect',side_effect=connect)
        self.connect_patch.start()
        self.addCleanup(self.connect_patch.stop)
        self.legacy=LegacyStore(self.admin_url); self.legacy.initialise('/missing-test-only.db')
        self.monthly=dict(id='month-a',title='Fixture month',source_filename='fixture.txt',plan_text='Maths rounding.',start_date='2026-09-01',end_date='2026-09-30')
        self.legacy.save_monthly_plan(self.monthly,True)
        self.legacy.save_document('teacher_profile',{'class_level':'5th Class','note':'fixture only'})
        from monthly_learning import fingerprint
        self.item=dict(id='item-a',monthly_plan_id='month-a',subject='Maths',description='Round numbers',source='Maths rounding.',fingerprint=fingerprint(self.monthly['plan_text']),type='discrete',archived=False)
        self.legacy.save_learning_items(self.monthly,[self.item])
        self.plan=sample_plan('2026-09-30'); self.plan['monthly_plan']={k:self.monthly[k] for k in ('id','title','start_date','end_date')}
        self.plan['lessons'][0]['monthly_item_links']=[{'item_id':'item-a','coverage':'Round numbers'}]
        from planning_quality import digest
        self.plan['planning_quality']=dict(state='Pass',context_digest=digest(self.legacy.planning_quality_context('2026-09-30')))
        self.legacy.save_day_plan(self.plan)
        self.payload=self.legacy.export_backup()
        self.a_scope=WorkspaceScope(str(uuid4()),str(uuid4()))
        self.b_scope=WorkspaceScope(str(uuid4()),str(uuid4()))
        with self.real_connect(self.admin_url) as c:
            self.migration=migrate(c,legacy_user_id=self.a_scope.user_id,legacy_workspace_id=self.a_scope.workspace_id,runtime_role='teacher_runtime')
            c.execute("INSERT INTO users(id,state) VALUES(%s,'active')",(self.b_scope.user_id,))
            c.execute("INSERT INTO workspaces(id,display_name,state) VALUES(%s,'Synthetic B','active')",(self.b_scope.workspace_id,))
            c.execute("INSERT INTO workspace_memberships VALUES(%s,%s,'owner','active')",(self.b_scope.workspace_id,self.b_scope.user_id))
        self.a=Store(self.runtime_url,self.a_scope);self.b=Store(self.runtime_url,self.b_scope)

    def assert_preserved(self):
        self.assertEqual(self.a.export_backup()['payload'],self.payload)

    def test_exact_migration_inventory_and_complete_export_equivalence(self):
        self.assertEqual(self.migration['before'],self.migration['after'])
        self.assert_preserved()
        with self.real_connect(self.admin_url) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM invites').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT count(*) FROM user_identities').fetchone()[0],0)

    def test_restricted_role_and_forced_rls_on_every_class_table(self):
        with self.real_connect(self.runtime_url) as c:
            self.assertEqual(c.execute('SELECT rolsuper,rolbypassrls,rolcreaterole,rolcreatedb FROM pg_roles WHERE rolname=current_user').fetchone(),(False,False,False,False))
            for table in CLASS_TABLES+('workspace_data_migrations',):
                self.assertEqual(c.execute('SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=%s::regclass',(table,)).fetchone(),(True,True))
                self.assertEqual(c.execute('SELECT pg_has_role(current_user,relowner,\'MEMBER\') FROM pg_class WHERE oid=%s::regclass',(table,)).fetchone(),(False,))

    def test_unscoped_raw_reads_empty_and_writes_denied(self):
        with self.real_connect(self.runtime_url) as c:
            for table in CLASS_TABLES:
                self.assertEqual(c.execute(f'SELECT count(*) FROM {table}').fetchone()[0],0)
        with self.assertRaises(psycopg.Error):
            with self.real_connect(self.runtime_url) as c:
                c.execute('INSERT INTO teacher_profile(workspace_id,id,profile_data) VALUES(%s,1,\'{}\')',(self.a_scope.workspace_id,))

    def test_wrong_membership_scope_and_revocation_fail_closed(self):
        bad=Store(self.runtime_url,WorkspaceScope(self.b_scope.user_id,self.a_scope.workspace_id))
        with self.assertRaises(StorageError):bad.export_backup()
        with self.real_connect(self.admin_url) as c:
            c.execute("UPDATE workspace_memberships SET state='revoked' WHERE workspace_id=%s",(self.a_scope.workspace_id,))
        with self.assertRaises(StorageError):self.a.load_document('teacher_profile')
        with self.assertRaises(StorageError):self.a.save_document('teacher_profile',{})

    def test_admin_or_table_owner_runtime_connection_rejected(self):
        with self.assertRaises(StorageError):Store(self.admin_url,self.a_scope).load_document('teacher_profile')

    def test_read_paths_return_no_first_workspace_content(self):
        calls=[('load_document',('teacher_profile',),{}),('list_monthly_plans',(),[]),('select_monthly_plan',('2026-09-30',),None),
               ('load_progress_history',(),[]),('load_recent_progress',(),[]),('list_carryover',(),[]),('list_learning_items',(),[]),
               ('approved_resource_plans',(),[]),('list_resources',('2026-09-30',),[])]
        for method,args,expected in calls:
            with self.subTest(method=method):self.assertEqual(getattr(self.b,method)(*args),expected)
        self.assertEqual(self.b.load_day('2026-09-30'),{'plan':None,'progress':None})
        self.assertEqual(self.b.export_backup()['payload']['monthly_plans'],[])
        for method,args in [('resource_context',('2026-09-30',self.plan['plan_id'],self.plan['lessons'][0]['lesson_id'])),('resource_day_contexts',('2026-09-30',self.plan['plan_id']))]:
            with self.assertRaises(StorageError):getattr(self.b,method)(*args)

    def test_same_dates_singleton_ids_and_monthly_ranges_are_independent(self):
        self.b.save_document('teacher_profile',{'class_level':'1st Class'})
        self.b.save_monthly_plan({**self.monthly,'id':'month-b'},True)
        bplan=sample_plan('2026-09-30');self.b.save_day_plan(bplan)
        self.assertEqual(self.a.load_document('teacher_profile'),self.payload['teacher_profile'])
        self.assertEqual(self.b.load_day('2026-09-30')['plan']['plan_id'],bplan['plan_id'])
        self.assertEqual(self.a.load_day('2026-09-30')['plan']['plan_id'],self.plan['plan_id'])

    def test_forged_monthly_and_learning_upserts_do_not_touch_owner(self):
        with self.assertRaises(StorageError):self.b.save_monthly_plan(self.monthly,True)
        with self.assertRaises(StorageError):self.b.save_learning_items(self.monthly,[self.item])
        self.assert_preserved()

    def test_forged_plan_learning_and_carryover_references_are_rejected(self):
        with self.assertRaises(StorageError):self.b.save_day_plan(self.plan)
        with self.assertRaises(StorageError):self.b.link_carryover_item('foreign-carry','item-a')
        with self.assertRaises(StorageError):self.b.correct_learning_item('item-a','In progress','Scope','fixture',False)
        self.assert_preserved()

    def test_direct_json_reference_attack_rejected_at_database(self):
        with self.assertRaises(StorageError):
            with self.b._connection() as c:
                c.execute('INSERT INTO monthly_learning_items(workspace_id,id,item_data) VALUES(%s,%s,%s)',(self.b_scope.workspace_id,'forged-item',json.dumps({**self.item,'id':'forged-item'})))
        self.assert_preserved()

    def test_direct_wrong_workspace_insert_and_update_denied(self):
        with self.assertRaises(StorageError):
            with self.b._connection() as c:
                c.execute('INSERT INTO teacher_profile(workspace_id,id,profile_data) VALUES(%s,1,\'{}\')',(self.a_scope.workspace_id,))
        with self.b._connection() as c:
            self.assertEqual(c.execute('UPDATE teacher_profile SET profile_data=\'{}\' WHERE workspace_id=%s',(self.a_scope.workspace_id,)).rowcount,0)
        self.assert_preserved()

    def test_cross_workspace_backup_restore_and_legacy_formats_refused(self):
        with self.assertRaises(StorageError):self.b.restore_backup(self.a.export_backup())
        for version in range(1,7):
            with self.subTest(version=version),self.assertRaises(StorageError):self.b.restore_backup({'format_version':version})
        self.assert_preserved()

    def test_same_workspace_empty_restore_preserves_ids_and_other_workspace(self):
        backup=self.a.export_backup()
        self.b.save_document('teacher_profile',{'note':'independent fixture'})
        before_b=self.b.export_backup()['payload']
        with self.real_connect(self.admin_url) as c:
            for table in ('monthly_item_updates','lesson_resources','lesson_progress','carryover_items','period_reviews','monthly_learning_items','day_plans','actual_progress','monthly_plans','teacher_profile','planning_setup','current_learning_position'):
                c.execute(f'DELETE FROM {table} WHERE workspace_id=%s',(self.a_scope.workspace_id,))
        self.assertTrue(self.a.restore_backup(backup))
        self.assertEqual(self.a.export_backup()['payload'],backup['payload'])
        self.assertEqual(self.b.export_backup()['payload'],before_b)
        self.assertFalse(self.a.restore_backup(backup))

    def test_malformed_checksum_and_forged_json_restore_atomic(self):
        backup=self.b.export_backup();backup['payload']['teacher_profile']={'note':'changed'}
        with self.assertRaises(StorageError):self.b.restore_backup(backup)
        forged=self.b.export_backup();forged['payload']['teacher_profile']={'workspace_id':self.a_scope.workspace_id}
        forged['checksum']=checksum(forged['payload'])
        with self.assertRaises(StorageError):self.b.restore_backup(forged)
        self.assertEqual(self.b.load_document('teacher_profile'),{})

    def test_held_owner_lock_does_not_block_other_workspace(self):
        with self.a._connection() as ca:
            self.a._lock(ca)
            with self.b._connection() as cb:
                cb.execute("SET LOCAL lock_timeout='250ms'")
                self.b._lock(cb)
                cb.execute('INSERT INTO teacher_profile(workspace_id,id,profile_data) VALUES(%s,1,\'{}\')',(self.b_scope.workspace_id,))

    def test_same_workspace_lock_contention_is_serialized(self):
        with self.a._connection() as ca:
            self.a._lock(ca)
            with self.assertRaises(StorageError):
                with self.a._connection() as cb:
                    cb.execute("SET LOCAL lock_timeout='100ms'")
                    self.a._lock(cb)

    def test_runtime_cannot_migrate_change_roles_or_read_identity_records(self):
        for query in ('CREATE TABLE public.forbidden(id int)','ALTER ROLE teacher_runtime BYPASSRLS','SELECT * FROM users','SELECT * FROM invites','SELECT * FROM workspace_memberships'):
            with self.subTest(query=query),self.assertRaises(psycopg.Error):
                with self.real_connect(self.runtime_url) as c:c.execute(query)

    def test_owner_planning_and_progress_crud_scoped_projection(self):
        self.a.save_lesson_progress('2026-09-30',self.plan['plan_id'],outcomes(self.plan))
        history=self.a.load_progress_history();self.assertEqual(len(history),1)
        self.assertEqual(self.b.load_progress_history(),[])
        self.assertEqual(self.b.load_document('current_learning_position'),{})
        record=history[0]['id']
        with self.assertRaises(StorageError):self.b.correct_lesson_progress(record,'2026-09-30',outcomes(self.plan))
        with self.assertRaises(StorageError):self.b.correct_progress(record,'2026-09-30','Wednesday','Not taught','fixture')
        self.a.correct_lesson_progress(record,'2026-09-30',outcomes(self.plan))

    def test_owner_resource_save_revision_and_stale_checks_remain(self):
        from lesson_resources import generate
        context=self.a.resource_context('2026-09-30',self.plan['plan_id'],self.plan['lessons'][0]['lesson_id'])
        client=Mock();client.responses.create.side_effect=[SimpleNamespace(output_text=json.dumps({'resources':[dict(type='whiteboard',title='Rounding',body='Round 12345 to the nearest 1000.',guidance='12000',evidence_ids=['lesson'])]})),SimpleNamespace(output_text=json.dumps({'checks':[dict(type='whiteboard',pass_=True,findings=[])]}).replace('pass_','pass'))]
        candidate=generate(context,['whiteboard'],'no printing','',True,client)[0]
        saved=self.a.save_resource(candidate)
        self.assertEqual(saved['revision'],1);self.assertEqual(self.b.list_resources('2026-09-30'),[])
        with self.assertRaises(StorageError):self.b.save_resource(saved,1)
        revised=self.a.save_resource({**saved,'title':'Edited title'},1)
        self.assertEqual(revised['revision'],2)
        with self.assertRaises(StorageError):self.a.save_resource(saved,1)
        self.a.save_document('teacher_profile',{'class_level':'1st Class'})
        with self.assertRaises(StorageError):self.a.save_resource(revised,2)

    def test_migration_failure_rolls_back_schema_and_original_data(self):
        # A second migrate must refuse, not reassign the first workspace.
        with self.assertRaises(ValueError):
            with self.real_connect(self.admin_url) as c:
                migrate(c,legacy_user_id=self.b_scope.user_id,legacy_workspace_id=self.b_scope.workspace_id,runtime_role='teacher_runtime')
        self.assert_preserved()

    def test_transaction_local_context_is_cleared_after_commit(self):
        with self.real_connect(self.runtime_url) as c:
            with c.transaction():
                c.execute("SELECT set_config('teacher_ai.user_id',%s,true),set_config('teacher_ai.workspace_id',%s,true)",(self.a_scope.user_id,self.a_scope.workspace_id))
                self.assertEqual(c.execute('SELECT count(*) FROM teacher_profile').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT count(*) FROM teacher_profile').fetchone()[0],0)

    def test_carryover_review_links_and_manual_state_are_workspace_scoped(self):
        carry=dict(id='carry-a',period_id='month-a',subject='Maths',learning='Fixture scope',evidence='Fixture only',created_date='2026-09-30',state='outstanding',monthly_item_id='item-a')
        self.a.save_period_review(self.monthly,'2026-09-30',[carry],True)
        self.assertEqual(len(self.a.carryover_context(self.monthly,'2026-09-30')['items']),1)
        with self.assertRaises(StorageError):self.b.save_period_review(self.monthly,'2026-09-30',[carry],True)
        with self.assertRaises(StorageError):self.b.set_carryover_state('carry-a','completed')
        with self.assertRaises(StorageError):self.b.link_carryover_item('carry-a','item-a')
        self.a.link_carryover_item('carry-a','item-a')
        self.a.set_carryover_state('carry-a','removed')
        self.assertEqual(self.b.list_carryover(),[])

    def test_regrouping_cannot_use_other_workspace_bundle(self):
        bundle=dict(monthly_plan_id='month-a',expected_items=self.a.list_learning_items('month-a'),
                    expected_updates=[],expected_carryover=[],items=[self.item])
        with self.assertRaises(StorageError):self.b.apply_reviewed_regrouping(self.monthly,bundle,True)
        self.assert_preserved()

    def test_whole_day_progress_and_context_remain_independent(self):
        self.a.save_progress('2026-09-29','Tuesday','Not taught','Isolated fixture only')
        self.b.save_progress('2026-09-29','Tuesday','Not taught','Independent fixture only')
        arow=self.a.load_progress_history()[0]; brow=self.b.load_progress_history()[0]
        self.assertNotEqual(arow['id'],brow['id'])
        with self.assertRaises(StorageError):self.b.correct_progress(arow['id'],'2026-09-28','Monday','Not taught','Forged')
        self.assertTrue(self.a.correct_progress(arow['id'],'2026-09-28','Monday','Not taught','Fixture correction'))
        self.assertEqual(self.b.planning_quality_context('2026-09-30')['monthly_plan'],None)
        self.assertNotEqual(self.a.load_document('current_learning_position'),self.b.load_document('current_learning_position'))

    def test_forged_workspace_setting_without_membership_returns_no_rows(self):
        with self.b._connection() as c:
            c.execute("SELECT set_config('teacher_ai.workspace_id',%s,true)",(self.a_scope.workspace_id,))
            for table in CLASS_TABLES:
                self.assertEqual(c.execute(f'SELECT count(*) FROM {table}').fetchone()[0],0)

    def test_failed_migration_is_transactionally_reversible(self):
        with self.real_connect(self.admin_url) as c:c.execute('DROP SCHEMA public CASCADE;CREATE SCHEMA public')
        legacy=LegacyStore(self.admin_url);legacy.initialise('/missing-test-only.db')
        self.assertTrue(legacy.restore_backup(self.payload))
        original=legacy.export_backup()
        with self.real_connect(self.admin_url) as c:before=inventory(c)
        with patch('workspace_migration.inventory',side_effect=[before,ValueError('Injected validation failure')]):
            with self.assertRaises(ValueError):
                with self.real_connect(self.admin_url) as c:
                    migrate(c,legacy_user_id=self.a_scope.user_id,legacy_workspace_id=self.a_scope.workspace_id,runtime_role='teacher_runtime')
        self.assertEqual(legacy.export_backup(),original)
        with self.real_connect(self.admin_url) as c:
            self.assertIsNone(c.execute("SELECT to_regclass('public.workspaces')").fetchone()[0])
            self.assertEqual(c.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND column_name='workspace_id'").fetchone()[0],0)

    def test_restore_keeps_numeric_ids_and_reserves_sequence_for_later_saves(self):
        payload=self.b.export_backup()['payload']
        payload['actual_progress']=[dict(id=901,planning_day='Tuesday',subject='Full day',lesson_topic='Fixture',status='Not taught',notes='Isolated fixture only',planning_date='2026-09-29')]
        backup=wrap_backup(payload,self.b_scope.workspace_id)
        self.assertTrue(self.b.restore_backup(backup))
        self.b.save_progress('2026-09-28','Monday','Not taught','Isolated fixture only')
        ids={r['id'] for r in self.b.load_progress_history()}
        self.assertIn(901,ids);self.assertTrue(any(i>901 for i in ids))
        self.assert_preserved()

    def test_accidental_rls_disable_denies_runtime_store(self):
        with self.real_connect(self.admin_url) as c:c.execute('ALTER TABLE monthly_learning_items NO FORCE ROW LEVEL SECURITY')
        with self.assertRaises(StorageError):self.a.export_backup()

    def test_every_public_store_operation_rechecks_revoked_membership(self):
        """No new method may bypass the scoped connection authorization gate."""
        calls={
            'verify_schema':(), 'load_document':('teacher_profile',),'save_document':('teacher_profile',{}),
            'list_monthly_plans':(),'select_monthly_plan':('2026-09-30',),'save_monthly_plan':(self.monthly,True),
            'list_carryover':(),'carryover_context':(self.monthly,'2026-09-30'),
            'save_period_review':(self.monthly,'2026-09-30',[],True),'set_carryover_state':('carry-a','removed'),
            'link_carryover_item':('carry-a','item-a'),'list_learning_items':(),
            'save_learning_items':(self.monthly,[self.item]),'correct_learning_item':('item-a','In progress','scope','fixture',False),
            'apply_reviewed_regrouping':(self.monthly,dict(monthly_plan_id='month-a',expected_items=[self.item],expected_updates=[],expected_carryover=[],items=[self.item]),True),
            'load_progress_history':(),'load_recent_progress':(),'load_day':('2026-09-30',),
            'planning_quality_context':('2026-09-30',),'resource_context':('2026-09-30',self.plan['plan_id'],self.plan['lessons'][0]['lesson_id']),
            'resource_day_contexts':('2026-09-30',self.plan['plan_id']),'approved_resource_plans':(),
            'list_resources':('2026-09-30',),'save_resource':({},),'save_day_plan':(self.plan,),
            'save_lesson_progress':('2026-09-30',self.plan['plan_id'],outcomes(self.plan)),
            'correct_lesson_progress':(1,'2026-09-30',outcomes(self.plan)),
            'save_progress':('2026-09-29','Tuesday','Not taught','fixture'),
            'correct_progress':(1,'2026-09-29','Tuesday','Not taught','fixture'),
            'export_backup':(),'restore_backup':(self.a.export_backup(),),
        }
        methods={name for name in dir(Store) if not name.startswith('_') and callable(getattr(Store,name))}
        self.assertEqual(methods,set(calls))
        with self.real_connect(self.admin_url) as c:
            c.execute("UPDATE workspace_memberships SET state='revoked' WHERE workspace_id=%s",(self.a_scope.workspace_id,))
        for method,args in calls.items():
            with self.subTest(method=method),self.assertRaisesRegex(StorageError,'not authorized'):
                getattr(self.a,method)(*args)

    def test_legacy_recovery_is_admin_only_and_cannot_target_migrated_workspace(self):
        from legacy_recovery_admin import recover
        with self.assertRaises(ValueError):recover(self.runtime_url,self.payload)
        with self.assertRaises(ValueError):recover(self.admin_url,self.payload)
        self.assert_preserved()

    def test_concurrent_workspace_restores_preserve_ids_without_lock_upgrade_deadlock(self):
        pa=self.a.export_backup()['payload'];pb=self.b.export_backup()['payload']
        for payload,record in ((pa,901),(pb,902)):
            payload['actual_progress']=[dict(id=record,planning_day='Tuesday',subject='Full day',lesson_topic='Fixture',status='Not taught',notes='Isolated fixture only',planning_date='2026-09-29')]
        with self.real_connect(self.admin_url) as c:
            for table in ('monthly_item_updates','lesson_resources','lesson_progress','carryover_items','period_reviews','monthly_learning_items','day_plans','actual_progress','monthly_plans','teacher_profile','planning_setup','current_learning_position'):
                c.execute(f'DELETE FROM {table} WHERE workspace_id=%s',(self.a_scope.workspace_id,))
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(store.restore_backup,wrap_backup(payload,store.scope.workspace_id)) for store,payload in ((self.a,pa),(self.b,pb))]
            self.assertEqual([f.result() for f in futures],[True,True])
        self.assertEqual(self.a.export_backup()['payload'],pa)
        self.assertEqual(self.b.export_backup()['payload'],pb)

    def test_real_scoped_streamlit_navigation_reopen_and_unauthorized_scope(self):
        from streamlit.testing.v1 import AppTest
        client=Mock()
        self.b.save_document('teacher_profile',{'class_level':'1st Class'})
        def app(scope):
            result=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'streamlit_app.py'),default_timeout=20)
            result.secrets.update(OPENAI_API_KEY='isolated-test-only',DATABASE_URL=self.runtime_url,
                ACCESS_MODE='legacy_owner',LEGACY_OWNER_ACCESS_RESTRICTED=True,
                LEGACY_OWNER_USER_ID=scope.user_id,LEGACY_WORKSPACE_ID=scope.workspace_id)
            result.run();self.assertEqual(len(result.exception),0)
            return result
        with patch('openai.OpenAI',return_value=client):
            first=app(self.a_scope);state=ScopedSessionState(SimpleNamespace(session_state=first.session_state))
            self.assertEqual(state['teacher_profile']['class_level'],'5th Class')
            first.radio[0].set_value('Current Learning').run();self.assertEqual(len(first.exception),0)
            reopened=app(self.b_scope)
            self.assertEqual(ScopedSessionState(SimpleNamespace(session_state=reopened.session_state))['teacher_profile']['class_level'],'1st Class')
            first.secrets['LEGACY_OWNER_USER_ID']=self.b_scope.user_id
            first.run();self.assertEqual(len(first.exception),0)
            self.assertTrue(any('not authorized' in e.value for e in first.error))
            self.assertNotIn('_authorized_scope',first.session_state)
            client.responses.create.assert_not_called()
