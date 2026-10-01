import streamlit as st
from openai import OpenAI
import io
import hashlib
from uuid import uuid4
from monthly_plans import suggest_dates
import importlib
import monthly_learning_ui
if getattr(monthly_learning_ui, "MODULE_VERSION", None) != 2:
    importlib.reload(monthly_learning_ui)
from monthly_learning_ui import review_items, item_inputs, suggest_outcomes
from monthly_learning import MARKER, fingerprint
import importlib
import timetable_constraints
if getattr(timetable_constraints, "CONSTRAINT_VERSION", None) != 2:
    importlib.reload(timetable_constraints)
from timetable_constraints import singing_day, validate_protected_plan
import carryover
if not hasattr(carryover, "retain_explicit_links"):
    importlib.reload(carryover)
from carryover import SUGGESTION_FORMAT, retain_explicit_links
from pypdf import PdfReader
from docx import Document
import lesson_progress
refresh_lessons = "monthly_item_links" not in lesson_progress.PLAN_FORMAT["schema"]["properties"]["lessons"]["items"]["properties"]
if refresh_lessons:
    importlib.reload(lesson_progress)
import persistence
# Streamlit hot reload can retain the previous imported storage module.
# Reload only when that cached module lacks this rollout's additive API.
if refresh_lessons or not hasattr(persistence.Store, "list_learning_items"):
    importlib.reload(persistence)
from persistence import Store, StorageError
import json
from datetime import date, timedelta
from lesson_progress import (
    EVIDENCE_MARKER, PLAN_FORMAT, STATUSES,
    parse_generated_plan, plan_markdown,
)

client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

def storage_call(operation, *args):
    try:
        return operation(*args)
    except StorageError as error:
        st.error(str(error))
        st.stop()


# No local fallback: production saves must go to the durable database.
try:
    store = Store(st.secrets.get("DATABASE_URL", ""))
except StorageError as error:
    st.error(str(error))
    st.stop()


@st.cache_resource
def initialise_storage(database_url, schema_version):
    # A code hot reload can preserve Streamlit's resource cache. Bump this
    # explicit key whenever additive tables/schema must be initialized.
    Store(database_url).initialise()


storage_call(initialise_storage, st.secrets.get("DATABASE_URL", ""), 6)


def save_teacher_profile(profile):
    storage_call(store.save_document, "teacher_profile", profile)


def load_teacher_profile():
    return storage_call(store.load_document, "teacher_profile")


def save_planning_setup(planning_setup):
    storage_call(store.save_document, "planning_setup", planning_setup)


def load_planning_setup():
    return storage_call(store.load_document, "planning_setup")


def save_current_learning_position(position):
    storage_call(store.save_document, "current_learning_position", position)


def load_current_learning_position():
    return storage_call(store.load_document, "current_learning_position")


def load_progress_history():
    return storage_call(store.load_progress_history)


def rebuild_current_learning_from_history():
    history = load_progress_history()
    if not history:
        return st.session_state.get("current_learning_position", {})

    existing_position = st.session_state.get("current_learning_position", {})
    response = client.responses.create(
        model="gpt-5.4-mini",
        input=(
            "Rebuild a primary teacher's CURRENT LEARNING POSITION from the valid dated "
            "progress history below. Use the existing position only as background for facts "
            "that are not contradicted by the dated history.\n\n"
            "RULES:\n"
            "- Process dated progress chronologically. Later teacher-confirmed progress overrides earlier progress.\n"
            "- Never invent textbook pages, stopping points, concepts taught, or topic completion.\n"
            "- Completed means the specific lesson/day was completed, not automatically the whole topic/unit.\n"
            "- Partial means retain only what is safely known and preserve uncertainty where needed.\n"
            "- Not taught due to time/interruption remains outstanding and does not imply pupil difficulty.\n"
            "- Preserve stable constraints in Other (for example fixed PE times) unless history contradicts them.\n"
            "- Return ONLY valid JSON with exactly these keys: Maths, English, Gaeilge, SESE, Other. "
            "Each value must be a plain string.\n\n"
            f"EXISTING POSITION:\n{existing_position}\n\n"
            f"VALID DATED PROGRESS HISTORY:\n{history}\n"
        )
    )
    rebuilt = json.loads(response.output_text)
    required_keys = ["Maths", "English", "Gaeilge", "SESE", "Other"]
    if not all(key in rebuilt and isinstance(rebuilt[key], str) for key in required_keys):
        raise ValueError("Invalid rebuilt Current Learning Position")
    save_current_learning_position(rebuilt)
    st.session_state["current_learning_position"] = rebuilt
    return rebuilt

def load_recent_progress(limit=10):
    return storage_call(store.load_recent_progress, limit)


