# Workspace isolation — staged cutover and recovery

Status on 2 October 2026: implementation and isolated rehearsal complete; **production cutover NOT performed**. Keep this change on its draft branch until the gates below pass. Main remains `d8c4cb6`. No beta invitations, OIDC or pooling.

## Recorded product decisions

Invite-only beta; Google first later; one active teacher-owner per workspace; membership architecture retained without co-teaching UI. Workspace owns classroom data. Minimize pupil identifiers; preserve genuine evidence. Format-7 restore is same authorized workspace and empty destination only. No cloning/import-between-teachers UI. Durable drafts and retention/deletion UI wait. Investigate pooling only after scoped deployment is complete and measured.

## Implementation boundaries

- `Store(database_url, WorkspaceScope(user_id, workspace_id))` has no unscoped constructor or runtime initializer. Every transaction rechecks active membership/user/workspace and restricted role, and verifies forced RLS remains installed. All classroom SQL has explicit workspace ownership/predicates; joined progress rows use composite ownership.
- Runtime must not be superuser, BYPASSRLS, CREATEROLE, CREATEDB, table owner or member of privileged ownership roles. Migration rejects existing runtime role memberships. Runtime gets only required CRUD, identity-sequence usage, schema-version reads and fixed authorization/restore functions. It cannot create schema objects or read identity/invite tables.
- `teacher_schema_owner` is non-login/non-superuser/non-BYPASSRLS and owns tables/functions. The migration administrator can assume it; runtime cannot. Provider must support these role boundaries before cutover.
- Twelve existing class tables have mandatory relational workspace IDs and FORCE RLS. Workspace import markers have a separate FORCE-RLS ledger. Global `storage_migrations` holds only schema markers.
- Existing global IDs remain globally unique. Document singleton keys and day/date keys become composite workspace keys. Lesson progress has composite workspace/progress FK; period reviews have composite workspace/monthly FK. Deferred JSON triggers check learning lineage, monthly/progress/item/carryover relationships, resource IDs and snapshots. Historical resources are not attached to mutable current-day rows or cascade-deleted.
- Every public Store operation is exercised with revoked membership. Ordinary transaction advisory locks derive deterministically from workspace UUID. AI never holds a database transaction/lock.
- Format-7 envelope contains workspace/schema/build/time/checksum and the complete historical payload. Checksum is integrity, not a signature. Uploaded metadata never grants ownership. Cross-workspace source envelopes and formats 1–6 are rejected by runtime.
- Restore preserves numeric IDs. A restricted definer function reserves the restored progress-ID range transactionally, before inserts. This rare operation takes a shared progress-table/sequence reservation lock to avoid conflicting allocations and lock-upgrade deadlocks; ordinary class operations keep independent workspace locks. Large restores can delay other progress writes, but cannot change another workspace's rows.
- Session, draft, explicit widget and download keys are namespaced by workspace/user. Switching scope clears prior buffers; authorization failure clears them. Normal navigation retains drafts. No durable draft storage.
- Owner-only bridge requires explicit ACCESS_MODE, user/workspace IDs, and confirmation of private hosting. It is not authentication and cannot authorize beta visitors. ACCESS_MODE other than `legacy_owner` fails closed. No email is matched and no OIDC identity is invented.
- `legacy_storage_admin.py` / `legacy_learning_admin.py` freeze the pre-migration format readers for isolated administrator recovery and regression comparison. Runtime UI does not import them. Do not build new functionality against those compatibility classes.

## Evidence already obtained

Fresh app export: 471,839 bytes, format 6; file SHA-256 `7e5bbc694058d696b472c4b6cb621539dfada4641ddd19d98c3fb94e7d648d7c`.

Complete canonical payload SHA-256 before/after isolated migration:
`ab273d25a2727a816ce16cacf072f2cdab48b10dceb480a9ad49ad835c50318f`.

The export restored into isolated PostgreSQL 16.15 and re-exported exactly before migration. Migration retained every original stored-column row checksum; scoped format-7 payload equals the entire original export. `WORKSPACE_MIGRATION_REHEARSAL.json` records counts/checksums, contains no teaching payload, and explicitly says production was not migrated.

