"""Administrator-only old-format recovery into an explicitly isolated database.

No UI entry point, no scoped-workspace overwrite, no provider identity matching.
"""
import argparse
import json
import os
from pathlib import Path
import psycopg
from legacy_storage_admin import LegacyStore


def recover(database_url, backup):
    with psycopg.connect(database_url,connect_timeout=15,sslmode='require') as c:
        if not c.execute("SELECT has_schema_privilege(current_user,'public','CREATE')").fetchone()[0]:
            raise ValueError('Administrator privileges required.')
        if c.execute("SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND column_name='workspace_id'").fetchone():
            raise ValueError('Use an isolated pre-migration recovery database, never an existing workspace.')
    store=LegacyStore(database_url)
    store.initialise('/__teacher_ai_no_automatic_sqlite_import__')
    if not store.restore_backup(backup):
        raise ValueError('Recovery database is not empty. Nothing overwritten.')
    return store.export_backup()


def main():
    parser=argparse.ArgumentParser(description='Recover formats 1-6 in isolated administrator database only.')
    parser.add_argument('--backup',type=Path,required=True)
    parser.add_argument('--format6-output',type=Path,required=True)
    parser.add_argument('--isolated-destination-confirmed',action='store_true',required=True)
    args=parser.parse_args()
    try:
        backup=json.loads(args.backup.read_text())
        if backup.get('format_version') not in (1,2,3,4,5,6):raise ValueError()
        payload=recover(os.environ['LEGACY_RECOVERY_DATABASE_URL'],backup)
        args.format6_output.write_text(json.dumps(payload,ensure_ascii=False,indent=2))
        args.format6_output.chmod(0o600)
        print('Isolated recovery completed. No live workspace changed. Use the explicit legacy-owner migration/recovery runbook next.')
    except Exception:
        raise SystemExit('Legacy recovery was not confirmed. Keep the destination isolated; no live workspace restore is available through this command.') from None


if __name__=='__main__':main()
