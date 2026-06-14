import pytest
from streamlit.testing.v1 import AppTest
from unittest.mock import patch, MagicMock
import time

@pytest.fixture
def chatbot_app(mock_db_connection):
    with patch("streamlit.components.v1.html"), \
         patch("google.generativeai.configure"), \
         patch("google.generativeai.embed_content", return_value={"embedding": [0.1]*3072}), \
         patch("google.generativeai.GenerativeModel") as mock_model:
        
        # Mock the chat response generator
        mock_chat = MagicMock()
        mock_response = [MagicMock(text="Mocked scholar response")]
        mock_chat.send_message.return_value = mock_response
        mock_model.return_value.start_chat.return_value = mock_chat
        mock_model.return_value.generate_content.return_value = MagicMock(text="YES")
        
        at = AppTest.from_file("views/chatbot.py")
        yield at

def test_chatbot_guest_renders(chatbot_app):
    chatbot_app.session_state.authenticated = False
    chatbot_app.session_state.role = None
    chatbot_app.run()
    assert not chatbot_app.exception
    assert any("How can I help you today?" in m.value for m in chatbot_app.markdown)
    assert any("Sign Up Free" in b.label for b in chatbot_app.button)

def test_chatbot_guest_limit_nudge(chatbot_app):
    chatbot_app.session_state.authenticated = False
    chatbot_app.session_state.guest_question_count = 2
    chatbot_app.run()
    
    # Send a prompt to reach limit
    chatbot_app.chat_input[0].set_value("Tell me about Surah Fatiha").run()
    
    assert chatbot_app.session_state.guest_question_count == 3
    # Check that the signup dialog button is rendered
    assert any("Continue without account" in b.label for b in chatbot_app.button)

def test_chatbot_authenticated_sidebar_and_new_chat(chatbot_app, mock_db_connection):
    chatbot_app.session_state.authenticated = True
    chatbot_app.session_state.role = "user"
    chatbot_app.session_state.user_email = "user@test.com"
    
    # Pre-populate some user chats in MongoDB
    mock_db_connection["chat_sessions"].insert_one({
        "_id": "chat_1",
        "user_email": "user@test.com",
        "title": "Historical Chat 1",
        "is_temp": False,
        "is_bookmarked": False,
        "updated_at": "2026-06-14T12:00:00"
    })
    
    chatbot_app.run()
    assert not chatbot_app.exception
    assert any("New Chat" in b.label for b in chatbot_app.button)
    # Check that historical chat is listed
    assert any("Historical Chat 1" in b.label for b in chatbot_app.button)

def test_chatbot_temp_chat_toggle(chatbot_app):
    chatbot_app.session_state.authenticated = True
    chatbot_app.session_state.role = "user"
    chatbot_app.session_state.user_email = "user@test.com"
    chatbot_app.run()
    
    # Find the toggle for Temp Mode
    temp_toggle = chatbot_app.toggle[0]
    assert "Temp Chat" in temp_toggle.label
    
    # Toggle it
    temp_toggle.set_value(True).run()
    assert chatbot_app.session_state.temp_mode is True

def test_chatbot_tts_button(chatbot_app):
    chatbot_app.session_state.authenticated = True
    chatbot_app.session_state.role = "user"
    chatbot_app.session_state._was_guest = False
    chatbot_app.session_state.current_chat_id = "mock_chat_tts_test"
    chatbot_app.session_state.messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Peace be upon you.", "references": []}
    ]
    
    with patch("gtts.gTTS") as mock_gtts:
        mock_instance = MagicMock()
        mock_gtts.return_value = mock_instance
        chatbot_app.run()
        
        # Click the speaker button (button key prefix 'tts_btn_')
        tts_btn = next(b for b in chatbot_app.button if b.key and b.key.startswith("tts_btn_"))
        tts_btn.click().run()
        assert mock_gtts.called


def test_chatbot_init_failure():
    import streamlit as st
    st.cache_resource.clear()

    with patch("pymongo.MongoClient", side_effect=Exception("MongoDB connection timeout")):
        at = AppTest.from_file("views/chatbot.py")
        at.run()
        assert any("Initialization Error: MongoDB connection timeout" in e.value for e in at.error)


