"""Version 7 workspace envelope; checksums are integrity checks, not signatures."""
import copy
import hashlib
import json
from datetime import datetime, timezone


def checksum(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def wrap_backup(payload, workspace_id):
    from app_diagnostics import build_identity
    return dict(format_version=7, workspace_id=workspace_id, schema_version='workspace_isolation_v1',
                application_build=build_identity(), exported_at=datetime.now(timezone.utc).isoformat(), payload=payload, checksum=checksum(payload))


def unwrap_backup(backup, workspace_id):
    from persistence import StorageError
    try:
        if not isinstance(backup, dict) or backup.get('format_version') != 7:
            raise ValueError()
        if backup.get('workspace_id') != workspace_id or backup.get('schema_version') != 'workspace_isolation_v1':
            raise ValueError()
        payload = backup['payload']
        if payload.get('format_version') != 6 or checksum(payload) != backup.get('checksum'):
            raise ValueError()
        # No ownership assertions may be smuggled inside classroom payloads.
        def validate(value):
            if isinstance(value, dict):
                if any(k in value for k in ('workspace_id', 'user_id', 'created_by', 'updated_by')):
                    raise ValueError()
                for v in value.values(): validate(v)
            elif isinstance(value, list):
                for v in value: validate(v)
        validate(payload)
        return copy.deepcopy(payload)
    except (ValueError, TypeError, KeyError, AttributeError):
        raise StorageError('Restore requires an intact backup from this same workspace. Nothing has been changed.') from None
