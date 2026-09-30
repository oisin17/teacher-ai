# Durable persistence rollout

This branch replaces the Streamlit runtime's SQLite database with PostgreSQL
for Teacher Profile, Planning Setup, Current Learning Position and Actual
Progress. Priority 2 also saves generated day plans and individual lesson
outcomes in the same PostgreSQL database; no additional service or secret is needed.

## Lesson progress (Priority 2)

- `day_plans` stores one structured generated plan per school date. The same
  lesson objects render the visible plan and provide the progress snapshots.
  They contain stable lesson IDs, time, subject, topic, learning intention and
  the original lesson details. Separate lessons in a subject stay separate.
- `actual_progress` remains the daily record, including every historical
  whole-day row. The additive `lesson_progress` table stores a JSON snapshot
  against the daily record's ID. Existing tables are not destructively migrated.
- New lesson outcomes start unset. **Mark all completed** fills the statuses;
  change exceptions, add optional notes (up to 300 characters), then save once.
  A partial set of statuses cannot be saved. Draft edits are not teaching records.
- Lesson outcomes and the Current Learning evidence section save atomically,
  under the existing advisory lock. Recording requires no extra model call.
  The update preserves existing context and records exact planned intentions,
  outcomes and verbatim teacher notes. Notes override conflicting intentions or
  statuses; completion never establishes whole-topic completion. Partial work
  retains uncertainty and missed learning stays outstanding.
- Evidence is rebuilt from dated durable lesson history, newest first. Retrying
  a save does not duplicate evidence; corrections remove obsolete outcomes and
  can move a record's school date without colliding with another record.
  An explicit Current Learning edit becomes teacher-confirmed context.
- The next generation reads fresh durable Current Learning and recent detailed
  progress, including the original lesson content. Existing planning rules and
  the existing model are preserved; the response now uses a validated JSON
  schema rather than trying to extract lessons from free-form markdown.
- Once progress exists, generation for that date is disabled. Use the existing
  lesson outcomes/corrections; do not replace their original plan with newly
  generated learning. Another session's regenerated plan invalidates stale IDs.
- Refresh restores the saved plan and submitted outcomes for the selected date.
  Unsaved form edits remain session/browser drafts; select the school date again
  after a new session. Historical whole-day records remain correctable through
  their original controls and are never converted using invented intentions.
- Backup format 2 includes plans and lesson snapshots. Restore still accepts
  format 1, validates everything before writing, and refuses any nonempty store.

## Setup

1. Create a **Free** Neon project named Teacher AI, in a suitable EU region.
   No paid upgrade is required for this rollout.
2. Obtain its pooled PostgreSQL connection string from **Connect**.
3. In the deployed app's Streamlit settings, add this top-level secret alongside
   the existing OPENAI_API_KEY:

   ```toml
   DATABASE_URL = "<Neon pooled PostgreSQL connection string>"
   ```

   Do not put the real connection string in GitHub, an issue, a PR or chat.
   Keep the existing OPENAI_API_KEY.
4. The Neon connection string should include its supplied SSL/channel-binding
   settings. The application also enforces TLS through the driver.
5. Merge only when the connection secret is configured and CI has passed.
   All four tables are created automatically on first startup.

## Existing data and cutover

If teacher_ai.db is still present in the runtime at first startup, the application
copies all four data areas into a completely empty PostgreSQL database, in one
transaction. Undated older progress is retained. A migration marker prevents a
stale SQLite file from overwriting subsequent edits. An import error rolls back
the entire import and stops the app rather than starting with partial data.

**Important:** adding a Streamlit secret or deploying dependencies can restart
the runtime. An ephemeral SQLite file may disappear before the new code can read
it. Automatic migration cannot recover a file that Streamlit has already removed.
Use the legacy app's **Saved data backup → Prepare saved data backup → Download
saved data backup** before changing Streamlit settings. This export includes
all four data areas, including monthly plan text and dated/undated progress.
Do not commit classroom data to this public repository.

After cutover, compare the saved data to the backup. If automatic migration could
not run because the runtime lost SQLite, upload the JSON backup under **Saved
data backup** and click **Restore saved data backup**. Restore is transactional
and refuses to overwrite any nonempty durable database. If the old database and
backup cannot be accessed, resolve recovery before calling migration complete.

An unavailable/misconfigured PostgreSQL database stops reads/saves with a safe
message. There is no silent local fallback. Session values and success messages
are updated only after a confirmed save.

## Validation

- Local: `python -m unittest discover -s tests -v`.
  Streamlit AppTest exercises real UI reruns with mocked AI responses, avoiding
  paid model calls. Storage tests use an explicitly test-only SQLite SQL adapter.
- GitHub Actions also repeats the storage suite against PostgreSQL 16, including
  concurrency, rollback and migration checks. Its database is disposable.
- Deployed acceptance remains required after setup:
  - Verify profile, all three planning documents and Current Learning values.
  - Generate a dated plan; change progress radio; confirm plan remains.
  - Save progress notes; confirm history and learning update.
  - Refresh and open a fresh browser session; verify all four areas.
  - Restart/redeploy the app; verify the same saved data again.
  - Generate the following day's plan; verify unfinished/missed learning
    continues and completed learning progresses.

## Scope

This remains the existing single-teacher prototype. PostgreSQL credentials are
server-side; no public database API or new teacher authentication is added.
Every browser session still accesses the same teacher data, as in the original.
Neon's free-tier limits and backup/restore retention should be reviewed before
production use. PostgreSQL is portable to another provider via DATABASE_URL.

Do not roll back to the old SQLite code after durable writes and assume that
those writes will be available locally. Preserve PostgreSQL as the data source
when fixing or rolling back application behaviour.
