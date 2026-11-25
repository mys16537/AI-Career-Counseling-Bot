import os
import re
import ssl
import hmac
import smtplib
import secrets
import hashlib
import sqlite3
import json

from email.message import EmailMessage

from dotenv import load_dotenv

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    jsonify
)

from authlib.integrations.flask_client import OAuth

from itsdangerous import (
    URLSafeTimedSerializer,
    SignatureExpired,
    BadSignature
)

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

from ai_engine import (
    generate_ai_response,
    warm_up_model
)


# =========================================================
# LOAD .ENV
# =========================================================

load_dotenv()


# =========================================================
# FLASK APPLICATION
# =========================================================

app = Flask(__name__)

app.secret_key = os.getenv(
    "FLASK_SECRET_KEY",
    "careerbot-development-secret-change-me"
)

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


# =========================================================
# PASSWORD RESET CONFIGURATION
# =========================================================

RESET_TOKEN_MAX_AGE = 900
# 900 seconds = 15 minutes

RESET_TOKEN_SALT = os.getenv(
    "RESET_TOKEN_SALT",
    "careerbot-password-reset-v1"
)

token_serializer = URLSafeTimedSerializer(
    app.secret_key
)


# =========================================================
# EMAIL CONFIGURATION
# =========================================================

MAIL_SERVER = os.getenv(
    "MAIL_SERVER",
    "smtp.gmail.com"
)

MAIL_PORT = int(
    os.getenv(
        "MAIL_PORT",
        "465"
    )
)

MAIL_USE_TLS = (
    os.getenv(
        "MAIL_USE_TLS",
        "False"
    ).lower()
    == "true"
)

MAIL_USE_SSL = (
    os.getenv(
        "MAIL_USE_SSL",
        "True"
    ).lower()
    == "true"
)

MAIL_USERNAME = os.getenv(
    "MAIL_USERNAME",
    ""
)

MAIL_PASSWORD = os.getenv(
    "MAIL_PASSWORD",
    ""
)

MAIL_SENDER = os.getenv(
    "MAIL_SENDER",
    MAIL_USERNAME
)


# =========================================================
# OAUTH CONFIGURATION
# =========================================================

oauth = OAuth(app)


# ---------------------------------------------------------
# GOOGLE
# ---------------------------------------------------------

google = oauth.register(

    name="google",

    client_id=os.getenv(
        "GOOGLE_CLIENT_ID"
    ),

    client_secret=os.getenv(
        "GOOGLE_CLIENT_SECRET"
    ),

    server_metadata_url=(
        "https://accounts.google.com/"
        ".well-known/openid-configuration"
    ),

    client_kwargs={
        "scope": "openid email profile"
    }
)


# ---------------------------------------------------------
# LINKEDIN
# ---------------------------------------------------------

linkedin = oauth.register(

    name="linkedin",

    client_id=os.getenv(
        "LINKEDIN_CLIENT_ID"
    ),

    client_secret=os.getenv(
        "LINKEDIN_CLIENT_SECRET"
    ),

    server_metadata_url=(
        "https://www.linkedin.com/oauth/"
        ".well-known/openid-configuration"
    ),

    client_kwargs={
        "scope": "openid profile email"
    }
)


# ---------------------------------------------------------
# MICROSOFT
# ---------------------------------------------------------

microsoft = oauth.register(

    name="microsoft",

    client_id=os.getenv(
        "MICROSOFT_CLIENT_ID"
    ),

    client_secret=os.getenv(
        "MICROSOFT_CLIENT_SECRET"
    ),

    server_metadata_url=(
        "https://login.microsoftonline.com/"
        "common/v2.0/"
        ".well-known/openid-configuration"
    ),

    client_kwargs={
        "scope": "openid profile email"
    }
)


# =========================================================
# CACHE CONTROL
# =========================================================

@app.after_request
def add_header(response):

    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, "
        "post-check=0, pre-check=0, max-age=0"
    )

    response.headers["Pragma"] = "no-cache"

    return response


# =========================================================
# DATABASE CONNECTION
# =========================================================

def get_db_connection():

    conn = sqlite3.connect(
        "database.db",
        timeout=10
    )

    conn.row_factory = sqlite3.Row

    return conn


# =========================================================
# DATABASE INITIALIZATION / MIGRATION
# =========================================================