def lesson_progress_inputs(lessons, prefix):
    """One quick row per real lesson; unset is not a teaching outcome."""
    def mark_all_completed():
        for lesson in lessons:
            st.session_state[f"{prefix}_{lesson['lesson_id']}_status"] = "Completed"
    outcomes = []
    learning_items = {i["id"]: i for i in storage_call(store.list_learning_items)}
    carry_labels = {i["id"]: i["learning"] for i in storage_call(store.list_carryover)}
    with st.form(f"{prefix}_form"):
        # Submit draft inputs to the callback so a late bulk action preserves
        # any notes already typed in the form. It does not save teaching data.
        st.form_submit_button("Mark all completed", on_click=mark_all_completed)
        for lesson in lessons:
            status_key = f"{prefix}_{lesson['lesson_id']}_status"
            note_key = f"{prefix}_{lesson['lesson_id']}_note"
            st.session_state.setdefault(status_key, lesson.get("status"))
            st.session_state.setdefault(note_key, lesson.get("note", ""))
            title, status_column, note_column = st.columns([2, 3, 2])
            with title:
                st.markdown(f"**{lesson['subject']} — {lesson['topic']}**")
                st.caption(lesson["time"])
            with status_column:
                status = st.radio(
                    f"{lesson['subject']} — {lesson['topic']} progress",
                    STATUSES, index=None, horizontal=True, key=status_key,
                    label_visibility="collapsed",
                )
            with note_column:
                note = st.text_input(
                    f"{lesson['subject']} — {lesson['topic']} note (optional)",
                    placeholder="Short note (optional)", max_chars=300,
                    key=note_key, label_visibility="collapsed",
                )
            completed_ids = []
            for carry_id in lesson.get("carryover_ids", []):
                if st.checkbox(f"This carryover is now finished: {carry_labels.get(carry_id, carry_id)}",
                               value=carry_id in lesson.get("completed_carryover_ids", []),
                               key=f"{prefix}_{lesson['lesson_id']}_carry_{carry_id}"):
                    completed_ids.append(carry_id)
            outcome = {**lesson, "status": status, "note": note.strip()}
            if lesson.get("carryover_ids"):
                outcome["completed_carryover_ids"] = completed_ids
            draft = st.session_state.get(prefix + '_item_suggestions', {}).get(lesson['lesson_id'])
            if draft is not None:
                outcome['item_updates'] = draft
            outcome["item_updates"] = item_inputs(outcome, prefix, learning_items)
            outcomes.append(outcome)
        suggest = st.form_submit_button('Suggest item outcomes from notes') if any(l.get('monthly_item_links') for l in lessons) else False
        submitted = st.form_submit_button(
            "Save Today's Progress" if prefix.startswith("today_") else "Save Correction",
            type="primary",
        )
    if suggest:
        try:
            with st.spinner('Suggesting item outcomes — nothing is saved…'):
                suggestions = suggest_outcomes(client, outcomes, learning_items)
            st.session_state[prefix + '_item_suggestions'] = suggestions
            for lesson in outcomes:
                for update in suggestions.get(lesson['lesson_id'], []):
                    base = prefix + lesson['lesson_id'] + update['item_id']
                    # Widget updates on the next rerun, after this form has submitted.
                    st.session_state[base + '_pending'] = update
            st.rerun()
        except Exception:
            st.warning('Suggestions could not be verified. Save conservative progress or enter item exceptions yourself.')
    return outcomes, submitted


def transition_review(monthly, selected_date):
    context = storage_call(store.carryover_context, monthly, selected_date)
    needs_review = bool(context["previous"] and context["review"] is None)
    if needs_review:
        st.subheader("Month Transition / Carryover")
        st.write(f"Moving into {monthly['title']} — anything to carry over?")
        st.caption("Review suggestions, uncheck incorrect items, or add your own. They are not saved until you confirm.")
        draft_key = f"carry_suggestions_{monthly['id']}_{selected_date}"
        if draft_key not in st.session_state:
            try:
                response = client.responses.create(model="gpt-5.4-mini", text={"format": SUGGESTION_FORMAT}, input=(
                    "Suggest at most 6 specific unfinished or not-taught learning items from the prior period's actual progress and Current Learning below. "
                    "These are suggestions for teacher review, not completion decisions. Quote the source date/note in evidence. "
                    "Teacher notes override statuses. Do not infer unfinished learning from the monthly curriculum itself, invent a stopping point, "
                    "or suggest already resolved learning. Return an empty list when evidence is insufficient. Exclude existing carryover items.\n"
                    f"PRIOR PROGRESS: {context['history']}\nCURRENT LEARNING: {context['position']}\nEXISTING ITEMS: {context['items']}"))
                suggested = json.loads(response.output_text)["items"]
                if not isinstance(suggested, list) or len(suggested) > 6 or any(
                    not isinstance(i, dict) or any(not isinstance(i.get(k), str) for k in ("subject", "learning", "evidence")) for i in suggested):
                    raise ValueError("Invalid suggestions")
                st.session_state[draft_key] = suggested
            except Exception:
                st.session_state[draft_key] = []
                st.warning("Suggestions could not be loaded. You can add carryover manually or choose Nothing to carry over.")
        chosen = []
        with st.form(f"carry_review_{monthly['id']}"):
            for index, suggestion in enumerate(st.session_state[draft_key]):
                keep = st.checkbox(f"Carry over {suggestion['subject']}", value=True, key=f"{draft_key}_{index}_keep")
                learning = st.text_input(f"{suggestion['subject']} unfinished learning", value=suggestion['learning'][:300], max_chars=300, key=f"{draft_key}_{index}_text")
                st.caption(suggestion["evidence"][:1500])
                if keep:
                    chosen.append({"subject": suggestion["subject"], "learning": learning, "evidence": suggestion["evidence"][:1500]})
            for learning_item in context.get('unfinished_items', []):
                if st.checkbox(f"Carry over Monthly item: {learning_item['subject']} — {learning_item['remaining'] or learning_item['description']}", value=False, key=draft_key + learning_item['id']):
                    chosen.append(dict(subject=learning_item['subject'], learning=(learning_item['remaining'] or learning_item['description'])[:300], evidence=learning_item['evidence'] or 'Teacher confirmed unfinished Monthly Plan item', monthly_item_id=learning_item['id']))
            subject = st.selectbox("Add another item — subject", ["Maths", "English", "Gaeilge", "SESE", "Other"])
            learning = st.text_area("Another carryover item (optional)", max_chars=900, help="One item per line; keep each under 300 characters.")
            confirm = st.form_submit_button("Save carryover and continue", type="primary")
            nothing = st.form_submit_button("Nothing to carry over")
        if confirm or nothing:
            if nothing:
                chosen = []
            else:
                chosen.extend({"subject": subject, "learning": line.strip(), "evidence": "Teacher added manually"} for line in learning.splitlines() if line.strip())
            items = [{**i, "id": uuid4().hex, "period_id": monthly["id"], "created_date": selected_date, "state": "outstanding"} for i in chosen]
            try:
                store.save_period_review(monthly, selected_date, items, True)
            except StorageError as error:
                st.error(str(error))
            else:
                st.rerun()
    return context, needs_review


