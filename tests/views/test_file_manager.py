import pytest
from streamlit.testing.v1 import AppTest
from unittest.mock import patch, MagicMock
import io

@pytest.fixture
def file_manager_app(mock_db_connection):
    at = AppTest.from_file("views/file_manager.py")
    yield at

def test_file_manager_unauthorized_redirect(file_manager_app):
    file_manager_app.session_state.authenticated = False
    with patch("streamlit.switch_page") as mock_switch:
        file_manager_app.run()
        assert mock_switch.called

def test_file_manager_rendering_and_upload(file_manager_app, mock_db_connection):
    file_manager_app.session_state.authenticated = True
    file_manager_app.session_state.role = "admin"
    
    file_manager_app.run()
    assert not file_manager_app.exception
    
    # Check upload section exists
    assert any("Upload Files" in s.value for s in file_manager_app.subheader)
    
    # Simulate uploading a file
    mock_file = io.BytesIO(b"Dummy PDF content")
    mock_file.name = "test_document.pdf"
    
    # Mock GridFS put & streamlit file uploader
    with patch("streamlit.file_uploader", return_value=[mock_file]):
        file_manager_app.run()
        # Find upload button
        btn = next(b for b in file_manager_app.button if b.label == "Start GridFS Upload")
        with patch("streamlit.rerun"):
            btn.click().run()
            
    # Verify metadata synced in Mongo DB stub
    dataset = mock_db_connection["datasets"].find_one({"filePath": "test_document.pdf"})
    assert dataset is not None
    assert dataset["status"] == "PENDING"

def test_file_manager_trigger_indexing(file_manager_app, mock_db_connection):
    file_manager_app.session_state.authenticated = True
    file_manager_app.session_state.role = "admin"
    
    # Seed a pending file
    mock_db_connection["datasets"].insert_one({
        "filePath": "pending_doc.pdf",
        "status": "PENDING",
        "dataType": "Uploaded"
    })
    
    file_manager_app.run()
    
    # Since we can edit the selection in the dataframe editor, we mock the button behavior:
    # We click 'Index Selected Files (RAG)' button after stubbing selection.
    # To mock selection in st.data_editor, we can pass edited_df output directly via mocks or session state.
    # We will mock subprocess.Popen so we don't actually execute the indexing script
    with patch("subprocess.Popen") as mock_popen:
        mock_process = MagicMock()
        mock_process.poll.return_value = 0
        mock_process.stdout.readline.side_effect = ["Starting...", "[UI_PROGRESS] 1/1", ""]
        mock_popen.return_value = mock_process
        
        # We can trigger the RAG Index button directly
        # Let's search if the button exists in render
        # In file_manager.py, the action buttons are displayed once rows are selected.
        # So we can patch pandas.DataFrame returned by st.data_editor to have Selected = True
        import pandas as pd
        mock_df = pd.DataFrame([{"Selected": True, "filePath": "pending_doc.pdf", "status": "PENDING", "dataType": "Uploaded", "uploadDate": None}])
        with patch("streamlit.data_editor", return_value=mock_df):
            file_manager_app.run()
            # Click the Index button
            btn = next(b for b in file_manager_app.button if "Index Selected" in b.label)
            with patch("streamlit.rerun"):
                btn.click().run()
                assert mock_popen.called


def test_file_manager_db_connection_fail(file_manager_app):
    file_manager_app.session_state.authenticated = True
    file_manager_app.session_state.role = "admin"
    with patch("utils.admin_utils.init_connection", return_value=(None, None, None)):
        file_manager_app.run()
        assert any("Database connection failed." in e.value for e in file_manager_app.error)


def test_file_manager_non_admin_blocked(file_manager_app):
    file_manager_app.session_state.authenticated = True
    file_manager_app.session_state.role = "user"
    file_manager_app.run()
    assert any("Unauthorized Access" in e.value for e in file_manager_app.error)


def test_file_manager_missing_api_key_for_indexing(file_manager_app, mock_db_connection):
    file_manager_app.session_state.authenticated = True
    file_manager_app.session_state.role = "admin"
    
    mock_db_connection["datasets"].insert_one({
        "filePath": "pending_doc.pdf",
        "status": "PENDING",
        "dataType": "Uploaded"
    })
    
    import pandas as pd
    mock_df = pd.DataFrame([{"Selected": True, "filePath": "pending_doc.pdf", "status": "PENDING", "dataType": "Uploaded", "uploadDate": None}])
    with patch("streamlit.data_editor", return_value=mock_df), \
         patch("utils.config.GOOGLE_API_KEY", None), \
         patch("os.getenv", return_value=None):
        file_manager_app.run()
        btn = next(b for b in file_manager_app.button if "Index Selected" in b.label)
        btn.click().run()
        assert any("Google API Key missing" in e.value for e in file_manager_app.error)


def test_file_manager_indexing_job_failed(file_manager_app, mock_db_connection):
    file_manager_app.session_state.authenticated = True
    file_manager_app.session_state.role = "admin"
    
    mock_db_connection["datasets"].insert_one({
        "filePath": "pending_doc.pdf",
        "status": "PENDING",
        "dataType": "Uploaded"
    })
    
    import pandas as pd
    mock_df = pd.DataFrame([{"Selected": True, "filePath": "pending_doc.pdf", "status": "PENDING", "dataType": "Uploaded", "uploadDate": None}])
    with patch("streamlit.data_editor", return_value=mock_df):
        file_manager_app.run()
        
        with patch("subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.poll.return_value = 1
            mock_process.stdout.readline.side_effect = ["Error indexing file...", ""]
            mock_popen.return_value = mock_process
            
            btn = next(b for b in file_manager_app.button if "Index Selected" in b.label)
            btn.click().run()
            
            assert any("Indexing job failed" in e.value for e in file_manager_app.error)

