# Teacher AI hardening and multi-user readiness — 2 October 2026

Baseline: main `44fc6897c9c55c37230126a936251e8f82912bd6`; its CI run
36985034503 succeeded. Resources for Tomorrow is complete, not reimplemented.
This is a technical review, not new classroom acceptance. No genuine outcomes,
plans, resources or class records are intentionally written by this review.

## Safe work completed

- Session-only numeric diagnostics: storage method counts/durations; DB connect,
  SQL read/write/setup/lock, fetch and commit/rollback/close; evidence preparation;
  resource batch execution, generation/review calls and resource-card rendering.
  A Generate callback retains a trace through the surrounding full server rerun.
  Ordinary reruns have separate snapshots. Failed calls are counted. No telemetry
  service, prompt, SQL text, parameters, class content, URL or exception body is
  recorded. Timings are inclusive where nested and must not be added together.
- Collapsed About / diagnostics shows a deterministic SHA-256-derived source
  fingerprint and installed package versions. It deliberately does not claim to
  be a Git SHA. Compare the fingerprint computed from the committed Python files
  and requirements with the running deployment. Changes to handoff/docs do not
  change application identity; package versions distinguish dependency drift.
- Reused history and projected learning within one locked evidence read:
  `_quality_context` previously read history twice and projected learning twice
  through `_carryover`. It now reads each once, preserving its exact output and
  fresh generation/save checks. Three SELECTs removed per evidence packet
  (11 -> 8), not a cross-request cache or change to connection architecture.
- Malformed generation field types now fail safely inside the existing group
  handler instead of escaping during code checks and stopping later lessons.
- Regeneration instruction edits survive normal navigation in session state,
  without AI or durable writes while typing. Existing content/title drafts remain.
- Current stateless AI calls default to `store=False`: optional provider response
  application-state storage is not needed by any current workflow. This does NOT
  promise zero retention; provider abuse-monitoring controls still apply.
- Added 12 regression tests: 164 total; 63 persistence cases eligible for real PG
  CI. Tests use isolated fixtures/mocks, not production teaching outcomes.

## Performance findings and measurement plan

Earlier measured four-lesson preparation: 14.80s AI-only, 54.56s through server
result rendering; browser completion bounded by observations at 55.31–77.33s.
Those old samples cannot retrospectively be split into connection, SQL and UI
time. There is no evidence for calling all the ~40s difference "rendering".

Concrete execution path:

1. Generate callback -> entire Today script reruns: monthly selection, transition
   context (full history/learning projections), day state and today's resources.
2. Tomorrow loads approved raw plans, saved resources and a fresh day-wide evidence
   packet even when its expander is collapsed (Streamlit expanders execute body).
3. Every lesson/instruction group rereads evidence using a new connection, then
   makes generation/review calls. Existing selected resources regenerate singly.
4. Pending cards, progress controls, backup controls and diagnostics render.

Each Store operation creates a fresh TLS connection (`connect_timeout=15`), sets
a local SQL timeout (30s) and closes after commit/rollback. Context reads and
writes take the same global advisory lock; no AI calls hold that lock. Connection
handshake/cold-start, SQL round trips, contention and repeat reads can now be
measured separately. `db.sql.lock` includes lock round-trip/wait; it cannot split
those two. SQL execute includes provider execution/network transfer; it is not
an EXPLAIN ANALYZE server CPU estimate. `db.fetch` measures Python fetch work.

Use About / diagnostics after a rerun or an explicitly requested unsaved batch.
`elapsed_seconds` covers callback -> end of server page; nested `storage.*`,
`preparation.*`, `resource.*`, `ui.*` spans explain paths. Add only disjoint leaf
DB stages and AI stages when calculating residual Python/UI execution. Browser
transport/paint remains outside the trace. The OpenAI SDK can internally retry;
call counts are SDK invocations, not HTTP attempts. AI timings include such waits.
An uncaught stop/error before the footer can prevent a completed snapshot.

Do not add pooling or cross-request caching based on the historic aggregate alone.
If connect time dominates, propose a small bounded psycopg pool with checkout
health checks, pool exhaustion tests and transaction-local ownership/RLS settings.
If SQL dominates, first reduce duplicate projections within a transaction and
measure relevant query/index plans. If incidental rerun reads dominate, consider
request-local snapshots invalidated after writes, never cached save validation.
These larger changes require a reviewed proposal and remain unimplemented.

## Ownership model and every persistent table

Recommend User -> workspace membership -> Workspace/Class. One owner per class
initially; membership permits later co-teaching without putting two independent
tenant keys on every row. Class data uses mandatory `workspace_id`. `created_by` /
`updated_by` user IDs are audit attribution, not a second ownership boundary.
Teacher Profile is presently class/programme/differentiation context: scope the
existing profile to workspace. Separate future personal preferences if needed.

