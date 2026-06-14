import pytest
from streamlit.testing.v1 import AppTest
from unittest.mock import patch, MagicMock

@pytest.fixture
def rag_config_app(mock_db_connection):
    at = AppTest.from_file("views/rag_configuration.py")
    yield at

def test_rag_config_unauthorized_redirect(rag_config_app):
    rag_config_app.session_state.authenticated = False
    with patch("streamlit.switch_page") as mock_switch:
        rag_config_app.run()
        assert mock_switch.called

def test_rag_config_load_and_save(rag_config_app, mock_db_connection):
    rag_config_app.session_state.authenticated = True
    rag_config_app.session_state.role = "admin"
    
    # Load form initially
    rag_config_app.run()
    assert not rag_config_app.exception
    
    # Fill in configuration values
    rag_config_app.text_input[0].input("new-google-key")
    rag_config_app.text_input[1].input("gemini-1.5-pro")
    rag_config_app.text_input[2].input("gemini-embedding-002")
    rag_config_app.number_input[0].set_value(10) # Top K
    rag_config_app.number_input[1].set_value(600) # Chunk size
    rag_config_app.number_input[2].set_value(100) # Chunk overlap
    rag_config_app.slider[0].set_value(0.5).run() # Temperature
    
    # Save configuration
    save_btn = next(b for b in rag_config_app.button if "Save Configuration" in b.label)
    save_btn.click().run()
    
    # Assert settings were saved in Mongo DB stub
    saved_doc = mock_db_connection["llmConfigs"].find_one({"config_id": "default_rag_config"})
    assert saved_doc is not None
    assert saved_doc["GOOGLE_API_KEY"] == "new-google-key"
    assert saved_doc["LLM_MODEL"] == "gemini-1.5-pro"
    assert saved_doc["TOP_K"] == 10
    assert saved_doc["TEMPERATURE"] == 0.5

def test_rag_config_start_indexing_pipeline(rag_config_app, mock_db_connection):
    rag_config_app.session_state.authenticated = True
    rag_config_app.session_state.role = "admin"
    rag_config_app.run()
    
    # Index trigger
    index_btn = next(b for b in rag_config_app.button if "Start Full Indexing" in b.label)
    with patch("subprocess.Popen") as mock_popen:
        mock_process = MagicMock()
        mock_process.poll.return_value = 0
        mock_process.stdout.readline.side_effect = ["Indexing... done", ""]
        mock_popen.return_value = mock_process
        
        index_btn.click().run()
        assert mock_popen.called


def test_rag_config_google_key_required(rag_config_app):
    rag_config_app.session_state.authenticated = True
    rag_config_app.session_state.role = "admin"
    rag_config_app.run()
    
    rag_config_app.text_input[0].input("")
    
    btn = next(b for b in rag_config_app.button if "Save Configuration" in b.label)
    btn.click().run()
    
    assert any("Google API Key is required." in e.value for e in rag_config_app.error)


def test_rag_config_load_db_error(rag_config_app, mock_db_connection):
    rag_config_app.session_state.authenticated = True
    rag_config_app.session_state.role = "admin"
    
    from pymongo.errors import PyMongoError
    from tests.mock_mongo import MockCollection
    
    with patch.object(MockCollection, "find_one", side_effect=PyMongoError("Find error")):
        rag_config_app.run()
        
    assert any("Failed to load config from DB" in e.value for e in rag_config_app.error)


def test_rag_config_save_db_error(rag_config_app, mock_db_connection):
    rag_config_app.session_state.authenticated = True
    rag_config_app.session_state.role = "admin"
    rag_config_app.run()
    
    rag_config_app.text_input[0].input("somekey")
    btn = next(b for b in rag_config_app.button if "Save Configuration" in b.label)
    
    from pymongo.errors import PyMongoError
    from tests.mock_mongo import MockCollection
    
    with patch.object(MockCollection, "update_one", side_effect=PyMongoError("Update error")):
        btn.click().run()
        
    assert any("Failed to save config" in e.value for e in rag_config_app.error)


def test_rag_config_indexing_job_failed(rag_config_app, mock_db_connection):
    rag_config_app.session_state.authenticated = True
    rag_config_app.session_state.role = "admin"
    rag_config_app.run()
    
    btn = next(b for b in rag_config_app.button if "Start Full Indexing" in b.label)
    with patch("subprocess.Popen") as mock_popen:
        mock_process = MagicMock()
        mock_process.poll.return_value = 1
        mock_process.stdout.readline.side_effect = ["Starting...", "Indexing failed due to error", ""]
        mock_popen.return_value = mock_process
        
        btn.click().run()
        assert any("Indexing Failed." in e.value for e in rag_config_app.error)

