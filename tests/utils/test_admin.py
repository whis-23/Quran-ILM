import pytest
from utils import admin_utils
from tests.mock_mongo import MockGridFS

def test_normalize_path():
    assert admin_utils.normalize_path("folder\\file.txt") == "folder/file.txt"
    assert admin_utils.normalize_path("/folder/test/") == "folder/test"

def test_delete_files(mock_db_connection):
    # Setup Stub Db with fake files
    mock_db_connection["datasets"].insert_one({
        "filePath": "test_doc.pdf",
        "status": "INDEXED"
    })
    
    mock_db_connection["ragChunks"].insert_one({
        "metadata": {"source": "test_doc.pdf"},
        "text": "sample text chunk"
    })
    
    # We must mock GridFS explicitly since delete_files accepts it as a parameter
    mock_fs = MockGridFS()
    mock_fs.put(b"fake data", filename="test_doc.pdf")
    
    # Run the utility function
    deleted_count, errors = admin_utils.delete_files(["test_doc.pdf"], mock_db_connection, mock_fs)
    
    # Verify outputs
    assert deleted_count == 1
    assert len(errors) == 0
    
    # Verify Data Sources were cleared correctly
    assert mock_db_connection["datasets"].count_documents({"filePath": "test_doc.pdf"}) == 0
    assert mock_db_connection["ragChunks"].count_documents({"metadata.source": "test_doc.pdf"}) == 0
    assert mock_fs.exists({"filename": "test_doc.pdf"}) is False

from unittest.mock import patch

import importlib
import utils.admin_utils

def test_init_connection_no_uri():
    with patch("streamlit.cache_resource", lambda **k: lambda f: f):
        reloaded_admin = importlib.reload(utils.admin_utils)
        
    with patch("utils.config.MONGO_URI", None):
        client, db, fs = reloaded_admin.init_connection()
        assert client is None

def test_init_connection_exception():
    with patch("streamlit.cache_resource", lambda **k: lambda f: f):
        reloaded_admin = importlib.reload(utils.admin_utils)
        
    with patch("pymongo.MongoClient", side_effect=Exception("DB boom")):
        client, db, fs = reloaded_admin.init_connection()
        assert client is None

def test_delete_files_rag_db_exception(mock_db_connection):
    mock_fs = MockGridFS()
    with patch("utils.config.MONGO_RAG_URI", "mongodb://localhost"), \
         patch("pymongo.MongoClient", side_effect=Exception("RAG DB boom")):
        deleted_count, errors = admin_utils.delete_files(["ghost.pdf"], mock_db_connection, mock_fs)
        assert len(errors) == 1
        assert "Could not connect to RAG DB" in errors[0]

def test_delete_files_no_gridfs_file(mock_db_connection):
    mock_fs = MockGridFS()
    mock_db_connection["datasets"].insert_one({"filePath": "ghost.pdf"})
    
    with patch("utils.config.MONGO_RAG_URI", None):
        deleted_count, errors = admin_utils.delete_files(["ghost.pdf"], mock_db_connection, mock_fs)
        
    assert deleted_count == 1
    assert mock_db_connection["datasets"].count_documents({"filePath": "ghost.pdf"}) == 0

def test_delete_files_exception_during_delete(mock_db_connection):
    mock_fs = MockGridFS()
    
    from tests.mock_mongo import MockCollection
    with patch.object(MockCollection, "delete_one", side_effect=Exception("Delete boom")):
        deleted_count, errors = admin_utils.delete_files(["ghost.pdf"], mock_db_connection, mock_fs)
        
    assert deleted_count == 0
    assert len(errors) == 1
    assert "Error deleting" in errors[0]
