# Teacher AI — Development Handoff

**Repository:** `oisin17/teacher-ai`  
**Current deployment:** Streamlit prototype (currently used through `teacher-ai-oisin.streamlit.app`)  
**Handoff date:** 2026-09-30  
**Target:** testable V1 by February 2027, with real classroom/placement testing beginning in January 2027.

## 1. Product vision

Teacher AI is an adaptive planning assistant for primary-school teachers.

The core idea is not simply "generate a lesson plan." Teacher AI should maintain an evolving understanding of the teacher, class, curriculum/plans, timetable constraints, available resources, and what actually happened in class. It should then use that information to generate the next useful plan.

The intended loop is:

1. Teacher sets up profile, programmes/resources, timetable and planning documents.
2. Teacher AI generates the day's plan.
3. Teacher teaches.
4. Teacher records what actually happened.
5. Teacher AI updates the class's Current Learning Position.
6. The next plan adapts to that reality.

The current prototype has now successfully demonstrated this loop at a basic level.

## 2. Product principles

### Teacher control
The teacher is always in control. AI should make useful planning decisions, but teachers must be able to amend any timetable item, lesson, resource or assumption and ask the AI to redo a specific part for a stated reason.

### Plan from evidence, not invention
Teacher-confirmed information is stronger than inferred information.

Priority of evidence should generally be:

1. Newer teacher-entered Actual Progress / explicit corrections
2. Teacher-confirmed Current Learning Position
3. Monthly plan
4. Yearly plan
5. General curriculum/programme knowledge

The monthly plan is intended coverage, not proof that learning has happened.

Never invent textbook page numbers, exercise numbers, story names, chapters or specific programme content that has not been supplied or made available.

### Adaptive, not repetitive
A completed lesson does not mean a whole subject/topic/unit is complete. Core recurring subjects should continue progressing.

Partially completed learning should sensibly continue or be revisited.

Learning that was not taught should remain outstanding and be rescheduled where appropriate.

Do not restart learning already known to be complete.

If the exact next focus is genuinely uncertain, use a short diagnostic/retrieval step rather than inventing certainty.

### Practical teacher UX
Plans should be concise, scannable and usable during a real school day. Avoid long scripts.

Prefer engaging, practical, low-preparation lessons where appropriate, but do not force games into every lesson.

Differentiation should be built into the lesson rather than appended as generic boilerplate.

## 3. Teacher/class context used for prototype testing

The prototype is currently being tested with a mainstream 5th Class of 27 pupils in an Irish primary-school setting.

Typical school day constraints:

- 08:50–09:10 Work It Out / morning work while roll is taken
- 09:10–approx. 09:20 Work It Out correction
- approx. 09:20 Morning Meeting
- 10:45–11:00 Lunch
- 11:00–11:15 Yard
- 12:30–12:45 Lunch
- 12:45–13:05 Yard
- 13:05–13:20 DEAR
- 14:20–14:30 Pack up / tidy up
- School finishes 14:30

Weekly fixed constraints currently used:

- Wednesday 11:45–12:15 Sport
- Friday 11:15–11:45 Sport
- Friday afternoon Art

These should be protected as real scheduling constraints.

## 4. Teacher Profile structure

The current Teacher Profile UI has these fields:

- Class
- Books & Programmes
- Classroom Resources
- Teaching Style
- Differentiation & Additional Needs
- Recurring Classroom Arrangements

The current prototype profile includes the following useful defaults/context.

### Books & Programmes

**Maths**
- Planet Maths — 5th Class
- Work It Out — 5th Class
- Times Tables Rock Stars
- Daily 10
- Work It Out is generally used as morning Maths practice

**English**
- Reading Zone — 5th Class
- Explore With Me — 5th Class
- Class novels where relevant
- Explicit morphology and spelling instruction
- RACE strategy for comprehension responses

**Gaeilge**
- Abair Liom — 5th Class
- Am Don Léamh

**SESE**
- Explore With Me — 5th Class
- Teacher-selected online and supplementary resources

Digital/online versions of core programmes may be available on the teacher laptop and projected to the interactive touchscreen.

Teacher AI should use the Monthly Plan and Current Learning Position to determine relevant programme content.

### Classroom Resources