def init_db():

    conn = get_db_connection()

    # -----------------------------------------------------
    # USERS
    # -----------------------------------------------------

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            full_name TEXT,
            email TEXT,
            auth_provider TEXT
        )
        """
    )

    # Upgrade older database automatically
    user_columns = conn.execute(
        "PRAGMA table_info(users)"
    ).fetchall()

    user_column_names = [
        row["name"]
        for row in user_columns
    ]

    required_user_columns = {

        "full_name": "TEXT",

        "email": "TEXT",

        "auth_provider": "TEXT"
    }

    for column_name, column_type in required_user_columns.items():

        if column_name not in user_column_names:

            conn.execute(
                f"""
                ALTER TABLE users
                ADD COLUMN {column_name} {column_type}
                """
            )

    # -----------------------------------------------------
    # PROFILES
    # -----------------------------------------------------

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS profiles (

            username TEXT PRIMARY KEY,

            name TEXT,

            phone TEXT,

            degree TEXT,

            interests TEXT,

            current_education TEXT,

            graduation_year TEXT,

            current_skills TEXT,

            skill_level TEXT,

            career_goal TEXT,

            career_preference TEXT,

            preferred_country TEXT,

            preferred_city TEXT
        )
        """
    )

    profile_columns = conn.execute(
        "PRAGMA table_info(profiles)"
    ).fetchall()

    profile_column_names = [
        row["name"]
        for row in profile_columns
    ]

    required_profile_columns = {

        "current_education": "TEXT",

        "graduation_year": "TEXT",

        "current_skills": "TEXT",

        "skill_level": "TEXT",

        "career_goal": "TEXT",

        "career_preference": "TEXT",

        "preferred_country": "TEXT",

        "preferred_city": "TEXT"
    }

    for column_name, column_type in required_profile_columns.items():

        if column_name not in profile_column_names:

            conn.execute(
                f"""
                ALTER TABLE profiles
                ADD COLUMN {column_name} {column_type}
                """
            )

    # -----------------------------------------------------
    # MESSAGES
    # -----------------------------------------------------

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            username TEXT NOT NULL,

            role TEXT NOT NULL,

            content TEXT NOT NULL
        )
        """
    )

    # Keep each conversation separate without removing existing messages.
    message_columns = {row["name"] for row in conn.execute(
        "PRAGMA table_info(messages)"
    )}
    if "conversation_id" not in message_columns:
        conn.execute("ALTER TABLE messages ADD COLUMN conversation_id TEXT NOT NULL DEFAULT 'legacy'")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(username, conversation_id, id)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS conversation_profiles (
            username TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            profile_json TEXT NOT NULL,
            PRIMARY KEY (username, conversation_id)
        )
    """)
    conn.commit()
    conn.close()


init_db()


# =========================================================
# EMAIL VALIDATION
# =========================================================

def valid_email(email):

    pattern = (
        r"^[A-Za-z0-9._%+-]+"
        r"@[A-Za-z0-9.-]+"
        r"\.[A-Za-z]{2,}$"
    )

    return bool(
        re.match(
            pattern,
            email
        )
    )


# =========================================================
# PASSWORD HELPERS
# =========================================================

def is_password_hash(password_value):

    if not password_value:
        return False

    return password_value.startswith(
        (
            "scrypt:",
            "pbkdf2:"
        )
    )


def verify_local_password(
    stored_password,
    entered_password
):

    # Modern hashed password
    if is_password_hash(
        stored_password
    ):

        return check_password_hash(
            stored_password,
            entered_password
        )

    # -----------------------------------------------------
    # SUPPORT OLD PLAINTEXT ACCOUNTS
    # -----------------------------------------------------

    return hmac.compare_digest(
        str(stored_password),
        str(entered_password)
    )


# =========================================================
# DISPLAY NAME
# =========================================================

def get_display_name(
    conn,
    username
):

    if session.get(
        "is_guest"
    ):

        return session.get(
            "display_name",
            "Guest"
        )

    user_row = conn.execute(
        """
        SELECT full_name
        FROM users
        WHERE username = ?
        """,
        (username,)
    ).fetchone()

    if (
        user_row
        and user_row["full_name"]
        and user_row["full_name"].strip()
    ):

        return user_row[
            "full_name"
        ]

    return username


# =========================================================
# LOGIN SESSION HELPER
# =========================================================

def start_session(
    username,
    provider,
    display_name
):

    session.clear()

    session["user"] = username

    session["display_name"] = (
        display_name
    )

    session["auth_provider"] = (
        provider
    )

    session["is_guest"] = False


# =========================================================
# SOCIAL USER HELPERS
# =========================================================

def social_username(
    provider,
    provider_user_id
):

    raw_value = (
        f"{provider}:"
        f"{provider_user_id}"
    )

    digest = hashlib.sha256(
        raw_value.encode(
            "utf-8"
        )
    ).hexdigest()[:20]

    return (
        f"{provider}_{digest}"
    )


def save_social_user(
    provider,
    user_info
):

    provider_user_id = (

        user_info.get("sub")

        or user_info.get("oid")
    )

    if not provider_user_id:

        raise ValueError(
            "Provider did not return "
            "a valid user ID."
        )

    full_name = (

        user_info.get("name")

        or user_info.get(
            "given_name"
        )

        or "CareerBot User"
    )

    email = (

        user_info.get("email")

        or user_info.get(
            "preferred_username"
        )

        or ""
    )

    username = social_username(
        provider,
        provider_user_id
    )

    conn = get_db_connection()

    existing_user = conn.execute(
        """
        SELECT username
        FROM users
        WHERE username = ?
        """,
        (username,)
    ).fetchone()

    if existing_user:

        conn.execute(
            """
            UPDATE users

            SET
                full_name = ?,
                email = ?,
                auth_provider = ?

            WHERE username = ?
            """,
            (
                full_name,
                email,
                provider,
                username
            )
        )

    else:

        # Social accounts do not use
        # CareerBot local passwords.
        random_password = (
            secrets.token_urlsafe(
                48
            )
        )

        internal_password_hash = (
            generate_password_hash(
                random_password
            )
        )

        conn.execute(
            """
            INSERT INTO users (

                username,

                password,

                full_name,

                email,

                auth_provider
            )

            VALUES (?, ?, ?, ?, ?)
            """,
            (
                username,
                internal_password_hash,
                full_name,
                email,
                provider
            )
        )

    # -----------------------------------------------------
    # PROFILE
    # -----------------------------------------------------

    profile = conn.execute(
        """
        SELECT username
        FROM profiles
        WHERE username = ?
        """,
        (username,)
    ).fetchone()

    if profile:

        conn.execute(
            """
            UPDATE profiles

            SET name = ?

            WHERE username = ?
            """,
            (
                full_name,
                username
            )
        )

    else:

        conn.execute(
            """
            INSERT INTO profiles (
                username,
                name
            )

            VALUES (?, ?)
            """,
            (
                username,
                full_name
            )
        )

    conn.commit()
    conn.close()

    return (
        username,
        full_name
    )


