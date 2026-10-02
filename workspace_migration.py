"""Explicit administrator tooling. Never imported by the Streamlit runtime.

Run only during maintenance, after pg_dump/snapshot verification. No credentials
are printed. Existing JSON and IDs are backfilled without reserialization.
"""
import hashlib
import json
from pathlib import Path
from uuid import UUID
from psycopg import sql
from workspace_scope import CLASS_TABLES
MARKER = 'workspace_isolation_v1'


def inventory(connection, workspace_id=None):
    """Canonical original-column inventory; includes exact stored JSON strings."""
    result = {}
    for table in CLASS_TABLES:
        columns = [r[0] for r in connection.execute("""SELECT column_name FROM information_schema.columns
            WHERE table_schema='public' AND table_name=%s AND column_name <> 'workspace_id'
            ORDER BY ordinal_position""", (table,)).fetchall()]
        query = sql.SQL('SELECT {} FROM public.{}').format(sql.SQL(',').join(map(sql.Identifier, columns)), sql.Identifier(table))
        params = ()
        if workspace_id:
            query += sql.SQL(' WHERE workspace_id=%s::uuid')
            params = (workspace_id,)
        rows = connection.execute(query, params).fetchall()
        canonical = sorted(json.dumps(list(row), ensure_ascii=False, default=str, separators=(',', ':')) for row in rows)
        result[table] = dict(count=len(rows), sha256=hashlib.sha256('\n'.join(canonical).encode()).hexdigest())
    return result