def carryover_controls(items):
    with st.expander("Carryover learning", expanded=any(i["state"] == "outstanding" for i in items)):
        if not items:
            st.caption("No confirmed carryover items.")
        for item in items:
            st.write(f"**{item['subject']} — {item['learning']}** ({item['state']})")
            st.caption(item["evidence"])
            if not item.get('monthly_item_id'):
                available = [i for i in storage_call(store.list_learning_items) if not i['archived']]
                if available:
                    with st.expander('Link to a Monthly Plan item (optional)'):
                        target = st.selectbox('Same underlying learning item', [i['id'] for i in available], format_func=lambda id: next(i['subject'] + ' — ' + i['description'] for i in available if i['id'] == id), key='carry_link_' + item['id'])
                        if st.button('Confirm same learning', key='carry_link_save_' + item['id']):
                            storage_call(store.link_carryover_item, item['id'], target)
                            st.rerun()
            if item["state"] == "outstanding":
                completed = st.button("Mark complete", key=f"complete_{item['id']}")
                removed = st.button("Remove", key=f"remove_{item['id']}")
                if completed or removed:
                    storage_call(store.set_carryover_state, item["id"], "completed" if completed else "removed")
                    st.rerun()
            elif item["state"] == "completed" and item.get("completion_source") != "lesson":
                if st.button("Reopen item", key=f"reopen_{item['id']}"):
                    storage_call(store.set_carryover_state, item["id"], "outstanding")
                    st.rerun()
            elif item["state"] == "removed":
                if st.button("Restore item", key=f"restore_{item['id']}"):
                    storage_call(store.set_carryover_state, item["id"], "outstanding")
                    st.rerun()


if "teacher_profile" not in st.session_state:
    st.session_state["teacher_profile"] = load_teacher_profile()
if "planning_setup" not in st.session_state:
    st.session_state["planning_setup"] = load_planning_setup()
if "current_learning_position" not in st.session_state:
    st.session_state["current_learning_position"] = load_current_learning_position()
    
def extract_text_from_file(uploaded_file):
    if uploaded_file is None:
        return ""

    file_name = uploaded_file.name.lower()

    try:
        if file_name.endswith(".pdf"):
            uploaded_file.seek(0)
            reader = PdfReader(uploaded_file)

            text = ""
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"

            uploaded_file.seek(0)
            return text

        elif file_name.endswith(".docx"):
            uploaded_file.seek(0)
            document = Document(uploaded_file)

            text_parts = []

            # Read normal paragraphs
            for paragraph in document.paragraphs:
                if paragraph.text.strip():
                    text_parts.append(paragraph.text.strip())

            # Read text inside tables
            for table in document.tables:
                for row in table.rows:
                    row_text = []

                    for cell in row.cells:
                        cell_text = cell.text.strip()

                        if cell_text:
                            row_text.append(cell_text)

                    if row_text:
                        text_parts.append(" | ".join(row_text))

            text = "\n".join(text_parts)

            uploaded_file.seek(0)
            return text

        else:
            return ""

    except Exception:
        uploaded_file.seek(0)
        return ""
        
st.set_page_config(
    page_title="Teacher AI",
    page_icon="📚",
    layout="wide"
)

# ---------- HEADER ----------

st.title("📚 Teacher AI")
st.caption("Your adaptive AI teaching planner")

# ---------- NAVIGATION ----------

page = st.radio(
    "Navigation",
    ["Today", "Progress History", "Current Learning", "Teacher Profile", "Planning Setup"],
    horizontal=True,
    label_visibility="collapsed"
)

st.divider()

# ---------- TODAY ----------

