import pytest
from streamlit.testing.v1 import AppTest
from unittest.mock import patch, MagicMock
import pandas as pd
from datetime import datetime

@pytest.fixture
def analytics_app(mock_db_connection):
    at = AppTest.from_file("views/analytics.py")
    yield at

def test_analytics_unauthorized_redirect(analytics_app):
    analytics_app.session_state.authenticated = False
    with patch("streamlit.switch_page") as mock_switch:
        analytics_app.run()
        assert mock_switch.called

def test_analytics_empty_db(analytics_app, mock_db_connection):
    analytics_app.session_state.authenticated = True
    analytics_app.session_state.role = "admin"
    
    # Mock database command stats
    mock_db_stats = {
        "dataSize": 1024 * 1024,
        "storageSize": 2 * 1024 * 1024,
        "objects": 50,
        "avgObjSize": 2048
    }
    mock_coll_stats = {
        "count": 50,
        "size": 1024 * 1024,
        "avgObjSize": 2048
    }
    
    # We must patch command on MockDatabase since it runs command("dbStats") and command("collStats")
    from tests.mock_mongo import MockDatabase
    with patch.object(MockDatabase, "command") as mock_cmd, \
         patch.object(MockDatabase, "list_collection_names", return_value=["chats"]):
        mock_cmd.side_effect = lambda cmd, *args, **kwargs: mock_db_stats if cmd == "dbStats" else mock_coll_stats
        
        analytics_app.run()
        assert not analytics_app.exception
        # Should display info if chats collection has no data
        assert any("No chat history found" in i.value for i in analytics_app.info)

def test_analytics_with_chat_history(analytics_app, mock_db_connection):
    analytics_app.session_state.authenticated = True
    analytics_app.session_state.role = "admin"
    
    # Mock stats
    mock_db_stats = {
        "dataSize": 1024 * 1024,
        "storageSize": 2 * 1024 * 1024,
        "objects": 5,
        "avgObjSize": 2048
    }
    mock_coll_stats = {
        "count": 5,
        "size": 1024 * 1024,
        "avgObjSize": 2048
    }
    
    # Populate chats collection
    # Note: views/analytics.py queries db_meta["chats"].find(...)
    mock_db_connection["chats"].insert_one({
        "timestamp": datetime.utcnow(),
        "tokens": {"total_tokens": 1500}
    })
    mock_db_connection["chats"].insert_one({
        "timestamp": datetime.utcnow(),
        "tokens": {"total_tokens": 2500}
    })
    
    from tests.mock_mongo import MockDatabase
    with patch.object(MockDatabase, "command") as mock_cmd, \
         patch.object(MockDatabase, "list_collection_names", return_value=["chats"]):
        mock_cmd.side_effect = lambda cmd, *args, **kwargs: mock_db_stats if cmd == "dbStats" else mock_coll_stats
        
        analytics_app.run()
        assert not analytics_app.exception
        
        # Verify metric calculation
        metrics = {m.label: m.value for m in analytics_app.metric}
        assert "Total Conversations" in metrics
        assert "Total Tokens Consumed" in metrics
        assert metrics["Total Conversations"] == "2"
        assert metrics["Total Tokens Consumed"] == "4,000"
