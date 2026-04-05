import streamlit as st
from datetime import datetime, timedelta
from utils.admin_utils import init_connection

# --- AUTH CHECK ---
if not st.session_state.get("authenticated"):
    st.switch_page("Home.py")
    st.stop()

st.title("✍️ Submit Feedback")
st.markdown("We value your feedback! Please let us know how we can improve your experience.")

# --- DB CONNECTION ---
client, db, fs = init_connection()
if not client:
    st.error("Database connection failed.")
    st.stop()

feedback_collection = db["feedback"]
user_email = st.session_state.get("user_email", "Anonymous")
user_name = user_email.split("@")[0] if "@" in user_email else user_email

# --- WEEKLY LIMIT CHECK ---
one_week_ago = datetime.utcnow() - timedelta(weeks=1)
recent_feedback = feedback_collection.find_one({
    "email": user_email,
    "date": {"$gte": one_week_ago}
})

if recent_feedback:
    submitted_at = recent_feedback["date"]
    next_allowed = submitted_at + timedelta(weeks=1)
    days_left = (next_allowed - datetime.utcnow()).days + 1
    st.warning(
        f"⏳ You have already submitted feedback this week. "
        f"You can submit again in **{days_left} day{'s' if days_left != 1 else ''}**."
    )
    st.info(f"Your last submission was on **{submitted_at.strftime('%B %d, %Y')}**.")
    st.stop()

# --- CONFIRMATION DIALOG for star-only submissions ---
@st.dialog("⚠️ No Description Added")
def confirm_star_only(rating):
    st.markdown(
        "You haven't added any comments or suggestions.\n\n"
        "A description helps us understand your experience better. "
        "Would you like to submit with **only a star rating**?"
    )
    col1, col2 = st.columns(2)
    with col1:
        if st.button("✅ Yes, submit anyway", type="primary", use_container_width=True):
            _do_submit(rating, comment="")
            st.rerun()
    with col2:
        if st.button("✏️ Add description", use_container_width=True):
            st.rerun()  # Just closes the dialog

def _do_submit(rating, comment):
    feedback_data = {
        "user": user_name,
        "email": user_email,
        "rating": rating + 1,   # st.feedback returns 0-4 index, store as 1-5
        "comment": comment.strip(),
        "date": datetime.utcnow()
    }
    try:
        feedback_collection.insert_one(feedback_data)
        st.session_state["feedback_submitted"] = True
    except Exception as e:
        st.error(f"Error submitting feedback: {e}")

# --- SHOW SUCCESS BANNER (persists after dialog rerun) ---
if st.session_state.get("feedback_submitted"):
    st.session_state.pop("feedback_submitted")
    st.success("🎉 Thank you! Your feedback has been submitted.")
    st.balloons()
    st.stop()

# --- FEEDBACK FORM ---
with st.form("feedback_form"):
    st.subheader("⭐ How would you rate your experience?")
    rating = st.feedback("stars")

    st.subheader("💬 Any comments or suggestions?")
    comment = st.text_area(
        "Your Feedback",
        placeholder="Tell us what you liked or what we can improve...",
        height=150,
        label_visibility="collapsed"
    )

    submitted = st.form_submit_button("Submit Feedback", type="primary")

if submitted:
    if rating is None:
        st.error("⚠️ Please select a star rating before submitting.")
    elif not comment.strip():
        # No description — show confirmation dialog
        confirm_star_only(rating)
    else:
        # Full submission (rating + description)
        _do_submit(rating, comment)
        st.success("🎉 Thank you! Your feedback has been submitted.")
        st.balloons()