if page == "Today":

    st.header("Today's Plan")
    if st.session_state.pop("lesson_progress_saved", False):
        st.success("Lesson progress saved and Current Learning Position updated.")
    st.write(
        "Your teaching day will appear here based on your timetable, "
        "plans and actual classroom progress."
    )
    # Keep the selected planning date stable across Streamlit widget reruns.
    # Without an explicit session-state key, interactions elsewhere on this
    # page (such as the progress radio) can rebuild the date input from today.
    if "planning_date" not in st.session_state:
        st.session_state["planning_date"] = date.today()

    planning_date = st.date_input(
        "Which school date are you planning?",
        key="planning_date",
        format="DD/MM/YYYY"
    )
    planning_day = planning_date.strftime("%A")
    st.caption(f"Planning for **{planning_day}, {planning_date.strftime('%d %B %Y')}**")

    if planning_day in ["Saturday", "Sunday"]:
        st.warning("This date falls on a weekend. Choose a school day unless you intentionally want to plan for it.")
    selected_monthly = storage_call(store.select_monthly_plan, planning_date.isoformat())
    if selected_monthly:
        st.info(f"Using {selected_monthly['title']}.")
        st.caption(f"Confirmed coverage: {selected_monthly['start_date']} to {selected_monthly['end_date']}")
    else:
        st.warning("No confirmed Monthly Plan covers this date. Upload or confirm its dates in Planning Setup before generating.")
    carry_context, needs_review = transition_review(selected_monthly, planning_date.isoformat()) if selected_monthly else ({"items": []}, False)
    carryover_controls(carry_context["items"])
    outstanding_carryover = [i for i in carry_context["items"] if i["state"] == "outstanding"]
    day_state = storage_call(store.load_day, planning_date.isoformat())
    if day_state["progress"]:
        st.caption("Progress is already saved for this date. You can update it below or in Progress History.")
    if st.button("✨ Generate Today's Plan", type="primary", disabled=day_state["progress"] is not None or selected_monthly is None or needs_review):

        teacher_profile = load_teacher_profile()
        st.session_state["teacher_profile"] = teacher_profile
        planning_setup = storage_call(store.load_document, "planning_setup")

        timetable_text = planning_setup.get("timetable_text", "")
        monthly_plan_text = selected_monthly["plan_text"] if selected_monthly else ""
        yearly_plan_text = planning_setup.get("yearly_plan_text", "")

        if not teacher_profile:
            st.warning("Please save your Teacher Profile first.")

        elif not monthly_plan_text:
            st.warning("Please upload and save your Monthly Plan first.")



        else:
            with st.spinner("Teacher AI is planning your day..."):
                try:
                    learning_items = storage_call(store.list_learning_items, None, planning_date.isoformat())
                    current_items = [i for i in learning_items if not i["archived"] and ((i["monthly_plan_id"] == selected_monthly["id"] and i["fingerprint"] == fingerprint(selected_monthly["plan_text"])) or i["id"] in {c.get("monthly_item_id") for c in outstanding_carryover})]
                    recent_progress = load_recent_progress()
                    current_learning_position = load_current_learning_position()
                    st.session_state["current_learning_position"] = current_learning_position

                    response = client.responses.create(
                        model="gpt-5.4-mini",
                        text={"format": PLAN_FORMAT},
                        input=(
                            "You are Teacher AI, an adaptive planning assistant "
                            "for primary school teachers.\n\n"

                            f"Your job is to create a practical teaching plan for {planning_day}, {planning_date.isoformat()}. "
                            "Use the teacher's real context below.\n\n"

                            "PRIORITY ORDER:\n"
                            "1. Teacher Profile\n"
                            "2. Current Monthly Plan\n"
                            "3. Weekly Timetable\n"
                            "4. Yearly Plan if available\n\n"

                            "IMPORTANT RULES:\n"
                            + ("- PROTECTED THURSDAY: external teacher Singing 14:00–14:30 is fixed, overrides uploaded timetable/monthly coverage, and must appear in the overview only. Do not derive Singing content from the Monthly Plan or add it to lesson progress. Finish ALL normal teaching by 14:00. Schedule pack-up/tidy-up 13:50–14:00 before Singing; school finishes at 14:30, with no second pack-up slot.\n" if singing_day(teacher_profile, planning_date.isoformat()) else "")
                            +
                            f"- The day being planned is {planning_day}.\n"
                            "- If a weekly timetable has been supplied, follow it for this day unless the teacher has explicitly provided a temporary change.\n"
                            "- If no weekly timetable has been supplied, construct a practical timetable for the day using the Teacher Profile, recurring routines, fixed arrangements, current Monthly Plan and curriculum requirements.\n"
                            "- When constructing a day without a weekly timetable, use the school-day start and finish times and recurring times recorded in the Teacher Profile. Treat these as real scheduling constraints.\n"
                            "- Schedule teaching only inside the available teaching periods between those fixed routines. Never extend the day beyond the recorded school finish time or schedule a lesson across a protected break, yard, fixed lesson or tidy-up period.\n"
                            "- Use curriculum time requirements as a guide to sensible weekly coverage, not as a requirement to teach every subject every day.\n"
                            "- Prioritise subjects and learning that are due from the Monthly Plan, unfinished learning where known, recurring learning, and subjects that need appropriate coverage across the week.\n"
                            "- Do not create lessons for non-teaching routines such as roll call, food breaks, yard or tidy-up. Preserve them in the timetable where they affect when teaching can occur.\n"
                            "- If a recurring routine can legitimately contribute to curriculum provision, such as DEAR or the recorded Religion routine, account for it appropriately without unnecessarily duplicating that provision elsewhere.\n"
                            "- When no weekly timetable exists, the resulting plan should still show practical clock times for the teaching lessons because the Teacher Profile provides the boundaries of the school day.\n"
                            "- Use the monthly plan as the main authority for intended current learning, but use ACTUAL PROGRESS to determine what has really been taught.\n"
                            "- AUTHORITY: Teacher-confirmed CURRENT LEARNING POSITION and newer ACTUAL PROGRESS override conflicting Monthly Plan suggestions. The Monthly Plan is intended coverage, not permission to restart learning already confirmed complete.\n"
                            "- HARD CONSTRAINT: Never schedule, recommend, or reintroduce a lesson focus that CURRENT LEARNING POSITION explicitly says is completed, finished, or should not be restarted, unless newer teacher-confirmed progress explicitly says to revisit it. Retrieval may briefly reference prior learning, but it must not become the main lesson focus.\n"
                            "- Before finalising the plan, silently cross-check every proposed lesson against CURRENT LEARNING POSITION. If any lesson contradicts a teacher-confirmed current position, replace that lesson with the next evidence-supported learning focus.\n"
                            "- If the next learning focus cannot be established safely from Current Learning, recent progress, or the Monthly Plan, say that the precise next focus is uncertain and use a short diagnostic/retrieval step rather than reverting to known-completed work.\n"
                            "- Treat saved actual classroom progress as more authoritative than assumptions based only on the monthly plan.\n"
                            "- If progress says learning was partially completed, intelligently continue or revisit unfinished learning rather than assuming the planned lesson was completed.\n"
                            "- If progress says a lesson was not taught, reschedule it when appropriate without assuming pupils struggled with the content.\n"
                            "- COMPLETED means that specific planned lesson was successfully taught. It does NOT mean the subject should receive less teaching next time, and it does NOT mean the wider topic, chapter, unit or recurring objective is complete unless the teacher explicitly says so.\n"
                            "- Do not replace a normal core-subject lesson with a short retrieval/check-in merely because the previous day's lesson in that subject was completed. Continue with the next appropriate learning unless the teacher explicitly says the wider topic or unit is finished.\n"
                            "- For recurring core subjects such as Maths, English and Gaeilge, preserve normal teaching entitlement and progression across the week. Previous completion should normally move learning FORWARD, not reduce subject time.\n"
                            "- Use teacher progress notes to identify what was actually taught, unfinished, moved or missed.\n"
                            "- A monthly plan describes intended learning across a period; it does NOT prove the class is currently at the first objective listed. Never infer current classroom position from document order alone.\n"
                            "- When recent progress does not establish the current position within a monthly objective, choose the safest evidence-supported continuation. If necessary, use a brief diagnostic/retrieval check, but do not reset the class to beginning-of-month material merely because it appears earlier in the monthly plan.\n"
                            "- Treat dated or late-month planning as potentially further advanced through the monthly plan. Use actual progress as the main evidence of position, and state uncertainty where position is genuinely unknown.\n"
                            "- Never invent an exact stopping point. If the stopping point is unclear, begin with a brief check or retrieval activity and continue from the safest supported point.\n"
                            "- Do not invent textbook pages, exercises or content that is not supplied.\n"
                            "- Do not assume a PowerPoint or worksheet exists.\n"
                            "- Lessons must stand alone without optional generated resources.\n"
                            "- Make lessons enjoyable, active and engaging where this genuinely "
                            "supports the learning intention.\n"
                            "- Consider mini-games, challenges, mystery, pupil-v-teacher, "
                            "mini-whiteboards, movement, hands-on learning, prediction, "
                            "partner challenges and interactive-board activities where appropriate.\n"
                            "- Do not force games or activities where straightforward teaching "
                            "would be better.\n"
                            "- Keep teacher-facing plans concise and easy to scan.\n"
                            "- Avoid long teacher scripts.\n"
                            "- Lesson phase timings must add exactly to the available lesson time.\n"
                            "- Include differentiation based on the Teacher Profile.\n"
                            "- Include an early-finisher activity where useful.\n"
                            "- If information needed to plan safely is genuinely unknown, "
                            "state the uncertainty rather than inventing it.\n\n"

                            "FOR EACH ACTUAL TEACHING LESSON TODAY, GIVE:\n"
                            "- Time\n"
                            "- Subject and topic\n"
                            "- Learning intention\n"
                            "- Resources\n"
                            "- A small number of timed lesson phases\n"
                            "- Brief differentiation\n"
                            "- Brief assessment/check for understanding\n"
                            "- Early finisher where appropriate\n\n"

                            "Do not create lessons for breaks, lunch, yard, roll call, "
                            "tidy-up or other non-teaching periods.\n\n"
                            "RETURN THE STRUCTURED DAY PLAN:\n"
                            "- overview: concise Markdown timetable including the protected non-teaching routines.\n"
                            "- lessons: one item for EVERY actual teaching lesson in that timetable, in time order; "
                            "keep separate lessons in the same subject separate. Do not list breaks or yard as lessons.\n"
                            "- Each lesson has time, subject, topic, learning_intention, and details. "
                            "Use standard subject names (Maths, English, Gaeilge, Science, History, Geography, etc.).\n"
                            "- details is the concise usable Markdown lesson content: resources, timed phases, "
                            "differentiation, assessment and early finisher where appropriate. "
                            "The app will display the supplied subject, topic and learning intention directly above it.\n"
                            "- The learning intention must precisely match what those lesson phases teach.\n"
                            "- Dated individual LESSON progress is evidence of that lesson's outcome. "
                            "Teacher notes override both the selected status and any conflicting planned intention. "
                            "Use newer dated evidence ahead of older entries; never assume a completed lesson finishes its unit.\n\n"

                            f"CONFIRMED MONTHLY LEARNING ITEMS (status and remaining learning are authoritative):\n{current_items}\n"
                            "For every lesson addressing a confirmed item, put its exact item_id and the specific addressed scope in monthly_item_links. Use [] when no confirmed item applies. Never fabricate IDs, link just by subject, repeat completed items, or claim one lesson finishes a recurring/broad objective. Plan remaining learning instead of repeating already completed aspects. Include 'Monthly item:' plus the exact ID and addressed scope in lesson details.\n"
                            f"TEACHER PROFILE:\n{teacher_profile}\n\n"
                            f"WEEKLY TIMETABLE:\n{timetable_text}\n\n"
                            f"CURRENT MONTHLY PLAN (teacher-confirmed {selected_monthly['start_date']} to {selected_monthly['end_date']}; these override stale document headings):\n{monthly_plan_text}\n\n"
                            f"CONFIRMED OUTSTANDING CARRYOVER:\n{outstanding_carryover}\n\n"
                            "Carryover is a short-term priority alongside the new month's main coverage. Schedule into appropriate lessons over the next days; do not cram everything into day one. "
                            "For a lesson addressing carryover, include its exact ID in carryover_ids. Use [] for other lessons. Do not link unrelated learning or already completed/removed items. "
                            "A carryover lesson must state the specific unfinished learning it addresses. Teacher completion of carryover overrides stale older evidence for that item.\n"
                            "Do not label an unknown previous lesson as the new month's topic. If the prior task/topic is unspecified, explicitly include a brief teacher/pupil recall check to identify it, then resume the actual missed/unfinished task. "
                            "Link carryover only when the lesson phases explicitly identify and address that prior task; sharing a subject is insufficient.\n"
                            f"ALL REVIEWED CARRYOVER DECISIONS:\n{carry_context['items']}\n\n"
                            f"YEARLY PLAN:\n{yearly_plan_text}\n\n"
                            f"CURRENT LEARNING POSITION (teacher-confirmed current classroom position):\n{current_learning_position}\n\n"
                            f"RECENT ACTUAL CLASSROOM PROGRESS (most recent first):\n{recent_progress}\n\n"

                            "Treat CURRENT LEARNING POSITION as the strongest evidence of where each subject currently is, unless newer actual-progress notes explicitly update it. The monthly plan describes intended coverage, not the class's current starting point. "
                            "Any explicit statement such as completed, finished, do not restart, moved on from, or currently working on is a planning constraint, not merely background context. "
                            "Before generating the plan, silently determine for each core subject whether the evidence shows: (a) a specific lesson completed and ready to progress, (b) unfinished learning to continue, (c) missed learning to reschedule, or (d) current position genuinely unknown. Do not equate a completed lesson with a completed subject/topic/unit. "
                            "FINAL VALIDATION: compare every lesson focus against Current Learning Position and teacher-confirmed carryover decisions. Completed/removed carryover overrides older contradictory evidence for that item. "
                            "For EACH carryover ID linked to a lesson, its phases must explicitly resume that specific previous task. "
                            "Include a 'Carryover:' line in that lesson's details quoting the item's exact learning text verbatim. Without that explicit reference its completion link will be discarded. "
                            "When the previous task is unknown, use a neutral title and intention (identify and resume the missed/unfinished task), with a short teacher recall check followed by work on the identified task. "
                            "Do not assume it was procedural writing, Bia, or any other new-month content without actual progress evidence. "
                            "If you instead teach only new-month learning today, leave carryover_ids empty and keep that item for another appropriate day. Remove any unsupported link before returning the plan. Then generate today's practical teaching plan now."
                        )
                    )

                    generated_plan = parse_generated_plan(response.output_text, planning_date.isoformat())
                    validate_protected_plan(generated_plan, teacher_profile)
                    retain_explicit_links(generated_plan, outstanding_carryover)
                    generated_plan["monthly_plan"] = {key: selected_monthly[key] for key in ("id", "title", "start_date", "end_date")}
                    storage_call(store.save_day_plan, generated_plan)
                    day_state = {"plan": generated_plan, "progress": None}
                    st.session_state["todays_plan"] = plan_markdown(generated_plan)
                    st.session_state["todays_plan_date"] = planning_date.isoformat()
                    st.session_state["todays_plan_day"] = planning_day

                except Exception:
                    st.error("Teacher AI could not generate a complete lesson plan. Your previous saved plan is unchanged. Please try again.")

    st.subheader("Lessons")

    saved_plan = day_state["plan"]
    if saved_plan:
        provenance = day_state["plan"].get("monthly_plan") if day_state["plan"] else None
        if provenance:
            st.caption(f"Saved day plan generated using: {provenance['title']} ({provenance['start_date']} to {provenance['end_date']}).")
        else:
            st.caption("This saved day plan predates dated Monthly Plans; its original monthly source was not recorded.")
        st.caption(f"Generated for **{planning_day}, {planning_date.strftime('%d/%m/%Y')}**")
        st.markdown(plan_markdown(saved_plan))
        st.divider()
        st.subheader("How did today go?")
        st.caption("Mark all completed, then change any exceptions. Notes are optional. Nothing is saved until you press Save.")
        if day_state["progress"] and not day_state["progress"].get("lessons"):
            st.info("This date has a historical whole-day record. Review or correct it in Progress History.")
        else:
            outcomes, submitted = lesson_progress_inputs(
                saved_plan["lessons"], f"today_{planning_date.isoformat()}_{saved_plan['plan_id']}"
            )
            if submitted:
                if any(lesson["status"] is None for lesson in outcomes):
                    st.warning("Choose a progress status for every lesson, or use Mark all completed.")
                else:
                    position = storage_call(store.save_lesson_progress, planning_date.isoformat(),
                                            saved_plan["plan_id"], outcomes)
                    st.session_state["current_learning_position"] = position
                    st.session_state["lesson_progress_saved"] = True
                    st.rerun()
    elif day_state["progress"]:
        st.info("This date has a historical whole-day record. Review or correct it in Progress History.")
    else:
        st.info("No lessons generated for this date yet. Upload your planning documents and click Generate Today's Plan.")

