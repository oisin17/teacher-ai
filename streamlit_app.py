import streamlit as st
from openai import OpenAI
import io
from pypdf import PdfReader
from docx import Document
import sqlite3
import json
from datetime import date, timedelta

client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

def init_database():
    connection = sqlite3.connect("teacher_ai.db")
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS teacher_profile (
            id INTEGER PRIMARY KEY,
            profile_data TEXT NOT NULL
        )
    """)    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS actual_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            planning_day TEXT NOT NULL,
            subject TEXT NOT NULL,
            lesson_topic TEXT,
            status TEXT NOT NULL,
            notes TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS planning_setup (
            id INTEGER PRIMARY KEY,
            planning_data TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS current_learning_position (
            id INTEGER PRIMARY KEY,
            position_data TEXT NOT NULL
        )
    """)
    # V0 migration: attach a real school date to progress records.
    cursor.execute("PRAGMA table_info(actual_progress)")
    progress_columns = [row[1] for row in cursor.fetchall()]
    if "planning_date" not in progress_columns:
        cursor.execute("ALTER TABLE actual_progress ADD COLUMN planning_date TEXT")

    connection.commit()
    connection.close()


init_database()

def save_teacher_profile(profile):
    connection = sqlite3.connect("teacher_ai.db")
    cursor = connection.cursor()

    profile_json = json.dumps(profile)

    cursor.execute(
        """
        INSERT OR REPLACE INTO teacher_profile (id, profile_data)
        VALUES (1, ?)
        """,
        (profile_json,)
    )

    connection.commit()
    connection.close()


def load_teacher_profile():
    connection = sqlite3.connect("teacher_ai.db")
    cursor = connection.cursor()

    cursor.execute(
        "SELECT profile_data FROM teacher_profile WHERE id = 1"
    )

    result = cursor.fetchone()
    connection.close()

    if result:
        return json.loads(result[0])

    return {}


def save_planning_setup(planning_setup):
    connection = sqlite3.connect("teacher_ai.db")
    cursor = connection.cursor()

    planning_json = json.dumps(planning_setup)

    cursor.execute(
        """
        INSERT OR REPLACE INTO planning_setup (id, planning_data)
        VALUES (1, ?)
        """,
        (planning_json,)
    )

    connection.commit()
    connection.close()

def load_planning_setup():
    connection = sqlite3.connect("teacher_ai.db")
    cursor = connection.cursor()

    cursor.execute(
        "SELECT planning_data FROM planning_setup WHERE id = 1"
    )

    result = cursor.fetchone()
    connection.close()

    if result:
        return json.loads(result[0])

    return {}

def save_current_learning_position(position):
    connection = sqlite3.connect("teacher_ai.db")
    cursor = connection.cursor()
    position_json = json.dumps(position)
    cursor.execute(
        """
        INSERT OR REPLACE INTO current_learning_position (id, position_data)
        VALUES (1, ?)
        """,
        (position_json,)
    )
    connection.commit()
    connection.close()

def load_current_learning_position():
    connection = sqlite3.connect("teacher_ai.db")
    cursor = connection.cursor()
    cursor.execute(
        "SELECT position_data FROM current_learning_position WHERE id = 1"
    )
    result = cursor.fetchone()
    connection.close()
    if result:
        return json.loads(result[0])
    return {}

