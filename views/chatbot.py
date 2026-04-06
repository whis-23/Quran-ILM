import streamlit as st
import pymongo
import os
import io
import google.generativeai as genai
from datetime import datetime
from utils import config
import time
import uuid
from utils.auth_utils import send_email

# --- CONFIGURATION (Default Fallbacks) ---
DEFAULT_RAG_DB = "Quran_RAG_Vectors"
VECTOR_COLLECTION = "ragChunks"

# --- 1. INITIALIZATION & CONFIG LOADING ---
@st.cache_resource
def init_resources():
    # A. Connect to Primary DB (Metadata & Config)
    mongo_uri = config.MONGO_URI
    db_name = config.MONGO_DB_NAME
    
    if not mongo_uri:
        st.error("MONGO_URI not found.")
        st.stop()
        
    client_meta = pymongo.MongoClient(mongo_uri)
    db_meta = client_meta[db_name]
    
    # B. Load LLM Configuration from DB
    try:
        config_doc = db_meta["llmConfigs"].find_one({"config_id": "default_rag_config"}) or {}
    except Exception as e:
        st.warning(f"Could not load config from DB: {e}")
        config_doc = {}
        
    # Helper to resolve Config Priority: DB > Env > Default
    def get_conf(key, default):
        # Prefer MongoDB config if it exists and is not empty string, otherwise fallback to Env/Secret/Default
        db_val = config_doc.get(key)
        if db_val and str(db_val).strip():
            return db_val
        return config.get_env(key, default)

    google_api_key = config.get_env("GOOGLE_API_KEY", "")  # Always from env — paid key must not be overridden by DB
    llm_model_name = get_conf("LLM_MODEL", "gemini-2.5-flash")
    embedding_model_name = get_conf("EMBEDDING_MODEL", "gemini-embedding-001")
    top_k = int(get_conf("TOP_K", 5))
    temperature = float(get_conf("TEMPERATURE", 0.3))
    
    if not google_api_key:
        st.error("Google API Key not found. Please configure it in 'manage_dataset.py'.")
        st.stop()
        
    # Configure GenAI
    genai.configure(api_key=google_api_key)
        
    # C. Connect to RAG DB (Vectors)
    mongo_rag_uri = config.MONGO_RAG_URI
    rag_db_name = config.MONGO_RAG_DB_NAME
    
    if not mongo_rag_uri:
        st.error("MONGO_RAG_URI not found.")
        st.stop()
        
    client_rag = pymongo.MongoClient(mongo_rag_uri)
    db_rag = client_rag[rag_db_name]
    collection_rag = db_rag[VECTOR_COLLECTION]
    
    return collection_rag, db_meta, embedding_model_name, llm_model_name, top_k, temperature

# Initialize
try:
    collection_rag, db_meta, EMBEDDING_MODEL, LLM_MODEL, TOP_K, TEMPERATURE = init_resources()
except Exception as e:
    st.error(f"Initialization Error: {e}")
    st.stop()

# --- 2. SESSION MANAGEMENT ---

# Guest question limit (how many free questions before signup prompt)
GUEST_QUESTION_LIMIT = 3

if "current_chat_id" not in st.session_state:
    st.session_state.current_chat_id = None
if "messages" not in st.session_state:
    st.session_state.messages = []
if "temp_mode" not in st.session_state:
    st.session_state.temp_mode = False
if "guest_question_count" not in st.session_state:
    st.session_state.guest_question_count = 0
if "show_signup_prompt" not in st.session_state:
    st.session_state.show_signup_prompt = False
# Track auth state across reruns to detect guest→login transition
if "_was_guest" not in st.session_state:
    st.session_state._was_guest = True

def create_new_chat():
    """Starts a new chat session. Preserves any current temp_mode setting."""
    st.session_state.current_chat_id = str(uuid.uuid4())
    st.session_state.messages = []
    # NOTE: deliberately NOT resetting temp_mode here — let the caller control it

def load_chat(chat_id):
    """Loads a chat from DB."""
    chat_doc = db_meta["chat_sessions"].find_one({"_id": chat_id})
    if chat_doc:
        st.session_state.current_chat_id = chat_id
        st.session_state.messages = chat_doc.get("messages", [])
        st.session_state.temp_mode = chat_doc.get("is_temp", False)
    else:
         st.error("Chat not found.")