def migrate(connection, *, legacy_user_id, legacy_workspace_id, runtime_role, schema_owner_role='teacher_schema_owner'):
    """One caller-owned transaction: either all migration work commits or none."""
    legacy_user_id, legacy_workspace_id = str(UUID(legacy_user_id)), str(UUID(legacy_workspace_id))
    connection.execute('SELECT pg_advisory_xact_lock(%s)', (73190421,))
    if connection.execute('SELECT name FROM storage_migrations WHERE name=%s', (MARKER,)).fetchone():
        raise ValueError('Workspace migration is already installed; no automatic rebinding.')
    role = connection.execute('SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb FROM pg_roles WHERE rolname=%s', (runtime_role,)).fetchone()
    if not role or any(role):
        raise ValueError('Provision a restricted runtime role before migration.')
    if connection.execute('SELECT EXISTS(SELECT 1 FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=%s))', (runtime_role,)).fetchone()[0]:
        raise ValueError('Runtime role must not inherit or switch into another privileged role.')
    if connection.execute("""SELECT EXISTS(SELECT 1 FROM pg_class c
        WHERE c.relnamespace='public'::regnamespace AND c.relname=ANY(%s)
          AND pg_has_role(%s,c.relowner,'MEMBER'))""", (list(CLASS_TABLES),runtime_role)).fetchone()[0]:
        raise ValueError('Runtime role cannot own or inherit ownership of classroom tables.')
    owner=connection.execute('SELECT rolcanlogin,rolsuper,rolbypassrls,rolcreaterole,rolcreatedb FROM pg_roles WHERE rolname=%s',(schema_owner_role,)).fetchone()
    if owner is None:
        connection.execute(sql.SQL('CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS').format(sql.Identifier(schema_owner_role)))
        administrator=connection.execute('SELECT current_user').fetchone()[0]
        connection.execute(sql.SQL('GRANT {} TO {}').format(sql.Identifier(schema_owner_role),sql.Identifier(administrator)))
    elif any(owner):
        raise ValueError('Schema owner must be a restricted non-login role.')
    if runtime_role==schema_owner_role:
        raise ValueError('Runtime and schema ownership must be separate.')
    connection.execute(sql.SQL('GRANT USAGE,CREATE ON SCHEMA public TO {}').format(sql.Identifier(schema_owner_role)))
    before = inventory(connection)
    for table in CLASS_TABLES:
        connection.execute(sql.SQL('LOCK TABLE public.{} IN ACCESS EXCLUSIVE MODE').format(sql.Identifier(table)))
    connection.execute("""
        CREATE TABLE users (id uuid PRIMARY KEY, state text NOT NULL CHECK(state IN ('active','disabled')),
            created_at timestamptz NOT NULL DEFAULT now());
        CREATE TABLE user_identities (user_id uuid NOT NULL REFERENCES users(id), issuer text NOT NULL,
            subject text NOT NULL, PRIMARY KEY(issuer,subject));
        CREATE TABLE workspaces (id uuid PRIMARY KEY, display_name text NOT NULL,
            timezone text NOT NULL DEFAULT 'Europe/Dublin', state text NOT NULL CHECK(state IN ('active','disabled')),
            created_at timestamptz NOT NULL DEFAULT now());
        CREATE TABLE workspace_memberships (workspace_id uuid NOT NULL REFERENCES workspaces(id),
            user_id uuid NOT NULL REFERENCES users(id), role text NOT NULL CHECK(role='owner'),
            state text NOT NULL CHECK(state IN ('active','revoked')), PRIMARY KEY(workspace_id,user_id));
        CREATE UNIQUE INDEX one_active_owner ON workspace_memberships(workspace_id)
            WHERE role='owner' AND state='active';
        CREATE TABLE invites (id uuid PRIMARY KEY, intended_email text NOT NULL,
            workspace_id uuid REFERENCES workspaces(id), invited_by uuid NOT NULL REFERENCES users(id),
            token_hash text UNIQUE, expires_at timestamptz NOT NULL, accepted_at timestamptz,
            revoked_at timestamptz);
        CREATE TABLE workspace_data_migrations (workspace_id uuid NOT NULL REFERENCES workspaces(id),
            name text NOT NULL, PRIMARY KEY(workspace_id,name));
    """)
    connection.execute("INSERT INTO users(id,state) VALUES(%s,'active')", (legacy_user_id,))
    connection.execute("INSERT INTO workspaces(id,display_name,state) VALUES(%s,'Legacy classroom','active')", (legacy_workspace_id,))
    connection.execute("INSERT INTO workspace_memberships VALUES(%s,%s,'owner','active')", (legacy_workspace_id,legacy_user_id))
    for table in ('users','user_identities','workspaces','workspace_memberships','invites','workspace_data_migrations'):
        connection.execute(sql.SQL('REVOKE ALL ON {} FROM PUBLIC, {}').format(sql.Identifier(table),sql.Identifier(runtime_role)))
    for table in CLASS_TABLES:
        ident = sql.Identifier(table)
        connection.execute(sql.SQL('ALTER TABLE {} ADD COLUMN workspace_id uuid REFERENCES workspaces(id)').format(ident))
        connection.execute(sql.SQL('UPDATE {} SET workspace_id=%s').format(ident), (legacy_workspace_id,))
        connection.execute(sql.SQL('ALTER TABLE {} ALTER COLUMN workspace_id SET NOT NULL').format(ident))
        connection.execute(sql.SQL('CREATE INDEX ON {}(workspace_id)').format(ident))
    for table in ('teacher_profile','planning_setup','current_learning_position'):
        connection.execute(sql.SQL('ALTER TABLE {} DROP CONSTRAINT {}, ADD PRIMARY KEY(workspace_id,id)').format(sql.Identifier(table),sql.Identifier(table+'_pkey')))
    connection.execute('ALTER TABLE day_plans DROP CONSTRAINT day_plans_pkey, ADD PRIMARY KEY(workspace_id,planning_date)')
    for table, key in [('actual_progress','id'),('monthly_plans','id'),('monthly_learning_items','id'),('carryover_items','id'),('period_reviews','period_id')]:
        connection.execute(sql.SQL('ALTER TABLE {} ADD UNIQUE(workspace_id,{})').format(sql.Identifier(table),sql.Identifier(key)))
    connection.execute('ALTER TABLE lesson_progress DROP CONSTRAINT lesson_progress_record_id_fkey')
    connection.execute('ALTER TABLE lesson_progress ADD FOREIGN KEY(workspace_id,record_id) REFERENCES actual_progress(workspace_id,id)')
    connection.execute('ALTER TABLE period_reviews ADD FOREIGN KEY(workspace_id,period_id) REFERENCES monthly_plans(workspace_id,id)')
    connection.execute('CREATE INDEX ON actual_progress(workspace_id,planning_date)')
    connection.execute('CREATE INDEX ON lesson_resources(workspace_id,planning_date,plan_id,lesson_id)')
    connection.execute('CREATE INDEX ON monthly_plans(workspace_id,start_date,end_date)')
    for marker, in connection.execute('SELECT name FROM storage_migrations').fetchall():
        connection.execute('INSERT INTO workspace_data_migrations VALUES(%s,%s)', (legacy_workspace_id,marker))
    connection.execute('DELETE FROM storage_migrations')
    connection.execute('INSERT INTO storage_migrations VALUES(%s)', (MARKER,))
    # Membership metadata is inaccessible to runtime except this fixed function.
    connection.execute("""
        CREATE FUNCTION teacher_ai_authorized_workspace(w uuid) RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
          SELECT w = NULLIF(current_setting('teacher_ai.workspace_id',true),'')::uuid
            AND EXISTS(SELECT 1 FROM public.workspace_memberships m
              JOIN public.users u ON u.id=m.user_id JOIN public.workspaces c ON c.id=m.workspace_id
              WHERE m.workspace_id=w AND m.user_id=NULLIF(current_setting('teacher_ai.user_id',true),'')::uuid
                AND m.state='active' AND m.role='owner' AND u.state='active' AND c.state='active')
        $$;
        REVOKE ALL ON FUNCTION teacher_ai_authorized_workspace(uuid) FROM PUBLIC;
    """)
    connection.execute(sql.SQL('GRANT EXECUTE ON FUNCTION teacher_ai_authorized_workspace(uuid) TO {}').format(sql.Identifier(runtime_role)))
    connection.execute("""
        CREATE FUNCTION teacher_ai_reserve_restored_progress_ids(restored_max bigint DEFAULT 0) RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
        DECLARE next_id bigint; w uuid;
        BEGIN
          w=NULLIF(current_setting('teacher_ai.workspace_id',true),'')::uuid;
          IF NOT public.teacher_ai_authorized_workspace(w) THEN RAISE EXCEPTION 'Workspace access unavailable'; END IF;
          -- Rare restore only: block progress INSERTs while reserving restored IDs.
          -- Normal classroom transactions still use independent workspace locks.
          LOCK TABLE public.actual_progress IN SHARE ROW EXCLUSIVE MODE;
          SELECT greatest(coalesce(max(id),0),(SELECT last_value FROM public.actual_progress_id_seq),restored_max)+1
            INTO next_id FROM public.actual_progress WHERE workspace_id=w;
          EXECUTE format('ALTER SEQUENCE public.actual_progress_id_seq RESTART WITH %s',next_id);
        END $$;
        REVOKE ALL ON FUNCTION teacher_ai_reserve_restored_progress_ids(bigint) FROM PUBLIC;
    """)
    connection.execute(sql.SQL('GRANT EXECUTE ON FUNCTION teacher_ai_reserve_restored_progress_ids(bigint) TO {}').format(sql.Identifier(runtime_role)))
    for table in CLASS_TABLES:
        ident=sql.Identifier(table)
        connection.execute(sql.SQL('ALTER TABLE {} ENABLE ROW LEVEL SECURITY').format(ident))
        connection.execute(sql.SQL('ALTER TABLE {} FORCE ROW LEVEL SECURITY').format(ident))
        connection.execute(sql.SQL('CREATE POLICY workspace_access ON {} USING (teacher_ai_authorized_workspace(workspace_id)) WITH CHECK (teacher_ai_authorized_workspace(workspace_id))').format(ident))
        connection.execute(sql.SQL('REVOKE ALL ON {} FROM PUBLIC').format(ident))
        connection.execute(sql.SQL('REVOKE ALL ON {} FROM {}').format(ident,sql.Identifier(runtime_role)))
        connection.execute(sql.SQL('GRANT SELECT,INSERT,UPDATE,DELETE ON {} TO {}').format(ident,sql.Identifier(runtime_role)))
    connection.execute(sql.SQL('GRANT USAGE ON SEQUENCE actual_progress_id_seq TO {}').format(sql.Identifier(runtime_role)))
    connection.execute(sql.SQL('GRANT SELECT ON storage_migrations TO {}').format(sql.Identifier(runtime_role)))
    connection.execute('ALTER TABLE workspace_data_migrations ENABLE ROW LEVEL SECURITY')
    connection.execute('ALTER TABLE workspace_data_migrations FORCE ROW LEVEL SECURITY')
    connection.execute('CREATE POLICY workspace_access ON workspace_data_migrations USING (teacher_ai_authorized_workspace(workspace_id)) WITH CHECK (teacher_ai_authorized_workspace(workspace_id))')
    connection.execute('REVOKE CREATE ON SCHEMA public FROM PUBLIC')
    connection.execute(sql.SQL('REVOKE CREATE ON SCHEMA public FROM {}').format(sql.Identifier(runtime_role)))
    connection.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(sql.Identifier(runtime_role)))
    connection.execute(Path(__file__).with_name('workspace_reference_checks.sql').read_text())
    for function in ('teacher_ai_check_reference(uuid,text,text)', 'teacher_ai_check_json_references()'):
        connection.execute(sql.SQL('GRANT EXECUTE ON FUNCTION {} TO {}').format(sql.SQL(function), sql.Identifier(runtime_role)))
    for table in ('monthly_learning_items','monthly_item_updates','carryover_items','period_reviews','day_plans','lesson_progress','lesson_resources'):
        connection.execute(sql.SQL('CREATE CONSTRAINT TRIGGER workspace_references AFTER INSERT OR UPDATE ON {} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION teacher_ai_check_json_references()').format(sql.Identifier(table)))
    for table in CLASS_TABLES+('users','user_identities','workspaces','workspace_memberships','invites','workspace_data_migrations','storage_migrations'):
        connection.execute(sql.SQL('ALTER TABLE {} OWNER TO {}').format(sql.Identifier(table),sql.Identifier(schema_owner_role)))
    for function in ('teacher_ai_authorized_workspace(uuid)','teacher_ai_reserve_restored_progress_ids(bigint)',
                     'teacher_ai_check_reference(uuid,text,text)','teacher_ai_check_json_references()'):
        connection.execute(sql.SQL('ALTER FUNCTION {} OWNER TO {}').format(sql.SQL(function),sql.Identifier(schema_owner_role)))
    # FORCE also protects a non-superuser migration owner; supply explicit legacy scope.
    connection.execute("SELECT set_config('teacher_ai.user_id',%s,true),set_config('teacher_ai.workspace_id',%s,true)", (legacy_user_id,legacy_workspace_id))
    after=inventory(connection,legacy_workspace_id)
    if before != after:
        raise ValueError('Migration preservation checks failed; roll back.')
    connection.execute('SELECT teacher_ai_reserve_restored_progress_ids()')
    return dict(legacy_workspace_id=legacy_workspace_id,legacy_user_id=legacy_user_id,before=before,after=after,unchanged=True)


