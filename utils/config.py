import os
import streamlit as st
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

def get_env(key, default=None, secret_path=None):
    """
    Retrieves configuration value with the following priority:
    1. System Environment Variable (os.environ)
    2. Streamlit Secrets (st.secrets) - if secret_path is provided
    3. Default value
    """
    # 1. Environment Variable
    value = os.getenv(key)
    if value is not None:
        return value

    # 2. Streamlit Secrets
    try:
        if secret_path:
            val = st.secrets
            for k in secret_path:
                val = val[k]
            return val
        else:
            return st.secrets[key]
    except (KeyError, FileNotFoundError, AttributeError, TypeError):
        pass

    return default

# ==========================================
# DATABASE CONFIGURATION
# ==========================================
MONGO_URI = get_env("MONGO_URI", secret_path=("mongodb", "uri"))
MONGO_DB_NAME = get_env("MONGO_DB_NAME", "Quran_Metadata")

MONGO_RAG_URI = get_env("MONGO_RAG_URI") 
MONGO_RAG_DB_NAME = get_env("MONGO_RAG_DB_NAME", "Quran_RAG_Vectors")

# ==========================================
# EMAIL / SMTP CONFIGURATION
# ==========================================
SMTP_SERVER = get_env("SMTP_SERVER", "smtp.gmail.com")
_smtp_port = get_env("SMTP_PORT", "587")
SMTP_PORT = int(_smtp_port) if _smtp_port else 587

SMTP_EMAIL = get_env("SMTP_EMAIL")
SMTP_PASSWORD = get_env("SMTP_PASSWORD")

# ==========================================
# AI / LLM CONFIGURATION
# ==========================================
GOOGLE_API_KEY = get_env("GOOGLE_API_KEY") 
EMBEDDING_DIMENSIONS = 3072

# ==========================================
# AUTHENTICATION CONFIGURATION (Descope)
# ==========================================
DESCOPE_PROJECT_ID = get_env("DESCOPE_PROJECT_ID") 
BASE_URL = get_env("BASE_URL") 
RESTRICTED_EMAILS = [SMTP_EMAIL] if SMTP_EMAIL else []

# ==========================================
# INGESTION CONFIGURATION
# ==========================================
TARGET_FILES_LIST = get_env("TARGET_FILES_LIST")