| Rehearsal table | Before | After |
|---|---:|---:|
| teacher_profile | 1 | 1 |
| planning_setup | 1 | 1 |
| current_learning_position | 1 | 1 |
| actual_progress | 1 | 1 |
| lesson_progress | 0 | 0 |
| day_plans | 2 | 2 |
| monthly_plans | 2 | 2 |
| monthly_learning_items | 349 | 349 |
| monthly_item_updates | 0 | 0 |
| period_reviews | 1 | 1 |
| carryover_items | 2 | 2 |
| lesson_resources | 7 | 7 |

These are isolated-clone counts, not a claim that raw production tables were inspected. Export does not include every infrastructure detail; a verified database snapshot remains mandatory.

252 tests pass locally with both PostgreSQL test configurations enabled: original 165; 52 business regressions rerun on restricted scoped Store; 35 scope/isolation tests (32 use PostgreSQL, 3 are unit tests). Thus 147 cases run against real PostgreSQL: 63 legacy-administrator persistence plus 84 restricted-runtime/rehearsal cases. No production outcomes were fabricated, and all AI responses in automated tests are mocked.

CI adds a dedicated PostgreSQL 16 restricted-role/RLS stage after baseline regression and legacy persistence stages. Publication/CI verification is recorded in the handoff; do not equate local success with published CI success.

## Cutover gates — before any production schema change

1. Obtain authenticated PostgreSQL administration and Streamlit deployment/maintenance access. Existing browser exposes ordinary app controls only; no provider snapshot or secrets-management access was available during this task. Do not put credentials in chat or git.
2. Confirm owner-only hosting. The bridge cannot substitute for an access gate. Close/drain old app sessions and stop all writes; prevent old/scoped versions running concurrently. No beta access.
3. Take a **new** format-6 export during maintenance. The recorded export will become stale if classroom data changes.
4. Take provider snapshot or `pg_dump` custom-format snapshot with the appropriate administrator. Record SHA-256 and snapshot time. Restore it into a separate PostgreSQL 16 database and compare original-column inventory plus full export. Listing an archive alone is not verification.
5. Verify provider role support, including owner/admin ability to create the non-login owner role and function ownership/grants. Provision a dedicated login runtime role with no role memberships and no elevated flags. Configure its credential securely outside code.
6. Choose and retain one explicit legacy internal owner UUID and workspace UUID. These are not the random rehearsal IDs. No email/OIDC matching. Record them in the administrator's cutover manifest.
7. Rehearse on the fresh snapshot, with actual restricted runtime role and all tests below. Only then run the migration on production.

## Administrator migration command

Use administrator environment `MIGRATION_DATABASE_URL`, separate from runtime `DATABASE_URL`. The command requires a fresh export matching the database, a verified snapshot with its exact digest, explicit scope/role IDs, and maintenance/restore verification attestations. It never prints credentials/driver errors/class payloads. These flags do not take the snapshot or verify its restore for you.

```bash
python -m workspace_migration \
  --owner-id "$legacy_owner_uuid" \
  --workspace-id "$legacy_workspace_uuid" \
  --runtime-role teacher_runtime \
  --schema-owner-role teacher_schema_owner \
  --backup "$fresh_export_path" \
  --verified-snapshot "$verified_snapshot_path" \
  --snapshot-sha256 "$snapshot_digest" \
  --snapshot-restore-verified \
  --report "$private_cutover_report_path" \
  --maintenance-confirmed
```

One transaction locks the old write boundary/tables, creates metadata, backfills all rows, installs scoped keys/FKs/policies/roles, moves import markers and compares exact original-column inventories. Validation/DDL/permission failure rolls back. A second invocation refuses rather than rebinding ownership. Report-write failures after commit require administrator inspection; do not assume the database stayed unmodified just because the CLI exit was unsuccessful.

The report is private, contains ownership UUIDs/counts/checksums and no classroom text. Keep it with the snapshot. Verify the committed schema and scoped export directly after the command, independently of its report.

## Before reopening owner deployment

