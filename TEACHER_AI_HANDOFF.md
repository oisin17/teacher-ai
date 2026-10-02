# Teacher AI — Development Handoff

**Repository:** `oisin17/teacher-ai`  
**Current deployment:** Streamlit prototype (currently used through `teacher-ai-oisin.streamlit.app`)  
**Handoff date:** 2026-10-02  
**Target:** testable V1 by February 2027, with real classroom/placement testing beginning in January 2027.

**Latest completed milestone:** hardening and multi-user readiness review; safe
diagnostics and fixes deployed. Resources for Tomorrow V1 remains complete.
165 automated tests pass; 63 persistence tests pass against PostgreSQL 16 in CI.
See TEACHER_AI_HARDENING_REVIEW.md and the final review section below. Prior
Resources for Tomorrow acceptance/data/restore evidence remains preserved.

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
sections 18–21. The owner confirmed September and October 2026 plans;
month-transition carryover is implemented. Continue with Priority 3 (planning quality). The original
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

### Confirmed dates and live boundary check — 2026-10-01

The owner confirmed that the plans are for 2026 despite stale 2025 document
headings. The migrated original document was retained without reupload and
confirmed for September 1–30, 2026. The actual supplied October Word document
was uploaded, its suggestions shown and dates explicitly confirmed for October
1–31, 2026. Live September 30 selects September; October 1 selects October.
Real October generation is covered in section 21.


## 21. Month transition and carryover — 2026-10-01

PR #4 adds a first-use review when a confirmed Monthly Plan follows an earlier
confirmed period. AI suggests at most six specific unfinished items from recent
prior-period Actual Progress and Current Learning. Suggestions remain drafts until
the teacher confirms, edits/unchecks them, adds items manually, or chooses Nothing
to carry over. The decision is stored once per Monthly Plan ID.

Additive PostgreSQL tables `period_reviews` and `carryover_items` use the existing
advisory write lock. No new infrastructure or credentials were added. Review and
items save atomically; concurrent confirmation and stale monthly edits are guarded.
Outstanding items supplement the new month coverage without requiring all of them
on day one. Generated lessons retain stable `carryover_ids`; an explicit completion
checkbox and Completed lesson status close an item. Partial/not-taught leaves it
outstanding. Corrections rederive linked closures from durable lesson history.
Manual Mark complete/Remove controls handle learning resolved elsewhere; Reopen
and Restore make those manual actions reversible. Removal retains the record.
Backup format 4 preserves reviews, items and linked progress; formats 1–3 remain
compatible. Existing teacher context and whole-day history are unchanged.

50 local automated checks pass, including review confirmation and date guards,
concurrency, durable no-repeat reviews, mixed/linked outcomes, corrections, manual
completion/reopening/removal/restoration, backup roundtrip and the original loop.
Live acceptance results are recorded below.

### Live acceptance

The deployed October first-use review suggested exactly the unfinished English
final activity and Gaeilge missed due to assembly, quoting the existing genuine
September 30 notes. Both were confirmed and saved. Manual complete → reopen and
remove → restore were exercised; both items ended outstanding. Refresh after
redeployment preserved the confirmed review without prompting again. Real October
generation restored from PostgreSQL and displayed explicit carryover completion
checkboxes. An observed unsupported prior-task assumption prompted stricter final
validation: identify an unknown missed task before linking; new-month topic alone
is not evidence of addressing carryover. A code check also drops a completion
link unless lesson details explicitly quote that confirmed item’s learning text;
same-subject new learning alone cannot attach a completion control.

The downloaded format-4 export matched the pre-rollout backup exactly for Teacher
Profile, Planning Setup, Current Learning and Actual Progress. It included one
period review and two outstanding items. No fictional teaching outcomes were
saved. Full linked completion, partial/not-taught persistence and correction
reopening are tested with isolated automated data; a genuine classroom lesson
progress save remains teacher acceptance work.

## 22. Protected Thursday Singing — 2026-10-01

The owner confirmed external Singing every Thursday, 14:00–14:30, independent
of Monthly Plan coverage. Teacher Profile now has a durable `thursday_singing`
checkbox alongside the existing recurring-arrangements text. Thursday pack-up
moves to 13:50–14:00, replacing the usual 14:20–14:30 slot; school ends at 14:30.
Generation reloads the durable profile, so another session's new constraint is
not missed. The prompt protects the external block and excludes it from generated
curriculum lessons/progress. `timetable_constraints.py` validates Thursday lesson
and overview ranges before saving: no normal lesson/routine can run beyond 14:00,
Singing must occupy 14:00–14:30, and pack-up must occupy 13:50–14:00.
Normal lessons finish by 13:50 so they cannot overwrite pack-up either. Invalid
output leaves the previous plan unchanged. Other weekdays and existing weekly
arrangements are preserved. No new table, service or backup format is needed.

55 local tests and PostgreSQL CI passed. Tests cover valid Thursday scheduling,
overlapping lessons/routines, missing Singing/pack-up, other days, disabled
constraints, and actual Streamlit generation rejecting conflicting output without
replacing the saved plan. The live owner profile was saved with the checkbox and
an appended Thursday exception while retaining existing daily/Sport/Art text.

The live October 1 plan was regenerated and validated: literacy/writing ends
at 13:50, pack-up is 13:50–14:00, Singing is 14:00–14:30, with no Singing
curriculum lesson/progress row and no fictional teaching outcomes saved.

## 23. Item-level Monthly Plan progress — 2026-10-01

The owner approved stable item records, exact lesson links and teacher-accepted
outcomes. Additive `monthly_learning_items` and `monthly_item_updates` tables
retain original monthly text and historical lesson references. Items have UUIDs,
subject, description, quoted document source, fingerprint, discrete/recurring/broad
type, revision and recoverable archived state. PostgreSQL write locks and item
revisions protect edits; a changed document requires reviewing replacement items.

