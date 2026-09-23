import streamlit as st

st.set_page_config(
    page_title="Teacher AI",
    page_icon="📚",
    layout="wide"
)

st.title("📚 Teacher AI")
st.subheader("Your adaptive AI teaching planner")

st.write(
    "Plan engaging lessons, create optional classroom resources, "
    "and adapt your teaching plan as the week actually happens."
)

st.divider()

st.header("Today's Plan")

st.info("Your lessons will appear here.")

if st.button("Generate Today's Plan"):
    st.success("Teacher AI is ready to generate today's lessons.")
