import streamlit as st

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
        st.info("AI lesson generation will be connected here next.")

    st.subheader("Lessons")

    st.info(
        "No lessons generated yet. Once Teacher AI is connected, "
        "your timetable and lessons will appear here."
    )

# ---------- TEACHER PROFILE ----------

elif page == "Teacher Profile":

    st.header("Teacher Profile")

    st.write(
        "Tell Teacher AI about your class, teaching style and "
        "classroom resources."
    )

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

    language = st.selectbox(
        "School language",
        ["English-medium", "Irish-medium"]
    )

    resources = st.text_area(
        "Classroom resources",
        placeholder=(
            "e.g. interactive board, mini-whiteboards, "
            "Chromebooks, dice, counters..."
        )
    )

    teaching_style = st.text_area(
        "Teaching preferences",
        placeholder=(
            "e.g. active lessons, mini-whiteboards, hands-on activities, "
            "pupil challenges, minimal group work..."
        )
    )

    differentiation = st.text_area(
        "Differentiation / additional needs",
        placeholder=(
            "Add relevant classroom needs, exemptions or "
            "differentiation requirements."
        )
    )

    if st.button("Save Teacher Profile", type="primary"):
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
        st.success("Planning setup saved for this session.")