def main():
    """Cutover command: credentials come only from administrator environment."""
    import argparse
    import os
    import psycopg
    from legacy_storage_admin import LegacyStore
    from workspace_backup import checksum
    parser=argparse.ArgumentParser(description='Maintenance-only workspace migration; never run from UI.')
    parser.add_argument('--owner-id',required=True)
    parser.add_argument('--workspace-id',required=True)
    parser.add_argument('--runtime-role',required=True)
    parser.add_argument('--schema-owner-role',required=True)
    parser.add_argument('--backup',type=Path,required=True)
    parser.add_argument('--verified-snapshot',type=Path,required=True)
    parser.add_argument('--snapshot-sha256',required=True)
    parser.add_argument('--snapshot-restore-verified',action='store_true',required=True)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--maintenance-confirmed',action='store_true',required=True)
    args=parser.parse_args()
    try:
        admin_url=os.environ['MIGRATION_DATABASE_URL']
        if not args.verified_snapshot.is_file() or args.verified_snapshot.stat().st_size==0:
            raise ValueError('Verified database snapshot is required.')
        if hashlib.sha256(args.verified_snapshot.read_bytes()).hexdigest()!=args.snapshot_sha256:
            raise ValueError('Snapshot checksum does not match.')
        backup=json.loads(args.backup.read_text())
        if backup.get('format_version')!=6:
            raise ValueError('Fresh production format-6 backup is required.')
        if LegacyStore(admin_url).export_backup()!=backup:
            raise ValueError('Database differs from backup; refresh the backup during maintenance.')
        with psycopg.connect(admin_url,connect_timeout=15,sslmode='require') as c:
            result=migrate(c,legacy_user_id=args.owner_id,legacy_workspace_id=args.workspace_id,runtime_role=args.runtime_role,schema_owner_role=args.schema_owner_role)
        result['backup_payload_checksum']=checksum(backup)
        result['snapshot_checksum']=args.snapshot_sha256
        # This report contains numeric counts/checksums/explicit ownership IDs, no class text.
        args.report.write_text(json.dumps(result,indent=2))
        args.report.chmod(0o600)
        print('Migration committed; preservation inventory unchanged. Owner deployment remains closed pending runtime/export verification.')
    except Exception:
        # Never echo URLs, driver errors, secrets or teaching payloads.
        raise SystemExit('Migration did not complete verification. Keep deployment closed; inspect the administrator runbook.') from None


if __name__=='__main__':
    main()