def delete_chat(chat_id):
    db_meta["chat_sessions"].delete_one({"_id": chat_id})
    if st.session_state.current_chat_id == chat_id:
        create_new_chat()
    st.rerun()

def rename_chat(chat_id, new_title):
    db_meta["chat_sessions"].update_one({"_id": chat_id}, {"$set": {"title": new_title}})
    st.rerun()

def toggle_bookmark(chat_id, current_status):
    """Toggles the bookmark status of a chat."""
    new_status = not current_status
    db_meta["chat_sessions"].update_one({"_id": chat_id}, {"$set": {"is_bookmarked": new_status}})
    st.rerun()

@st.dialog("Rename Chat")
def rename_dialog(chat_id, current_title):
    new_name = st.text_input("Enter new name", value=current_title)
    if st.button("Save Name"):
        rename_chat(chat_id, new_name)
        st.rerun()

# --- 3. VECTOR SEARCH FUNCTION ---
def vector_search(query, k=5):
    """
    Performs Atlas Vector Search using the raw MongoDB Aggregation pipeline.
    """
    # 1. Embed Query
    try:
        embedding_result = genai.embed_content(
            model=EMBEDDING_MODEL,
            content=query,
            task_type="retrieval_query",
            output_dimensionality=3072 # Force 3072 dimensions to match data
        )
        query_vector = embedding_result['embedding']
    except Exception as e:
        st.error(f"Embedding Error: {e}")
        return []

    # 2. Aggregation Pipeline
    pipeline = [
        {
            "$vectorSearch": {
                "index": "default", 
                "path": "embedding",
                "queryVector": query_vector,
                "numCandidates": 100, 
                "limit": k
            }
        },
        {
            "$project": {
                "_id": 0,
                "text": 1,
                "metadata": 1,
                "score": {"$meta": "vectorSearchScore"}
            }
        }
    ]
    
    # 3. Execute
    try:
        results = list(collection_rag.aggregate(pipeline))
        return results
    except pymongo.errors.OperationFailure as e:
        st.error(f"MongoDB OperationFailure: {e.details}")
        print(f"MongoDB OperationFailure: {e.details}") # Log to console
        return []
    except Exception as e:
        st.error(f"Vector Search Error: {e}")
        print(f"Vector Search Error: {e}")
        return []

# --- 3. UI LAYOUT & SIDEBAR ---

# Custom CSS — icon toolbar inside chat input bar
st.markdown("""
<style>
    /* ── AUDIO INPUT (Microphone): Placed inside right of Chat Input ── */
    div[data-testid="stAudioInput"] label { display: none; }
    div[data-testid="stAudioInput"] {
        position: fixed;
        bottom: 82px;
        right: 150px; /* Snugly aligned to the left of the fast-send button */
        z-index: 1001;
        width: 36px;
        height: 36px;
    }
    div[data-testid="stAudioInput"] > div {
        background-color: transparent !important;
        border: none !important;
        box-shadow: none !important;
        padding: 0 !important;
        margin: 0 !important;
    }
    div[data-testid="stAudioInput"] canvas,
    div[data-testid="stAudioInput"] audio,
    div[data-testid="stAudioInput"] div[data-testid="stMarkdownContainer"] {
        display: none !important;
    }
    div[data-testid="stAudioInput"] button {
        background-color: transparent !important;
        border: 1.5px solid rgba(150,150,150,0.3) !important;
        color: #6b7280 !important;
        padding: 0 !important;
        width: 36px !important;
        height: 36px !important;
        border-radius: 50% !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        transition: border-color 0.2s, color 0.2s, background 0.2s !important;
    }
    div[data-testid="stAudioInput"] button:hover {
        color: #8B6BB1 !important;
        border-color: #8B6BB1 !important;
        background-color: rgba(139,107,177,0.07) !important;
    }

    /* ── Chat input: push placeholder text right to clear the Mic & Native Attachment icons ── */
    div[data-testid="stChatInput"] textarea {
        padding-right: 90px !important;
    }
</style>
""", unsafe_allow_html=True)