Planning Setup offers explicit AI extraction, editable suggestions, split, merge,
archive/restore, subject progress totals and manual outcome/remaining-work corrections.
Extraction is not past-progress inference. Split/merged replacements get new IDs;
original items remain archived for historical references. Merges preserve prior
unfinished evidence and migrate shared carryover references without duplicate priorities.

Generated lessons use exact `monthly_item_links` IDs plus addressed scope. Unknown,
archived, completed or unrelated-period IDs are rejected before saving. Existing
saved plans without these links remain usable and are not retrospectively mapped.
Generation receives exact item states/remaining learning alongside existing context.

Daily progress retains bulk completion and optional notes. Only linked items appear
in collapsed exception controls. Completed lessons alone set In progress, never
whole-item completion (including discrete items). Whole-item completion requires
an explicit checkbox. Optional AI note mappings remain drafts, quote teacher notes,
and are accepted only by Save; model failure leaves conservative/manual controls.
Partial notes retain exact remaining learning; untaught work does not erase prior
completion. Explicit mixed item outcomes can complete three items while leaving the
fourth unfinished. Progress, item events and Current Learning commit atomically.
Corrections replace that record's events, replay states, and remove stale evidence.

Carryover may reference the same monthly item. Item completion closes its linked
carryover; manual carryover completion/reopen updates the same underlying item.
Removing carryover changes scheduling priority only. Existing free-text carryover
is preserved and can be explicitly linked by the teacher. Transition reviews offer
unfinished prior items for confirmation, never automatically carrying over all items.

Backup format 5 includes item definitions and updates; formats 1–4 remain supported.
Restore validates references, remaps restored progress IDs and refuses nonempty stores.
No new infrastructure, credentials, authentication or paid service was added.

Live extraction initially rejected AI-reproduced source quotations. Extraction now uses numbered original document lines: AI selects the line index, and the app copies its text verbatim. Live acceptance and final test results will be appended after deployment verification.

### Item rollout verification

70 local automated tests (plus four subtests) and PostgreSQL 16 CI pass. Additional
checks cover newer explicitly accepted outcomes reopening an item, immutable
historical references after merges, rollback on unverifiable sources, and correction
of linked carryover closures. Daily AI mapping is tested as an unsaved draft until
teacher acceptance, including explicit whole-item completion confirmation.

The deployed app extracted and saved reviewed learning items from both existing
confirmed September and October 2026 documents, without reupload. October History
was reviewed live: an overlapping summary was split into events and responses,
two effects suggestions were merged, and a redundant broad summary archived.
September's digital-learning suggestion was corrected from Religion to Other.
No past teaching completion was inferred; all new items remained Not started.
The live date boundary still selects September for September 30 and October for
October 1. The existing October transition decision is retained without repeating
the review. Final live generation/refresh and backup results follow below.

Mixed partial notes addressing several linked items now trigger a draft exception review before the first durable save. Suggestions remain editable and whole-item completion still requires explicit confirmation. AI failure retains conservative/manual saving. The isolated AppTest verifies the first Save creates no teaching record, then teacher acceptance saves exact completed/unfinished items.


### Final verification after interrupted-run recovery

PR #5 was already merged and the reviewed item sets plus linked October 1 day
plan already saved before the interruption. Recovery inspected current main,
all branches/PRs, deployed UI and local outputs before continuing only unfinished
verification. No extraction, item review or saved day-plan generation was repeated.

The real October 1 plan restored in a fresh browser and after refresh: five lessons
with nine exact monthly-item links, pack-up 13:50–14:00 and protected external
Singing 14:00–14:30. A live unsaved History note (“Causes finished; events and the
final effects activity unfinished.”) produced Completed for causes and In progress
for events/effects with specific remaining text. Every whole-item confirmation
checkbox remained unchecked. Refresh discarded those fictional test drafts.

The final format-5 production export matched the pre-item rollout backup exactly
for Teacher Profile, Planning Setup, Current Learning, Actual Progress, both original
Monthly Plans, period reviews and existing carryover. It contained 300 item records
(146 September, 154 October including four archived originals), no item outcome
events, and only the one pre-existing Actual Progress record. The linked October
1 plan is the intentional day-plan change. No fictional teaching outcomes were saved.

An additional atomic guard prevents the same underlying unfinished item becoming
duplicate outstanding carryover in another period; transition suggestions also
exclude already outstanding references. All 70 local tests passed on the final
code, and GitHub Actions run 36856758087 passed both the full Streamlit/regression
suite and real PostgreSQL 16 storage/concurrency tests. Backup/restore and complete
progress → item state → Current Learning → next-generation inputs are verified
with isolated automated data. A genuine classroom progress save remains owner
acceptance work; it was not simulated in production.


## 24. Approved October regrouping — applied 1 October 2026

Code commit: 953b56d1955e486e99524373ab2d0806f460162e.
The owner approved October_2026_Item_Regrouping_Review.md, including E14 held
for teacher clarification and immutable source quotations with separately confirmed
display corrections. The deployed reviewed-file importer applies an atomic,
revision/status/event/carryover-checked update under the existing database lock.

The fresh format-5 backup was checked before application. All October items were
Not started and no item outcome events existed. Production now retains all 154
old October IDs and adds 49 replacement scopes, with 106 active reviewed items:
English 27, Gaeilge 24, Science 5, Visual Arts 6; History 9, Geography 8, Maths 9,
Music 6, Drama 3, PE 4, SPHE 3, Religion 1, Other 1. Replacements use
replacement_from provenance, not outcome inheritance. Archived historical IDs
and October 1 lesson snapshots remain intact and usable for progress recording.

