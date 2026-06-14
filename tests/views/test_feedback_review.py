import pytest
from streamlit.testing.v1 import AppTest
from unittest.mock import patch, MagicMock

@pytest.fixture
def feedback_review_app(mock_db_connection):
    at = AppTest.from_file("views/feedback_review.py")
    yield at

def test_feedback_review_unauthorized_redirect(feedback_review_app):
    feedback_review_app.session_state.authenticated = False
    with patch("streamlit.switch_page") as mock_switch:
        feedback_review_app.run()
        assert mock_switch.called

def test_feedback_review_dummy_seeding(feedback_review_app, mock_db_connection):
    feedback_review_app.session_state.authenticated = True
    feedback_review_app.session_state.role = "admin"
    
    # Run first time -> seeds dummy data and triggers rerun
    with patch("streamlit.rerun") as mock_rerun:
        feedback_review_app.run()
        assert mock_rerun.called
        assert mock_db_connection["feedback"].count_documents({}) == 5

def test_feedback_review_metrics(feedback_review_app, mock_db_connection):
    feedback_review_app.session_state.authenticated = True
    feedback_review_app.session_state.role = "admin"
    
    # Seed custom feedback data
    mock_db_connection["feedback"].insert_one({"user": "Zaid", "rating": 5, "comment": "Good", "date": "2026-06-14T12:00:00"})
    mock_db_connection["feedback"].insert_one({"user": "Sara", "rating": 3, "comment": "Okay", "date": "2026-06-14T12:00:00"})
    
    feedback_review_app.run()
    assert not feedback_review_app.exception
    
    metrics = {m.label: m.value for m in feedback_review_app.metric}
    assert "Total Reviews" in metrics
    assert "Average Rating" in metrics
    assert metrics["Total Reviews"] == "2"
    assert metrics["Average Rating"] == "4.0 ⭐"


def test_feedback_review_non_admin_blocked(feedback_review_app):
    feedback_review_app.session_state.authenticated = True
    feedback_review_app.session_state.role = "user"  # Standard user, not admin
    feedback_review_app.run()
    
    assert any("Unauthorized Access" in e.value for e in feedback_review_app.error)


def test_feedback_review_db_connection_fail(feedback_review_app):
    feedback_review_app.session_state.authenticated = True
    feedback_review_app.session_state.role = "admin"
    
    with patch("utils.admin_utils.init_connection", return_value=(None, None, None)):
        feedback_review_app.run()
        assert any("Database connection failed." in e.value for e in feedback_review_app.error)