# --- FILE EXTRACTION HELPER ---
DOC_MIME_TYPES = {
    "pdf":  "application/pdf",
    "txt":  "text/plain",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "png":  "image/png",
    "jpg":  "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif":  "image/gif",
}
IMAGE_EXTS = {"png", "jpg", "jpeg", "webp", "gif"}

def extract_file_content(uploaded_file):
    """
    Returns (content, mime_type, is_image).
    - For images: content = raw bytes, is_image = True
    - For text/pdf/docx: content = extracted str, is_image = False
    """
    ext = uploaded_file.name.rsplit(".", 1)[-1].lower()
    mime = DOC_MIME_TYPES.get(ext, "application/octet-stream")
    raw = uploaded_file.getvalue()

    if ext in IMAGE_EXTS:
        return raw, mime, True

    if ext == "pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(raw))
            text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
            return text.strip(), mime, False
        except Exception as e:
            return f"[PDF extraction failed: {e}]", mime, False

    if ext == "docx":
        try:
            from docx import Document
            doc = Document(io.BytesIO(raw))
            text = "\n".join(p.text for p in doc.paragraphs)
            return text.strip(), mime, False
        except Exception as e:
            return f"[DOCX extraction failed: {e}]", mime, False

    if ext == "txt":
        return raw.decode("utf-8", errors="replace").strip(), mime, False

    return f"[Unsupported file type: {ext}]", mime, False

# --- AUTH / GUEST CHECK ---
IS_GUEST = not st.session_state.get("authenticated", False)

# --- FIX: Clear guest messages when user logs in ---
if st.session_state._was_guest and not IS_GUEST:
    # User just transitioned from guest → authenticated: wipe the guest chat
    st.session_state.messages = []
    st.session_state.current_chat_id = None
    st.session_state.guest_question_count = 0
st.session_state._was_guest = IS_GUEST  # Update tracker for next rerun