E14 ID 44e32344ff1c46d597729e54d3ec045d has requires_clarification=true.
Generation excludes it and explicitly instructs the model not to prioritise the
ambiguous recount wording from the original document. The review editor can clear
the flag after teacher clarification. Display corrections require an explicit
confirmation and never edit source/sources. Original source evidence is immutable.
Extraction instructions now favour independently teachable/assessable scopes, not
individual games, worksheet steps, repetition or delivery methods.

A bookkeeping error in the review's History appendix swapped the archived summary
and active Famine project. This was disclosed to the owner before application:
7e026f39085640f7817c75497c1f1832 remains archived; the active project
abe9d1d29b784e4b9f585efb97fe2f1c remains active as H08. The approved English,
Gaeilge, Science and Art mappings were unaffected.

Carryover references are reconciled: one-to-one outstanding references follow the
replacement; split/removed/completed references retain prior evidence/state as
free text pending explicit teacher scope selection; duplicate shared priorities
are removed recoverably. The owner's two existing free-text carryover entries
required no changes.

The post-application export matched the fresh backup exactly for every other
saved area, including Current Learning, Actual Progress, Monthly Plans, carryover,
period reviews, item outcome events and day plans. September item metadata was
unchanged. All original item source quotations and historical IDs were preserved.
No fictional teaching outcomes were saved.

75 local unittest tests pass. GitHub Actions run 36862135753 succeeded, including
real PostgreSQL persistence/migration/concurrency checks. New tests cover stale
revisions/progress, immutable sources, historical links, no completion transfer,
carryover reconciliation, held items and display corrections.

Live browser generation for Friday 2 October used the regrouped scopes and saved
a new day plan without replacing October 1. Examples: Art Angle City links A03
28af726eb3d643fb9c94dd59e6a5511a; procedural text features links E11
25b49c7eb8a84eaca3909d7642b37f78; paired food conversations links G02
fb095e38b66d41e9b0f991bc1f531985. Friday Sport remains 11:15–11:45 and
pack-up 14:20–14:30. No progress-save action was performed in this live check.


## 25. Planning quality rubric — implemented; final live verification pending (1 October 2026)

PR #6 merged the additive V1 planning quality gate:
https://github.com/oisin17/teacher-ai/pull/6

The day-plan JSON now stores planning_quality metadata with Pass / Revise /
Blocked / Unchecked, version, initial/final findings, revision count, extra model
calls, check/repair timing, generation timing, carryover decisions and context
digest. Only Pass can replace the saved plan. Original plans without phases or
quality metadata remain readable; format-5 backups preserve the new metadata.
No new database table, infrastructure, account or credential.

Code checks run first: selected confirmed Monthly Plan/date/provenance; explicit
Daily/weekday protected timetable blocks; school bounds, lesson/overview overlaps
and matching slots; structured positive phase minutes summing to the clock slot;
Friday afternoon Art; Thursday 13:50–14:00 pack-up and 14:00–14:30 external Singing;
active, current, non-completed, non-held Monthly Plan links and valid outstanding
carryover IDs. Semantic hard-block codes cannot be downgraded by the model.

One compact whole-day semantic review checks alignment, progression, timetable,
lesson quality, practicality, specificity and usability. At most ONE targeted
whole-plan repair is allowed, followed by code checks and a semantic recheck.
No evaluation writes Actual Progress, Current Learning, item outcomes, carryover
state or period reviews. Saving rechecks the evidence digest under the existing
database lock; changed teacher evidence rejects the candidate and preserves the
previous plan. Feedback is optional collapsed "Planning checks"; no visible score.

The semantic rules preserve short retrieval, reasoned scheduling deferral of
carryover, identified-prior-task continuation where the exact prior task is
unknown, and addressing PART of broad/recurring objectives without claiming their
completion. Unsupported named programme content, contradiction of unfinished
learning, main-focus repetition of explicitly completed learning and invalid scope
remain hard blockers. Optional resources need usable fallbacks.

Live rollout exposed:
- AI phase arithmetic can remain wrong after repair. Inside the single repair,
  code compiles only modest residual discrepancies (<=25% of slot duration) to
  positive whole minutes, preserving activities and clock slots. Larger discrepancies
  remain blockers. phase_adjustments retains before/after allocations and semantic
  review still must find delivery practical.
- Retyped review quotes could be unverifiable. Production review now selects
  schema-constrained evidence IDs from one annotated packet. These resolve to exact
  original passages for readable metadata. IDs are deduplicated and capped at 900;
  long texts are exact contiguous passages. This adds no extra model call.
- The reviewer needed exact saved item source quotations to recognise known titles,
  and explicit rules against confusing partial broad coverage with full completion
  or demanding invented detail for unspecified carryover.
- Canonical carryover source labels are rendered from explicit IDs. They are
  references ONLY: semantic review independently checks that actual phases resume
  the task, and blocks unrelated teaching. Labels do not authorise completion.
- Technical/malformed reviews remain Unchecked. Safe diagnostics expose only our
  validation reason or exception class, never credential/API error bodies.

Read-only browser diagnostic: append rubric_probe=read-only. Once a selected date
has a saved structured plan, "Test conflicting candidate without saving" moves a
COPY into a protected slot, runs the same bounded gate, and reports whether the
original saved plan is unchanged. It has no save action.

Validation: 96 local tests passed on the final implementation. GitHub Actions run
36875414520 succeeded, including PostgreSQL persistence/migration/concurrency:
https://github.com/oisin17/teacher-ai/actions/runs/36875414520
Tests cover all blocker categories, code-before-AI ordering, the one-repair bound,
phase budgets, exact evidence references, carryover deferral, retrieval, reviewer
failure, previous-plan preservation, unchanged progress, stale evidence, metadata
backup round-trip and the read-only diagnostic.