# ---------- PROGRESS HISTORY ----------

elif page == "Progress History":

    st.header("Progress History")
    st.write(
        "Review or correct saved classroom progress. One record is kept per school date."
    )

    history = load_progress_history()

    if not history:
        st.info("No dated progress has been saved yet.")
    else:
        display_options = {
            f"{date.fromisoformat(item['planning_date']).strftime('%d/%m/%Y')} — {item['planning_day']}": item
            for item in reversed(history)
        }

        selected_label = st.selectbox(
            "Choose a saved school date",
            list(display_options.keys())
        )
        selected = display_options[selected_label]

        edited_date = st.date_input(
            "School date",
            value=date.fromisoformat(selected["planning_date"]),
            format="DD/MM/YYYY",
            key=f"history_date_{selected['id']}"
        )
        edited_day = edited_date.strftime("%A")

        if selected.get("lessons"):
            with st.expander("Original lesson intentions"):
                for lesson in selected["lessons"]:
                    st.markdown(f"**{lesson['subject']} — {lesson['topic']}**: {lesson['learning_intention']}")
            outcomes, submitted = lesson_progress_inputs(selected["lessons"], f"history_{selected['id']}")
            if submitted:
                position = storage_call(store.correct_lesson_progress, selected["id"], edited_date.isoformat(), outcomes)
                if position is None:
                    st.error("Another progress record already exists for that date. Choose the existing date instead.")
                else:
                    st.session_state["current_learning_position"] = position
                    st.success("Lesson progress corrected and Current Learning Position updated.")
        else:
            st.caption("Historical whole-day record")
            edited_status = st.radio(
                "Overall progress",
                ["Completed", "Partially completed", "Not taught"],
                index=["Completed", "Partially completed", "Not taught"].index(selected["status"]),
                horizontal=True,
                key=f"history_status_{selected['id']}"
            )
            edited_notes = st.text_area(
                "What actually happened?",
                value=selected["notes"],
                height=160,
                key=f"history_notes_{selected['id']}"
            )

            st.caption(
                f"This record will be stored as **{edited_day}, {edited_date.strftime('%d %B %Y')}**."
            )

            if st.button("Save Correction", type="primary"):
                corrected = storage_call(
                    store.correct_progress,
                    selected["id"],
                    edited_date.isoformat(),
                    edited_day,
                    edited_status,
                    edited_notes,
                )
                if not corrected:
                    st.error(
                        "Another progress record already exists for that date. "
                        "Choose the existing date instead of creating a duplicate."
                    )
                else:
                    try:
                        rebuild_current_learning_from_history()
                        st.success(
                            "Progress corrected and Current Learning Position rebuilt from the valid history."
                        )
                        st.rerun()
                    except Exception:
                        st.warning(
                            "Progress was corrected, but Current Learning Position could not be rebuilt automatically."
                        )

