import pytest
from streamlit.testing.v1 import AppTest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

@pytest.fixture
def user_feedback_app(mock_db_connection):
    with patch("streamlit.feedback", return_value=4):
        at = AppTest.from_file("views/user_feedback.py")
        yield at

def test_user_feedback_unauthorized_redirect(user_feedback_app):
    user_feedback_app.session_state.authenticated = False
    with patch("streamlit.switch_page") as mock_switch:
        user_feedback_app.run()
        assert mock_switch.called

def test_user_feedback_weekly_limit_blocked(user_feedback_app, mock_db_connection):
    user_feedback_app.session_state.authenticated = True
    user_feedback_app.session_state.user_email = "submitter@test.com"
    
    # Seed feedback from 2 days ago
    mock_db_connection["feedback"].insert_one({
        "email": "submitter@test.com",
        "rating": 5,
        "comment": "Nice app",
        "date": (datetime.utcnow() - timedelta(days=2)).isoformat()
    })
    
    user_feedback_app.run()
    assert not user_feedback_app.exception
    # Should show warning that already submitted
    assert any("already submitted" in w.value for w in user_feedback_app.warning)

def test_user_feedback_full_submit_success(user_feedback_app, mock_db_connection):
    user_feedback_app.session_state.authenticated = True
    user_feedback_app.session_state.user_email = "newsubmitter@test.com"
    
    user_feedback_app.run()
    assert not user_feedback_app.exception
    
    # Fill in comments
    user_feedback_app.text_area[0].input("Stunning work on the UI").run()
    
    # Find the submit button
    btn = next(b for b in user_feedback_app.button if "Submit Feedback" in b.label)
    
    # Click submit button
    with patch("streamlit.feedback", return_value=4): # 5 Stars (0-indexed 4)
        btn.click().run()
        
    # Check feedback collection in stub DB
    feedback = mock_db_connection["feedback"].find_one({"email": "newsubmitter@test.com"})
    assert feedback is not None
    assert feedback["rating"] == 5
    assert feedback["comment"] == "Stunning work on the UI"


def test_user_feedback_db_connection_fail(user_feedback_app):
    user_feedback_app.session_state.authenticated = True
    with patch("utils.admin_utils.init_connection", return_value=(None, None, None)):
        user_feedback_app.run()
        assert any("Database connection failed." in e.value for e in user_feedback_app.error)


def test_user_feedback_submit_missing_rating(user_feedback_app):
    user_feedback_app.session_state.authenticated = True
    user_feedback_app.session_state.user_email = "rating@test.com"
    user_feedback_app.run()
    
    btn = next(b for b in user_feedback_app.button if "Submit Feedback" in b.label)
    with patch("streamlit.feedback", return_value=None):
        btn.click().run()
        
    assert any("Please select a star rating" in e.value for e in user_feedback_app.error)


def test_user_feedback_submit_db_error(user_feedback_app, mock_db_connection):
    user_feedback_app.session_state.authenticated = True
    user_feedback_app.session_state.user_email = "dberror@test.com"
    user_feedback_app.run()
    
    user_feedback_app.text_area[0].input("some comment")
    btn = next(b for b in user_feedback_app.button if "Submit Feedback" in b.label)
    
    from pymongo.errors import PyMongoError
    from tests.mock_mongo import MockCollection
    with patch.object(MockCollection, "insert_one", side_effect=PyMongoError("Insert error")):
        btn.click().run()
        
    assert any("Error submitting feedback" in e.value for e in user_feedback_app.error)


def test_user_feedback_empty_comment_dialog(user_feedback_app, mock_db_connection):
    user_feedback_app.session_state.authenticated = True
    user_feedback_app.session_state.user_email = "staronly@test.com"
    user_feedback_app.run()
    
    btn = next(b for b in user_feedback_app.button if "Submit Feedback" in b.label)
    btn.click().run()
    
    assert any("You haven't added any comments" in m.value for m in user_feedback_app.markdown)


