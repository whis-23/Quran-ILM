import pytest
import time
from streamlit.testing.v1 import AppTest
from unittest.mock import patch, MagicMock


@pytest.fixture
def login_app(mock_db_connection):
    # Mocking st.components.v1.html out, since AppTest doesn't process it natively well
    with patch("streamlit.components.v1.html"):
        at = AppTest.from_file("views/login.py")
        yield at


# ---------------------------------------------------------------------------
# BASIC LOGIN VIEW
# ---------------------------------------------------------------------------

def test_login_page_renders(login_app):
    login_app.run()
    assert not login_app.exception
    assert any("Sign in to your account" in m.value for m in login_app.markdown)


def test_login_missing_fields(login_app):
    login_app.run()
    # Sign In Button is the first button in the app (inside the form)
    login_app.button[0].click().run()
    assert "Please fill in all fields" in login_app.warning[0].value


def test_login_success(login_app, mock_db_connection):
    from utils.auth_utils import hash_password
    mock_db_connection["users"].insert_one({
        "email": "user@test.com",
        "password_hash": hash_password("ValidPassword1!"),
        "role": "user",
        "verified": True
    })

    login_app.run()
    login_app.text_input[0].input("user@test.com")
    login_app.text_input[1].input("ValidPassword1!")

    with patch("streamlit.rerun"):
        login_app.button[0].click().run()

    assert login_app.session_state["authenticated"] is True
    assert login_app.session_state["role"] == "user"


def test_login_error(login_app, mock_db_connection):
    """Test wrong password shows error message."""
    login_app.run()
    login_app.text_input[0].input("nobody@test.com")
    login_app.text_input[1].input("WrongPass1!")
    login_app.button[0].click().run()
    assert len(login_app.error) > 0


def test_login_admin_triggers_2fa(login_app, mock_db_connection):
    from utils.auth_utils import hash_password
    mock_db_connection["users"].insert_one({
        "email": "admin@test.com",
        "password_hash": hash_password("AdminPass1!"),
        "role": "admin",
        "verified": True
    })

    login_app.run()
    login_app.text_input[0].input("admin@test.com")
    login_app.text_input[1].input("AdminPass1!")

    # Mock trigger_2fa to prevent real SMTP call.
    # Mock switch_to to set session state without calling st.rerun (which would trigger
    # a second script run and hit "Forms cannot be nested" error inside AppTest).
    # We must patch these at the module level where they are used (views.login).
    with patch("utils.auth_utils.trigger_2fa"):
        with patch("streamlit.rerun"):
            login_app.button[0].click().run()

    # If the exception occurred (form nesting), session state may have been set before it
    # so we check it even if there's an exception in login_app.exception
    try:
        auth_mode = login_app.session_state["auth_mode"]
    except Exception:
        auth_mode = None
    assert auth_mode == "2fa"


# ---------------------------------------------------------------------------
# MAGIC LINK LOGIN
# ---------------------------------------------------------------------------

def test_login_magic_link(login_app):
    login_app.run()
    login_app.radio[0].set_value("Magic Link").run()

    # Click with no email entered
    login_app.button[0].click().run()
    assert "Please enter email" in login_app.warning[0].value

    # Click with email — send fails
    login_app.text_input[0].input("ghost@test.com")
    with patch("utils.auth_utils.send_magic_link", return_value=(False, "Failed")):
        login_app.button[0].click().run()
        assert "Failed" in login_app.error[0].value

    # Click with email — send succeeds
    with patch("utils.auth_utils.send_magic_link", return_value=(True, "Success")):
        login_app.button[0].click().run()
        assert "Success" in login_app.success[0].value


def test_magic_link_token_login(login_app):
    """Test arriving with a ?t= token in the URL sets authenticated state."""
    login_app.query_params["t"] = "mock_token"

    with patch("utils.auth_utils.verify_magic_link_token", return_value=({"email": "magic@test.com"}, "OK")):
        with patch("utils.auth_utils.sync_descope_user", return_value=(True, "user", "Welcome")):
            with patch("streamlit.rerun"):
                login_app.run()

    assert login_app.session_state["authenticated"] is True


def test_magic_link_token_bad(login_app):
    """Test arriving with an invalid ?t= token shows an error."""
    login_app.query_params["t"] = "bad_token"

    with patch("utils.auth_utils.verify_magic_link_token", return_value=(None, "Invalid token")):
        login_app.run()

    assert len(login_app.error) > 0


# ---------------------------------------------------------------------------
# SIGN UP FLOW
# ---------------------------------------------------------------------------