# ---------- CURRENT LEARNING ----------

elif page == "Current Learning":

    st.header("Current Learning Position")
    st.write(
        "Record where the class actually is now. This overrides assumptions "
        "Teacher AI might otherwise make from the order of the monthly plan."
    )

    saved_position = st.session_state.get("current_learning_position", {})

    maths_position = st.text_area(
        "Maths",
        value=saved_position.get("Maths", ""),
        placeholder="e.g. Addition completed. Currently moving through Subtraction."
    )
    english_position = st.text_area(
        "English",
        value=saved_position.get("English", ""),
        placeholder="e.g. Narrative writing completed. Current reading/comprehension focus..."
    )
    gaeilge_position = st.text_area(
        "Gaeilge",
        value=saved_position.get("Gaeilge", ""),
        placeholder="e.g. Current oral language / grammar / reading position..."
    )
    sese_position = st.text_area(
        "SESE",
        value=saved_position.get("SESE", ""),
        placeholder="e.g. Science Heat lesson outstanding; current History/Geography position..."
    )
    other_position = st.text_area(
        "Other subjects / notes",
        value=saved_position.get("Other", ""),
        placeholder="Anything else Teacher AI should know about the class's current position."
    )

    if st.button("Save Current Learning Position", type="primary"):
        position = {
            "Maths": maths_position,
            "English": english_position,
            "Gaeilge": gaeilge_position,
            "SESE": sese_position,
            "Other": other_position
        }
        # Explicit teacher edits become confirmed context; newer saved lesson
        # outcomes can subsequently update it without discarding the edit.
        position = {key: value.replace(MARKER, "\n\nTeacher-confirmed item context:\n").replace(EVIDENCE_MARKER, "\n\nTeacher-confirmed lesson context:\n")
                    for key, value in position.items()}
        save_current_learning_position(position)
        st.session_state["current_learning_position"] = position
        st.success("Current Learning Position saved.")