# =========================================================
# PASSWORD RESET TOKEN
# =========================================================

def create_password_reset_token(
    username,
    email
):

    return token_serializer.dumps(
        {
            "username": username,
            "email": email
        },
        salt=RESET_TOKEN_SALT
    )


def verify_password_reset_token(
    token
):

    return token_serializer.loads(
        token,
        salt=RESET_TOKEN_SALT,
        max_age=RESET_TOKEN_MAX_AGE
    )


# =========================================================
# SEND PASSWORD RESET EMAIL
# =========================================================

def send_password_reset_email(
    recipient_email,
    full_name,
    reset_url
):

    if (
        not MAIL_USERNAME
        or not MAIL_PASSWORD
        or not MAIL_SENDER
    ):

        raise RuntimeError(
            "Email service is not configured. "
            "Check MAIL_USERNAME, MAIL_PASSWORD "
            "and MAIL_SENDER in .env."
        )

    message = EmailMessage()

    message["Subject"] = (
        "CareerBot Password Reset"
    )

    message["From"] = MAIL_SENDER
    message["To"] = recipient_email

    safe_name = (
        full_name
        or "CareerBot User"
    )

    message.set_content(
        f"""
Hello {safe_name},

We received a request to reset your CareerBot password.

Open the link below to create a new password:

{reset_url}

This link will expire in 15 minutes.

If you did not request this password reset, you can ignore this email.

CareerBot
AI Career Counseling System
        """.strip()
    )

    smtp_context = ssl.create_default_context()

    # Gmail SSL mode: port 465
    if MAIL_USE_SSL:

        with smtplib.SMTP_SSL(
            MAIL_SERVER,
            MAIL_PORT,
            context=smtp_context,
            timeout=30
        ) as smtp:

            smtp.login(
                MAIL_USERNAME,
                MAIL_PASSWORD
            )

            smtp.send_message(
                message
            )

    # STARTTLS mode: normally port 587
    else:

        with smtplib.SMTP(
            MAIL_SERVER,
            MAIL_PORT,
            timeout=30
        ) as smtp:

            smtp.ehlo()

            if MAIL_USE_TLS:

                smtp.starttls(
                    context=smtp_context
                )

                smtp.ehlo()

            smtp.login(
                MAIL_USERNAME,
                MAIL_PASSWORD
            )

            smtp.send_message(
                message
            )


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():

    if "user" in session:

        return redirect(
            url_for(
                "dashboard"
            )
        )

    return redirect(
        url_for(
            "login"
        )
    )


# =========================================================
# LOGIN + REGISTRATION
# =========================================================

