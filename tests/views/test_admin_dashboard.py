import pytest
from streamlit.testing.v1 import AppTest
from unittest.mock import patch, MagicMock

@pytest.fixture
def admin_app(mock_db_connection):
    at = AppTest.from_file("views/admin_dashboard.py")
    yield at

def test_admin_unauthorized_redirect(admin_app):
    admin_app.session_state.authenticated = False
    with patch("streamlit.switch_page") as mock_switch:
        admin_app.run()
        assert mock_switch.called
        assert mock_switch.call_args[0][0] == "Home.py"

def test_admin_non_admin_blocked(admin_app):
    admin_app.session_state.authenticated = True
    admin_app.session_state.role = "user"
    admin_app.run()
    assert any("Unauthorized Access" in e.value for e in admin_app.error)

def test_admin_dashboard_metrics(admin_app, mock_db_connection):
    admin_app.session_state.authenticated = True
    admin_app.session_state.role = "admin"
    
    # Pre-seed metrics data
    mock_db_connection["datasets"].insert_one({"filePath": "test.pdf", "status": "INDEXED"})
    mock_db_connection["llmConfigs"].insert_one({"config_id": "default_rag_config", "LLM_MODEL": "gemini-test-model"})
    mock_db_connection["feedback"].insert_one({"rating": 5, "comment": "Excellent!"})
    
    admin_app.run()
    assert not admin_app.exception
    assert any("Connected to MongoDB Atlas" in s.value for s in admin_app.success)
    
    # Assert metric displays
    metrics = [m.label for m in admin_app.metric]
    assert "Total Files in Library" in metrics
    assert "Active LLM Model" in metrics
    assert "Total Feedback" in metrics