# ---------- TEACHER PROFILE ----------

elif page == "Teacher Profile":

    st.header("Teacher Profile")

    saved_profile = st.session_state.get("teacher_profile", {})

    st.write(
        "Tell Teacher AI about your class, teaching preferences and "
        "classroom setup. This context will shape future lesson planning."
    )

    # ----- CLASS -----

    st.subheader("Class")

    col1, col2 = st.columns(2)

    with col1:
        class_options = [
            "Junior Infants",
            "Senior Infants",
            "1st Class",
            "2nd Class",
            "3rd Class",
            "4th Class",
            "5th Class",
            "6th Class"
        ]

        saved_class = saved_profile.get("class_level", "5th Class")

        class_level = st.selectbox(
            "Class level",
            class_options,
            index=class_options.index(saved_class)
        )

    with col2:
        language_options = ["English-medium", "Irish-medium"]

        saved_language = saved_profile.get(
            "language",
            "English-medium"
        )

        language = st.selectbox(
            "School language",
            language_options,
            index=language_options.index(saved_language)
        )

    pupil_count = st.number_input(
        "Number of pupils",
        min_value=1,
        max_value=40,
        value=saved_profile.get("pupil_count", 27)
    )
    st.divider()

    # ----- PROGRAMMES -----

    st.subheader("Books & Programmes")

    st.caption(
        "Add the main books or programmes you use. "
        "Teacher AI should never invent specific pages or exercises "
        "unless their contents are available."
    )

    programmes = st.text_area(
        "Books / programmes",
        placeholder=(
            "e.g.\n"
            "Maths — Busy at Maths 5, Work It Out 5\n"
            "English — Starlight 5\n"
            "Gaeilge — Abair Liom 5, Am don Léamh 5\n"
            "SESE — Explore With Me 5"
        ),
        value=saved_profile.get("programmes", ""),
        height=140
    )

    st.divider()

    # ----- RESOURCES -----

    st.subheader("Classroom Resources")

    resources = st.text_area(
        "Resources available",
        placeholder=(
            "e.g. interactive touchscreen, mini-whiteboards, "
            "Chromebooks, dice, counters, maths manipulatives, "
            "A4/A3 paper..."
        ),
        value=saved_profile.get("resources", ""),
        height=120
    )

    st.divider()

    # ----- TEACHING STYLE -----

    st.subheader("Teaching Style")

    st.write(
        "Choose approaches you generally enjoy using. "
        "Teacher AI should still select activities based on what "
        "best suits each lesson."
    )

    preferred_methods = st.multiselect(
        "I like using:",
        [
            "Active learning",
            "Mini-games and challenges",
            "Mystery / detective / mission activities",
            "Pupil vs teacher challenges",
            "Mini-whiteboards",
            "Movement",
            "Real-life scenarios",
            "Hands-on activities / manipulatives",
            "Pupil choice",
            "Partner challenges",
            "Creative / designing / making",
            "Prediction / surprise / reveal",
            "Technology / interactive board",
            "Explicit teacher modelling",
            "Independent practice",
            "Discussion"
        ],
        default=saved_profile.get("preferred_methods", [])
    )
    

    minimise_methods = st.multiselect(
        "I prefer to minimise:",
        [
            "Long teacher explanations",
            "Group work",
            "Pair work",
            "Textbook-heavy lessons",
            "Worksheets",
            "Technology",
            "Competition",
            "Movement",
            "Creative activities"
        ],
        default=saved_profile.get("minimise_methods", [])
    )

    teaching_notes = st.text_area(
        "Anything else about how you like to teach?",
        placeholder=(
            "e.g. Keep lessons practical and engaging. "
            "I like concise plans that I can understand quickly."
        ),
        value=saved_profile.get("teaching_notes", ""),
        height=100
    )

    st.divider()

    # ----- DIFFERENTIATION -----

    st.subheader("Differentiation & Additional Needs")

    irish_exemptions = st.number_input(
        "Number of pupils with Irish exemptions",
        min_value=0,
        max_value=40,
        value=saved_profile.get("irish_exemptions", 0)
    )

    differentiation = st.text_area(
        "Differentiation / additional needs",
        placeholder=(
            "Describe recurring differentiation needs or classroom "
            "arrangements Teacher AI should account for."
        ),
        value=saved_profile.get("differentiation", ""),
        height=120
    )

    st.divider()

    # ----- RECURRING ARRANGEMENTS -----

    st.subheader("Recurring Classroom Arrangements")

    recurring = st.text_area(
        "Regular arrangements Teacher AI should know",
        placeholder=(
            "e.g. fixed PE times, recurring support teaching, "
            "Religion arrangements, Chromebook access, "
            "regular classroom routines..."
        ),
        value=saved_profile.get("recurring_arrangements", ""),
        height=120
    )
    thursday_singing = st.checkbox("Thursday Singing with external teacher, 14:00–14:30 (protected)",
                                   value=saved_profile.get("thursday_singing", False))

    st.divider()

    # ----- REFERENCE MATERIALS -----

    st.subheader("Reference Materials")

    st.caption(
        "Optional examples or templates that can later help Teacher AI "
        "match how you like lessons and resources presented."
    )

    reference_files = st.file_uploader(
        "Upload lesson templates or example resources",
        type=["pdf", "docx", "pptx"],
        accept_multiple_files=True
    )

    st.divider()

    if st.button("Save Teacher Profile", type="primary"):

        profile = {
            "class_level": class_level,
            "language": language,
            "pupil_count": pupil_count,
            "programmes": programmes,
            "resources": resources,
            "preferred_methods": preferred_methods,
            "minimise_methods": minimise_methods,
            "teaching_notes": teaching_notes,
            "irish_exemptions": irish_exemptions,
            "differentiation": differentiation,
            "recurring_arrangements": recurring,
            "thursday_singing": thursday_singing
        }

        save_teacher_profile(profile)
        st.session_state["teacher_profile"] = profile

        st.success("Teacher Profile saved.")