def load_progress_history():
    connection = sqlite3.connect("teacher_ai.db")
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT id, planning_date, planning_day, status, notes
        FROM actual_progress
        WHERE planning_date IS NOT NULL
        ORDER BY planning_date ASC, id ASC
        """
    )
    rows = cursor.fetchall()
    connection.close()
    return [
        {
            "id": row[0],
            "planning_date": row[1],
            "planning_day": row[2],
            "status": row[3],
            "notes": row[4] or ""
        }
        for row in rows
    ]

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
    st.session_state["current_learning_position"] = rebuilt
    save_current_learning_position(rebuilt)
    return rebuilt

def load_recent_progress(limit=10):
    connection = sqlite3.connect("teacher_ai.db")
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT planning_day, subject, lesson_topic, status, notes, planning_date
        FROM actual_progress
        ORDER BY COALESCE(planning_date, '') DESC, id DESC
        LIMIT ?
        """,
        (limit,)
    )
    rows = cursor.fetchall()
    connection.close()
    return [
        {
            "planning_day": row[0],
            "subject": row[1],
            "lesson_topic": row[2],
            "status": row[3],
            "notes": row[4],
            "planning_date": row[5]
        }
        for row in rows
    ]

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
    st.write(
        "Your teaching day will appear here based on your timetable, "
        "plans and actual classroom progress."
    )
    default_date = date.today()
    planning_date = st.date_input(
        "Which school date are you planning?",
        value=default_date,
        format="DD/MM/YYYY"
    )
    planning_day = planning_date.strftime("%A")
    st.caption(f"Planning for **{planning_day}, {planning_date.strftime('%d %B %Y')}**")

    if planning_day in ["Saturday", "Sunday"]:
        st.warning("This date falls on a weekend. Choose a school day unless you intentionally want to plan for it.")
    if st.button("✨ Generate Today's Plan", type="primary"):

        teacher_profile = st.session_state.get("teacher_profile", {})
        planning_setup = st.session_state.get("planning_setup", {})

        timetable_text = planning_setup.get("timetable_text", "")
        monthly_plan_text = planning_setup.get("monthly_plan_text", "")
        yearly_plan_text = planning_setup.get("yearly_plan_text", "")

        if not teacher_profile:
            st.warning("Please save your Teacher Profile first.")

        elif not monthly_plan_text:
            st.warning("Please upload and save your Monthly Plan first.")



        else:
            with st.spinner("Teacher AI is planning your day..."):
                try:
                    recent_progress = load_recent_progress()
                    current_learning_position = st.session_state.get("current_learning_position", {})

                    response = client.responses.create(
                        model="gpt-5.4-mini",
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

                            f"TEACHER PROFILE:\n{teacher_profile}\n\n"
                            f"WEEKLY TIMETABLE:\n{timetable_text}\n\n"
                            f"CURRENT MONTHLY PLAN:\n{monthly_plan_text}\n\n"
                            f"YEARLY PLAN:\n{yearly_plan_text}\n\n"
                            f"CURRENT LEARNING POSITION (teacher-confirmed current classroom position):\n{current_learning_position}\n\n"
                            f"RECENT ACTUAL CLASSROOM PROGRESS (most recent first):\n{recent_progress}\n\n"

                            "Treat CURRENT LEARNING POSITION as the strongest evidence of where each subject currently is, unless newer actual-progress notes explicitly update it. The monthly plan describes intended coverage, not the class's current starting point. "
                            "Any explicit statement such as completed, finished, do not restart, moved on from, or currently working on is a planning constraint, not merely background context. "
                            "Before generating the plan, silently determine for each core subject whether the evidence shows: (a) a specific lesson completed and ready to progress, (b) unfinished learning to continue, (c) missed learning to reschedule, or (d) current position genuinely unknown. Do not equate a completed lesson with a completed subject/topic/unit. "
                            "FINAL VALIDATION: compare every lesson focus in the proposed day against Current Learning Position one last time. Remove or replace any contradiction before returning the plan. Then generate today's practical teaching plan now."
                        )
                    )

                    st.session_state["todays_plan"] = response.output_text

                except Exception as e:
                    st.error(f"Teacher AI error: {e}")

    st.subheader("Lessons")

    if "todays_plan" in st.session_state:
        st.markdown(st.session_state["todays_plan"])
        st.divider()
        st.subheader("How did today go?")

        progress_status = st.radio(
            "Overall progress",
            ["Completed", "Partially completed", "Not taught"],
            horizontal=True
        )
    
        progress_notes = st.text_area(
            "What actually happened? (optional)",
            placeholder="e.g. Maths completed. Gaeilge only reached the first activity. Science was not taught because of an assembly."
        )
    
        if st.button("Save Today's Progress"):
            connection = sqlite3.connect("teacher_ai.db")
            cursor = connection.cursor()
    
            planning_date_text = planning_date.isoformat()

            cursor.execute(
                """
                SELECT id FROM actual_progress
                WHERE planning_date = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (planning_date_text,)
            )
            existing_progress = cursor.fetchone()

            if existing_progress:
                cursor.execute(
                    """
                    UPDATE actual_progress
                    SET planning_day = ?, subject = ?, lesson_topic = ?, status = ?, notes = ?
                    WHERE id = ?
                    """,
                    (
                        str(planning_day),
                        "Full day",
                        "Daily teaching plan",
                        progress_status,
                        progress_notes,
                        existing_progress[0]
                    )
                )
                progress_was_updated = True
            else:
                cursor.execute(
                    """
                    INSERT INTO actual_progress
                    (planning_day, subject, lesson_topic, status, notes, planning_date)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(planning_day),
                        "Full day",
                        "Daily teaching plan",
                        progress_status,
                        progress_notes,
                        planning_date_text
                    )
                )
                progress_was_updated = False
    
            connection.commit()
            connection.close()

            # Use the teacher's account of what actually happened to update
            # Teacher AI's persistent understanding of the class position.
            if progress_notes.strip():
                try:
                    current_position = st.session_state.get(
                        "current_learning_position", {}
                    )

                    update_response = client.responses.create(
                        model="gpt-5.4-mini",
                        input=(
                            "You maintain a primary teacher's persistent CURRENT LEARNING POSITION. "
                            "Update it conservatively from today's teacher-confirmed progress.\n\n"
                            "RULES:\n"
                            "- The teacher's progress notes are authoritative for what actually happened today.\n"
                            "- Preserve existing information that today's notes do not change.\n"
                            "- Do not invent textbook pages, stopping points, concepts taught, or topic completion.\n"
                            "- 'Completed' means the specific lesson/day was completed, not automatically the whole topic/unit.\n"
                            "- If something was partially completed, record only what is safely known and retain uncertainty about the exact stopping point unless stated.\n"
                            "- If something was not taught because of time or interruption, keep it outstanding; do not infer pupil difficulty.\n"
                            "- Keep entries concise and useful for planning the next lesson.\n"
                            "- Return ONLY valid JSON with exactly these keys: Maths, English, Gaeilge, SESE, Other. "
                            "Each value must be a plain string.\n\n"
                            f"EXISTING CURRENT LEARNING POSITION:\n{current_position}\n\n"
                            f"DATE: {planning_date.isoformat()} ({planning_day})\n"
                            f"OVERALL STATUS: {progress_status}\n"
                            f"TEACHER PROGRESS NOTES:\n{progress_notes}\n"
                        )
                    )

                    updated_position = json.loads(update_response.output_text)

                    required_keys = ["Maths", "English", "Gaeilge", "SESE", "Other"]
                    if all(
                        key in updated_position
                        and isinstance(updated_position[key], str)
                        for key in required_keys
                    ):
                        st.session_state["current_learning_position"] = updated_position
                        save_current_learning_position(updated_position)
                        if progress_was_updated:
                            st.success(
                                "Progress for this date was updated and Current Learning Position refreshed."
                            )
                        else:
                            st.success(
                                "Today's progress saved and Current Learning Position updated."
                            )
                    else:
                        st.warning(
                            "Today's progress was saved, but the Current Learning Position "
                            "could not be updated automatically."
                        )

                except Exception:
                    st.warning(
                        "Today's progress was saved, but the Current Learning Position "
                        "could not be updated automatically."
                    )
            else:
                if progress_was_updated:
                    st.success(
                        "Progress for this date was updated. Add a short note if you want "
                        "Teacher AI to update Current Learning Position automatically."
                    )
                else:
                    st.success(
                        "Today's progress saved. Add a short note next time if you want "
                        "Teacher AI to update Current Learning Position automatically."
                    )
    else:
        st.info(
            "No lessons generated yet. Upload your planning documents "
            "and click Generate Today's Plan."
        )

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
            connection = sqlite3.connect("teacher_ai.db")
            cursor = connection.cursor()

            new_date_text = edited_date.isoformat()
            cursor.execute(
                """
                SELECT id FROM actual_progress
                WHERE planning_date = ? AND id != ?
                LIMIT 1
                """,
                (new_date_text, selected["id"])
            )
            conflict = cursor.fetchone()

            if conflict:
                connection.close()
                st.error(
                    "Another progress record already exists for that date. "
                    "Choose the existing date instead of creating a duplicate."
                )
            else:
                cursor.execute(
                    """
                    UPDATE actual_progress
                    SET planning_date = ?, planning_day = ?, status = ?, notes = ?
                    WHERE id = ?
                    """,
                    (
                        new_date_text,
                        edited_day,
                        edited_status,
                        edited_notes,
                        selected["id"]
                    )
                )
                connection.commit()
                connection.close()

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
        st.session_state["current_learning_position"] = position
        save_current_learning_position(position)
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
            "recurring_arrangements": recurring
        }

        st.session_state["teacher_profile"] = profile
        save_teacher_profile(profile)

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

    st.subheader("Monthly Plan")

    monthly_plan = st.file_uploader(
        "Upload current monthly plan",
        type=["pdf", "docx"]
    )
    saved_planning = st.session_state.get("planning_setup", {})

    if saved_planning.get("monthly_plan_text"):
        st.success("✓ Monthly Plan saved")
    st.subheader("Yearly Plan")

    yearly_plan = st.file_uploader(
        "Upload yearly plan (optional)",
        type=["pdf", "docx"]
    )

    if st.button("Save Planning Setup", type="primary"):

        timetable_text = extract_text_from_file(timetable)
        monthly_plan_text = extract_text_from_file(monthly_plan)
        yearly_plan_text = extract_text_from_file(yearly_plan)

        st.session_state["planning_setup"] = {
            "timetable_text": timetable_text,
            "monthly_plan_text": monthly_plan_text,
            "yearly_plan_text": yearly_plan_text
        }
        save_planning_setup(st.session_state["planning_setup"])

        st.success("Planning setup saved and documents processed.")