@app.route(
    "/login",
    methods=[
        "GET",
        "POST"
    ]
)
def login():

    if request.method == "POST":

        action = request.form.get(
            "action",
            ""
        )

        username = request.form.get(
            "username",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        full_name = request.form.get(
            "full_name",
            ""
        ).strip()

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        # =================================================
        # REGISTER
        # =================================================

        if action == "register":

            if not all([
                full_name,
                email,
                username,
                password
            ]):

                return render_template(
                    "login.html",

                    error=(
                        "Full name, email, "
                        "username and password "
                        "are required."
                    ),

                    active_form="register",

                    register_full_name=(
                        full_name
                    ),

                    register_email=(
                        email
                    ),

                    register_username=(
                        username
                    )
                )

            # -------------------------------------------------
            # EMAIL FORMAT
            # -------------------------------------------------

            if not valid_email(
                email
            ):

                return render_template(
                    "login.html",

                    error=(
                        "Please enter a valid "
                        "email address."
                    ),

                    active_form="register",

                    register_full_name=(
                        full_name
                    ),

                    register_email=(
                        email
                    ),

                    register_username=(
                        username
                    )
                )

            # -------------------------------------------------
            # PASSWORD LENGTH
            # -------------------------------------------------

            if len(password) < 8:

                return render_template(
                    "login.html",

                    error=(
                        "Password must contain "
                        "at least 8 characters."
                    ),

                    active_form="register",

                    register_full_name=(
                        full_name
                    ),

                    register_email=(
                        email
                    ),

                    register_username=(
                        username
                    )
                )

            conn = get_db_connection()

            # -------------------------------------------------
            # USERNAME EXISTS?
            # -------------------------------------------------

            existing_username = (
                conn.execute(
                    """
                    SELECT username
                    FROM users
                    WHERE username = ?
                    """,
                    (username,)
                ).fetchone()
            )

            if existing_username:

                conn.close()

                return render_template(
                    "login.html",

                    error=(
                        "Username already exists."
                    ),

                    active_form="register",

                    register_full_name=(
                        full_name
                    ),

                    register_email=(
                        email
                    ),

                    register_username=(
                        username
                    )
                )

            # -------------------------------------------------
            # EMAIL EXISTS?
            # -------------------------------------------------

            existing_email = (
                conn.execute(
                    """
                    SELECT username
                    FROM users
                    WHERE LOWER(email) = LOWER(?)
                    """,
                    (email,)
                ).fetchone()
            )

            if existing_email:

                conn.close()

                return render_template(
                    "login.html",

                    error=(
                        "This email address is "
                        "already registered."
                    ),

                    active_form="register",

                    register_full_name=(
                        full_name
                    ),

                    register_email=(
                        email
                    ),

                    register_username=(
                        username
                    )
                )

            # -------------------------------------------------
            # HASH PASSWORD
            # -------------------------------------------------

            password_hash = (
                generate_password_hash(
                    password
                )
            )

            # -------------------------------------------------
            # CREATE USER
            # -------------------------------------------------

            conn.execute(
                """
                INSERT INTO users (

                    username,

                    password,

                    full_name,

                    email,

                    auth_provider
                )

                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    username,
                    password_hash,
                    full_name,
                    email,
                    "local"
                )
            )

            # -------------------------------------------------
            # BASIC PROFILE
            # -------------------------------------------------

            conn.execute(
                """
                INSERT OR IGNORE INTO profiles (
                    username,
                    name
                )

                VALUES (?, ?)
                """,
                (
                    username,
                    full_name
                )
            )

            conn.commit()
            conn.close()

            return render_template(
                "login.html",

                success=(
                    "Account created successfully. "
                    "Please sign in."
                ),

                active_form="login",

                login_username=username
            )

        # =================================================
        # NORMAL LOGIN
        # =================================================

        elif action == "login":

            if (
                not username
                or not password
            ):

                return render_template(
                    "login.html",

                    error=(
                        "Username and password "
                        "are required."
                    ),

                    active_form="login",

                    login_username=username
                )

            conn = get_db_connection()

            user = conn.execute(
                """
                SELECT *
                FROM users

                WHERE username = ?

                AND (
                    auth_provider IS NULL
                    OR auth_provider = 'local'
                )
                """,
                (username,)
            ).fetchone()

            # -------------------------------------------------
            # USER NOT FOUND
            # -------------------------------------------------

            if user is None:

                conn.close()

                return render_template(
                    "login.html",

                    error=(
                        "Invalid username "
                        "or password."
                    ),

                    active_form="login",

                    login_username=username
                )

            # -------------------------------------------------
            # VERIFY PASSWORD
            # -------------------------------------------------

            valid_password = (
                verify_local_password(
                    user["password"],
                    password
                )
            )

            if not valid_password:

                conn.close()

                return render_template(
                    "login.html",

                    error=(
                        "Invalid username "
                        "or password."
                    ),

                    active_form="login",

                    login_username=username
                )

            # -------------------------------------------------
            # UPGRADE OLD PLAINTEXT PASSWORD
            # -------------------------------------------------

            if not is_password_hash(
                user["password"]
            ):

                upgraded_hash = (
                    generate_password_hash(
                        password
                    )
                )

                conn.execute(
                    """
                    UPDATE users
                    SET password = ?
                    WHERE username = ?
                    """,
                    (
                        upgraded_hash,
                        username
                    )
                )

                conn.commit()

            full_name_for_session = (
                user["full_name"]
                or username
            )

            conn.close()

            start_session(
                username=username,
                provider="local",
                display_name=(
                    full_name_for_session
                )
            )

            return redirect(
                url_for(
                    "dashboard"
                )
            )

        # =================================================
        # INVALID ACTION
        # =================================================

        else:

            return render_template(
                "login.html",

                error="Invalid request.",

                active_form="login"
            )

    # =====================================================
    # GET
    # =====================================================

    return render_template(
        "login.html",
        active_form="login"
    )


# =========================================================
# FORGOT PASSWORD
# =========================================================

@app.route(
    "/forgot-password",
    methods=[
        "GET",
        "POST"
    ]
)
def forgot_password():

    if request.method == "GET":

        return render_template(
            "login.html",
            active_form="forgot"
        )

    email = request.form.get(
        "email",
        ""
    ).strip().lower()

    if (
        not email
        or not valid_email(email)
    ):

        return render_template(
            "login.html",

            error=(
                "Please enter a valid "
                "email address."
            ),

            active_form="forgot",

            forgot_email=email
        )

    conn = get_db_connection()

    # -----------------------------------------------------
    # ONLY LOCAL ACCOUNTS
    # -----------------------------------------------------

    user = conn.execute(
        """
        SELECT
            username,
            full_name,
            email,
            auth_provider

        FROM users

        WHERE LOWER(email) = LOWER(?)

        AND (
            auth_provider IS NULL
            OR auth_provider = 'local'
        )
        """,
        (email,)
    ).fetchone()

    conn.close()

    # -----------------------------------------------------
    # IMPORTANT:
    # DO NOT REVEAL WHETHER EMAIL EXISTS
    # -----------------------------------------------------

    generic_success_message = (
        "If a CareerBot account exists "
        "for that email address, "
        "a password reset link has been sent."
    )

    # No local user found
    if user is None:

        return render_template(
            "login.html",

            success=(
                generic_success_message
            ),

            active_form="login"
        )

    # -----------------------------------------------------
    # CREATE RESET TOKEN
    # -----------------------------------------------------

    reset_token = (
        create_password_reset_token(
            user["username"],
            user["email"]
        )
    )

    # -----------------------------------------------------
    # CREATE ABSOLUTE RESET URL
    # -----------------------------------------------------

    reset_url = url_for(
        "reset_password",
        token=reset_token,
        _external=True
    )

    # -----------------------------------------------------
    # SEND EMAIL
    # -----------------------------------------------------

    try:

        send_password_reset_email(

            recipient_email=(
                user["email"]
            ),

            full_name=(
                user["full_name"]
            ),

            reset_url=(
                reset_url
            )
        )

    except Exception as error:

        print(
            "\nEMAIL RESET ERROR:"
        )

        print(
            error
        )

        return render_template(
            "login.html",

            error=(
                "CareerBot could not send "
                "the reset email. "
                "Please check the email "
                "configuration in .env."
            ),

            active_form="forgot",

            forgot_email=email
        )

    return render_template(
        "login.html",

        success=(
            generic_success_message
        ),

        active_form="login"
    )


# =========================================================
# RESET PASSWORD USING TOKEN
# =========================================================

@app.route(
    "/reset-password/<token>",
    methods=[
        "GET",
        "POST"
    ]
)
def reset_password(
    token
):

    # -----------------------------------------------------
    # VERIFY TOKEN
    # -----------------------------------------------------

    try:

        token_data = (
            verify_password_reset_token(
                token
            )
        )

    except SignatureExpired:

        return render_template(
            "login.html",

            error=(
                "This password reset link "
                "has expired. Please request "
                "a new one."
            ),

            active_form="forgot"
        )

    except BadSignature:

        return render_template(
            "login.html",

            error=(
                "This password reset link "
                "is invalid."
            ),

            active_form="forgot"
        )

    username = token_data.get(
        "username"
    )

    email = token_data.get(
        "email"
    )

    if (
        not username
        or not email
    ):

        return render_template(
            "login.html",

            error=(
                "Invalid password reset request."
            ),

            active_form="forgot"
        )

    # =====================================================
    # SHOW RESET FORM
    # =====================================================

    if request.method == "GET":

        return render_template(
            "login.html",

            active_form="reset",

            reset_token=token
        )

    # =====================================================
    # PROCESS NEW PASSWORD
    # =====================================================

    new_password = request.form.get(
        "new_password",
        ""
    )

    confirm_password = request.form.get(
        "confirm_password",
        ""
    )

    if (
        not new_password
        or not confirm_password
    ):

        return render_template(
            "login.html",

            error=(
                "Please enter and confirm "
                "your new password."
            ),

            active_form="reset",

            reset_token=token
        )

    if new_password != confirm_password:

        return render_template(
            "login.html",

            error=(
                "The two passwords "
                "do not match."
            ),

            active_form="reset",

            reset_token=token
        )

    if len(new_password) < 8:

        return render_template(
            "login.html",

            error=(
                "Password must contain "
                "at least 8 characters."
            ),

            active_form="reset",

            reset_token=token
        )

    conn = get_db_connection()

    # -----------------------------------------------------
    # VERIFY ACCOUNT STILL MATCHES TOKEN
    # -----------------------------------------------------

    user = conn.execute(
        """
        SELECT username
        FROM users

        WHERE username = ?

        AND LOWER(email) = LOWER(?)

        AND (
            auth_provider IS NULL
            OR auth_provider = 'local'
        )
        """,
        (
            username,
            email
        )
    ).fetchone()

    if user is None:

        conn.close()

        return render_template(
            "login.html",

            error=(
                "The account associated "
                "with this reset link "
                "could not be found."
            ),

            active_form="forgot"
        )

    # -----------------------------------------------------
    # SAVE HASHED NEW PASSWORD
    # -----------------------------------------------------

    new_password_hash = (
        generate_password_hash(
            new_password
        )
    )

    conn.execute(
        """
        UPDATE users

        SET password = ?

        WHERE username = ?
        """,
        (
            new_password_hash,
            username
        )
    )

    conn.commit()
    conn.close()

    return render_template(
        "login.html",

        success=(
            "Password reset successfully. "
            "You can now sign in using "
            "your new password."
        ),

        active_form="login",

        login_username=username
    )


# =========================================================
# GUEST LOGIN
# =========================================================

@app.route(
    "/guest-login"
)
def guest_login():

    session.clear()

    guest_username = (
        "guest_"
        + secrets.token_hex(
            5
        )
    )

    session["user"] = (
        guest_username
    )

    session["display_name"] = (
        "Guest"
    )

    session["auth_provider"] = (
        "guest"
    )

    session["is_guest"] = (
        True
    )

    return redirect(
        url_for(
            "dashboard"
        )
    )


# =========================================================
# GOOGLE LOGIN
# =========================================================

@app.route(
    "/auth/google"
)
def google_login():

    if (
        not os.getenv(
            "GOOGLE_CLIENT_ID"
        )
        or not os.getenv(
            "GOOGLE_CLIENT_SECRET"
        )
    ):

        return render_template(
            "login.html",

            error=(
                "Google Login is not "
                "configured yet."
            ),

            active_form="login"
        )

    callback_url = url_for(
        "google_callback",
        _external=True
    )

    return google.authorize_redirect(
        callback_url
    )


@app.route(
    "/auth/google/callback"
)
def google_callback():

    try:

        token = (
            google.authorize_access_token()
        )

        user_info = token.get(
            "userinfo"
        )

        if not user_info:

            response = google.get(
                "https://openidconnect.googleapis.com/"
                "v1/userinfo",
                token=token
            )

            user_info = (
                response.json()
            )

        username, full_name = (
            save_social_user(
                "google",
                user_info
            )
        )

        start_session(
            username,
            "google",
            full_name
        )

        return redirect(
            url_for(
                "dashboard"
            )
        )

    except Exception as error:

        print(
            "GOOGLE LOGIN ERROR:",
            error
        )

        return render_template(
            "login.html",

            error=(
                "Google login failed. "
                "Please check the OAuth "
                "configuration."
            ),

            active_form="login"
        )


# =========================================================
# LINKEDIN LOGIN
# =========================================================

@app.route(
    "/auth/linkedin"
)
def linkedin_login():

    if (
        not os.getenv(
            "LINKEDIN_CLIENT_ID"
        )
        or not os.getenv(
            "LINKEDIN_CLIENT_SECRET"
        )
    ):

        return render_template(
            "login.html",

            error=(
                "LinkedIn Login is not "
                "configured yet."
            ),

            active_form="login"
        )

    callback_url = url_for(
        "linkedin_callback",
        _external=True
    )

    return linkedin.authorize_redirect(
        callback_url
    )


@app.route(
    "/auth/linkedin/callback"
)
def linkedin_callback():

    try:

        token = (
            linkedin.authorize_access_token()
        )

        user_info = token.get(
            "userinfo"
        )

        if not user_info:

            response = linkedin.get(
                "https://api.linkedin.com/"
                "v2/userinfo",
                token=token
            )

            user_info = (
                response.json()
            )

        username, full_name = (
            save_social_user(
                "linkedin",
                user_info
            )
        )

        start_session(
            username,
            "linkedin",
            full_name
        )

        return redirect(
            url_for(
                "dashboard"
            )
        )

    except Exception as error:

        print(
            "LINKEDIN LOGIN ERROR:",
            error
        )

        return render_template(
            "login.html",

            error=(
                "LinkedIn login failed. "
                "Please check the OAuth "
                "configuration."
            ),

            active_form="login"
        )


# =========================================================
# MICROSOFT LOGIN
# =========================================================

@app.route(
    "/auth/microsoft"
)
def microsoft_login():

    if (
        not os.getenv(
            "MICROSOFT_CLIENT_ID"
        )
        or not os.getenv(
            "MICROSOFT_CLIENT_SECRET"
        )
    ):

        return render_template(
            "login.html",

            error=(
                "Microsoft Login is not "
                "configured yet."
            ),

            active_form="login"
        )

    callback_url = url_for(
        "microsoft_callback",
        _external=True
    )

    return microsoft.authorize_redirect(
        callback_url
    )


@app.route(
    "/auth/microsoft/callback"
)
def microsoft_callback():

    try:

        token = (
            microsoft.authorize_access_token()
        )

        user_info = token.get(
            "userinfo"
        )

        if not user_info:

            response = microsoft.get(
                "https://graph.microsoft.com/"
                "oidc/userinfo",
                token=token
            )

            user_info = (
                response.json()
            )

        username, full_name = (
            save_social_user(
                "microsoft",
                user_info
            )
        )

        start_session(
            username,
            "microsoft",
            full_name
        )

        return redirect(
            url_for(
                "dashboard"
            )
        )

    except Exception as error:

        print(
            "MICROSOFT LOGIN ERROR:",
            error
        )

        return render_template(
            "login.html",

            error=(
                "Microsoft login failed. "
                "Please check the OAuth "
                "configuration."
            ),

            active_form="login"
        )


# =========================================================
# LOGOUT
# =========================================================

@app.route(
    "/logout"
)
def logout():

    # -----------------------------------------------------
    # DELETE TEMPORARY GUEST INFORMATION
    # -----------------------------------------------------

    if session.get(
        "is_guest"
    ):

        guest_username = (
            session.get(
                "user"
            )
        )

        if guest_username:

            conn = (
                get_db_connection()
            )

            conn.execute(
                """
                DELETE FROM messages
                WHERE username = ?
                """,
                (
                    guest_username,
                )
            )

            conn.execute(
                """
                DELETE FROM profiles
                WHERE username = ?
                """,
                (
                    guest_username,
                )
            )

            conn.execute("DELETE FROM conversation_profiles WHERE username = ?", (guest_username,))
            conn.commit()
            conn.close()

    session.clear()

    return redirect(
        url_for(
            "login"
        )
    )


def get_active_conversation(conn, username, requested_id=None):
    current = session.get("conversation_id")
    if isinstance(requested_id, str) and requested_id != current:
        owned = conn.execute(
            "SELECT 1 FROM messages WHERE username = ? AND conversation_id = ? LIMIT 1",
            (username, requested_id)
        ).fetchone()
        if owned:
            current = requested_id
    if not current:
        last = conn.execute(
            "SELECT conversation_id FROM messages WHERE username = ? ORDER BY id DESC LIMIT 1",
            (username,)
        ).fetchone()
        current = last["conversation_id"] if last else secrets.token_hex(16)
    session["conversation_id"] = current
    return current


# =========================================================
# DASHBOARD
# =========================================================

@app.route(
    "/dashboard",
    methods=[
        "GET",
        "POST"
    ]
)
def dashboard():

    if "user" not in session:

        return redirect(
            url_for(
                "login"
            )
        )

    username = (
        session["user"]
    )

    conn = (
        get_db_connection()
    )

    conversation_id = get_active_conversation(conn, username, request.args.get("conversation_id"))

    display_name = (
        get_display_name(
            conn,
            username
        )
    )

    # =====================================================
    # ROADMAP FORM
    # =====================================================

    if request.method == "POST":

        current_education = (
            request.form.get(
                "current_education",
                ""
            ).strip()
        )

        graduation_year = (
            request.form.get(
                "graduation_year",
                ""
            ).strip()
        )

        current_skills = (
            request.form.get(
                "current_skills",
                ""
            ).strip()
        )

        skill_level = (
            request.form.get(
                "skill_level",
                ""
            ).strip()
        )

        career_goal = (
            request.form.get(
                "career_goal",
                ""
            ).strip()
        )

        career_preference = (
            request.form.get(
                "career_preference",
                ""
            ).strip()
        )

        preferred_country = (
            request.form.get(
                "preferred_country",
                ""
            ).strip()
        )

        preferred_city = (
            request.form.get(
                "preferred_city",
                ""
            ).strip()
        )

        if not all(
            [
                current_education,
                graduation_year,
                current_skills,
                skill_level,
                career_goal,
                career_preference,
                preferred_country,
                preferred_city
            ]
        ):

            conn.close()

            return redirect(
                url_for(
                    "dashboard"
                )
            )

        # -------------------------------------------------
        # SAVE / UPDATE PROFILE
        # -------------------------------------------------

        profile_exists = (
            conn.execute(
                """
                SELECT username
                FROM profiles
                WHERE username = ?
                """,
                (
                    username,
                )
            ).fetchone()
        )

        if profile_exists:

            conn.execute(
                """
                UPDATE profiles

                SET
                    name = ?,
                    current_education = ?,
                    graduation_year = ?,
                    current_skills = ?,
                    skill_level = ?,
                    career_goal = ?,
                    career_preference = ?,
                    preferred_country = ?,
                    preferred_city = ?

                WHERE username = ?
                """,
                (
                    display_name,
                    current_education,
                    graduation_year,
                    current_skills,
                    skill_level,
                    career_goal,
                    career_preference,
                    preferred_country,
                    preferred_city,
                    username
                )
            )

        else:

            conn.execute(
                """
                INSERT INTO profiles (

                    username,

                    name,

                    current_education,

                    graduation_year,

                    current_skills,

                    skill_level,

                    career_goal,

                    career_preference,

                    preferred_country,

                    preferred_city
                )

                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    username,
                    display_name,
                    current_education,
                    graduation_year,
                    current_skills,
                    skill_level,
                    career_goal,
                    career_preference,
                    preferred_country,
                    preferred_city
                )
            )

        conn.commit()

        # -------------------------------------------------
        # LOAD CONVERSATION HISTORY
        # -------------------------------------------------

        history_rows = (
            conn.execute(
                """
                SELECT
                    role,
                    content

                FROM messages

                WHERE username = ? AND conversation_id = ?

                ORDER BY id ASC
                """,
                (
                    username, conversation_id,
                )
            ).fetchall()
        )

        conversation_history = [
            dict(row)
            for row in history_rows
        ]

        # -------------------------------------------------
        # CAREER ROADMAP REQUEST
        # -------------------------------------------------

        user_message = (
            f"My current education is "
            f"{current_education}. "
            f"My graduation year is "
            f"{graduation_year}. "
            f"My current skills are "
            f"{current_skills}. "
            f"My skill level is "
            f"{skill_level}. "
            f"My career goal is "
            f"{career_goal}. "
            f"My career preference is "
            f"{career_preference}. "
            f"My preferred country for study or work is "
            f"{preferred_country}. "
            f"My preferred city is "
            f"{preferred_city}. "
            f"Please generate my personalized "
            f"career roadmap according to my preferred location."
        )

        conn.execute(
            """
            INSERT INTO messages (

                username,

                role,

                content, conversation_id
            )

            VALUES (?, ?, ?, ?)
            """,
            (
                username,
                "user",
                user_message, conversation_id
            )
        )

        conn.commit()

        # -------------------------------------------------
        # PROFILE FOR AI
        # -------------------------------------------------

        profile_for_ai = {

            "name":
                display_name,

            "degree":
                current_education,

            "interests":
                (
                    f"Current Skills: "
                    f"{current_skills}. "

                    f"Skill Level: "
                    f"{skill_level}. "

                    f"Career Goal: "
                    f"{career_goal}. "

                    f"Career Preference: "
                    f"{career_preference}. "

                    f"Preferred Country: "
                    f"{preferred_country}. "

                    f"Preferred City: "
                    f"{preferred_city}. "

                    f"Graduation Year: "
                    f"{graduation_year}."
                ),

            "current_education":
                current_education,

            "graduation_year":
                graduation_year,

            "current_skills":
                current_skills,

            "skill_level":
                skill_level,

            "career_goal":
                career_goal,

            "career_preference":
                career_preference,

            "preferred_country":
                preferred_country,

            "preferred_city":
                preferred_city
        }

        conn.execute(
            "INSERT OR REPLACE INTO conversation_profiles (username, conversation_id, profile_json) VALUES (?, ?, ?)",
            (username, conversation_id, json.dumps(profile_for_ai))
        )
        conn.commit()

        # -------------------------------------------------
        # AI GENERATION
        # -------------------------------------------------

        try:

            ai_text = (
                generate_ai_response(

                    user_profile=(
                        profile_for_ai
                    ),

                    conversation_history=(
                        conversation_history
                    ),

                    user_message=(
                        user_message
                    )
                )
            )

        except Exception as error:

            print(
                "AI ERROR:",
                error
            )

            ai_text = (
                "### AI Engine Error\n\n"
                "CareerBot could not generate "
                "your roadmap right now."
            )

        if (
            not ai_text
            or not ai_text.strip()
        ):

            ai_text = (
                "### Empty AI Response\n\n"
                "Please make sure the AI "
                "engine is running."
            )

        # -------------------------------------------------
        # SAVE AI RESPONSE
        # -------------------------------------------------

        conn.execute(
            """
            INSERT INTO messages (

                username,

                role,

                content, conversation_id
            )

            VALUES (?, ?, ?, ?)
            """,
            (
                username,
                "ai",
                ai_text, conversation_id
            )
        )

        conn.commit()
        conn.close()

        return redirect(
            url_for(
                "dashboard"
            )
        )

    # =====================================================
    # LOAD DASHBOARD
    # =====================================================

    profile_row = conn.execute(
        """
        SELECT *
        FROM profiles
        WHERE username = ?
        """,
        (
            username,
        )
    ).fetchone()

    profile = (
        dict(
            profile_row
        )
        if profile_row
        else None
    )

    chat_rows = conn.execute(
        """
        SELECT
            id,
            role,
            content

        FROM messages

        WHERE username = ? AND conversation_id = ?

        ORDER BY id ASC
        """,
        (
            username, conversation_id,
        )
    ).fetchall()

    chat_history = [
        dict(row)
        for row in chat_rows
    ]

    recent_chats = [dict(row) for row in conn.execute(
        """SELECT id, content, conversation_id FROM messages
           WHERE username = ? AND role = 'user' ORDER BY id DESC LIMIT 7""",
        (username,)
    ).fetchall()]

    conn.close()

    return render_template(

        "dashboard.html",

        user=username,

        display_name=display_name,

        profile=profile,

        chat_history=chat_history,

        recent_chats=recent_chats,

        active_conversation_id=conversation_id,

        is_guest=session.get(
            "is_guest",
            False
        ),

        auth_provider=session.get(
            "auth_provider",
            "local"
        )
    )