Live observations BEFORE the browser environment disconnected:
- 30 September displayed September's confirmed 2026 plan; genuine progress already
  saved prevented regeneration. 1 October displayed October's confirmed plan.
  Existing first-use review stayed reviewed and the two real carryovers remained
  outstanding (unfinished English final activity; Gaeilge missed due to assembly).
- Thursday and Friday generation attempts reached the gate. Invalid timing,
  references or unresolved semantic findings were Blocked/Unchecked and preserved
  the previous saved plans. Observed failed-attempt check/repair overhead was
  roughly 6–16 seconds and 1–2 extra model calls (generation time excluded).
- A fresh pre-rollout live backup matched the preceding export exactly. No fictional
  teaching outcomes or item/carryover completion actions were saved.

IMPORTANT: final successful-plan browser validation and its requested metrics are
NOT complete. After deploying the final evidence-reference/rule fix, a new Thursday
generation was started; the browser transport disconnected while attempting Friday.
The browser environment then returned environment_offline (409). Do not assume the
pending Thursday or Friday operation did/did not save. Inspect current saved plans
and export a fresh backup before doing further live writes. No successful-plan
average extra-call/latency measurement is available yet.

Next safe work:
1. Inspect current main, saved October 1/2 quality metadata and any pending results;
   do not regenerate a successful plan unnecessarily.
2. Finish live Thursday Singing / Friday Art and English/Gaeilge carryover checks
   against the real 2026 evidence, without saving fictional teaching progress.
3. Run the read-only deliberately conflicting candidate diagnostic; verify revised
   or blocked, original plan unchanged.
4. Export and compare all non-day-plan backup areas against the pre-rubric backup;
   report actual successful-plan revision/call/latency metrics and screenshot proof.
5. Update this section with observed completion rather than treating automated
   coverage as completed browser testing.

Local pre-rubric export was /workspace/scratch/teacher-ai-before-planning-rubric.json.
It contains the unchanged original October 1 plan 10ed7146968a4a04ad38dc42d6b1d6e9
and October 2 plan 20c6ed2c5c1842f397ea9e78b6b51e55, one genuine September 30 progress
record, 349 historical learning item records (106 active October), zero monthly
item outcome updates, and two outstanding free-text carryovers. Preserve all of
these historical IDs/evidence. The transient workspace may be inaccessible after
the environment failure; the GitHub implementation/CI/handoff are durable.

### Final rubric acceptance recovery — 1 October 2026

Inspected main and its latest commits, this handoff, deployed saved plans, rubric
implementation and regression tests before continuing. No implementation was
repeated. Tested code head: `4e474fed837c02225a23de1add7db746d00c59c1` (explicit
start/end intervals for all timed routines; QUALITY_MODULE_VERSION 18).
The live Friday rerun now has an explicit 09:20–09:35 Morning Meeting, with
English beginning at 09:35. Current-release behavior is verified in production;
the app does not expose a runtime Git SHA, so an independent exact deployed-SHA
attestation was not available from the public UI. Do not conflate the later
documentation-only commit with the code version exercised in these checks.

103 local unittest tests passed. GitHub Actions run 36910872621 on that exact
code head succeeded, including the Streamlit regression suite and real
PostgreSQL 16 persistence, migration and concurrent-save checks:
https://github.com/oisin17/teacher-ai/actions/runs/36910872621

The previously accepted Thursday plan was restored and inspected, not regenerated:
`cb2e0772b4ff457c9906712ad34d25e6`. English identifies and resumes its actual
unfinished final activity. Gaeilge identifies the unspecified missed task before
continuing it. History phases now include pupil research matching the linked item.
Pack-up remains 13:50–14:00 and external Singing 14:00–14:30, with no Singing
teaching/progress lesson. Its saved metadata records one whole-plan revision,
three extra AI calls, 64.63 seconds for checks/repair and 24.85 seconds for initial
generation (89.48 seconds combined AI stages, excluding storage/UI time).

Friday 2 October was rerun live and accepted as
`fdc5c01aed244cf386bf16de31347b3c`. Overview and all lesson phase totals pass
current code checks against the exported real context. Sport is overview-only
11:15–11:45; Art is an actual 60-minute teaching lesson 13:20–14:20, followed by
14:20–14:30 pack-up. English 09:35–10:15 resumes the unfinished final activity.
Gaeilge 11:45–12:25 identifies and resumes the assembly-missed task. The first
candidate assumed a food-topic lesson was the unknown missed task; semantic review
blocked this and the single repair corrected it. Final findings are empty and
both carryovers are addressed in planning, still outstanding in saved learning.
One whole-plan revision, three extra AI calls, 61.99 seconds checks/repair and
20.39 seconds initial generation (82.38 seconds combined AI stages, excluding
storage/UI time). These two successful plans are observations, not a benchmark
or guaranteed response time. Browser rendering/storage waits were additional and
were not instrumented as an end-to-end latency measurement.

The live 30 September → 1 October transition was rerun in one session: September
coverage selected on 30 September and generation disabled because genuine progress
already exists; October coverage selected on 1 October, existing reviewed transition
retained and both original English/Gaeilge carryovers present. No transition
confirmation, item completion or teaching-progress action was submitted.

Read-only diagnostic moved a COPY of Thursday's English lesson into protected
Yard 11:00–11:15. Code blocked protected overlap, phase duration and the unmatched
overview slot before semantic review. The bounded whole-plan repair returned Pass:
one revision, two extra AI calls, 36.95 seconds checks/repair. The candidate was
NOT saved and the diagnostic explicitly reported “Previous saved plan unchanged:
True”. The original Thursday plan ID remains intact.