Typical available resources:
- teacher laptop
- interactive touchscreen/whiteboard
- internet
- digital versions of core programmes where available
- mini-whiteboards / pupil whiteboards
- whiteboard markers
- dice
- counters
- playing cards
- number resources/manipulatives
- classroom library/books
- standard stationery/art materials
- printer/photocopier
- projectable online resources

Prefer little/no preparation or printing where possible.

### Teaching Style

Preferred characteristics:
- engaging
- active
- practical
- enjoyable with a clear learning purpose
- mini-whiteboards
- pupil-vs-teacher
- partner challenges
- short games
- quizzes
- movement
- mystery/problem-solving
- hands-on learning
- prediction
- discussion
- collaborative tasks
- interactive whiteboard use
- short competitions
- retrieval
- real-life contexts

Teacher-facing plans should be concise and practical.

### Differentiation

Support can include:
- worked examples
- reduced task quantity
- smaller instruction steps
- concrete materials
- visual supports
- vocabulary support
- sentence starters
- partner/teacher support
- extra modelling
- simplified starting points
- extra processing time

Challenge can include:
- reasoning
- explaining/proving
- unfamiliar applications
- independent challenges
- open-ended problems
- higher-order questioning
- meaningful early-finisher tasks

Do not simply give faster pupils more of the same work.

## 5. Planning hierarchy

Teacher AI should support both a monthly plan and an optional yearly plan.

- The **yearly plan** provides broad long-term direction, sequencing and coverage.
- The **monthly plan** should dominate day-to-day/monthly planning when present.
- The yearly plan should mainly act as background context, sequencing/coverage check, and a way to flag gaps or conflicts.
- It should not override a more specific monthly plan without a clear reason.

Teacher AI should eventually support two timetable modes:

1. Teacher uploads/creates their own subject timetable.
2. Teacher AI constructs a timetable using curriculum allocations plus fixed teacher constraints.

Teachers should always be able to edit individual timetable items.

## 6. Current app architecture

**Updated 2026-09-30 after the durable-persistence rollout.**

The existing UI and adaptive logic remain in `streamlit_app.py`. Database operations
now live in `persistence.py` and use managed PostgreSQL (the owner approved Neon
Free, in Frankfurt). The server-side `DATABASE_URL` is configured in Streamlit
Secrets alongside `OPENAI_API_KEY`; never put either value in this repository.

Dependencies currently listed in `requirements.txt`:
- streamlit==1.64.0 (the version tested locally and on the deployed app)
- openai
- pypdf
- python-docx
- psycopg[binary]>=3.2,<4

PostgreSQL is the sole production source for all four persistent data areas.
There is no SQLite fallback when PostgreSQL is unavailable. Short-lived TLS
connections, transactions and a single-teacher advisory write lock protect
saves and date corrections. Session state is updated only after a confirmed
database save.

The historical local `teacher_ai.db` is only a migration input. An available
legacy database is imported atomically into an empty PostgreSQL destination
once; migration never overwrites newer durable edits. The migration marker
lives in `storage_migrations`.

Tables/functions currently exist for:
- Teacher Profile
- Planning Setup
- Actual Progress
- Current Learning Position

Relevant persistence helpers currently in the code include:
- `save_teacher_profile(...)`
- `load_teacher_profile()`
- `save_planning_setup(...)`
- `load_planning_setup()`
- `save_current_learning_position(...)`
- `load_current_learning_position()`
- recent progress loading from `actual_progress`

On app startup, the app loads profile/planning/current-learning data into `st.session_state` if those keys do not already exist.

## 7. Historical persistence problem — resolved 2026-09-30

Although Teacher Profile and Planning Setup are already written to SQLite, the SQLite file is local to the Streamlit runtime.

A recent deployment/restart caused the saved Teacher Profile / Planning Setup to disappear and the app said:

> Please save your Teacher Profile first.

This indicates that local SQLite on the deployment is not adequate as durable persistent storage across Streamlit redeployments/restarts.

**This problem is now resolved on the deployed app.** The following describes the original failure.

Do not "solve" this by asking the teacher to re-enter data after deployment.

The durable solution should preserve:
- Teacher Profile
- Planning Setup
- Current Learning Position
- Actual Progress

across refreshes, sessions, app restarts and deployments.

Choose the simplest robust architecture for the current stage. Avoid adding unnecessary infrastructure. If an external paid/account-based database service is required, explain the choice and any cost/setup implications before locking the project into it.

## 8. Today's Plan — current working behaviour

The Today page allows the teacher to choose a school date and generate a daily plan.

