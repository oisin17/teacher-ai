import streamlit as st
from openai import OpenAI
import io
from pypdf import PdfReader
from docx import Document

client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
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
    ["Today", "Teacher Profile", "Planning Setup"],
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

    elif not timetable_text:
        st.warning("Please upload and save your Weekly Timetable first.")

    else:
        with st.spinner("Teacher AI is planning your day..."):
            try:
                response = client.responses.create(
                    model="gpt-5.4-mini",
                    input=(
                        "You are Teacher AI, an adaptive planning assistant "
                        "for primary school teachers.\n\n"

                        "Your job is to create a practical teaching plan for TODAY "
                        "using the teacher's real context below.\n\n"

                        "PRIORITY ORDER:\n"
                        "1. Teacher Profile\n"
                        "2. Current Monthly Plan\n"
                        "3. Weekly Timetable\n"
                        "4. Yearly Plan if available\n\n"

                        "IMPORTANT RULES:\n"
                        "- Follow the actual timetable for the day.\n"
                        "- Use the monthly plan as the main authority for current learning.\n"
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

                        "Generate today's practical teaching plan now."
                    )
                )

                st.session_state["todays_plan"] = response.output_text

            except Exception as e:
                st.error(f"Teacher AI error: {e}")

    st.subheader("Lessons")

    if "todays_plan" in st.session_state:
        st.markdown(st.session_state["todays_plan"])
    else:
        st.info(
            "No lessons generated yet. Upload your planning documents "
            "and click Generate Today's Plan."
        )

# ---------- TEACHER PROFILE ----------

elif page == "Teacher Profile":

    st.header("Teacher Profile")

    st.write(
        "Tell Teacher AI about your class, teaching preferences and "
        "classroom setup. This context will shape future lesson planning."
    )

    # ----- CLASS -----

    st.subheader("Class")

    col1, col2 = st.columns(2)

    with col1:
        class_level = st.selectbox(
            "Class level",
            [
                "Junior Infants",
                "Senior Infants",
                "1st Class",
                "2nd Class",
                "3rd Class",
                "4th Class",
                "5th Class",
                "6th Class"
            ],
            index=6
        )

    with col2:
        language = st.selectbox(
            "School language",
            ["English-medium", "Irish-medium"]
        )

    pupil_count = st.number_input(
        "Number of pupils",
        min_value=1,
        max_value=40,
        value=27
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
        ]
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
        ]
    )

    teaching_notes = st.text_area(
        "Anything else about how you like to teach?",
        placeholder=(
            "e.g. Keep lessons practical and engaging. "
            "I like concise plans that I can understand quickly."
        ),
        height=100
    )

    st.divider()

    # ----- DIFFERENTIATION -----

    st.subheader("Differentiation & Additional Needs")

    irish_exemptions = st.number_input(
        "Number of pupils with Irish exemptions",
        min_value=0,
        max_value=40,
        value=0
    )

    differentiation = st.text_area(
        "Differentiation / additional needs",
        placeholder=(
            "Describe recurring differentiation needs or classroom "
            "arrangements Teacher AI should account for."
        ),
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
        st.session_state["teacher_profile"] = {
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

        st.success("Teacher Profile saved for this session.")

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

        st.success("Planning setup saved and documents processed.")