The final live format-5 export was compared structurally, field by field, with
`/workspace/scratch/teacher-ai-rubric-resume-baseline.json`, the fresh pre-rubric
backup whose original day-plan IDs match the prior handoff. Every non-day-plan
area matches exactly: Teacher Profile, Planning Setup, Current Learning, Actual
Progress, monthly learning definitions, monthly item updates, period reviews,
carryover and both original monthly documents. It retains 349 item records,
zero item outcome events, the one genuine Actual Progress record and the two
outstanding carryovers. Only the intentionally replaced October 1/2 day plans
changed. No fictional teaching outcomes or classroom-data edits were saved.

Remaining limits: model generation/review is nondeterministic; a bad or malformed
candidate can remain Blocked/Unchecked after the single repair, preserving the
previous plan. Unknown historical task content still needs teacher identification;
the accepted recall steps do not recover information absent from stored evidence.
Semantic review cannot guarantee classroom usefulness or catch every factual error.
Legacy already-saved plans are readable rather than retroactively invalidated;
Friday's earlier accepted plan contained a single-time Morning Meeting, now replaced
by the explicit-interval rerun. A genuine classroom progress save remains teacher
acceptance work. Exact runtime-SHA display and complete browser/storage latency
instrumentation are not implemented; do not report either as measured.

## Integrated lesson resources V1 — 2 October 2026

Resume point: the interrupted implementation was already on main through
`b2174bb5014eaab70984bccd5841f6c7b1d201b8`. Inspection of main, its four resource
commits, this handoff, tests and the deployed controls confirmed that only live
resource acceptance and final documentation remained. A fresh format-6 export
contained zero resources before this continuation. The completed planning rubric
and real October 1/2 plans were inspected and preserved, not regenerated.

Implementation and live fixes are now through
`3aa354bb94204e7f3df62ce8121c5cd792468263`. The deployed app produced checked
resources using the latest resource code (version 5). Exact runtime Git SHA is
still not displayed. CI passed at
https://github.com/oisin17/teacher-ai/actions/runs/36969143355 : 131 unique tests in
the full suite, plus the 58 persistence tests rerun against real PostgreSQL 16.
Local final suite: 131 tests, 12.979 seconds, all passing.

### Additive architecture and teacher workflow

`lesson_resources.py` implements the eleven approved types: mini-whiteboard,
practice/task sheet, differentiated task sheet, quiz/retrieval, exit ticket,
discussion/oral language, modelling, challenge/early finisher, Gaeilge oral
language, source-grounded comprehension, and instructions/checklist. Suggestions
are code-only. Generate up to four selected types in one generation call and one
compact batch review with the existing `gpt-5.4-mini` model. Code can block before
review; missing comprehension source blocks before either AI call. There is no
automatic repair loop and no full daily-plan rubric invocation.

`lesson_resources_ui.py` attaches Create resources / saved resources to each
actual lesson. Drafts remain in session until explicit Save resource/Save changes.
Teachers edit freely; only submitted content/guidance edits cause one compact
review. Title-only changes use zero AI calls. Optional teacher answers are
separate from pupil content. Stored generation instructions, source material and
answer preference are reused for individual regeneration. Regeneration is a new
draft, retaining the resource identity; it does not overwrite storage until saved.
Copy controls and earlier saved versions are available.

`persistence.py` version 12 adds `lesson_resources` with owner_scope, date, plan
ID, lesson ID and JSON payload. Payload includes exact lesson/context snapshot,
evidence references/digests, original supplied source, instruction, answers
preference, timestamps, quality results, latency/call metrics, optimistic revision
and previous saved versions. Only saved Pass planning lessons can generate; fresh
parent/evidence checks and revision guards protect save. Historical/replaced
parent resources remain readable/copyable and are never silently reassociated.
Owner scope is currently single-teacher; authenticated user ownership/isolation
must be added before multi-user use. No progress, carryover, Current Learning,
Monthly Plan status or saved lesson writes occur in this resource workflow.

Backup format 6 includes resources and historical versions. Formats 1–5 remain
restorable. Restore validates the full payload before writes and returns False
for a nonempty store. Initial resource deployment's cached-schema bootstrap was
fixed earlier by keying initialization to PERSISTENCE_VERSION. No new service or
infrastructure was introduced.

### Live acceptance and measured calls

Six resources were saved from the existing approved real lessons:

| Lesson/resource | Generation | Review | Result |
| --- | ---: | ---: | --- |
| Friday Maths: whiteboard + differentiated batch | 3.34s | 1.19s | Both Pass; saved separately |
| Friday English: four unknown-task recall prompts | 2.64s | 1.03s | Pass; actual unfinished content not invented |
| Friday Gaeilge: four recall-only questions | 3.93s | 2.05s, then 2.26s edit review | Initial review blocked; corrected wording/check saved Pass |
| Friday Art: pumpkin-patch board checklist | 2.37s | 1.07s | Pass; no forced answer section |
| Thursday History: supplied TEST passage comprehension | 2.00s | 1.09s | Pass; title explicitly labels TEST passage |
| Maths individual whiteboard regeneration | 3.20s | 1.50s | Pass; same resource ID, revision 2 |

All resources used no-printing instructions. Differentiated Maths has smaller
support/core sets and a strategy-comparison reasoning challenge. English asks
what the unfinished task was without inventing a text or programme exercise.
Gaeilge's teacher-edited questions refer to assembly day rather than assuming
"yesterday". Comprehension with no source displayed “No AI call made”; the
labelled supplied Famine passage generated only questions supported by that text.
The test passage is acceptance material, not evidence that pupils were taught it.