A recent bug occurred where interacting with the progress radio reran the Streamlit page and the generated plan disappeared.

That was fixed by persisting the planning date in session state:

```python
if "planning_date" not in st.session_state:
    st.session_state["planning_date"] = date.today()

planning_date = st.date_input(
    "Which school date are you planning?",
    key="planning_date",
    format="DD/MM/YYYY"
)
```

The fix was committed on main as:

`636581b8d39b06da9fbff89ac731bc2d0b9327a8`

Commit message:
`Preserve planning date across progress widget reruns`

The plan remains protected by a date-match guard so a plan for one date is not incorrectly displayed under another date.

## 9. Current progress/adaptive loop

**Updated 2026-09-30 through Priority 2.** A generated plan now contains individual
lesson objects, used both for the displayed lesson and the saved progress snapshot.
The Today page restores the saved plan for the chosen school date from PostgreSQL.

- Each planned teaching lesson has Completed / Partially completed / Not taught.
- Statuses start unset; Mark all completed fills them in without saving progress.
- Every lesson has an optional short note (up to 300 characters).
- Save Today's Progress records the entire day once, with the exact original
  subject, topic, learning intention, time and lesson details per outcome.
- The progress snapshot and conservative Current Learning evidence save together
  in one transaction. No note or additional model call is required for the update.
- Teacher notes override conflicting statuses or planned intentions. Completed
  means this lesson only; partial work preserves the uncertain stopping point;
  missed learning remains outstanding and does not imply pupil difficulty.
- The next generation reads durable Current Learning and detailed recent progress.
- Historical whole-day records retain their original correction controls.
- New lesson records can be corrected individually in Progress History, including
  date correction without overwriting another day's record.

Current Learning retains the existing Maths / English / Gaeilge / SESE / Other
fields and remains editable. English strand labels such as Reading and Writing
map to English; Science, History and Geography map to SESE. See section 19.

## 10. Adaptive loop test already passed

A test progress note stated:

> Maths was fully completed. English was partially completed and we did not finish the final activity. Gaeilge was not taught because we had an assembly.

The saved Current Learning Position correctly became approximately:

- Maths: Fully completed today.
- English: Partially completed today; the final activity was not finished.
- Gaeilge: Not taught today due to assembly.

The next day's generated plan then behaved correctly at a basic level:

- English explicitly continued the unfinished activity.
- Maths recognised that the previous lesson was completed and moved forward rather than restarting.
- Gaeilge recognised that the prior lesson had not been taught and restored/rescheduled it.

This demonstrates that the core:

**Plan → Teach → Record reality → Update learning position → Adapt next plan**

loop works.

## 11. Progress granularity milestone

The former whole-day limitation is resolved for newly generated plans. Historical
rows do not contain precise lesson intentions and are not automatically converted.
Never invent lesson content to turn those old rows into granular outcomes.

The new form is designed for a quick bulk-complete-and-exceptions workflow.
Actual teacher timing/usability feedback is still needed to establish whether
real end-of-day recording consistently takes 30–60 seconds. Do not describe that
speed as measured from the automated checks.

## 12. Current planning-generation rules

The plan-generation prompt already receives:
- Teacher Profile
- Planning Setup
- timetable text
- monthly plan text
- yearly plan text
- Current Learning Position
- recent Actual Progress

Important existing rules include:
- Current Learning Position and newer Actual Progress override monthly-plan assumptions
- completed specific lesson != whole subject/topic complete
- Maths/English/Gaeilge should continue progressing
- partial work should continue/revisit
- not-taught work should be rescheduled where appropriate
- do not restart known-completed learning
- if next focus is uncertain, use a brief diagnostic/retrieval step instead of fabricating specifics
- monthly plan is intended coverage, not proof of learning
- teacher-confirmed Current Learning is strong evidence unless newer progress updates it
- perform a final validation against Current Learning Position before returning the plan

## 13. What not to do

- Do not rebuild working features from scratch without a reason.
- Do not replace working adaptive logic simply for architectural neatness.
- Do not make large speculative refactors while a smaller safe change will solve the current issue.
- Do not invent programme pages/content.
- Do not make the teacher copy/paste code as part of the normal development workflow.
- Do not rely on Streamlit session state as durable data storage.
- Do not treat an overall "Completed" status as meaning an entire curriculum topic is finished.
- Do not polish visual design ahead of core reliability.
- Do not add authentication/multi-user complexity before it is required for the next test milestone.