| Existing table | Current boundary/key | Beta ownership and constraint |
|---|---|---|
| teacher_profile | global singleton id=1 | workspace_id PK; author optional |
| planning_setup | global singleton id=1 | workspace_id PK; timetable/yearly text remain class-owned |
| current_learning_position | global singleton id=1 | workspace_id PK; projections must use only this workspace |
| actual_progress | global numeric id, date index | workspace_id NOT NULL; unique workspace/date for new dated records; retain undated legacy rows |
| lesson_progress | record_id FK | workspace_id; composite FK(workspace_id,record_id) to actual_progress |
| day_plans | planning_date global PK | PK(workspace_id,planning_date); preserve plan/lesson UUIDs and snapshots |
| monthly_plans | global text id | workspace_id; workspace-scoped dates/overlap checks and composite parent references |
| monthly_learning_items | global id, links in JSON | workspace_id; validate all monthly/split/merge references within workspace |
| monthly_item_updates | global id, event links in JSON | workspace_id; created_by user; item/record/lesson references restricted to same workspace |
| period_reviews | period_id global PK | PK(workspace_id,period_id); workspace monthly parent |
| carryover_items | global id, links in JSON | workspace_id; validate period/item/lesson links within workspace |
| lesson_resources | id, literal owner_scope=single-teacher | workspace_id; created_by user; exact parent IDs; replace literal owner_scope through versioned migration |
| storage_migrations | name global PK | global schema markers stay global; legacy/data-import markers become workspace-scoped |

Add `users` (internal UUID plus unique issuer/subject), `workspaces` (class UUID,
owner_user_id, display name, timezone), `workspace_memberships` (workspace/user,
role), and minimal invite records. No authentication or tables added in this review.
Use relational workspace columns, not JSON payload ownership assertions.

### Query/write-path inventory

All these paths currently operate on the shared dataset and must require a
server-authorized workspace before beta; no global/default workspace fallback.

- Documents: load/save_document; singleton reads inside `_quality_context`,
  `_project_position`, carryover_context and legacy migration.
- Monthly plans: `_monthly`, list/select/save_monthly_plan, date overlap checks.
- Evidence/history: `_history`, load_progress_history/load_recent_progress,
  load_day, planning_quality_context, `_learning`, `_carryover`. Scope joins,
  LIMIT/ORDER BY and projections, not just the final displayed list.
- Carryover: list_carryover/carryover_context, save_period_review,
  set_carryover_state and inherited link_carryover_item; validate linked items.
- Monthly learning: `_learning_raw`, `_learning_events`, list/save_learning_items,
  apply_reviewed_regrouping, correct_learning_item, `_save_item_progress`; retain
  archive/split/merge lineage and event IDs. Event order is workspace-local.
- Plans/resources: save_day_plan, approved_resource_plans, resource_day_contexts,
  resource_context, list_resources/save_resource. Scope read-before-write revision
  checks, exact parent lookup and stale-context validation. `owner_scope` currently
  filters some resource reads but save-by-ID and export remain global.
- Outcomes/corrections: save_lesson_progress/correct_lesson_progress,
  save_progress/correct_progress and `_project_position`. Scope duplicate-date
  checks, record-ID updates and derived Current Learning writes in one transaction.
- initialise, `_import_legacy`, `_migrate_monthly`: separate schema installation
  privileges from runtime; no new user's login can trigger import of legacy data.
- export_backup/restore_backup: global currently, including resource history.
  Empty-destination check and all writes must be scoped to authorized workspace.

### Preventing cross-teacher access

Construct Store with authenticated server identity and verified membership, never
an unchecked widget/query parameter. Every SQL path needs workspace predicates,
including JSON-derived relationships and joined tables. Deny absent/invalid scope.
Use composite workspace/parent constraints where relational links exist.

Add PostgreSQL RLS with USING and WITH CHECK policies on class tables, enforced
for the runtime role (not superuser/table owner/BYPASSRLS). Set transaction-local
workspace context only after membership authorization. Missing scope returns no
rows/rejects writes; connection reuse cannot retain an earlier user's scope.
RLS supplements application authorization, not a substitute for authenticating a
caller. Migration/admin role stays separate. Replace global LOCK_ID with a stable
workspace advisory lock to avoid serializing all teachers. Never hold it over AI.

Scope session-state keys, exports, draft registries and future cache keys by
workspace; clear them on logout/workspace switch. Cached schema initialization
may remain global. Never globally cache class/profile data without tenant keys.

### Existing-data migration and historical records