Across this continuation: 25 resource AI calls = 12 generation + 10 compact review
+ 3 edit-review calls. This includes pre-fix failures and explicit manual retries.
There were seven manual generation reruns/regenerations (three Maths batch
reruns, and one each for Art, Gaeilge, comprehension and the saved whiteboard),
two blocked differentiated-edit submissions, and one successful Gaeilge edit.
There were zero automatic repairs. Art's later title-only edit used no AI and
became revision 2. No other resource changed during individual Maths regeneration;
the differentiated resource matches the pre-regeneration export exactly. Samples
are observations, not a benchmark or promised response time. Initial generation
samples ranged 1.75–4.48s; review samples 1.03–2.26s, excluding code-only blocks.
Storage/rerender waits added noticeable latency and were not instrumented end to
end. There is no token/dollar accounting yet.

Acceptance exposed and fixed actual issues rather than rebuilding the feature:
constrain evidence categories and exact resource type IDs in structured outputs;
state that passing checks have empty findings; separate pupil content/answers;
exclude previous quality failures/version history from edit review to prevent
anchoring; clarify valid unknown-task recall questions; explicitly require lesson
and (for comprehension) source evidence references. Malformed responses, omitted
references and incorrect/confusing answers remained unsaved. Model review still
has false positives/negatives and cannot guarantee factual or classroom quality.

The read-only stale-reference probe rejected a replaced plan ID and explicitly
reported saved resources unchanged. Both Art and Maths were refreshed/reopened;
saved content and versions persisted. Real replaced-parent writes are covered by
automated tests, without replacing the real classroom plans in acceptance.

### Data preservation and restore validation

Fresh baseline and final format-6 exports were compared field by field. ONLY
lesson_resources changed. Teacher Profile, Planning Setup, Current Learning,
Actual Progress, all monthly definitions/status updates/documents, period reviews,
carryover and both exact approved day plans match. Counts remain 349 learning
items, zero item outcome events, one genuine September 30 progress record, two
outstanding carryovers and two day plans. Final export has six resources; Art and
whiteboard have two saved versions each. No fictional teaching outcomes were saved.

The entire final export, including historical resource versions, restored into
an isolated SQLite test adapter and re-exported exactly. A second restore returned
False and left it unchanged. Separate PostgreSQL CI passes resource backup/restore,
atomic invalid-backup rejection, legacy compatibility, optimistic saves and
stale/replaced parents. Production was never cleared or overwritten. Browser
file-chooser/upload attempts did not leave an uploaded file available to the live
Restore button, so live UI restore/refusal remains unverified. Do not describe that
specific browser acceptance as passed; the core restore and PostgreSQL CI passed.

Remaining V1 limits: nondeterministic review may block a valid resource; manual
edit/regeneration is required. Source minimum length is only a preliminary gate,
with relevance/sufficiency checked semantically. Unknown task content still needs
teacher identification. Unsaved drafts may be lost on refresh/deployment. Streamlit
hot reload briefly produced an import KeyError during acceptance; refresh recovered
and durable data was unaffected. Runtime-SHA display, full storage/UI latency and
AI token-cost telemetry are absent. PDF/Word/slides, packs, templates, uploaded
style exemplars and multi-user authentication remain future work.

## Resources for Tomorrow V1 — implementation checkpoint (2026-10-02)

