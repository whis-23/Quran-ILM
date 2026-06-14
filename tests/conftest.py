import pytest
import sys
import os
from unittest.mock import patch
from .mock_mongo import MockMongoClient, MockGridFS, save_db

# Make sure the root is in sys.path so utils imports work
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Set mock environment variables for testing
os.environ["GOOGLE_API_KEY"] = "mock-google-key"
os.environ["MONGO_URI"] = "mongodb://localhost"
os.environ["MONGO_DB_NAME"] = "mock_db"
os.environ["MONGO_RAG_URI"] = "mongodb://localhost"
os.environ["MONGO_RAG_DB_NAME"] = "mock_rag_db"

@pytest.fixture(autouse=True)
def mock_db_connection():
    """
    Clears the JSON file and forces all database interactions to use 
    the MockMongoClient instead of an actual MongoDB connection.
    """
    save_db({}) 

    mock_client = MockMongoClient()
    mock_db = mock_client["quran_ilm_test_db"]
    mock_fs = MockGridFS()

    # 1. Patch the connection initializer and PyMongo globally
    with patch("utils.admin_utils.init_connection", return_value=(mock_client, mock_db, mock_fs)), \
         patch("pymongo.MongoClient", return_value=mock_client):
        
        # 2. Patch module-level persistent DB references
        # Since some files like auth_utils declare `client, db, fs = init_connection()` 
        # at the module level immediately on import, we explicitly overwrite them.
        try:
            from utils import auth_utils
            auth_utils.client = mock_client
            auth_utils.db = mock_db
            auth_utils.fs = mock_fs
            auth_utils.users_collection = mock_db["users"]
        except ImportError:
            pass
            
        yield mock_db