def test_signup_flow_password(login_app):
    login_app.run()
    # Navigate to signup — button[2] = "Create new account"
    login_app.button[2].click().run()
    assert login_app.session_state["auth_mode"] == "signup"

    # Passwords mismatch
    login_app.text_input[0].input("new@test.com")
    login_app.text_input[1].input("Pass1!")
    login_app.text_input[2].input("Pass2!")
    login_app.button[0].click().run()
    assert "Passwords do not match" in login_app.error[0].value

    # Weak password
    login_app.text_input[1].input("weak")
    login_app.text_input[2].input("weak")
    login_app.button[0].click().run()
    assert "Weak password" in login_app.error[0].value

    # Empty fields
    login_app.text_input[0].input("")
    login_app.text_input[1].input("")
    login_app.text_input[2].input("")
    login_app.button[0].click().run()
    assert "Please fill in all fields" in login_app.warning[0].value


def test_signup_flow_magic_link(login_app):
    login_app.run()
    login_app.button[2].click().run()
    assert login_app.session_state["auth_mode"] == "signup"

    login_app.radio[0].set_value("Magic Link").run()

    # Empty email
    login_app.button[0].click().run()
    assert "Please enter email" in login_app.warning[0].value

    # With email — triggers disclaimer dialog
    login_app.text_input[0].input("new_magic@test.com")
    login_app.button[0].click().run()
    assert len(login_app.warning) > 0


# ---------------------------------------------------------------------------
# VERIFY SIGNUP (OTP)
# ---------------------------------------------------------------------------

def test_verify_signup_flow(login_app):
    login_app.session_state["auth_mode"] = "verify_signup"
    login_app.session_state["temp_email"] = "test@verify.com"
    login_app.session_state["otp_expiry"] = time.time() + 3600

    with patch("streamlit.rerun"):
        login_app.run()

    login_app.text_input[0].input("123456")

    # Failure path — stays on verify page
    with patch("utils.auth_utils.verify_user_otp", return_value=(False, "Failed")):
        login_app.button[0].click().run()
        assert "Failed" in login_app.error[0].value

    # Success path — would rerun to login
    with patch("utils.auth_utils.verify_user_otp", return_value=(True, "Verified")):
        with patch("streamlit.rerun"):
            login_app.button[0].click().run()
            assert "Account Verified!" in login_app.success[0].value

    # Back button — resets to signup
    login_app.session_state["auth_mode"] = "verify_signup"
    login_app.run()
    with patch("streamlit.rerun"):
        login_app.button[-1].click().run()
        assert login_app.session_state["auth_mode"] == "signup"


# ---------------------------------------------------------------------------
# FORGOT PASSWORD
# ---------------------------------------------------------------------------

def test_forgot_password_flow(login_app):
    login_app.session_state["auth_mode"] = "forgot"
    login_app.run()

    login_app.text_input[0].input("forgot@test.com")

    # Email not found
    with patch("utils.auth_utils.reset_password_request", return_value=(False, "Not found")):
        login_app.button[0].click().run()
        assert "Not found" in login_app.error[0].value

    # Email found — advance to reset_final
    with patch("utils.auth_utils.reset_password_request", return_value=(True, "Sent")):
        with patch("streamlit.rerun"):
            login_app.button[0].click().run()
            assert "Sent" in login_app.success[0].value
            assert login_app.session_state["auth_mode"] == "reset_final"

    # Back to login
    login_app.session_state["auth_mode"] = "forgot"
    login_app.run()
    with patch("streamlit.rerun"):
        login_app.button[1].click().run()
        assert login_app.session_state["auth_mode"] == "login"


# ---------------------------------------------------------------------------
# RESET FINAL (set new password)
# ---------------------------------------------------------------------------

def test_reset_final_flow(login_app):
    login_app.session_state["auth_mode"] = "reset_final"
    login_app.session_state["reset_email"] = "reset@test.com"
    login_app.session_state["otp_expiry"] = time.time() + 3600

    with patch("streamlit.rerun"):
        login_app.run()

    login_app.text_input[0].input("111111")
    login_app.text_input[1].input("NewPass1!")
    login_app.text_input[2].input("Mismatch!")

    # Passwords don't match
    login_app.button[0].click().run()
    assert "Passwords do not match" in login_app.error[0].value

    login_app.text_input[2].input("NewPass1!")

    # Invalid OTP
    with patch("utils.auth_utils.reset_password_confirm", return_value=(False, "Invalid OTP")):
        login_app.button[0].click().run()
        assert "Invalid OTP" in login_app.error[0].value

    # Success
    with patch("utils.auth_utils.reset_password_confirm", return_value=(True, "Success")):
        with patch("streamlit.rerun"):
            login_app.button[0].click().run()
            assert "Password Updated!" in login_app.success[0].value