- Export through the restricted runtime Store; compare its entire payload with maintenance export, and each raw original-column count/checksum with the snapshot inventory. Explicitly include undated progress, archived items, carryover, all plan/lesson IDs and resource version arrays.
- Verify allowed owner reads, editing/saving with reversible existing-data changes only if necessary, and stale/revision safeguards. Synthetic positive writes belong in isolated testing, not production.
- Deny absent/malformed scope, wrong membership, revoked membership and incorrectly privileged runtime role. Check ENABLE/FORCE RLS and object ownership directly for all class tables/ledger.
- Run synthetic second-workspace adversarial checks on the rehearsed isolated snapshot; do not fabricate classroom plans/outcomes in production. Cover every Store read/write, JSON/FK forgery, collisions, resource parents, export/restore, direct restricted SQL, independent workspace locks, same-workspace serialization and concurrent restores.
- Verify private hosting and clean restart with runtime credentials only:
  `ACCESS_MODE="legacy_owner"`, `LEGACY_OWNER_ACCESS_RESTRICTED=true`, explicit `LEGACY_OWNER_USER_ID`, explicit `LEGACY_WORKSPACE_ID`. Do not put administrator credentials in app secrets.
- Check reload/navigation/reopen isolation and namespaced downloads/drafts. Missing configuration stops before class reads or AI client initialization. Test evidence already includes real scoped Streamlit navigation and denial in isolation.
- Confirm exact running source fingerprint/package versions. No exact Git SHA is fabricated.
- Reopen owner only after all gates pass; record final production outcome and new format-7 backup in handoff. No invitations.

## Rollback and recovery — read before scoped writes

Before the migration commits: rollback its transaction; leave old app pinned to `d8c4cb6` and verify old export.

After commit but **before scoped writes**: keep app closed. Restore the verified pre-cutover database snapshot (including schema, sequences, functions/grants and import markers) into the recovery target; compare complete export and original inventory; deploy matching old app/config together. Recover credentials/role provisioning deliberately—the database snapshot may not include provider/global role metadata. Do not run old code against the scoped database.

After scoped writes: prefer forward fix. Preserve a snapshot/export of the scoped database and subsequent owner writes before considering recovery. Do not drop workspace columns, switch to old global code, discard new writes, or merge teachers' data. Reconcile subsequent writes explicitly in a isolated rehearsal and reverify. No automatic destructive rollback is implemented.

Runtime format-7 restore is atomic and only same-workspace/empty-workspace. Another workspace's rows neither block the emptiness check nor change. Failed/invalid/non-empty restore leaves class rows intact. Infrastructure/membership/import-marker rows do not count as classroom data.

For old formats 1–6, use `python -m legacy_recovery_admin` with `LEGACY_RECOVERY_DATABASE_URL`, `--backup`, `--format6-output`, and `--isolated-destination-confirmed`. It requires administrator schema privilege, refuses migrated workspace schemas/non-empty class data, preserves provided numeric IDs, and exports format 6 for reviewed recovery of the designated legacy owner. Formats missing IDs necessarily receive IDs in isolation. It does not import into a live beta workspace or clone between teachers.

## Remaining boundary before Google OIDC

Production isolation is unverified until cutover. OIDC must later map verified issuer/subject to an internal user and enforce invite/membership authorization before scope construction, every class read/export/AI call, and logout/revocation cleanup. The legacy owner claim must be administrator-controlled; never match email automatically.

RLS GUC settings are a trusted-server boundary, not cryptographic user identity. A compromised server/runtime SQL connection that can impersonate a different internal user is outside the protection of this shared-role design. Preserve parameterized SQL, narrow functions and inaccessible administrator credentials. Backup checksums do not authenticate source provenance; there is no cross-workspace restore route, but checksums alone are not proof against deliberate file retagging. Decide whether signed envelopes are required before beta.

Historical relationships wholly contained in retained snapshots are not normalized into an immutable plan-version registry. Preserve their snapshots; do not claim reconstructed missing evidence. Profile/progress last-write-wins and host-date manual events remain prior hardening debt. No pooling or latency improvement is claimed by this migration.


Publication verification — 2 October 2026: implementation commit `0157bd0d975e33342ddf666c3f7864bff1f0f6a9` is published in draft PR #8 (https://github.com/oisin17/teacher-ai/pull/8). GitHub Actions run 37007381622 completed successfully, including baseline regression tests, real PostgreSQL persistence, and the PostgreSQL 16 restricted-role/RLS adversarial stage. Local combined suite: 252 tests passed without skips; 147 distinct PostgreSQL cases (63 legacy and 84 restricted-role scoped cases). Production cutover has not occurred: authenticated administration and a fresh verified database snapshot/restore remain required. Main/live deployment stays at d8c4cb6. Earlier “CI pending” references describe the pre-publication checkpoint.