## 14. Preferred development workflow

The owner is a working primary teacher and product owner.

For development:

1. Inspect the existing repository first.
2. Preserve working behaviour.
3. Make small, safe commits.
4. Test the deployed Streamlit app after meaningful changes when browser access is available.
5. Diagnose and retest rather than asking the owner to shuttle code back and forth.
6. Ask the owner for a manual test only when teacher judgement, credentials, permissions or genuinely human acceptance testing is needed.

The owner should primarily make product/teaching decisions, not perform repetitive developer plumbing.

## 15. Current priority order

### Priority 1 — Durable persistence — completed 2026-09-30

Implemented and deployed through PR #1. See section 18 for verification and remaining scope.

Make Teacher Profile, Planning Setup, Current Learning Position and Actual Progress survive Streamlit restarts/redeployments.

Then explicitly test:
- enter/save profile
- enter/save planning setup
- enter/save current learning
- save progress
- refresh
- start a new session if possible
- redeploy/restart
- verify all data remains

### Priority 2 — Better progress granularity — implemented 2026-09-30
Implemented through PR #2. See section 19 for the UI, data model, tests and remaining acceptance scope.

### Priority 3 — Planning quality
Improve specificity of next-step planning once the system knows exactly what was completed.

Avoid vague output such as "likely focus" when sufficient evidence exists.

### Priority 4 — Resource generation
Allow generated lessons to produce useful teacher/pupil resources with the same class context and minimal preparation.

### Priority 5 — UX/reliability
Reduce friction, handle errors cleanly, preserve state correctly, and make the product feel dependable.

### Priority 6 — January placement testing
Have a stable V1 ready for a placement teacher to use in January 2027 and collect teacher/inspector feedback.

### Priority 7 — February V1
Incorporate placement feedback and have the V1 ready by February 2027.

## 16. First task for a new Work session

**Updated:** Priorities 1 and 2 are implemented. Inspect the current code and
sections 18–20. Finish the live dated-monthly acceptance check once the owner
confirms the existing plan dates and supplies the actual October document; then
continue with Priority 3 (planning quality). The original
persistence brief below is retained as acceptance context, not an outstanding task.

Start by inspecting `streamlit_app.py` and the current persistence helpers.

Confirm the cause of data loss across Streamlit redeployments, then propose and implement the smallest durable persistence solution appropriate for the prototype.

Preserve all currently working Today-plan/adaptive-loop behaviour.

Before adding external infrastructure that requires a new account, paid service, secret or irreversible architectural commitment, explain what is needed to the owner.

After implementation, test the persistence behaviour through the deployed app as far as browser access allows.

## 17. Definition of success for the next milestone

The next milestone is complete when:

- Teacher Profile survives refresh/restart/redeploy
- Planning Setup survives refresh/restart/redeploy
- Current Learning Position survives refresh/restart/redeploy
- Actual Progress survives refresh/restart/redeploy
- generating Today's Plan still works
- changing the progress radio does not make the plan disappear
- saving progress still updates Current Learning Position
- the next day's plan still adapts correctly

Do not move on to major new features until this foundation is reliable.


## 18. Durable persistence rollout and verification — 2026-09-30

- PR #1 (`codex/durable-persistence`) was merged at
  `7df71b22095b961a1583d7fbca8067730a818449`.
- Streamlit was pinned to its already-running/tested version 1.64.0 at
  `327ff008597f6620eef9f58f71c7f07f6a0769fd`, exercising another redeployment.
- A pre-cutover JSON backup was downloaded from the working deployed SQLite app.
  It contains all three saved context documents and every Actual Progress row.
  Classroom data and credentials were not committed to GitHub.
- The deployed PostgreSQL export matched that backup exactly after cutover.
- Live saves were checked for Teacher Profile, Planning Setup, Current Learning
  Position and the existing dated Actual Progress record. The existing status
  and teacher notes were reused; no fictional new teaching record was created.
- Saving Planning Setup with no new uploads retained all existing document text.
  Unreadable replacement uploads now leave saved documents untouched.
- A generated plan remained visible when the progress radio changed.
- Saving the existing progress notes reported a successful Current Learning
  update. The next-day plan explicitly continued unfinished English and restored
  Gaeilge missed because of assembly; its Maths planning recognised previous
  completion. The AI prompts and model were not rewritten in this rollout.
