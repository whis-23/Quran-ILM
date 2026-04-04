import streamlit as st
import time
from utils.auth_utils import (
    authenticate_user, 
    create_user_pending, 
    verify_user_otp, 
    trigger_2fa, 
    verify_2fa,
    reset_password_request,
    reset_password_confirm,
    send_magic_link,       # New
    verify_magic_link_token, # New
    sync_descope_user      # New
)

# --- UI HELPERS ---

def switch_to(mode):
    st.session_state.auth_mode = mode
    st.rerun()

def login_page():
    # --- CHECK FOR MAGIC LINK TOKEN ---
    query_params = st.query_params
    if "t" in query_params:
        token = query_params["t"]
        # Convert QueryParamsProxy to str if needed, usually direct access works
        
        with st.spinner("Verifying Magic Link..."):
            user_info, msg = verify_magic_link_token(token)
            
            if user_info:
                # Sync with local DB (Create if new + Email password)
                success, role, welcome_msg = sync_descope_user(user_info)
                
                if success:
                    st.session_state.authenticated = True
                    st.session_state.role = role
                    st.session_state.user_email = user_info.get("email") or user_info.get("loginIds", [])[0]
                    
                    # Clear query params
                    st.query_params.clear()
                    
                    st.success(welcome_msg)
                    time.sleep(2)
                    st.rerun()
                else:
                    st.error(welcome_msg)
            else:
                st.error(msg)
        
        # Stop execution to show result
        st.stop()

    # --- PAGE CONFIG ---
    # ... (Rest of CSS)
    
    st.markdown("""
    <style>
        /* Global Styles */
        [data-testid="stAppViewContainer"] {
            background-color: #f8f9fa;
        }
        
        /* Hide Streamlit Header/Footer */
        header {visibility: hidden;}
        footer {visibility: hidden;}
        
        /* Card Container */
        .auth-card {
            background-color: white;
            padding: 2rem;
            border-radius: 12px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
            max-width: 450px;
            margin: auto;
        }
        
        /* Input Fields */
        .stTextInput input {
            border-radius: 8px;
            padding: 10px;
        }
        
        /* Buttons */
        .stButton button {
            width: 100%;
            border-radius: 8px;
            font-weight: 600;
            padding-top: 0.5rem;
            padding-bottom: 0.5rem;
        }
        
        /* Links */
        .auth-link {
            color: #8B6BB1;
            text-decoration: none;
            cursor: pointer;
            font-size: 0.9rem;
        }
        .auth-link:hover {
            text-decoration: underline;
        }
        
        h1 {
            text-align: center;
            color: #1f2937;
            margin-bottom: 0.5rem;
        }
        p {
            text-align: center;
            color: #6b7280;
        }
    </style>
    """, unsafe_allow_html=True)

    # --- STATE MANAGEMENT ---
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if "role" not in st.session_state:
        st.session_state.role = None
    if "auth_mode" not in st.session_state:
        st.session_state.auth_mode = "login" # login, signup, forgot, 2fa, verify_signup
    if "otp_expiry" not in st.session_state:
        st.session_state.otp_expiry = 0

    # --- TIMER COMPONENT ---
    def display_countdown():
        # ... (Same Timer)
        """
        Injects a Javascript Countdown Timer based on st.session_state.otp_expiry.
        """
        expiry_timestamp = st.session_state.get("otp_expiry", 0)
        now = time.time()
        remaining = int(expiry_timestamp - now)
        
        if remaining <= 0:
            st.error("⚠️ OTP has expired. Please request a new code.")
            return

        # HTML/JS for Countdown
        timer_html = f"""
        <div style="
            background-color: #fff3cd; 
            border: 1px solid #ffeeba; 
            color: #856404; 
            padding: 10px; 
            border-radius: 8px; 
            text-align: center; 
            margin-bottom: 15px;
            font-weight: bold;
        ">
            ⏳ Time Remaining: <span id="countdown_timer">--:--</span>
        </div>
        <script>
        (function() {{
            var expiry = {expiry_timestamp};
            var timerElement = document.getElementById("countdown_timer");
            
            var interval = setInterval(function() {{
                var now = Date.now() / 1000;
                var remaining = expiry - now;
                
                if (remaining <= 0) {{
                    clearInterval(interval);
                    timerElement.innerHTML = "EXPIRED";
                    return;
                }}
                
                var minutes = Math.floor(remaining / 60);
                var seconds = Math.floor(remaining % 60);
                
                seconds = seconds < 10 ? "0" + seconds : seconds;
                
                timerElement.innerHTML = minutes + ":" + seconds;
            }}, 1000);
        }})();
        </script>
        """
        st.components.v1.html(timer_html, height=50)

    # --- MAIN RENDER ---
    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:
        # --- HEADER ---
        c1, c2, c3 = st.columns([1, 1.5, 1])
        with c2:
            st.image("quran_ilm.png", use_container_width=True)
        st.write("") # Spacer
        
        # --- LOGIN VIEW ---
        if st.session_state.auth_mode == "login":
            st.markdown("<p>Sign in to your account</p>", unsafe_allow_html=True)
            
            # --- LOGIN METHOD TOGGLE ---
            login_method = st.radio(
                "Choose Login Method", 
                ["Password", "Magic Link"], 
                horizontal=True,
                label_visibility="collapsed"
            )
            st.write("") # Spacer

            if login_method == "Password":
                with st.form("login_form"):
                    email = st.text_input("Email Address", placeholder="name@example.com")
                    password = st.text_input("Password", type="password", placeholder="••••••••")
                    submit = st.form_submit_button("Sign In", type="primary")
                
                if submit:
                    if not email or not password:
                        st.warning("Please fill in all fields.")
                    else:
                        success, role, msg = authenticate_user(email, password)
                        if success:
                            if role == "admin":
                                # Trigger 2FA
                                trigger_2fa(email) # No code returned
                                st.session_state.temp_email = email
                                st.session_state.temp_role = role
                                st.session_state.otp_expiry = time.time() + 300 # 5 Minutes for 2FA
                                switch_to("2fa")
                            else:
                                st.session_state.authenticated = True
                                st.session_state.role = role
                                st.session_state.user_email = email
                                st.rerun()
                        else:
                            st.error(msg)

            elif login_method == "Magic Link":
                with st.container(border=True): # Cleaner look than expander for main view
                     st.write("Enter your email to receive a magic login link.")
                     magic_email = st.text_input("Email Address for Magic Link")
                     if st.button("Send Magic Link", type="primary"):
                         if not magic_email:
                             st.warning("Please enter email.")
                         else:
                             success, msg = send_magic_link(magic_email, intent="login")
                             if success:
                                 st.success(msg)
                             else:
                                 st.error(msg)
            
            # Forgot Password Link (Tertiary Button)
            
            # Forgot Password Link (Tertiary Button)
            col_link, col_create = st.columns([1, 1])
            with col_link:
                if st.button("Forgot password?", type="tertiary"):
                    switch_to("forgot")
            
            st.markdown("---")
            if st.button("Create new account"):
                switch_to("signup")

        # --- SIGNUP VIEW ---
        elif st.session_state.auth_mode == "signup":
            st.markdown("<p>Create a new account</p>", unsafe_allow_html=True)
            
            # --- SIGNUP METHOD TOGGLE ---
            signup_method = st.radio(
                "Choose Signup Method", 
                ["Password", "Magic Link"], 
                horizontal=True,
                label_visibility="collapsed"
            )
            st.write("") # Spacer

            # --- DISCLAIMER DIALOG (Reused for both) ---
            @st.dialog("⚠️ Religious Disclaimer & Agreement")
            def show_disclaimer(email, password=None, method="password"):
                st.write("""
                **Please read and accept the following before proceeding:**
                
                Disclaimer: Users agree that this system is not intended to replace any Islamic
                scholar or madrasa, nor is it designed to mock any religious entity. The system
                does not issue any fatwa of its own; rather, it draws upon existing knowledge
                from authentic Islamic books. Its sole purpose is to provide guidance and
                facilitate easy access to religious matters related to the Quran.
                """)
                
                st.warning("By clicking 'I Agree', you acknowledge the above statement.")
                
                if st.button("I Agree & Verify", type="primary"):
                    if method == "password":
                        success, res_msg = create_user_pending(email, password, "user")
                        if success:
                            st.session_state.temp_email = email
                            st.session_state.otp_expiry = time.time() + 600 # 10 Minutes
                            st.success(res_msg)
                            time.sleep(1.5)
                            switch_to("verify_signup")
                            st.rerun()
                        else:
                            st.error(res_msg)
                    elif method == "magic_link":
                        success, res_msg = send_magic_link(email, intent="signup")
                        if success:
                            st.success(res_msg)
                            time.sleep(2)
                            st.rerun() # Refresh to let them check email
                        else:
                            st.error(res_msg)

            if signup_method == "Password":
                with st.form("signup_form"):
                    email = st.text_input("Email Address", placeholder="name@example.com")
                    password = st.text_input("Create Password", type="password", placeholder="Strong Password (Min 8 chars, Aa1!)")
                    confirm = st.text_input("Confirm Password", type="password", placeholder="Confirm Password")
                    submitted = st.form_submit_button("Sign Up", type="primary")

                if submitted:
                    if not email or not password:
                        st.warning("Please fill in all fields.")
                    elif password != confirm:
                        st.error("Passwords do not match.")
                    else:
                        from utils.auth_utils import validate_password_strength
                        is_valid, msg = validate_password_strength(password)
                        if not is_valid:
                            st.error(f"⚠️ Weak password: {msg}")
                        else:
                            show_disclaimer(email, password=password, method="password")

            elif signup_method == "Magic Link":
                with st.container(border=True):
                    st.write("Register with your email to receive a magic signup link.")
                    signup_email = st.text_input("Email Address")
                    
                    if st.button("Sign Up with Magic Link", type="primary"):
                         if not signup_email:
                             st.warning("Please enter email.")
                         else:
                             show_disclaimer(signup_email, method="magic_link")

            st.markdown("---")
            if st.button("Already have an account? Sign In"):
                switch_to("login")

        # --- VERIFY SIGNUP VIEW ---
        elif st.session_state.auth_mode == "verify_signup":
            st.markdown("<p>Verify your email</p>", unsafe_allow_html=True)
            st.info(f"We sent a code to {st.session_state.get('temp_email')}")
            
            # Timer
            display_countdown()
            
            # Hidden OTP Logic (No code display)
                
            otp = st.text_input("Enter 6-digit Code")
            if st.button("Verify Account", type="primary"):
                success, msg = verify_user_otp(st.session_state.temp_email, otp)
                if success:
                    st.success("Account Verified! Redirecting to Login...")
                    time.sleep(2)
                    switch_to("login")
                else:
                    st.error(msg)
                    
            if st.button("Back"):
                switch_to("signup")

        # --- FORGOT PASSWORD VIEW ---
        elif st.session_state.auth_mode == "forgot":
            st.markdown("<p>Reset your password</p>", unsafe_allow_html=True)
            
            email = st.text_input("Enter your registered email")
            if st.button("Send Reset Link", type="primary"):
                success, res_msg = reset_password_request(email)
                if success:
                    st.session_state.reset_email = email
                    st.session_state.otp_expiry = time.time() + 600 # 10 Minutes
                    st.success(res_msg)
                    time.sleep(1.5)
                    switch_to("reset_final")
                else:
                    st.error(res_msg)
                    
            st.markdown("---")
            if st.button("Back to Login"):
                switch_to("login")

        # --- RESET FINAL VIEW ---
        elif st.session_state.auth_mode == "reset_final":
            st.markdown("<p>Set new password</p>", unsafe_allow_html=True)
            
            # Timer
            display_countdown()
            
            # Hidden OTP
                
            otp = st.text_input("Reset Code")
            new_pass = st.text_input("New Password", type="password")
            confirm_pass = st.text_input("Confirm New Password", type="password")
            
            if st.button("Change Password", type="primary"):
                if new_pass != confirm_pass:
                    st.error("Passwords do not match.")
                else:
                    # Validate Password Strength
                    from utils.auth_utils import validate_password_strength
                    is_valid, msg = validate_password_strength(new_pass)
                    
                    if not is_valid:
                        st.error(msg)
                    else:
                        success, msg = reset_password_confirm(st.session_state.reset_email, otp, new_pass)
                        if success:
                            st.success("Password Updated! Redirecting...")
                            time.sleep(2)
                            switch_to("login")
                        else:
                            st.error(msg)

        # --- 2FA VIEW (Admin) ---
        elif st.session_state.auth_mode == "2fa":
            st.markdown("<p>Two-Factor Authentication</p>", unsafe_allow_html=True)
            st.warning("⚠️ Admin Access Verification")
            
            # Timer
            display_countdown()
            
            otp = st.text_input("Enter Security Code from Email")
            if st.button("Verify Login", type="primary"):
                if verify_2fa(st.session_state.temp_email, otp):
                    st.session_state.authenticated = True
                    st.session_state.role = st.session_state.temp_role
                    st.session_state.user_email = st.session_state.temp_email
                    st.rerun()
                else:
                    st.error("Invalid Code.")
                    
            if st.button("Cancel"):
                switch_to("login")
            
login_page()