# =========================================================
# NEW SESSION
# =========================================================

@app.route(
    "/clear_chat"
)
def clear_chat():

    if "user" not in session:
        return redirect(url_for("login"))

    # Start a new empty conversation. Do not delete any existing messages.
    session["conversation_id"] = secrets.token_hex(16)
    return redirect(url_for("dashboard"))


# =========================================================
# LIVE AI CHAT
# =========================================================

@app.route(
    "/chat",
    methods=["POST"]
)
def chat():

    if "user" not in session:

        return jsonify(
            {
                "response":
                    "Unauthorized"
            }
        ), 401

    username = (
        session["user"]
    )

    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

    user_message = (
        data.get(
            "message",
            ""
        ).strip()
    )

    if not user_message:

        return jsonify(
            {
                "response":
                    "Please enter a question."
            }
        ), 400

    conn = (
        get_db_connection()
    )

    conversation_id = get_active_conversation(conn, username, data.get("conversation_id"))

    display_name = (
        get_display_name(
            conn,
            username
        )
    )

    profile_row = (
        conn.execute(
            """
            SELECT *
            FROM profiles
            WHERE username = ?
            """,
            (
                username,
            )
        ).fetchone()
    )

    profile = (
        dict(
            profile_row
        )
        if profile_row
        else {}
    )

    history_rows = (
        conn.execute(
            """
            SELECT
                role,
                content

            FROM messages

            WHERE username = ? AND conversation_id = ?

            ORDER BY id ASC
            """,
            (
                username, conversation_id,
            )
        ).fetchall()
    )

    conversation_history = [
        dict(row)
        for row in history_rows
    ]

    conn.execute(
        """
        INSERT INTO messages (

            username,

            role,

            content, conversation_id
        )

        VALUES (?, ?, ?, ?)
        """,
        (
            username,
            "user",
            user_message, conversation_id
        )
    )

    conn.commit()

    profile_for_ai = {

        "name":
            display_name,

        "degree":
            (
                profile.get(
                    "current_education"
                )
                or "Unknown"
            ),

        "interests":
            (
                "Skills: "
                + str(
                    profile.get(
                        "current_skills",
                        "Unknown"
                    )
                )

                + ". Skill level: "
                + str(
                    profile.get(
                        "skill_level",
                        "Unknown"
                    )
                )

                + ". Career Goal: "
                + str(
                    profile.get(
                        "career_goal",
                        "Unknown"
                    )
                )

                + ". Career Preference: "
                + str(
                    profile.get(
                        "career_preference",
                        "Unknown"
                    )
                )

                + ". Preferred Country: "
                + str(
                    profile.get(
                        "preferred_country",
                        "Unknown"
                    )
                )

                + ". Preferred City: "
                + str(
                    profile.get(
                        "preferred_city",
                        "Unknown"
                    )
                )
            ),

        "preferred_country":
            profile.get(
                "preferred_country",
                "Unknown"
            ),

        "preferred_city":
            profile.get(
                "preferred_city",
                "Unknown"
            )
    }

    # Reopened conversations retain the student profile used for their roadmap.
    snapshot = conn.execute(
        "SELECT profile_json FROM conversation_profiles WHERE username = ? AND conversation_id = ?",
        (username, conversation_id)
    ).fetchone()
    if snapshot:
        profile_for_ai = json.loads(snapshot["profile_json"])

    try:

        ai_text = (
            generate_ai_response(

                user_profile=(
                    profile_for_ai
                ),

                conversation_history=(
                    conversation_history
                ),

                user_message=(
                    user_message
                )
            )
        )

    except Exception as error:

        print(
            "CHAT ERROR:",
            error
        )

        ai_text = (
            "CareerBot could not answer "
            "right now."
        )

    conn.execute(
        """
        INSERT INTO messages (

            username,

            role,

            content, conversation_id
        )

        VALUES (?, ?, ?, ?)
        """,
        (
            username,
            "ai",
            ai_text, conversation_id
        )
    )

    conn.commit()
    conn.close()

    return jsonify(
        {
            "response":
                ai_text
        }
    )


# =========================================================
# START APPLICATION
# =========================================================

if __name__ == "__main__":

    warm_up_model()

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True,
        use_reloader=False
    )