- The teacher-confirmed Current Learning values were returned to their original
  saved values after the update test.
- Refresh, separate browser sessions and the subsequent dependency redeployment
  were tested. The final exported JSON matched the pre-cutover backup exactly
  across all four data areas.
- 14 local storage/Streamlit AppTest checks passed. GitHub Actions passed the
  same suite plus 10 storage checks against PostgreSQL 16, including concurrency,
  migration rollback, backup roundtrip and overwrite refusal.
- CI runs on pushes and pull requests using a disposable local PostgreSQL
  service. Test credentials are not production credentials.

### Backup and recovery

The deployed app has **Saved data backup** export and restore controls.
Restore validates the entire backup, writes atomically and refuses to overwrite
any nonempty durable database. If automatic legacy migration cannot access
SQLite after a restart, a downloaded backup can restore an empty database.
See `PERSISTENCE_SETUP.md` for the rollout/recovery instructions.

### Scope and remaining work

- This remains the existing single-teacher prototype. All sessions access one
  teacher's saved data; no authentication or multi-user system was added.
- At the end of Priority 1, generated Today's Plan text remained session-based.
  Priority 2 now also saves structured day plans in PostgreSQL (see section 19).
- Local AppTest uses mocked AI responses; live generation/update were separately
  exercised through the deployed app.
- Persistence does not resolve coarse whole-day progress or guarantee every
  generated lesson's quality/timing. Continue with the Current Priority Order.
- Neon Free is the selected prototype service; no paid upgrade was made.
  Provider limits and backup retention still need review before a production launch.



## 19. Lesson-level progress rollout — 2026-09-30

### V1 UI and storage

PR #2 adds the compact lesson form: Mark all completed, one status per lesson,
optional short note, and one Save Today's Progress. Bulk completion submits
browser drafts to a callback so previously typed notes survive; it does not save
teaching outcomes. Unset statuses block a save.

The generation prompt retains the existing model and planning rules. A strict
JSON response now supplies a timetable overview and individual lesson objects.
The displayed headings, intentions and lesson details are rendered directly from
those objects, so no second extraction model guesses what was planned.
`lesson_progress.py` validates the objects and supplies stable IDs and conservative
Current Learning projection. Storage remains in `persistence.py`.

Additive tables (no new service, secret, authentication or paid infrastructure):

- `day_plans`: school date → structured plan JSON, including plan ID and lesson IDs.
- `lesson_progress`: Actual Progress daily record ID → original plan identity,
  overview and all lesson snapshots with recorded status/note.
- `actual_progress` remains the daily container and preserves historical rows.

Progress and Current Learning commit atomically under the existing advisory lock.
Current Learning preserves prior teacher context and replaces its generated,
dated evidence section from durable lesson history. Each entry states the actual
planned intention and selected outcome, with the teacher note quoted verbatim
and authoritative. No lesson completion is promoted to whole-unit completion;
no partial stopping point is guessed. The next AI plan determines the next
appropriate learning from this evidence and the existing monthly/yearly context.

Retrying does not duplicate rows or learning evidence. Corrections recalculate
the evidence and remove obsolete outcomes/dates. Explicit Current Learning edits
become teacher-confirmed context. Regeneration is disabled once progress exists;
stale plan IDs after another session's regeneration cannot save against a new
plan. Refresh restores submitted outcomes and the original lesson snapshot.
Unsaved form inputs remain drafts, and a fresh session may require selecting the
school date again.

Backup format 2 includes plans and lesson snapshots. Format 1 restore remains
supported. Restore still validates everything first and refuses a nonempty store.
See `PERSISTENCE_SETUP.md` for details.

### Validation and live checks

- 30 local checks pass: the original persistence checks plus new storage and
  Streamlit AppTest coverage for mixed outcomes, no-note updates, bulk completion,
  draft-note preservation, unset statuses, date guards, refresh/fresh sessions,
  stale plans, repeated subjects/English strands, corrections, concurrency,
  additive initialization, atomic rollback and backup compatibility.
- GitHub Actions runs the same suite plus 20 checks against PostgreSQL 16.
  The implementation and hot-reload fix passed both test stages.
- A deployed hot reload initially reused the previous cached storage initializer.
  Initialization now takes an explicit schema version (currently 2), forcing the
  additive table creation even when Streamlit preserves its resource cache.
  The deployed app then started successfully with the existing historical row.