# --- SAVE NUDGE DIALOG (ChatGPT-style) ---
@st.dialog("💾 Save Your Conversations")
def show_signup_prompt():
    c1, c2, c3 = st.columns([1, 1, 1])
    with c2:
        st.image("quran_ilm.png", use_container_width=True)
    st.markdown("""
    <div style="text-align:center; padding: 10px 0;">
        <h3 style="margin:0; color:#1f2937;">Don't lose your insights</h3>
        <p style="color:#6b7280; font-size:0.95rem; margin-top:8px;">
            Create a free account to save your chat history and
            revisit your Quranic guidance anytime.
        </p>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🚀 Sign Up Free", type="primary", use_container_width=True, key="dialog_signup"):
            st.session_state.auth_mode = "signup"
            st.session_state.show_login_page = True
            st.session_state.show_signup_prompt = False
            st.rerun()
    with col2:
        if st.button("🔐 Sign In", use_container_width=True, key="dialog_signin"):
            st.session_state.auth_mode = "login"
            st.session_state.show_login_page = True
            st.session_state.show_signup_prompt = False
            st.rerun()
    
    st.write("")
    if st.button("Continue without account", use_container_width=True, key="dialog_dismiss"):
        st.session_state.show_signup_prompt = False
        st.rerun()
    
    st.markdown("<p style='text-align:center; color:#9ca3af; font-size:0.8rem; margin-top:8px;'>No credit card required.</p>", unsafe_allow_html=True)

# --- SIDEBAR ---
with st.sidebar:
    # st.logo("quran_ilm.png")  # Removed mini logo

    if IS_GUEST:
        # Guest: minimal sidebar — just sign in/up options
        c1, c2, c3 = st.columns([0.3, 1, 0.3])
        with c2:
            st.image("quran_ilm.png", use_container_width=True)
        st.write("")
        st.markdown("<p style='color:#6b7280; font-size:0.85rem; text-align:center;'>Ask questions about the Quran and Tafsir.</p>", unsafe_allow_html=True)
        st.write("---")
        if st.button("🚀 Sign Up Free", type="primary", use_container_width=True, key="sidebar_signup"):
            st.session_state.auth_mode = "signup"
            st.session_state.show_login_page = True
            st.rerun()
        if st.button("🔐 Sign In", use_container_width=True, key="sidebar_signin"):
            st.session_state.auth_mode = "login"
            st.session_state.show_login_page = True
            st.rerun()
        # Track remaining questions silently (used to trigger signup nudge)
        remaining = max(0, GUEST_QUESTION_LIMIT - st.session_state.guest_question_count)
    else:
        # Authenticated: full chat history sidebar
        st.title("💬 Chats")
        
        # New Chat Button
        if st.button("➕ New Chat", use_container_width=True, type="primary"):
            st.session_state.temp_mode = False  # Always exit temp mode on new chat
            create_new_chat()
            st.rerun()
        
        # Temp Mode Toggle
        st.write("---")
        is_temp = st.toggle("🕵️ Temp Chat (No Save)", value=st.session_state.temp_mode)
        if is_temp != st.session_state.temp_mode:
            # Toggling either direction: set mode, clear messages, assign fresh chat ID
            # (do NOT set current_chat_id=None — that fires create_new_chat which used to reset temp_mode)
            st.session_state.temp_mode = is_temp
            st.session_state.messages = []
            st.session_state.current_chat_id = str(uuid.uuid4())
            st.rerun()
        
        # Search & Sort
        st.write("---")
        search_query = st.text_input("🔍 Search", placeholder="Filter by name...", label_visibility="collapsed")
        
        # Sort Options
        c_sort1, c_sort2 = st.columns([0.3, 0.7])
        with c_sort1:
            st.caption("Sort:")
        with c_sort2:
            sort_option = st.selectbox("Sort By", ["Recent", "Name"], label_visibility="collapsed")
            
        sort_order = pymongo.DESCENDING if sort_option == "Recent" else pymongo.ASCENDING
        sort_field = "updated_at" if sort_option == "Recent" else "title"
        
        # Fetch User's Chats
        user_email = st.session_state.get("user_email")
        if user_email:
            # Fetch all non-temp chats
            all_chats = list(db_meta["chat_sessions"].find(
                {"user_email": user_email, "is_temp": False}, 
                {"title": 1, "updated_at": 1, "is_bookmarked": 1}
            ).sort(sort_field, sort_order))
            
            # Filter by Search Query
            if search_query:
                all_chats = [c for c in all_chats if search_query.lower() in c.get("title", "").lower()]
            
            # Filter Bookmarks
            bookmarked_chats = [c for c in all_chats if c.get("is_bookmarked")]
            
            # --- SECTION: BOOKMARKS ---
            if bookmarked_chats:
                st.caption(f"⭐ Bookmarked ({len(bookmarked_chats)})")
                for chat in bookmarked_chats:
                    c1, c2 = st.columns([0.8, 0.2])
                    with c1:
                        title = chat.get("title", "Untitled")
                        if st.button(f"⭐ {title}", key=f"bm_load_{chat['_id']}", use_container_width=True):
                            load_chat(chat["_id"])
                            st.rerun()
                    with c2:
                        with st.popover("⋮", use_container_width=True):
                            if st.button("Rename", key=f"r_bm_{chat['_id']}"):
                                rename_dialog(chat["_id"], chat.get("title", ""))
                            if st.button("Un-Bookmark", key=f"unbm_{chat['_id']}"):
                                toggle_bookmark(chat["_id"], True)
                            if st.button("Delete", key=f"del_bm_{chat['_id']}", type="primary"):
                                delete_chat(chat["_id"])
                st.write("---")
            else:
                st.caption("⭐ 0 Bookmarked")
                st.write("---")

            # --- SECTION: HISTORY ---
            st.caption(f"🕒 History ({len(all_chats)})")
            
            for chat in all_chats:
                c1, c2 = st.columns([0.8, 0.2])
                with c1:
                    title = chat.get("title", "Untitled Chat")
                    if len(title) > 20: title = title[:20] + "..."
                    clicked = st.button(title, key=f"load_{chat['_id']}", use_container_width=True)
                    if clicked:
                        load_chat(chat["_id"])
                        st.rerun()
                with c2:
                    with st.popover("⋮", use_container_width=True):
                        if st.button("Rename", key=f"ren_{chat['_id']}"):
                            rename_dialog(chat["_id"], chat.get("title", ""))
                        is_bm = chat.get("is_bookmarked", False)
                        bm_label = "Un-Bookmark" if is_bm else "Bookmark"
                        if st.button(bm_label, key=f"tog_bm_{chat['_id']}"):
                            toggle_bookmark(chat["_id"], is_bm)
                        if st.button("Delete", key=f"del_{chat['_id']}", type="primary"):
                            delete_chat(chat["_id"])

# --- MAIN PAGE ---

# Center logo like ChatGPT
col1, col2, col3 = st.columns([1, 1, 1])
with col2:
    st.image("quran_ilm.png", use_container_width=True)

st.markdown("<h3 style='text-align: center; margin-bottom: 2rem; color: #4b5563;'>How can I help you today?</h3>", unsafe_allow_html=True)
if st.session_state.temp_mode:
    st.caption("🕵️ **Temporary Mode Active**: Chat will not be saved.")
else:
    st.caption("Ask questions about the Quran and Tafsir. Powered by RAG.")

# Initialize New Chat if needed (First Login generally has none, create one)
if not st.session_state.current_chat_id:
    create_new_chat()

# Display Messages
for i, message in enumerate(st.session_state.messages):
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message.get("references"):
             with st.expander("📚 References", expanded=False):
                for idx, ref in enumerate(message["references"], 1):
                    source = ref.get('source', 'Unknown')
                    score = ref.get('score', 0)
                    st.markdown(f"**[{idx}] {source}** (Confidence: {score:.2f})")
                    
                    if 'tafsir' in ref:
                        st.markdown(f"- **Tafsir/Book:** {ref['tafsir']}")
                        if ref['surah'] != 'N/A':
                            st.markdown(f"- **Surah:** {ref['surah']}")
                        if ref['page'] != 'N/A':
                            st.markdown(f"- **Page:** {ref['page']}")
                        st.caption(f"*\"{ref['snippet']}\"*")
                        st.divider()

        # Optional Speaker Icon for TTS on AI Responses
        if message["role"] == "assistant":
            # Container to align right
            col1, col2 = st.columns([0.95, 0.05])
            with col2:
                if st.button("🔊", key=f"tts_btn_{i}", type="tertiary", help="Listen to this response"):
                    if "audio_bytes" not in message:
                        with st.spinner("..."):
                            try:
                                from gtts import gTTS
                                import io
                                tts = gTTS(text=message["content"], lang='en')
                                fp = io.BytesIO()
                                tts.write_to_fp(fp)
                                message["audio_bytes"] = fp.getvalue()
                            except Exception as e:
                                st.error(f"Failed to generate audio: {e}")
                    
                    if "audio_bytes" in message:
                        import base64
                        b64 = base64.b64encode(message["audio_bytes"]).decode()
                        md = f"""
                            <audio autoplay="true" style="display:none;">
                            <source src="data:audio/mp3;base64,{b64}" type="audio/mp3">
                            </audio>
                            """
                        st.markdown(md, unsafe_allow_html=True)

# --- 4. CHAT LOGIC ---


# Voice Input Logic (Compact & Professional)
audio_value = st.audio_input("Voice Input", label_visibility="collapsed")

prompt = None
audio_prompt = None

if audio_value:
    audio_bytes = audio_value.getvalue()
    if "last_audio_bytes" not in st.session_state or st.session_state.last_audio_bytes != audio_bytes:
        # User Feedback / "Thoughtful" Animation
        with st.status("🎧 Processing Voice Command...", expanded=True) as status:
            st.write("Receiving audio stream...")
            time.sleep(0.5) # Slight delay for effect
            
            st.write("Transcribing with Gemini...")
            try:
                transcription_model = genai.GenerativeModel(LLM_MODEL)
                response = transcription_model.generate_content(
                    [
                        "Transcribe the following audio request into English. If the audio is in another language, translate it to English. Do not add any extra text or commentary.",
                        {"mime_type": "audio/wav", "data": audio_bytes}
                    ]
                )
                
                # Check for valid response
                if response.parts:
                    audio_prompt = response.text.strip()
                    st.session_state.last_audio_bytes = audio_bytes
                    st.toast("✅ Transcription complete!", icon="✅")
                else:
                    # Graceful fallback for empty/blocked responses
                    st.toast("⚠️ No speech detected or audio unclear.", icon="⚠️")
                    
            except ValueError:
                # Handle "Invalid operation: The response.text quick accessor..."
                st.toast("⚠️ Audio processing failed. Please try again.", icon="⚠️")
            except Exception as e:
                # Generic error but log to console, show toast to user
                print(f"Transcription Error: {e}")
                st.toast("⚠️ Error processing audio.", icon="⚠️")
            
            status.update(label="Voice Processed", state="complete", expanded=False)

# Main Chat Input (Text)
accept_exts = None if IS_GUEST else ["png", "jpg", "jpeg", "webp", "gif", "pdf", "txt", "docx"]
text_input = st.chat_input(
    "Ask a question about the Quran...", 
    accept_file=not IS_GUEST, 
    file_type=accept_exts
)

uploaded_file = None

# Determine final prompt source
if text_input:
    # Handle new Streamlit 1.40+ dictionary return for accept_file
    if isinstance(text_input, dict) or hasattr(text_input, "keys"):
        prompt = text_input.get("text", "")
        files = text_input.get("files", [])
        if files:
            uploaded_file = files[0]
            
        # Default text if they attached a file but sent without typing any prompt
        if not prompt and uploaded_file:
            prompt = "Please analyse this file and answer any Quran or Islamic questions related to it. Describe its content."
    else:
        prompt = text_input
elif audio_prompt:
    prompt = audio_prompt

if prompt:
    # Build display label for attachment
    attachment_label = f" \n\n📎 *{uploaded_file.name}*" if uploaded_file else ""

    # 1. Append User Message
    st.session_state.messages.append({"role": "user", "content": prompt + attachment_label})
    
    # Increment guest counter
    if IS_GUEST:
        st.session_state.guest_question_count += 1
    with st.chat_message("user"):
        st.markdown(prompt)
        if uploaded_file:
            ext = uploaded_file.name.rsplit(".", 1)[-1].lower()
            if ext in IMAGE_EXTS:
                st.image(uploaded_file, width=220)
            else:
                st.caption(f"📎 {uploaded_file.name}")
        
    # 2. Save to DB (User) — skip for guests
    if not IS_GUEST and not st.session_state.temp_mode:
        db_meta["chat_sessions"].update_one(
            {"_id": st.session_state.current_chat_id},
            {
                "$set": {
                    "user_email": st.session_state.user_email,
                    "updated_at": datetime.utcnow()
                },
                "$setOnInsert": {"created_at": datetime.utcnow(), "title": "New Chat", "is_temp": False},
                "$push": {"messages": {"role": "user", "content": prompt, "timestamp": datetime.utcnow()}}
            },
            upsert=True
        )

    # 3. Process Response
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        full_response = ""

        # A. Intent Classification (Zero-shot check to save time & prevent hallucination)
        def requires_rag_search(user_prompt, history):
            if len(user_prompt.split()) < 3 and user_prompt.lower() in ["hi", "hello", "salam", "assalamualaikum", "thanks", "ok"]:
                return False
            
            # Build short history string for the classifier
            hist_str = ""
            if history:
                hist_str = "Recent Conversation Context:\n"
                for m in history[-2:]: # Just last 2 messages for quick context
                    role = "User" if m["role"] == "user" else "Assistant"
                    hist_str += f"{role}: {m['content'][:200]}\n"
            
            check_prompt = f"""
            You are an intent classifier. Determine if the user's latest prompt requires searching an Islamic Database (Quran/Tafsir) to answer accurately.
            {hist_str}
            Latest Prompt: '{user_prompt}'
            Reply strictly with YES or NO.
            """
            
            try:
                genai.configure(api_key=google_api_key) 
                checker = genai.GenerativeModel("gemini-2.5-flash") 
                res = checker.generate_content(check_prompt).text.strip().upper()
                return "YES" in res
            except Exception as e:
                return True # Default to RAG on failure
                
        needs_rag = True
        if not uploaded_file: # Always RAG if document is attached for safety
            # We exclude the last message because it's the current prompt
            needs_rag = requires_rag_search(prompt, st.session_state.messages[:-1])

        # B. Vector Search (RAG)
        context_results = []
        with st.status("🔍 Searching Quran & Tafsir..." if needs_rag else "💭 Thinking...", expanded=False) as status:
            if needs_rag:
                context_results = vector_search(prompt, k=TOP_K)
                if context_results:
                    status.write("✅ Found relevant verses.")
                else:
                    status.write("⚠️ No direct matches found. Using scholarly knowledge.")
            else:
                status.write("💬 Conversational query. Skipping database search.")
            status.update(label="Complete", state="complete", expanded=False)

        # C. Extract attachment content
        file_content = None
        file_is_image = False
        file_mime = None
        if uploaded_file:
            uploaded_file.seek(0)
            file_content, file_mime, file_is_image = extract_file_content(uploaded_file)

        # C. Build context string from RAG results
        context_text = ""
        references = []
        for doc in context_results:
            text = doc.get('text', '')
            meta = doc.get('metadata', {})
            source = meta.get('source', 'Unknown')
            tafsir = meta.get('tafsirName', 'Unknown')
            surah = meta.get('surah_number', 'N/A')
            page = meta.get('page_number', meta.get('page', 'N/A'))
            score = doc.get('score', 0)
            
            context_text += f"Source ({source} - {tafsir}):\n{text}\n\n"
            
            # Save rich metadata for the UI expander
            references.append({
                "source": source, 
                "tafsir": tafsir,
                "surah": surah,
                "page": page,
                "score": score,
                "snippet": text[:150] + "..." if len(text) > 150 else text # Provide a small preview
            })

        # D. Generate Answer (multimodal-aware & emotionally intelligent)
        system_instruction = """
        You are a highly intelligent, empathetic, and knowledgeable Islamic scholar assistant named Quran-ILM.
        You have deep conversational memory. Understand the user's emotions, unstated intentions, and context from previous messages.
        
        CRITICAL RULES FOR USING CONTEXT AND ANSWERING:
        1. For questions about Islam, the Quran, or Tafsir: You MUST base your answer primarily on the provided [SYSTEM CONTEXT FROM RAG SEARCH].
        2. IF the user asks an off-topic question (e.g. asking for a recipe, coding help, casual general knowledge not related to Islam): You MUST politely decline to answer. State clearly that your purpose is to discuss the Quran and Islamic topics. Do NOT provide recipes or off-topic information.
        3. For general greetings or emotional expressions (e.g., "hello", "I feel sad"): Respond naturally and warmly as a supportive scholar, offering Islamic comfort or greetings without needing to cite specific texts unless asked.
        
        Act as an intelligent companion — ask clarifying questions if they seem confused, offer comfort if they seem distressed, and ensure your tone is always respectful, patient, and deeply rooted in Islamic wisdom.
        """

        try:
            model = genai.GenerativeModel(LLM_MODEL, system_instruction=system_instruction)

            # E. Build Native Chat History
            # Convert st.session_state.messages (up to the current one) into Gemini format
            gemini_history = []
            # We skip the very last message in session_state because that's the *current* prompt we will send.
            for msg in st.session_state.messages[:-1]:
                # Gemini expects role to be "user" or "model"
                role = "user" if msg["role"] == "user" else "model"
                gemini_history.append({
                    "role": role,
                    "parts": [msg["content"]]
                })
            
            # Start native chat session with the full previous history
            chat_session = model.start_chat(history=gemini_history)

            # Build the current prompt payload (Context + Prompt)
            # The context is invisibly passed to the model alongside the user's text for this turn only.
            base_prompt = (
                f"--- [SYSTEM CONTEXT FROM RAG SEARCH] ---\n{context_text}\n--- [END CONTEXT] ---\n\n"
                f"User's Current Query: {prompt}"
            )

            # Build parts list: text first, then optional file
            parts = [base_prompt]

            if file_content is not None:
                if file_is_image:
                    # Append raw image bytes inline
                    parts[0] += "\n\n[An image has been attached by the user. Please analyze it in relation to their query.]"
                    parts.append({"mime_type": file_mime, "data": file_content})
                else:
                    # Inject extracted document text into the prompt
                    parts = [(
                        f"--- [SYSTEM CONTEXT FROM RAG SEARCH] ---\n{context_text}\n--- [END CONTEXT] ---\n\n"
                        f"--- [ATTACHED DOCUMENT ({uploaded_file.name})] ---\n{file_content}\n"
                        f"--- [END DOCUMENT] ---\n\n"
                        f"User's Current Query: {prompt}"
                    )]

            # Stream response via the chat session to keep history intact natively
            response = chat_session.send_message(parts, stream=True)
            for chunk in response:
                if chunk.text:
                    full_response += chunk.text
                    message_placeholder.markdown(full_response + "▌")

            message_placeholder.markdown(full_response)

            # Show References
            if references:
                with st.expander("📚 Sources & References", expanded=False):
                    for idx, ref in enumerate(references, 1):
                        st.markdown(f"**[{idx}] {ref['source']}** (Confidence: {ref['score']:.2f})")
                        st.markdown(f"- **Tafsir/Book:** {ref['tafsir']}")
                        if ref['surah'] != 'N/A':
                            st.markdown(f"- **Surah:** {ref['surah']}")
                        if ref['page'] != 'N/A':
                            st.markdown(f"- **Page:** {ref['page']}")
                        st.caption(f"*\"{ref['snippet']}\"*")
                        st.divider()

        except Exception as e:
            error_str = str(e)
            # Catch Quota (429) or API Key issues (400 / Expired)
            if any(err in error_str for err in ["429", "Quota exceeded", "400", "API key expired", "API_KEY_INVALID"]):
                full_response = "⚠️ **System is down for maintenance.**\n\nPlease contact fypquranllm@gmail.com for details."
                message_placeholder.error(full_response)
                email_subject = "🚨 CRITICAL: Gemini API Failure"
                email_body = f"""
                <h2>System Outage Alert</h2>
                <p>A critical Gemini API error occurred causing a service disruption.</p>
                <p><b>Error Details:</b></p>
                <pre>{error_str}</pre>
                <p><b>User Email:</b> {st.session_state.get('user_email', 'Unknown')}</p>
                <p><b>Time:</b> {datetime.utcnow()}</p>
                """
                send_email("fypquranllm@gmail.com", email_subject, email_body)
            else:
                full_response = f"I encountered an error generating the response: {e}"
                message_placeholder.error(full_response)

    # 4. Append Assistant Message
    # Note: We store references in the message dict for history display
    msg_obj = {"role": "assistant", "content": full_response, "references": references}
    st.session_state.messages.append(msg_obj)
    
    # 5. Save to DB (Assistant) — skip for guests
    if not IS_GUEST and not st.session_state.temp_mode:
        db_meta["chat_sessions"].update_one(
            {"_id": st.session_state.current_chat_id},
            {
                "$set": {"updated_at": datetime.utcnow()},
                "$push": {"messages": {
                    "role": "assistant", 
                    "content": full_response, 
                    "references": references,
                    "timestamp": datetime.utcnow()
                }}
            }
        )
        
        # 6. Auto-Rename 
        if len(st.session_state.messages) <= 2:
            try:
                title_model = genai.GenerativeModel("gemini-2.5-flash")
                title_resp = title_model.generate_content(
                    f"Generate a short, concise title (max 4-5 words) for this chat based on the first question: '{prompt}'. Do not use quotes."
                )
                if title_resp.text:
                    new_title = title_resp.text.strip()
                    db_meta["chat_sessions"].update_one(
                        {"_id": st.session_state.current_chat_id},
                        {"$set": {"title": new_title}}
                    )
                    st.rerun()
            except:
                pass
    
    # --- SHOW SAVE NUDGE AFTER 3rd QUESTION (set flag, show BEFORE rerun) ---
    if IS_GUEST and st.session_state.guest_question_count >= GUEST_QUESTION_LIMIT:
        st.session_state.show_signup_prompt = True
    
    # Rerun to cleanly transition the streamed message into the standard history loop
    st.rerun()

# --- SHOW SIGNUP NUDGE (runs every page load, persists across reruns) ---
if IS_GUEST and st.session_state.get("show_signup_prompt", False):
    st.session_state.show_signup_prompt = False  # Reset so it only shows once
    show_signup_prompt()