# ---------- PLANNING SETUP ----------

elif page == "Planning Setup":

    st.header("Planning Setup")

    st.write(
        "Give Teacher AI the information it needs to understand "
        "what you intend to teach and when."
    )

    st.subheader("Weekly Timetable")

    timetable = st.file_uploader(
        "Upload timetable",
        type=["pdf", "docx", "xlsx", "png", "jpg", "jpeg"]
    )

    st.subheader("Monthly Plans")
    st.caption("Save each month's plan separately. Only dates you explicitly confirm control selection.")
    saved_planning = st.session_state.get("planning_setup", {})
    monthly_items = storage_call(store.list_monthly_plans)
    for item in monthly_items:
        coverage = f"{item['start_date']} to {item['end_date']}" if item['start_date'] else "confirm dates"
        st.write(f"**{item['title']}** — {coverage}")
    chosen_id = st.selectbox("Monthly Plan to add or edit", ["new"] + [p["id"] for p in monthly_items],
                            format_func=lambda value: "Add a new Monthly Plan" if value == "new" else next(p["title"] for p in monthly_items if p["id"] == value))
    existing = next((p for p in monthly_items if p["id"] == chosen_id), None)
    uploaded_monthly = st.file_uploader("Upload Monthly Plan (PDF or Word)", type=["pdf", "docx"], key=f"monthly_upload_{chosen_id}")
    text = existing["plan_text"] if existing else ""
    filename = existing["source_filename"] if existing else ""
    if uploaded_monthly is not None:
        text = extract_text_from_file(uploaded_monthly)
        filename = uploaded_monthly.name
        if not text.strip():
            st.error("Could not extract readable text. Your saved Monthly Plans have not been changed.")
    if text.strip():
        token = hashlib.sha256((chosen_id + filename + text).encode()).hexdigest()[:16]
        suggestions = suggest_dates(text, filename)
        st.caption(suggestions["evidence"])
        with st.expander("Preview Monthly Plan text"):
            st.text(text[:4000])
        with st.form(f"monthly_confirm_{token}"):
            initial_start = date.fromisoformat(existing["start_date"]) if existing and existing["start_date"] else suggestions["start"]
            initial_end = date.fromisoformat(existing["end_date"]) if existing and existing["end_date"] else suggestions["end"]
            default_title = existing["title"] if existing and existing["start_date"] else (initial_start.strftime("%B %Y Monthly Plan") if initial_start else "Monthly Plan")
            title = st.text_input("Monthly Plan title", value=default_title)
            start = st.date_input("Monthly Plan start date", value=initial_start, format="DD/MM/YYYY")
            end = st.date_input("Monthly Plan end date", value=initial_end, format="DD/MM/YYYY")
            confirmed = st.checkbox("I confirm these start and end dates for this Monthly Plan")
            save_monthly = st.form_submit_button("Save confirmed Monthly Plan", type="primary")
        if save_monthly:
            payload = {"id": chosen_id if existing else str(uuid4()), "title": title,
                       "source_filename": filename, "plan_text": text,
                       "start_date": start.isoformat() if start else None,
                       "end_date": end.isoformat() if end else None}
            try:
                store.save_monthly_plan(payload, confirmed)
            except StorageError as error:
                st.error(str(error))
            else:
                st.success("Monthly Plan saved with confirmed dates.")
                st.rerun()
    if existing and existing["start_date"]:
        review_items(store, client, existing, storage_call)
    st.subheader("Yearly Plan")

    yearly_plan = st.file_uploader(
        "Upload yearly plan (optional)",
        type=["pdf", "docx"]
    )

    if st.button("Save Planning Setup", type="primary"):

        # No new upload means retain the existing saved document.
        # Reject unreadable replacements instead of erasing saved plan text.
        planning_setup = dict(saved_planning)
        for field, uploaded in (
            ("timetable_text", timetable),
            ("yearly_plan_text", yearly_plan),
        ):
            if uploaded is not None:
                extracted = extract_text_from_file(uploaded)
                if not extracted.strip():
                    st.error(
                        f"Could not extract text from {uploaded.name}. "
                        "Please upload a readable PDF or Word document. "
                        "Your saved planning documents have not been changed."
                    )
                    st.stop()
                planning_setup[field] = extracted
            else:
                planning_setup.setdefault(field, "")

        save_planning_setup(planning_setup)
        st.session_state["planning_setup"] = planning_setup
        st.success("Planning setup saved and documents processed.")

# ---------- SAVED DATA BACKUP ----------

with st.expander("Saved data backup"):
    st.caption("Download a copy of all saved class context and progress.")
    if st.button("Prepare saved data backup"):
        backup = storage_call(store.export_backup)
        st.session_state["cutover_backup"] = json.dumps(
            backup, ensure_ascii=False, indent=2
        )
    if "cutover_backup" in st.session_state:
        st.download_button(
            "Download saved data backup",
            data=st.session_state["cutover_backup"],
            file_name="teacher_ai_saved_data_backup.json",
            mime="application/json",
            on_click="ignore",
        )
    st.caption("Restore a backup only into an empty database. Existing saved data will never be overwritten.")
    backup_upload = st.file_uploader("Saved data backup to restore", type=["json"])
    if st.button("Restore saved data backup", disabled=backup_upload is None):
        try:
            backup = json.loads(backup_upload.getvalue())
        except (ValueError, UnicodeDecodeError):
            st.error("This is not a readable Teacher AI backup. No data has been changed.")
            st.stop()
        restored = storage_call(store.restore_backup, backup)
        if restored:
            for key in ("teacher_profile", "planning_setup", "current_learning_position", "cutover_backup"):
                st.session_state.pop(key, None)
            st.success("All saved data restored.")
            st.rerun()
        else:
            st.info("The database already contains saved data. Nothing has been overwritten.")