- The live app generated a six-lesson plan for 2026-10-01 using the real model and
  existing saved teacher context. The per-lesson form was visually checked.
- Refresh restored the same six lessons from PostgreSQL without a new model
  call, and discarded the unsaved test form inputs. The format-2 export contained
  that saved plan; all four original data areas matched the pre-rollout backup
  exactly (profile, planning documents, Current Learning and the one old record).
- Live unset-status validation, Mark all completed, English/Gaeilge exceptions
  and short notes were exercised. Draft test outcomes were discarded rather than
  saving fictional future teaching into the teacher's Actual Progress.
- Full progress save → durable lesson history → Current Learning → next generation
  inputs is covered by AppTest and storage tests. Live saving of a genuine new
  lesson record remains a classroom acceptance check; do not claim that test
  was performed against production data during this rollout.

### Next work

Continue Priority 3 (planning quality), particularly exact programme/text
specificity when supplied, correct subject/strand sequencing and timetable
coverage. Do not weaken persistence or substitute speculative completed-topic
assumptions for the new granular learning evidence. Get teacher feedback on the
form's actual 30–60-second use in normal end-of-day recording.


## 20. Dated Monthly Plans — 2026-09-30

PR #3 adds the smallest date-aware Monthly Plan V1. The existing teacher profile,
yearly/timetable documents, Current Learning, progress projection and generation
rules are preserved. No new account, database, secret, authentication or paid
infrastructure was introduced.

- `monthly_plans` stores ID, title, original filename, extracted text and explicit
  inclusive PostgreSQL start/end dates. Selection uses those stored dates only.
- Upload detection is a conservative deterministic suggestion, with evidence and
  editable dates/title. Explicit teacher confirmation is required before save.
- Multiple plans remain saved; choose an existing entry to edit its dates or
  replace its document. Inclusive overlaps are rejected atomically under the
  existing advisory transaction lock, including concurrent saves.
- The `dated_monthly_v1` migration copies the old generic document verbatim into
  “Existing saved plan — confirm dates”, with null dates. The original Planning
  Setup JSON is retained. The teacher can confirm dates without uploading again.
- Today identifies the matching plan and coverage. Missing confirmed coverage
  blocks new generation; there is no generic/adjacent-month fallback.
- New day plans and lesson snapshots retain their original Monthly Plan ID/title/
  dates. Older saved day plans display an explicit source-not-recorded caption.
- Backup format 3 includes all Monthly Plans. Formats 1/2 remain restorable into
  an empty database and migrate generic documents into a pending entry.

### Tests and deployment

41 local automated tests pass, with the storage suite also passing against real
PostgreSQL 16 in GitHub Actions. Checks cover September 30 → September and October
1 → October (2026), inclusive bounds, year differences, missing coverage, misleading
filenames, corrected suggestions, explicit confirmation, concurrent overlap
rejection, legacy preservation/idempotence, backup compatibility, monthly source
retention and the existing adaptive loop. AppTest exercises Word upload → corrected
date confirmation → stored plan → date selection → mocked generation.

Live testing caught a Streamlit hot reload retaining the old imported storage
module and cached initializer. The app now reloads a legacy module lacking the
new API and uses initialization cache version 4. The fix was retested live and CI
passed. The deployed app now shows the migrated pending plan and offers confirmation
without reupload. A Word copy of the existing saved document was uploaded, its
suggested dates inspected, and saving without checking confirmation was rejected.
The temporary upload was removed without saving an extra plan.

The post-migration format-3 export matched the previous format-2 export exactly
for Teacher Profile, Planning Setup, Current Learning, Actual Progress and saved
day plans. The pending Monthly Plan text also matched the old generic text exactly.
Live September 30 and October 1 both correctly report no confirmed coverage; on
October 1 the previous six-lesson day plan is retained and explicitly marked as
predating recorded monthly sources. New generation is disabled, avoiding fallback.

### Remaining live acceptance check

The original document names September but has no explicit year and includes Irish
fortnight date headings. Its dates are deliberately left unconfirmed for the owner.
No genuine October plan has been supplied. Do not fabricate October coverage or
confirm inferred dates as teacher-approved. The complete real-model two-month
browser generation check requires the owner's confirmed September range and actual
October upload/range. Automated boundary and upload-to-generation checks have passed;
do not describe that remaining live confirmation/generation check as completed.