def test_chatbot_vector_search_failure(chatbot_app):
    chatbot_app.session_state.authenticated = False
    chatbot_app.run()

    from tests.mock_mongo import MockCollection
    with patch.object(MockCollection, "aggregate", side_effect=Exception("Vector search failed")), \
         patch("streamlit.error") as mock_st_error:
        chatbot_app.chat_input[0].set_value("Tell me about Islam").run()
        assert any("Vector Search Error: Vector search failed" in str(call) for call in mock_st_error.call_args_list)



def test_chatbot_gemini_quota_failure(chatbot_app):
    chatbot_app.session_state.authenticated = False
    chatbot_app.run()

    with patch("google.generativeai.GenerativeModel") as mock_model, \
         patch("utils.auth_utils.send_email") as mock_send_email:
        
        mock_chat = MagicMock()
        mock_chat.send_message.side_effect = Exception("429 ResourceExhausted: Quota exceeded")
        mock_model.return_value.start_chat.return_value = mock_chat
        mock_model.return_value.generate_content.return_value = MagicMock(text="YES")

        chatbot_app.chat_input[0].set_value("Tell me about Surah Fatiha").run()
        
        assert any("System is down for maintenance." in m.value for m in chatbot_app.markdown)
        assert mock_send_email.called
        args, kwargs = mock_send_email.call_args
        assert args[0] == "fypquranllm@gmail.com"
        assert "Gemini API Failure" in args[1]


def test_chatbot_gemini_general_failure(chatbot_app):
    chatbot_app.session_state.authenticated = False
    chatbot_app.run()

    with patch("google.generativeai.GenerativeModel") as mock_model:
        mock_chat = MagicMock()
        mock_chat.send_message.side_effect = Exception("General API Crash")
        mock_model.return_value.start_chat.return_value = mock_chat
        mock_model.return_value.generate_content.return_value = MagicMock(text="YES")

        chatbot_app.chat_input[0].set_value("Tell me about Surah Fatiha").run()
        
        assert any("I encountered an error generating the response: General API Crash" in m.value for m in chatbot_app.markdown)


def test_chatbot_upload_islamic_flag(chatbot_app):
    chatbot_app.session_state.authenticated = True
    chatbot_app.session_state.role = "user"
    chatbot_app.session_state.user_email = "user@test.com"
    chatbot_app.session_state.current_chat_id = "mock_chat_flag_test"
    chatbot_app.session_state.messages = []

    import io
    mock_file = io.BytesIO(b"mock_png_bytes")
    mock_file.name = "saudi_flag.png"

    # Use a side_effect to return the dictionary only on the first call, and None on subsequent calls (reruns) to prevent an infinite loop.
    mock_chat_input = MagicMock(side_effect=[{"text": "What is this flag?", "files": [mock_file]}, None, None, None])

    with patch("streamlit.chat_input", mock_chat_input), \
         patch("streamlit.image") as mock_st_image, \
         patch("google.generativeai.GenerativeModel") as mock_model:
        
        mock_chat = MagicMock()
        mock_response = [MagicMock(text="This is the flag of Saudi Arabia. It features the Shahada (declaration of faith in Islam): 'There is no god but Allah, and Muhammad is the messenger of Allah'.")]
        mock_chat.send_message.return_value = mock_response
        mock_model.return_value.start_chat.return_value = mock_chat
        mock_model.return_value.generate_content.return_value = MagicMock(text="YES")

        chatbot_app.run()

        
        # Check that the file was processed as an image and sent to Gemini
        assert mock_chat.send_message.called
        args, kwargs = mock_chat.send_message.call_args
        sent_parts = args[0]
        assert len(sent_parts) == 2
        assert "What is this flag?" in sent_parts[0]
        assert sent_parts[1]["mime_type"] == "image/png"
        assert sent_parts[1]["data"] == b"mock_png_bytes"
        
        # Check that st.image was called with the mock_file
        assert any(call[0][0] == mock_file for call in mock_st_image.call_args_list)
        
        # Check that the user prompt and file are listed
        assert any("saudi_flag.png" in m.value for m in chatbot_app.markdown)
        assert any("What is this flag?" in m.value for m in chatbot_app.markdown)
        
        # Check assistant's response is rendered
        assert any("This is the flag of Saudi Arabia" in m.value for m in chatbot_app.markdown)