Approved additive orchestration is implemented in resources_tomorrow.py and the
existing lesson_resources_ui.py. Next weekday is calculated after the explicitly
selected planning date (which defaults to today's Dublin date); Friday/weekends
move to Monday. Missing exact-day approved plans do not silently skip. An explicit
saved-day selector shows the selected date. Raw approved day_plans are used, not
progress snapshots. Suggestions reuse V1 rules, rank 1–3 types without AI, and
recognise exact current resources as “Already saved — regenerate?” (deselected).
Changed evidence and earlier plan associations remain distinct.

New selected types group by lesson/effective instruction/source/answer preference.
One generation and compact review handles each group. Selected saved resources use
the shared individual regeneration helper, retaining ID/revision/creation/title;
no duplicate record is created. Per-resource override replaces batch instruction;
both and the effective instruction persist in additive resource JSON metadata.
Source-blocked comprehension is filtered before calls. Review failures preserve
passing siblings; failed lesson groups do not stop other groups. Nothing autosaves,
repairs or retries. Only explicit V1 Save writes lesson_resources.

Editor inputs and Tomorrow options now have non-widget session draft state, and
the selected planning date survives navigation. AI runs only at explicit Generate,
Regenerate or content-edit Save. Hard-refresh/new-session recovery is not promised.
A single consistent day-context read reduces suggestion connection/query overhead;
generation and save still recheck fresh exact lesson evidence. Persistence API v13
requires no new table or backup format. Core resource module v6 / UI module v7
provide hot-reload detection. No planning rubric changes.

151 local tests pass, including 61 persistence tests eligible for real PostgreSQL
CI. Deployment, live acceptance, latency measurements, fresh export comparison and
restore-upload check are pending at this checkpoint. A read-only resources_probe
mode checks a deliberately wrong copied Maths answer beside a genuine saved
sibling; it never saves candidates or teaching outcomes.


## Resources for Tomorrow V1 — final acceptance (2026-10-02)

Status: complete, deployed and live-tested. Implementation commit 2096d44;
complete preparation timer 8930adc; calendar-grounding refinement 78ab276.
The latest code CI run 36983305666 passed all 152 tests and all 61 real
PostgreSQL persistence/migration/concurrency tests. No new infrastructure,
services, resource table or backup format. Planning rubric remains V18.
Final module versions: resource core 7, resource UI 9, Tomorrow orchestration 2,
persistence API 13. API v13 is additive read support, not a new schema model.

### Final behavior

Resources for Tomorrow lives in a compact Today-page expander. It uses the next
weekday after the explicitly selected planning date; the date defaults to today
in Europe/Dublin and now survives ordinary navigation. Friday/Saturday/Sunday
advance to Monday. A missing exact-date approved plan is explained without
silently choosing a later day. “Choose another saved day” is explicit and labels
the chosen date. Saved approved raw day_plans are used, never progress snapshots.

Code ranks 1–3 existing V1 suggestion types per lesson, considering phases and
unknown carryover. Two missing useful types are normally selected; comprehension
is opt-in and needs source. Exact current saved types show “Already saved —
regenerate?” and default unchecked. Selecting one takes the shared V1 individual
regeneration path, retaining its ID/revision/creation time/title until explicit
Save. Changed evidence is labelled separately; replaced-plan resources are kept
historical and never attached by matching titles. Show saved resources exposes
existing V1 cards, including types outside the three suggestions.

New types batch by lesson and effective instruction/source/answer preference.
Normal groups use one generation plus one compact resource review; multiple
resources share these calls. Saved-resource regeneration stays individual, and
different overrides can split a lesson into more groups. Comprehension without
source is excluded before generation. Failed reviews preserve passing siblings;
failed lesson groups do not prevent later groups. Nothing automatically saves,
repairs, retries or invokes the daily planning rubric. Only explicit resource Save
writes resources. No plan/progress/current learning/carryover/monthly status writes.

Per-resource instruction overrides replace the batch instruction for that resource;
the UI explicitly says to repeat constraints that should remain. Saved JSON stores
batch, override and effective instruction plus origin in instruction_context, with
the existing instruction field retaining the actual checked instruction. Existing
V1 title-only saves require no AI; instructional edits check on Save, never typing.
Original resources and version history remain valid.

Non-widget session state preserves editor inputs, pending candidates, Tomorrow
options and planning date across normal Streamlit reruns/navigation. A hard browser
refresh/new session/deployment can still lose unsaved work; durable saved resources
persist. One consistent day-context read serves suggestions; fresh generation/save
still enforce exact parent and evidence checks.

### Live acceptance

- Normal Thursday 1 October -> Friday 2 October selected the existing approved
  Friday plan. Actual Friday 2 October -> Monday 5 October showed no approved
  plan; it did not silently select another date. Explicit saved-day selection worked.
- Existing English/Maths/Gaeilge/Art resources displayed Already saved and were
  unchecked. Maths exit ticket became Already saved after its explicit save.
- Full-day batches used the real Friday English, Maths, Gaeilge and Art lessons.
  No-printing instructions were retained. Unknown unfinished English/missed
  Gaeilge content remained recall/identification prompts, not invented tasks.
- In the first batch, seven resources were generated: six Pass and one Maths
  challenge Blocked for an unavailable source evidence reference. Its Maths exit
  sibling remained Pass. Selected comprehension without a supplied passage was
  skipped before AI; other lesson groups completed.
- Second timing batch generated six new drafts across the same four lessons,
  with the saved Maths exit deselected and source-blocked comprehension skipped.
- Individual whiteboard override requested six small-number questions/no printing
  with teacher answers. Result Pass; answers 4,3,3,5,8,8 were manually verified.
  Explicit Save changed the original whiteboard record from revision 2 to 3,
  retaining ID/creation time/history and leaving other existing resources unchanged.
- Edited Maths exit title survived Current Learning -> Today navigation without
  saving or AI. It was later explicitly saved as “Friday division strategy exit
  ticket”. Saved exit and regenerated whiteboard remained after hard refresh/reopen.
- Read-only copied-candidate probe inserted an incorrect 12 / 2 = 99 answer beside
  a real saved sibling. First review rejected the wrong answer, but also falsely
  called 2026-10-02 Thursday and blocked the valid dated exit title. Resource prompts
  now receive code-verified calendar weekday labels without changing lesson context
  digests. Final manual read-only probe paired the bad copy with the genuine
  differentiated resource: bad Blocked, sibling Pass, saved resources unchanged.
- Same probe classified a copied changed-evidence reference as Evidence changed,
  did not associate a replaced-parent copy, and rejected a replaced plan ID. Actual
  replaced-parent writes are tested in isolated databases, not production.

### Calls and observed latency

| Action | Actual AI calls | AI-only | Generation action | Complete app preparation |
| --- | ---: | ---: | ---: | ---: |
| First four-lesson batch, 7 drafts + blocked comprehension | 8 | 14.36s | 29.03s | Not instrumented |
| Second four-lesson batch, 6 drafts + blocked comprehension | 8 | 14.80s | 29.35s | 54.56s |
| Saved whiteboard regeneration with individual override | 2 | 4.07s | 7.84s | 32.82s |
| First deliberately conflicting read-only review | 1 | 1.96s | — | — |
| Calendar-grounded mixed review | 1 | 1.69s | — | — |

Total acceptance calls: 20 = 9 generation + 11 compact reviews. Zero edit-review
calls for title-only edits; zero planning calls, automatic repairs or retries.
The second full-day batch was an explicit measurement repeat, not automatic repair.

Complete app preparation measures the Generate callback before the full app rerun
through completed result rendering, including app/database work. It excludes browser
transport/paint. Continuous browser measurement for saved regeneration was 33.65s.
The full-day browser sample was still pending at 55.31s and visible at 77.33s after
an observation gap, so those are sampling bounds, not an exact 77.33s duration or
an inference about network time. The calendar prompt refinement was added after
the full-day timing samples; its final review was 1.69s. These are observations,
not a performance guarantee. App/database overhead dominates the measured times.

### Exact data comparison and restore upload

Fresh pre-rollout and final format-6 backups were compared field by field. ONLY
lesson_resources changed: one new exit ticket, and the same whiteboard ID revision
2 -> 3. All six old IDs remain; the other five resources are exactly unchanged.
Teacher Profile, Planning Setup, Current Learning, Actual Progress, all monthly
plans/items/status updates, carryovers, period review and both exact approved plans
match the baseline. Counts: 349 learning items, zero monthly outcome events, one
real September 30 progress record, two outstanding carryovers, two day plans,
seven resources. No fictional plans or teaching outcomes were saved.

The complete real final export restored into an isolated SQLite adapter and
re-exported exactly. A second restore returned False and left it unchanged.
PostgreSQL CI separately covers restoration and additive resource metadata/history.

Live restore upload WAS completed this time: the visible upload button opened the
chooser; the verified 471,839-byte JSON attached and enabled Restore. Clicking
Restore safely displayed “The database already contains saved data. Nothing has
been overwritten.” A fresh post-refusal export is byte-for-byte identical to the
final export. Production was never cleared. The actual empty-database restore is
verified in isolation/CI; the live production acceptance verifies upload/refusal.

### Remaining limits and next-work boundary

- Weekday-only date logic; no holiday inference or new calendar service.
- Review remains nondeterministic. Unsupported references, false positives,
  malformed responses or API failures can block usable material. Manual editing
  or individual regeneration is required; no automatic retry/repair.
- A malformed review blocks all eligible resources in that affected group because
  no trustworthy approval exists; other groups retain their results.
- Per-resource overrides, source differences and existing-resource regeneration
  can increase calls beyond two per lesson. No cross-lesson AI batching/background
  jobs or token/dollar accounting.
- Hard refresh/new session can lose unsaved drafts. Repeated Generate for missing
  types can retain multiple unsaved candidate drafts; use individual regeneration
  when revising one. Saved records are never duplicated automatically.
- Source minimum length is a preliminary gate; semantic source relevance and
  sufficiency still require review. Unknown carryover content needs teacher input.
- App/database rerun overhead remains substantial. No new caching/background
  infrastructure was introduced to conceal it.
- PDFs/Word/slides, daily packs, holidays, templates and guaranteed browser draft
  recovery remain deferred. No further implementation/acceptance work is pending
  for this approved Resources for Tomorrow V1 scope.


## Hardening and multi-user readiness review — 2026-10-02 completed

Baseline main 44fc689 and CI 36985034503 inspected; deployed Tomorrow remains
complete. No classroom acceptance was repeated and no genuine teaching outcomes
were saved. See TEACHER_AI_HARDENING_REVIEW.md for all 13 persistent tables,
query/write inventory, proposed legacy-workspace migration/RLS, scoped backups,
OIDC proposal (not implemented), security findings and next five tasks.

Safe changes: session-only numeric performance tracing; collapsed source-build
fingerprint/package diagnostics (NOT a claimed Git SHA); three duplicate SELECTs
removed per locked evidence packet with exact-output regression coverage; malformed
resource generation contained per lesson group; regeneration instruction retained
across ordinary navigation; current stateless AI calls default store=False.
Resource core V8, UI V10, Tomorrow V3, persistence V14; rubric remains V18.
No new schema/auth/service, pooling, cross-request cache or durable drafts.
Full suite: 165 tests pass locally, including 63 persistence cases in real PostgreSQL CI.
Final code CI and live technical profiling completed; details below.

Diagnostic code commit 0cd3c24 passed real PostgreSQL CI 36995820976. Live source
fingerprint f726d1d4a7b8838c matched. Warm read-only saved-day rerun: 24.8753s,
11 connections 9.9660s, SQL reads 9.7325s, setup 3.2721s, lock 0.1477s,
commit/close 1.6373s. Disjoint DB stages consumed ~99.5% of that no-AI rerun.
One measured duplicate carryover-choice read is now removed with an additional
regression test. Bounded pooling is proposed in the review, not implemented.

Final code commit 77c35e85984f64a97d5627f47f5d26e42a276804: CI 36996222305
passed 165 tests plus 63 rerun on PostgreSQL 16. Live build source-bc5915edc7272e50
matched local/committed Python sources + requirements, with package versions shown
separately. Final documentation-only commit does not alter that build fingerprint.

Warm saved-day view after the carryover optimization: 23.2253s, 10 connections,
33 SELECTs (previous sample 24.8753s / 11 connections / 35 SELECTs). One unsaved
technical batch from the four real approved Friday lessons produced six drafts:
four Pass, both Art drafts code-blocked for unavailable source evidence references.
7 SDK calls = 4 generation + 3 review, AI-only 13.9723s. Main server page elapsed
49.4176s; DB connect 12.6505s, reads 15.6262s, setup 4.1484s, locks 0.7413s,
fetch 0.0051s, commit/close 2.0758s. Disjoint DB total 35.2473s; other main-page
execution 0.1980s, including six resource cards 0.0477s. Main-page timing excludes
diagnostics footer/browser transport/paint. No class DML write stage occurred.
No candidates saved, no teaching/progress/carryover action pressed and no planning
rubric run. This was technical profiling, not genuine classroom acceptance.

Before beta: mandatory workspace ownership, scoped Store and PostgreSQL RLS with
separate runtime/migration roles, scoped backups and adversarial two-tenant tests;
then invite-only OIDC/membership/session cleanup. Login alone does not isolate data.
No authentication or ownership migration implemented. The report maps all 13
persistent tables and every important read/write path, preserves historical IDs
and resource versions in its migration design and lists next five tasks.

Owner decisions: provider/invites and rights, pupil-data/retention policy, backup
cloning semantics, durable-draft recovery and whether to proceed with the measured
bounded connection-pool proposal. No pool, cross-request cache, new service or
durable drafts added. Larger performance changes require a reviewed proposal.
