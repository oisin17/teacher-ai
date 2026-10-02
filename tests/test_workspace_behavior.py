"""Existing business-rule regressions rerun through restricted scoped Store.

Format-6 assertions inspect the format-7 payload, without changing runtime API.
Legacy bootstrap/migration behavior is covered by the administrator tests instead.
"""
import os
import unittest
from unittest.mock import patch
from urllib.parse import urlparse
from uuid import uuid4
import psycopg
import test_persistence as regression
from persistence import Store, StorageError
from workspace_scope import WorkspaceScope
from workspace_backup import wrap_backup
from workspace_migration import migrate


@unittest.skipUnless(os.environ.get('TEST_WORKSPACE_DATABASE_URL'), 'Requires isolated PostgreSQL 16')
class ScopedBehaviorTests(regression.StoreTests):
    def setUp(self):
        url=os.environ['TEST_WORKSPACE_DATABASE_URL'];parsed=urlparse(url)
        if parsed.hostname not in ('localhost','127.0.0.1') or parsed.path!='/test_teacher_ai':
            raise RuntimeError('Only isolated localhost test_teacher_ai is accepted')
        with psycopg.connect(url) as c:
            c.execute('DROP SCHEMA public CASCADE; CREATE SCHEMA public')
            if not c.execute("SELECT 1 FROM pg_roles WHERE rolname='teacher_runtime'").fetchone():
                c.execute("CREATE ROLE teacher_runtime LOGIN PASSWORD 'isolated_test_only' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS")
        self.env_patch=patch.dict(os.environ,{'TEST_DATABASE_URL':url});self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        super().setUp()
        scope=WorkspaceScope(str(uuid4()),str(uuid4()))
        with self.real_connect(url) as c:
            migrate(c,legacy_user_id=scope.user_id,legacy_workspace_id=scope.workspace_id,runtime_role='teacher_runtime')
        runtime_url=parsed._replace(netloc=f'teacher_runtime:isolated_test_only@{parsed.hostname}:{parsed.port or 5432}').geturl()
        class PayloadAssertions(Store):
            def __init__(self, ignored_url):super().__init__(runtime_url,scope)
            def initialise(self, ignored_path=None):self.verify_schema()
            def export_backup(self):return super().export_backup()['payload']
            def restore_backup(self, payload):
                if payload.get('format_version')!=6:raise StorageError('Unsupported runtime backup')
                return super().restore_backup(wrap_backup(payload,scope.workspace_id))
        self.factory_patch=patch.object(regression,'Store',PayloadAssertions);self.factory_patch.start()
        self.addCleanup(self.factory_patch.stop)
        self.store=PayloadAssertions(runtime_url)

    def test_monthly_source_survives_progress_and_correction(self):
        # Scoped plans require a real same-workspace parent, rather than merely
        # accepting a supplied JSON identifier as the old prototype did.
        self.store.save_monthly_plan(self.monthly(),True)
        regression.StoreTests.test_monthly_source_survives_progress_and_correction(self)


# These intentionally exercise old privileged bootstrap or old SQL read counts,
# not the runtime business behavior. They still run in test_persistence.py.
EXCLUDED = {
    'test_existing_monthly_migration_retains_text_and_never_guesses_dates',
    'test_migration_is_complete_once_and_does_not_overwrite_edits',
    'test_legacy_undated_progress_is_preserved',
    'test_migration_rolls_back_all_data_on_invalid_legacy_json',
    'test_nonempty_destination_is_never_overwritten_by_legacy',
    'test_failure_is_safe_and_never_falls_back',
    'test_additive_initialisation_preserves_preexisting_documents_and_history',
    'test_evidence_reuse_preserves_packet_and_eliminates_repeated_reads',
    'test_commit_failure_is_sanitized_and_not_reported_as_confirmed_save',
    'test_backup_roundtrip_and_nonempty_restore_refused',
    'test_quality_metadata_backup_and_stale_context_guard',
}
for name in EXCLUDED:
    setattr(ScopedBehaviorTests,name,None)