1. Verified backup and row/JSON checksums before migration; rehearse on isolated
   PostgreSQL with current format-6 fixtures and anonymized/minimized data.
2. Create the owner user and one explicit legacy workspace. Add nullable workspace
   columns, backfill **all** existing rows to that workspace without rewriting
   teaching text, statuses, dates, resource versions or UUIDs.
3. Validate counts, references, date uniqueness and complete export comparison.
   Preserve undated legacy progress. Resolve any duplicate dated records by
   review, never silently dropping them. Associate every legacy singleton id=1.
4. Scope uniqueness/indexes/foreign keys, make ownership NOT NULL, switch Store
   reads/writes atomically, enable RLS with separate roles, deny unscoped access.
5. Verify owner can read all history and two isolated teachers cannot read,
   update, export, restore or link each other's records. Rehearse rollback with
   a pre-migration snapshot before new multi-user writes begin.

Historical replaced-plan resources retain original snapshots and IDs. Do not
FK them to only the current mutable day/date row or cascade-delete them. An
additive immutable plan-version registry is the clean future parent model; seed
available current/progress/resource snapshots and mark incomplete historical
evidence explicitly. Never reconstruct missing lessons by title matching. Until
that migration is ready, enforce workspace/exact parent validation in storage and
retain historical snapshots. No history-normalization migration performed here.

### Workspace backups/restores

Introduce a versioned envelope: source workspace ID, schema/application version,
export timestamp and checksums; exclude credentials, identity tokens and invite
secrets. Export only an authorized workspace, including all archived items and
resource versions. Current format 1–6 remains supported for explicit owner-only
legacy import. A format-6 file cannot choose its destination workspace.

Restore validates the whole graph before writing, checks emptiness only in the
authorized destination workspace and runs atomically. Never trust embedded
ownership/author IDs as authorization. Original-workspace disaster restore can
retain IDs; cloning into a new workspace needs a deliberate ID/relationship map,
resource context/digest migration and explicit origin/provenance. Preserve old
checked evidence/history rather than claiming newly verified approval. Production
overwrite/merge/import-between-teachers is a separate product decision.

### Authentication fit (proposal only)

Streamlit's native OIDC `st.login` / `st.user` fits the existing architecture;
authentication does not provide authorization. Use an existing suitable Google
or Microsoft provider with an invite allowlist, stable issuer+subject mapping and
verified identity claims. Authorize membership before **any** class read, export
or AI call. Test invitation revocation and active sessions. Do not assume school
accounts are configured or create any provider account without owner approval.
Provider choice and app registration are pending. No paid service selected.

## Concrete security/privacy findings

| Area | Finding | V1/beta mitigation |
|---|---|---|
| Access | UI loads saved class context without an application auth gate; hosting access restriction unknown | Verify hosting privacy now; mandatory invite authorization + scoped Store/RLS before beta |
| API key | Server-side st.secrets; not intentionally exported/logged; missing key can abort startup | Keep out of git/backups, generic configuration failure, provider project limits/rotation procedure |
| DATABASE_URL | st.secrets, credential-free StorageError, no SQLite fallback, TLS require | Separate runtime/migration roles; verify provider CA/hostname support before changing require to verify-full |
| Uploads | PDF/DOCX parsed server-side; filename extensions limit chooser, not trusted validation; no application size/page/zip-expansion cap | Bound bytes/pages/extracted characters/archive sizes; reject oversized or unreadable input before costly parsing/AI; do not execute embedded content |
| Reference uploads | UI offers examples but files are not persisted/used by resource generation | Say clearly they are not yet evidence; do not pretend source access |
| Prompts | Whole profile, current-learning and recent progress travel in resource packets; recent history may include unrelated pupil notes | Minimize/redact identifiers, supply only relevant learning; structured untrusted-input boundaries in extraction/rebuild/carryover prompts; teacher notice and school approval process |
| AI retention | Calls previously omitted store flag; no response-ID/stateful dependencies | Default store=False completed; review provider retention/project controls, do not claim zero retention |
| Resources/history | JSON contains copied context/source and versions; growth and sensitive details survive revisions | Purpose/retention policy and teacher-controlled deletion design; do not auto-delete genuine evidence |
| Errors/logs | DB errors sanitized; resource failures expose class names only. Unhandled/parser/SDK errors and rubric chained errors can reach operational logs | Bounded sanitized logging with correlation IDs; no prompt/raw response/URL logs; restrict log access; review debug settings |
| SQL | Values parameterized; table/column substitutions from fixed code allowlists | Preserve allowlists; no AI-generated SQL; scoped constraints/RLS. JSON references lack relational tenant protection today |
| Backup | Full plaintext class dataset, session download persists; empty-global-store refusal works | Authorized workspace export; clear downloads on scope switch; safe file handling and retention guidance; size/graph validation for restore; imported approval metadata is provenance, not cryptographic proof |
| Diagnostics | Numeric session state only; no external telemetry | Retain no arguments/SQL/prompts, no class identifiers; never add secrets/env dump |
| Abuse/cost | Unauthenticated access may spend shared API quota; no app user quotas; SDK retries are hidden within call timings | Invite gate first, bounded inputs/concurrency/user budget; configure timeout/retry policy explicitly after testing |
| Dependencies | Streamlit pinned; OpenAI/PDF/DOCX floating, psycopg range | Lock tested versions, update intentionally with CI; source fingerprint alone is not a dependency lock |

No credentials or production records were inspected by shell. Presence/handling
was assessed from code; deployment access permissions and account-level provider
settings cannot be certified from this review. Model review is not a security
boundary or proof of correctness. Generated Markdown does not enable unsafe HTML;
links can still be misleading, and unsupported claims can evade semantic review.

Official references checked 2 October 2026:
- https://docs.streamlit.io/develop/concepts/connections/authentication
- https://docs.streamlit.io/develop/api-reference/user/st.login
- https://developers.openai.com/api/docs/guides/your-data
- https://developers.openai.com/api/reference/python/resources/responses/methods/create

## Reliability, tests and remaining debt

Existing tests cover atomic saves, legacy migrations, PostgreSQL concurrency,
stale/replaced parents, optimistic resource revisions, rubric failure preservation,
malformed review JSON, missing source, title-only saves, edits/navigation and
backup refusal/restore. New cases cover privacy-safe timings, failure timing,
thread isolation, source identity, callback tracing, instruction navigation,
year/leap-day boundaries, malformed generation isolation and equivalent evidence
with fewer SQL reads, plus sanitized uncertain-commit failures. No genuine teaching outcomes saved for testing.

Before beta add two-tenant adversarial tests for EVERY inventory path and JSON
link, RLS missing-scope/bypass checks, revoked membership, concurrent workspace
operations, scoped backup/restore and migration rollback. Additional useful tests:
stale profile/progress edits (currently last-write-wins despite serialized writes),
concurrent plan generation/replacement, SQL timeout/network/commit uncertainty,
malicious/oversized uploads, bounded SDK retry/timeout behavior and a fresh-process
deployment smoke test. Hot reload is managed by manually synchronized module
versions; diagnostics identify code but cannot guarantee every module hot-reloaded.
A process restart remains safer for code/dependency rollouts than adding more
manual importlib reload paths. No guaranteed reconnect/draft-resume contract.

Drafts: content/title and now regeneration instructions survive ordinary reruns
and navigation. Unsubmitted form inputs may be lost if navigation occurs before
submission; do not claim all browser typing was received by the server. Pending
candidate registries can grow with repeated generation. Different simultaneously
open editor views can have independent widget buffers; explicit Save remains the
durable boundary. Hard refresh/new session/restart/deployment can lose drafts.

Durable-draft proposal (not implemented): a separate workspace/user-scoped draft
table holding exact plan/lesson IDs, context digest, selected inputs, last edit,
revision and expiry. Drafts remain unapproved, excluded from classroom projections
and saved-resource suggestions; restore can optionally include them as drafts.
Resume requires membership and stale-parent/evidence checks. Decide retention,
autosave debounce and recoverability UX before creating it. No localStorage of
class/pupil content or authentication tokens.

## Recommended next five tasks, in dependency order

1. Agree beta privacy/access, workspace ownership and identity-provider decisions;
   confirm current hosting restriction, data minimization and retention policy.
2. Implement/rehearse additive legacy-workspace migration, scoped Store APIs,
   constraints/RLS, scoped backup/restore and comprehensive two-tenant tests.
3. Add invite-only OIDC identity/membership gates, session cleanup, revocation and
   per-user budgets. No access until task 2's isolation is independently verified.
4. Address measured latency (pool/request-local snapshots only after numeric
   evidence), optimistic document/progress writes, bounded AI/network failures,
   upload limits, dependency locking and cold-deployment smoke checks.
5. Run a technical private-beta rehearsal, migration/export comparisons and
   adversarial cross-user acceptance; genuine classroom acceptance when possible.

Can wait: PDF/Word/slides, packs/templates, holiday inference, sharing/co-teaching,
background jobs, cross-lesson AI batching and durable drafts unless loss materially
blocks beta. Needs owner decision: provider/invites, owner vs collaborator rights,
retention/deletion and pupil-data policy, cloning/restore semantics, durable draft
recovery, acceptable latency/cost and whether measured pooling work is justified.
