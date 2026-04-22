import sys
import traceback
import logging

# WARNING level suppresses watchdog inotify DEBUG noise in Railway logs
logging.basicConfig(level=logging.WARNING)
# Silence watchdog specifically in case other libs set it lower
logging.getLogger("watchdog").setLevel(logging.ERROR)
logging.getLogger("watchdog.observers.inotify_buffer").setLevel(logging.ERROR)

try:
    import streamlit as st
    import google.generativeai as genai
    import os
    import json
    import requests
    import datetime
    from datetime import timedelta
    import base64
    import io
    import sys
    import secrets
except Exception as e:
    print("STARTUP ERROR:", e)
    traceback.print_exc()
    sys.exit(1)

import streamlit as st

try:
    from PIL import Image as _PILImage
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

try:
    from streamlit_mic_recorder import mic_recorder
    MIC_RECORDER_AVAILABLE = True
except ImportError:
    MIC_RECORDER_AVAILABLE = False

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False

st.set_page_config(
    page_title="Golden Draught",
    page_icon="🍺",
    layout="centered",
    initial_sidebar_state="collapsed",
)

STATIC_IMG_DIR = os.path.join(os.path.dirname(__file__), "static", "images")
LOG_DIR        = os.path.join(os.path.dirname(__file__), "log")
FEEDBACK_DIR   = os.path.join(os.path.dirname(__file__), "feedback")

# Only create static dir unconditionally — log/feedback dirs are only
# created on-demand (local fallback) to avoid watchdog inotify noise on Railway
os.makedirs(STATIC_IMG_DIR, exist_ok=True)

try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    genai = None

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

GEMINI_API_KEY           = os.getenv("GEMINI_API_KEY")
GOOGLE_CSE_API_KEY       = os.getenv("GOOGLE_CSE_API_KEY")
GOOGLE_CSE_CX            = os.getenv("GOOGLE_CSE_CX")
GOOGLE_PLACES_API_KEY    = os.getenv("GOOGLE_PLACES_API_KEY")
GOOGLE_GEOCODING_API_KEY = os.getenv("GOOGLE_GEOCODING_API_KEY") or GOOGLE_PLACES_API_KEY
DATABASE_URL             = os.getenv("DATABASE_URL")
BREWERY_SERVICE_URL      = os.getenv("BREWERY_SERVICE_URL", "")

# ── debug ────────────────────────────────────────────────────────────────────
def debug_print(msg, level="INFO"):
    c = {"INFO": "\033[94m", "SUCCESS": "\033[92m", "WARNING": "\033[93m",
         "ERROR": "\033[91m", "RESET": "\033[0m"}
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"{c.get(level, c['INFO'])}[{level}] [{ts}] {msg}{c['RESET']}", file=sys.stderr)

# ── PostgreSQL helpers ────────────────────────────────────────────────────────
def get_db_connection():
    """Return a psycopg2 connection using DATABASE_URL."""
    if not PSYCOPG2_AVAILABLE:
        debug_print("psycopg2 not installed", "ERROR")
        return None
    if not DATABASE_URL:
        debug_print("DATABASE_URL not set", "ERROR")
        return None
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except Exception as e:
        debug_print(f"DB connect error: {e}", "ERROR")
        return None

def init_db():
    """Create tables if they don't exist. Called once at startup."""
    conn = get_db_connection()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id           SERIAL PRIMARY KEY,
                username     VARCHAR(100),
                feedback_text TEXT NOT NULL,
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS beer_lists (
                id           SERIAL PRIMARY KEY,
                share_token  VARCHAR(20) UNIQUE NOT NULL,
                title        VARCHAR(200),
                username     VARCHAR(100),
                beers        JSONB NOT NULL,
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        cur.close()
        debug_print("DB tables ready", "SUCCESS")
    except Exception as e:
        debug_print(f"init_db error: {e}", "ERROR")
    finally:
        conn.close()

# Run once at module load
init_db()

# ── logging / feedback ────────────────────────────────────────────────────────


def save_feedback(username, feedback_text):
    """
    Save feedback to PostgreSQL (primary) with local file as fallback.
    """
    # ── Primary: PostgreSQL ──────────────────────────────────────────────────
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO feedback (username, feedback_text) VALUES (%s, %s)",
                (username, feedback_text)
            )
            conn.commit()
            cur.close()
            debug_print(f"Feedback saved to DB for {username}", "SUCCESS")
            return True
        except Exception as e:
            debug_print(f"DB feedback error, falling back: {e}", "WARNING")
        finally:
            conn.close()
    # ── Last resort: local file ───────────────────────────────────────────────
    try:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        content = (f"Feedback from: {username}\n"
                   f"Date: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                   + "=" * 50 + "\n\n" + feedback_text)
        os.makedirs(FEEDBACK_DIR, exist_ok=True)
        with open(os.path.join(FEEDBACK_DIR, f"{username}_{ts}.txt"), "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        debug_print(f"Local feedback failed: {e}", "ERROR")
    return True


def sanitize_beer_for_json(beer):
    """
    Return a copy of the beer dict with non-JSON-serializable fields removed.
    image_bytes is raw bytes and cannot be stored in PostgreSQL JSONB.
    The image URL (if any) is also transient so we drop it too — images
    are re-fetched from CSE when the shared page renders.
    """
    skip = {"image_bytes", "image"}
    return {k: v for k, v in beer.items() if k not in skip}


# ── Beer list persistence ─────────────────────────────────────────────────────
def save_beer_list(beers, username, title=None):
    """
    Save a list of beers to PostgreSQL and return the share token.
    Returns (token, error_message).
    Strips image_bytes and other non-serializable fields before storing.
    """
    conn = get_db_connection()
    if not conn:
        return None, "Database not available. Check DATABASE_URL."
    token = secrets.token_urlsafe(8)
    if not title:
        title = f"{username}'s Beer List — {datetime.datetime.now().strftime('%b %d %Y')}"
    try:
        # Strip bytes/non-serializable fields from every beer before storing
        clean_beers = [sanitize_beer_for_json(b) for b in beers]
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO beer_lists (share_token, title, username, beers)
               VALUES (%s, %s, %s, %s)""",
            (token, title, username, json.dumps(clean_beers))
        )
        conn.commit()
        cur.close()
        debug_print(f"Beer list saved with token {token}", "SUCCESS")
        return token, None
    except Exception as e:
        debug_print(f"save_beer_list error: {e}", "ERROR")
        return None, str(e)
    finally:
        conn.close()


def get_beer_list(token):
    """
    Retrieve a saved beer list by share token.
    Returns (title, beers_list, username, created_at) or None.
    """
    conn = get_db_connection()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT title, beers, username, created_at FROM beer_lists WHERE share_token = %s",
            (token,)
        )
        row = cur.fetchone()
        cur.close()
        if row:
            title, beers, username, created_at = row
            if isinstance(beers, str):
                beers = json.loads(beers)
            return title, beers, username, created_at
        return None
    except Exception as e:
        debug_print(f"get_beer_list error: {e}", "ERROR")
        return None
    finally:
        conn.close()


def format_list_as_text(beers, title, share_url):
    """Format beer list as plain text suitable for SMS or email copy/paste."""
    lines = [f"🍺 {title}", "=" * 40, ""]
    for i, beer in enumerate(beers, 1):
        lines.append(f"{i}. {beer.get('name', 'Unknown')} — {beer.get('brand', '')}")
        lines.append(f"   Style/ABV: {beer.get('abv', 'N/A')} | Cals: {beer.get('calories', 'N/A')}")
        lines.append(f"   {beer.get('description', '')}")
        lines.append("")
    lines.append(f"🔗 View full list: {share_url}")
    lines.append("Shared via Golden Draught 🍺 beer.dimensionunlimited.com")
    return "\n".join(lines)


# ── Gemini init ───────────────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def initialize_gemini_model():
    if not GENAI_AVAILABLE:
        return None, "google-generativeai not installed"
    if not GEMINI_API_KEY:
        return None, "GEMINI_API_KEY not set"
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        for model_name in ['gemini-3.1-flash-lite-preview', 'gemini-3-flash-preview']:
            try:
                debug_print(f"Trying {model_name}…", "INFO")
                m = genai.GenerativeModel(model_name)
                m.generate_content("hi")
                debug_print(f"Initialized {model_name}", "SUCCESS")
                return m, None
            except Exception as e:
                debug_print(f"Failed {model_name}: {e}", "WARNING")
        return None, "No Gemini model could be initialized"
    except Exception as e:
        return None, f"Gemini configure error: {e}"

processing_model, gemini_error = initialize_gemini_model()

# ── validation ────────────────────────────────────────────────────────────────
def validate_zipcode(zipcode):
    if not zipcode:
        return False, "Please enter a zipcode"
    clean = "".join(filter(str.isdigit, zipcode))
    if len(clean) != 5:
        return False, "Zipcode must be exactly 5 digits"
    if not (501 <= int(clean) <= 99950):
        return False, "Please enter a valid US zipcode"
    return True, clean

# ── CSS ───────────────────────────────────────────────────────────────────────
@st.cache_data
def get_mobile_css():
    return """
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Epilogue:wght@700;800;900&family=Plus+Jakarta+Sans:wght@400;500;600&family=Space+Grotesk:wght@500;700&display=swap');
        @import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=swap');

        :root {
            --bg-app:        #091421;
            --bg-card:       #121c2a;
            --bg-card-low:   #16202e;
            --text-main:     #d9e3f6;
            --text-sub:      #d3c5ac;
            --text-muted:    #9b8f79;
            --accent:        #ffd165;
            --accent-green:  #4ae176;
            --input-bg:      #0d1928;
            --input-text:    #d9e3f6;
            --border-gold:   rgba(255,209,101,0.40);
            --border-focus:  rgba(255,209,101,0.80);
        }

        .stApp { background-color: var(--bg-app) !important; color: var(--text-main); }

        .block-container {
            max-width: 460px !important;
            padding: 72px 16px 96px !important;
            margin: 0 auto;
        }

        header, footer, .stDeployButton,
        section[data-testid="stSidebarNav"],
        [data-testid="stToolbar"] { display: none !important; }

        /* ── APP BAR ── */
        .app-bar {
            position: fixed; top: 0; left: 0; right: 0; z-index: 999;
            background: #091421; border-bottom: 1px solid rgba(255,209,101,0.07);
            padding: 14px 20px; display: flex; align-items: center; justify-content: center;
        }
        .app-bar-title {
            font-family: 'Epilogue', sans-serif; font-weight: 900; font-size: 1rem;
            letter-spacing: 0.2em; text-transform: uppercase; color: #ffd165;
        }

        /* ── BOTTOM NAV ── */
        .bottom-nav {
            position: fixed; bottom: 0; left: 0; right: 0; z-index: 998;
            background: rgba(18,28,42,0.92); backdrop-filter: blur(24px);
            -webkit-backdrop-filter: blur(24px); height: 68px;
            display: flex; justify-content: space-around; align-items: center;
            border-radius: 24px 24px 0 0; box-shadow: 0 -8px 32px rgba(0,0,0,0.5);
            padding: 0 8px 4px;
        }
        .nav-item {
            display: flex; flex-direction: column; align-items: center; gap: 2px;
            color: rgba(217,227,246,0.4); padding: 4px 14px;
            font-family: 'Space Grotesk', sans-serif;
        }
        .nav-item.active { color: #ffd165; filter: drop-shadow(0 0 6px rgba(255,209,101,0.5)); }
        .nav-icon {
            font-family: 'Material Symbols Outlined'; font-size: 1.4rem; line-height: 1;
            font-variation-settings: 'FILL' 0,'wght' 400,'GRAD' 0,'opsz' 24;
        }
        .nav-icon.filled { font-variation-settings: 'FILL' 1,'wght' 400,'GRAD' 0,'opsz' 24; }
        .nav-label { font-size: 0.56rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.09em; }

        /* ── TYPOGRAPHY ── */
        h1, h2, h3, p, div {
            text-align: center !important;
            font-family: 'Plus Jakarta Sans', -apple-system, sans-serif;
        }
        .big-greeting {
            font-family: 'Epilogue', sans-serif; font-size: 2rem; font-weight: 900;
            margin: 14px 0 8px; letter-spacing: -0.01em;
            background: linear-gradient(90deg, #ffd165, #ffdf9a);
            -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
        }
        .gold-text { color: var(--accent) !important; }

        /* ── ALL TEXT INPUTS — gold border everywhere ── */
        .stTextInput > div > div {
            background-color: var(--input-bg) !important;
            border-radius: 14px !important;
            border: 1.5px solid var(--border-gold) !important;
            padding: 0 10px !important; box-shadow: none !important;
        }
        .stTextInput input {
            color: var(--input-text) !important; background-color: transparent !important;
            text-align: center !important; font-family: 'Plus Jakarta Sans', sans-serif !important;
            font-weight: 500 !important; caret-color: #ffd165 !important;
            padding: 12px 5px !important; outline: none !important;
            box-shadow: none !important; border: none !important;
        }
        .stTextInput input::placeholder { color: rgba(255,209,101,0.38) !important; opacity: 1 !important; }
        .stTextInput label {
            color: var(--accent) !important; font-family: 'Space Grotesk', sans-serif !important;
            font-size: 0.7rem !important; font-weight: 700 !important;
            text-transform: uppercase !important; letter-spacing: 0.12em !important;
            width: 100% !important; text-align: center !important;
        }
        .stTextInput > div > div:focus-within {
            border-color: var(--border-focus) !important;
            box-shadow: 0 0 0 3px rgba(255,209,101,0.12) !important;
        }
        .stTextInput input:focus { outline: none !important; box-shadow: none !important; }

        /* ── TEXT AREA — gold border ── */
        .stTextArea > div > div {
            background-color: var(--input-bg) !important;
            border-radius: 14px !important;
            border: 1.5px solid var(--border-gold) !important;
            box-shadow: none !important;
        }
        .stTextArea textarea {
            color: var(--input-text) !important; font-family: 'Plus Jakarta Sans', sans-serif !important;
            background-color: transparent !important; outline: none !important; box-shadow: none !important;
        }
        .stTextArea textarea::placeholder { color: rgba(255,209,101,0.38) !important; opacity: 1 !important; }
        .stTextArea label {
            color: var(--accent) !important; font-family: 'Space Grotesk', sans-serif !important;
            font-size: 0.7rem !important; font-weight: 700 !important;
            text-transform: uppercase !important; letter-spacing: 0.12em !important;
            width: 100% !important; text-align: center !important;
        }
        .stTextArea > div > div:focus-within {
            border-color: var(--border-focus) !important;
            box-shadow: 0 0 0 3px rgba(255,209,101,0.12) !important;
        }

        /* ── BUTTONS — centered, full-width ── */
        .stButton { display: flex !important; justify-content: center !important; width: 100% !important; }
        .stButton > button {
            width: 100% !important; border-radius: 14px !important; padding: 14px 20px !important;
            background: transparent !important; color: var(--accent) !important;
            border: 1.5px solid rgba(255,209,101,0.32) !important;
            font-family: 'Epilogue', sans-serif !important; font-weight: 900 !important;
            font-size: 0.82rem !important; text-transform: uppercase !important;
            letter-spacing: 0.07em !important; margin-top: 10px;
            transition: all 0.2s ease !important; opacity: 1 !important;
            margin-left: auto !important; margin-right: auto !important;
        }
        .stButton > button:hover {
            background: linear-gradient(135deg, #ffd165, #eab308) !important;
            color: #3f2e00 !important; border-color: transparent !important;
            box-shadow: 0 4px 16px rgba(255,209,101,0.25) !important;
        }
        .stButton > button:active, .stButton > button:focus { opacity: 1 !important; }

        div[data-testid="stFormSubmitButton"] {
            display: flex !important; justify-content: center !important; width: 100% !important;
        }
        div[data-testid="stFormSubmitButton"] > button {
            background: linear-gradient(135deg, #ffd165, #eab308) !important;
            color: #3f2e00 !important; border: none !important; width: 100% !important;
            opacity: 1 !important; box-shadow: 0 4px 16px rgba(255,209,101,0.2) !important;
        }
        .stForm [data-testid="InputInstructions"],
        div[class*="FormInstructions"] { display: none !important; }
        [data-testid="column"] .stButton { display: flex !important; justify-content: center !important; }
        [data-testid="column"] .stButton > button { width: 100% !important; }

        /* ── FILE UPLOADER — gold border ── */
        .stFileUploader label {
            color: var(--accent) !important; font-family: 'Space Grotesk', sans-serif !important;
            font-size: 0.7rem !important; font-weight: 700 !important; text-transform: uppercase !important;
        }
        .stFileUploader [data-testid="stFileUploaderDropzone"] {
            background: var(--input-bg) !important;
            border: 1.5px dashed var(--border-gold) !important; border-radius: 14px !important;
        }

        /* ── AUDIO INPUT — gold label ── */
        .stAudioInput { margin: 8px 0; }
        .stAudioInput label {
            color: var(--accent) !important; font-family: 'Space Grotesk', sans-serif !important;
            font-size: 0.7rem !important; font-weight: 700 !important;
            text-transform: uppercase !important; letter-spacing: 0.12em !important;
        }

        /* ── BEER CARD ── */
        .beer-card {
            background: var(--bg-card); border: 1px solid rgba(255,209,101,0.09);
            border-radius: 20px; padding: 20px; margin: 16px 0; position: relative; overflow: hidden;
        }
        .beer-card.unavailable { border-color: rgba(255,180,171,0.22); }
        .unavailable-badge {
            position: absolute; top: 14px; right: 14px;
            background: rgba(255,180,171,0.1); color: #ffb4ab;
            border: 1px solid rgba(255,180,171,0.3); border-radius: 20px; padding: 4px 10px;
            font-family: 'Space Grotesk', sans-serif; font-size: 0.62rem; font-weight: 700;
            text-transform: uppercase; letter-spacing: 0.08em;
        }
        .beer-title {
            font-family: 'Epilogue', sans-serif; font-size: 1.3rem; font-weight: 800;
            color: #d9e3f6; margin-bottom: 4px; letter-spacing: -0.01em;
        }
        .beer-brand {
            font-family: 'Space Grotesk', sans-serif; color: var(--accent);
            font-size: 0.7rem; font-weight: 700; text-transform: uppercase;
            letter-spacing: 0.12em; margin-bottom: 14px;
        }
        .beer-rating-badge {
            display: inline-flex; align-items: center; gap: 5px;
            background: rgba(255,209,101,0.1); border: 1px solid rgba(255,209,101,0.3);
            border-radius: 20px; padding: 4px 12px; margin-bottom: 10px;
            font-family: 'Space Grotesk', sans-serif; font-size: 0.72rem; font-weight: 700;
            color: #ffd165;
        }
        .beer-metrics { display: grid; grid-template-columns: repeat(3,1fr); gap: 8px; margin: 12px 0; }
        .metric-box {
            background: var(--bg-card-low); border-radius: 12px; padding: 10px 6px;
            text-align: center; border: 1px solid rgba(255,255,255,0.04);
        }
        .metric-value { font-family: 'Epilogue', sans-serif; font-size: 1.05rem; font-weight: 800; color: var(--accent); }
        .metric-label {
            font-family: 'Space Grotesk', sans-serif; font-size: 0.58rem; color: var(--text-muted);
            text-transform: uppercase; letter-spacing: 0.1em; margin-top: 2px;
        }
        .beer-detail-row {
            background: var(--bg-card-low); border-radius: 10px;
            padding: 10px 14px; margin: 7px 0; text-align: left !important;
        }
        .beer-detail-label {
            font-family: 'Space Grotesk', sans-serif; font-size: 0.62rem; font-weight: 700;
            color: var(--accent); text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 4px;
        }
        .beer-detail-value {
            font-family: 'Plus Jakarta Sans', sans-serif; font-size: 0.86rem;
            color: var(--text-sub); line-height: 1.5; text-align: left !important;
        }

        /* ── SHARE CARD ── */
        .share-card {
            background: linear-gradient(135deg, #121c2a, #16202e);
            border: 1px solid rgba(255,209,101,0.3); border-radius: 20px;
            padding: 20px; margin: 16px 0; text-align: center !important;
        }
        .share-url-box {
            background: #0d1928; border: 1px solid rgba(255,209,101,0.4);
            border-radius: 10px; padding: 12px; margin: 10px 0;
            font-family: 'Space Grotesk', sans-serif; font-size: 0.78rem;
            color: #ffd165; word-break: break-all; text-align: center !important;
        }
        .share-text-box {
            background: #0d1928; border: 1px solid rgba(255,209,101,0.2);
            border-radius: 10px; padding: 14px; margin: 10px 0;
            font-family: monospace; font-size: 0.75rem; color: #d3c5ac;
            text-align: left !important; white-space: pre-wrap; word-break: break-word;
            max-height: 280px; overflow-y: auto;
        }

        /* ── ZIP SEARCH PANEL ── */
        .zip-search-panel {
            background: var(--bg-card); border: 1px solid rgba(255,209,101,0.15);
            border-radius: 16px; padding: 16px; margin: 10px 0 4px;
        }
        .zip-search-title {
            font-family: 'Space Grotesk', sans-serif; font-size: 0.7rem; font-weight: 700;
            color: var(--accent); text-transform: uppercase; letter-spacing: 0.12em;
            text-align: center !important; margin-bottom: 8px;
        }

        /* ── BAR CARD ── */
        .bar-card {
            background: var(--bg-card-low); padding: 14px; margin: 10px 0;
            border-radius: 12px; border-left: 3px solid var(--accent);
        }
        .bar-name { font-family: 'Epilogue', sans-serif; font-weight: 800; color: #d9e3f6; font-size: 1rem; margin-bottom: 5px; }
        .bar-address { color: var(--text-sub); font-size: 0.82rem; margin: 4px 0; }
        .bar-rating  { color: var(--accent); margin-top: 6px; font-size: 0.85rem; }

        /* ── REFINE SEARCH BAR ── */
        .refine-bar {
            background: var(--bg-card); border: 1px solid rgba(255,209,101,0.15);
            border-radius: 16px; padding: 14px 16px; margin: 0 0 18px;
        }
        .refine-bar-label {
            font-family: 'Space Grotesk', sans-serif; font-size: 0.68rem; font-weight: 700;
            color: var(--accent); text-transform: uppercase; letter-spacing: 0.12em;
            text-align: center !important; margin-bottom: 8px;
        }

        /* ── VOICE BUBBLE ── */
        .voice-heard-bubble {
            background: #16202e; border-radius: 12px; padding: 12px 16px;
            border: 1px solid rgba(255,209,101,0.2); margin: 12px 0; text-align: center !important;
        }
        .voice-heard-label {
            font-size: 0.65rem; color: #ffd165; font-family: 'Space Grotesk',sans-serif;
            text-transform: uppercase; letter-spacing: 0.1em;
        }
        .voice-heard-text { color: #d9e3f6; font-size: 0.95rem; margin-top: 4px; }

        /* ── GAMES CARD ── */
        .game-card {
            background: var(--bg-card); border: 1px solid rgba(255,209,101,0.18);
            border-radius: 20px; padding: 20px; margin: 14px 0; cursor: pointer;
            transition: all 0.2s ease;
        }
        .game-card:hover { border-color: rgba(255,209,101,0.5); box-shadow: 0 4px 20px rgba(255,209,101,0.1); }
        .game-title { font-family: 'Epilogue', sans-serif; font-size: 1.2rem; font-weight: 900; color: #ffd165; }
        .game-desc { font-family: 'Plus Jakarta Sans', sans-serif; font-size: 0.82rem; color: #9b8f79; margin-top: 6px; }
        .score-badge {
            display: inline-block; background: rgba(255,209,101,0.12);
            border: 1px solid rgba(255,209,101,0.3); border-radius: 20px; padding: 4px 14px;
            font-family: 'Space Grotesk', sans-serif; font-size: 0.78rem; font-weight: 700; color: #ffd165;
            margin: 8px 0;
        }
        .celebrate-box {
            background: linear-gradient(135deg, #121c2a, #16202e);
            border: 2px solid #ffd165; border-radius: 20px; padding: 30px 20px;
            margin: 20px 0; text-align: center !important;
        }
        .celebrate-name {
            font-family: 'Epilogue', sans-serif; font-size: 1.6rem; font-weight: 900;
            background: linear-gradient(90deg, #ffd165, #4ae176);
            -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
        }

        /* ── MISC ── */
        .stSpinner > div { border-top-color: var(--accent) !important; }
        .streamlit-expanderHeader {
            background: var(--bg-card-low) !important; border-radius: 10px !important;
            color: var(--accent) !important; font-family: 'Space Grotesk',sans-serif !important;
            font-size: 0.82rem !important; font-weight: 700 !important;
        }
        .footer {
            margin-top: 40px; text-align: center !important;
            font-family: 'Space Grotesk', sans-serif; font-size: 0.7rem; color: var(--text-muted);
            padding: 20px 0 8px; border-top: 1px solid rgba(255,209,101,0.07); letter-spacing: 0.04em;
        }
        .debug-panel {
            background: var(--bg-card); border: 1px solid #333; border-radius: 12px;
            padding: 14px; margin: 16px 0; font-size: 0.8rem; color: #888; text-align: left !important;
        }
    </style>
    """

def inject_mobile_css():
    st.markdown(get_mobile_css(), unsafe_allow_html=True)

# ── image helpers ──────────────────────────────────────────────────────────────
@st.cache_data
def load_image_as_base64(image_path):
    if os.path.exists(image_path):
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return None

def render_logo():
    logo_path = os.path.join(os.path.dirname(__file__), "static", "images", "logo.png")
    enc = load_image_as_base64(logo_path)
    if enc:
        st.markdown(
            f'<div style="display:flex;justify-content:center;margin-bottom:20px;">'
            f'<img src="data:image/png;base64,{enc}" style="width:80px;height:80px;'
            f'border-radius:50%;border:2px solid #ffd165;box-shadow:0 0 20px rgba(255,209,101,0.25);">'
            f'</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div style="font-size:4rem;text-align:center;">🍺</div>', unsafe_allow_html=True)

def render_app_bar():
    st.markdown('<div class="app-bar"><span class="app-bar-title">Golden Draught</span></div>',
                unsafe_allow_html=True)

def render_bottom_nav(active="home"):
    items = [("home","home","Home"), ("search","document_scanner","Search"),
             ("saved","bookmarks","Saved"), ("feedback","rate_review","Feedback")]
    html = '<div class="bottom-nav">'
    for key, icon, label in items:
        is_active = (active == key)
        cls  = "nav-item active" if is_active else "nav-item"
        icls = "nav-icon filled" if is_active else "nav-icon"
        html += f'<span class="{cls}"><span class="{icls}">{icon}</span><span class="nav-label">{label}</span></span>'
    html += '</div>'
    st.markdown(html, unsafe_allow_html=True)

def render_footer():
    if st.session_state.step != 5:
        c1, c2, c3 = st.columns([1, 2, 1])
        with c2:
            if st.button("📝 Give us your feedback", key="feedback_link_btn", use_container_width=True):
                st.session_state.step = 5
                st.rerun()
    st.markdown('<div class="footer">© 2026 Dimension Unlimited. All rights reserved. Drink responsibly.</div>',
                unsafe_allow_html=True)

def render_debug_panel():
    if not st.session_state.get("show_debug"):
        return
    db_status = "✓" if (PSYCOPG2_AVAILABLE and DATABASE_URL) else "✗"
    st.markdown(f"""
    <div class="debug-panel">
        <strong>🔧 Debug</strong><br>
        • Gemini: {GENAI_AVAILABLE} | Key: {'✓' if GEMINI_API_KEY else '✗'} |
          Places: {'✓' if GOOGLE_PLACES_API_KEY else '✗'} |
          Model: {'✓' if processing_model else '✗'}<br>
        • Error: {gemini_error or 'None'}<br>
        • Step: {st.session_state.step} | Search: {st.session_state.user_data.get('search_type','—')}<br>
        • mic_recorder: {MIC_RECORDER_AVAILABLE} | audio_input: {hasattr(st,'audio_input')}<br>
        • DB: {db_status} | psycopg2: {PSYCOPG2_AVAILABLE}
    </div>""", unsafe_allow_html=True)

# ── DST-aware greeting ─────────────────────────────────────────────────────────
def get_greeting(zipcode="90210"):
    greeting = "Hello"
    time_str  = ""
    try:
        first = int(str(zipcode)[0]) if zipcode else 9
        if   first in [0, 1, 2, 3]: std = -5
        elif first in [4, 5, 6]:    std = -6
        elif first == 7:             std = -7
        else:                        std = -8

        now_utc = datetime.datetime.utcnow()
        y = now_utc.year

        def nth_sunday(yr, month, n):
            d = datetime.date(yr, month, 1)
            return d + timedelta(days=(6 - d.weekday()) % 7 + 7 * (n - 1))

        dst_on  = datetime.datetime(y, nth_sunday(y, 3,  2).month, nth_sunday(y, 3,  2).day, 2, 0)
        dst_off = datetime.datetime(y, nth_sunday(y, 11, 1).month, nth_sunday(y, 11, 1).day, 2, 0)

        approx_local = now_utc + timedelta(hours=std)
        offset       = std + (1 if dst_on <= approx_local < dst_off else 0)
        local_time   = now_utc + timedelta(hours=offset)
        hour         = local_time.hour

        if   5  <= hour < 12: greeting = "Good Morning"
        elif 12 <= hour < 17: greeting = "Good Afternoon"
        elif 17 <= hour < 22: greeting = "Good Evening"
        else:                 greeting = "Hey Night Owl"

        time_str = local_time.strftime("%I:%M %p")
    except Exception as e:
        debug_print(f"get_greeting: {e}", "WARNING")
    return greeting, time_str

# ── geocoding / image ──────────────────────────────────────────────────────────
_BLOCKED_DOMAINS = (
    "lookaside.fbsbx.com","fbcdn.net","facebook.com","fb.com",
    "instagram.com","cdninstagram.com","twimg.com","twitter.com","x.com",
    "tiktok.com","redd.it","reddit.com","pinterest.com","pinimg.com","snapchat.com",
)

def _safe_img(url):
    return not any(d in url for d in _BLOCKED_DOMAINS)

@st.cache_data(ttl=86400)
def _fetch_img_bytes(url):
    try:
        hdrs = {"User-Agent": "Mozilla/5.0 Chrome/124", "Accept": "image/*"}
        r    = requests.get(url, headers=hdrs, timeout=7)
        ct   = r.headers.get("Content-Type", "")
        if r.status_code != 200 or "image" not in ct or len(r.content) < 200:
            return None
        raw = r.content
        if _PIL_AVAILABLE:
            img = _PILImage.open(io.BytesIO(raw))
            img.thumbnail((400, 400), _PILImage.LANCZOS)
            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=82, optimize=True)
            return buf.getvalue()
        return raw if len(raw) <= 150_000 else None
    except Exception as e:
        debug_print(f"Image fetch: {e}", "WARNING")
    return None

@st.cache_data(ttl=86400)
def cse_image_search(query):
    if not GOOGLE_CSE_API_KEY or not GOOGLE_CSE_CX:
        return None
    try:
        r = requests.get("https://www.googleapis.com/customsearch/v1",
                         params={"key": GOOGLE_CSE_API_KEY, "cx": GOOGLE_CSE_CX,
                                 "q": query, "num": 6, "searchType": "image",
                                 "imgType": "photo", "safe": "active"}, timeout=5)
        if r.status_code == 200:
            for item in r.json().get("items", []):
                url = item.get("link", "")
                if url and _safe_img(url):
                    return url
    except Exception as e:
        debug_print(f"CSE: {e}", "ERROR")
    return None

@st.cache_data(ttl=86400)
def zip_to_coords(zipcode):
    if not GOOGLE_GEOCODING_API_KEY:
        return None, None
    try:
        r = requests.get("https://maps.googleapis.com/maps/api/geocode/json",
                         params={"address": zipcode, "key": GOOGLE_GEOCODING_API_KEY}, timeout=5)
        if r.status_code == 200:
            res = r.json().get("results", [])
            if res:
                loc = res[0]["geometry"]["location"]
                return loc["lat"], loc["lng"]
    except Exception as e:
        debug_print(f"Geocode: {e}", "ERROR")
    return None, None

@st.cache_data(ttl=86400)
def city_state_from_zip(zipcode):
    if not GOOGLE_GEOCODING_API_KEY:
        return "", ""
    try:
        r = requests.get("https://maps.googleapis.com/maps/api/geocode/json",
                         params={"address": zipcode, "key": GOOGLE_GEOCODING_API_KEY}, timeout=5)
        if r.status_code == 200:
            res = r.json().get("results", [])
            if res:
                city  = ""
                state = ""
                for c in res[0].get("address_components", []):
                    types = c.get("types", [])
                    if "locality" in types:
                        city  = c.get("long_name", "")
                    if "administrative_area_level_1" in types:
                        state = c.get("short_name", "")
                return city, state
    except Exception as e:
        debug_print(f"city_state_from_zip: {e}", "ERROR")
    return "", ""

def city_from_zip(zipcode):
    city, _ = city_state_from_zip(zipcode)
    return city

# ── bar-finding agents ─────────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def web_search_bars(beer_name, brand, zipcode, city):
    if not GOOGLE_CSE_API_KEY or not GOOGLE_CSE_CX:
        return []
    results = []
    for q in [f"{beer_name} {brand} bars near {zipcode}",
              f"where to drink {beer_name} in {city}"]:
        try:
            r = requests.get("https://www.googleapis.com/customsearch/v1",
                             params={"key": GOOGLE_CSE_API_KEY, "cx": GOOGLE_CSE_CX,
                                     "q": q, "num": 5}, timeout=10)
            if r.status_code == 200:
                results.extend(r.json().get("items", []))
        except Exception as e:
            debug_print(f"Bar search: {e}", "ERROR")
    return results

def ai_extract_bar_names(web_results, beer_name, city):
    if not processing_model or not web_results:
        return []
    try:
        summary = "\n".join(
            f"Result {i+1}: {r.get('title','')} - {r.get('snippet','')}"
            for i, r in enumerate(web_results[:8]))
        prompt = (f"Extract real bar names from these search results about {beer_name} in {city}.\n\n"
                  f"{summary}\n\n"
                  f'Return ONLY JSON: [{{"name":"Bar Name","confidence":"high/medium"}}] '
                  f"Max 8. No markdown.")
        resp = processing_model.generate_content(prompt)
        if not resp or not resp.text:
            return []
        text = resp.text.strip()
        if "```json" in text: text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:   text = text.split("```")[1].split("```")[0].strip()
        bars = json.loads(text)
        return bars if isinstance(bars, list) else []
    except Exception as e:
        debug_print(f"Bar extract: {e}", "ERROR")
        return []

def verify_bars_places(bar_names, lat, lng, radius=16093):
    if not GOOGLE_PLACES_API_KEY or not bar_names:
        return []
    verified = []
    for bd in bar_names[:10]:
        name = bd.get("name", "") if isinstance(bd, dict) else bd
        try:
            r = requests.post(
                "https://places.googleapis.com/v1/places:searchText",
                json={"textQuery": f"{name} near {lat},{lng}",
                      "locationBias": {"circle": {"center": {"latitude": lat, "longitude": lng},
                                                   "radius": radius}},
                      "maxResultCount": 1},
                headers={"Content-Type": "application/json",
                         "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
                         "X-Goog-FieldMask": ("places.displayName,places.formattedAddress,"
                                               "places.rating,places.priceLevel,places.id,places.location")},
                timeout=10)
            if r.status_code == 200:
                places = r.json().get("places", [])
                if places:
                    p  = places[0]
                    pl = p.get("priceLevel")
                    verified.append({
                        "name":        p.get("displayName", {}).get("text", name),
                        "address":     p.get("formattedAddress", "Address not available"),
                        "rating":      p.get("rating", "N/A"),
                        "price_level": "$" * int(pl) if pl and str(pl).isdigit() else "$$",
                        "place_id":    p.get("id", ""),
                        "lat":         p.get("location", {}).get("latitude"),
                        "lng":         p.get("location", {}).get("longitude"),
                    })
        except Exception as e:
            debug_print(f"Places verify: {e}", "ERROR")
        if len(verified) >= 5:
            break
    return verified

@st.cache_data(ttl=3600)
def find_bars_nearby(lat, lng, beer_name, brand, zipcode):
    city  = city_from_zip(zipcode)
    webs  = web_search_bars(beer_name, brand, zipcode, city)
    if not webs: return []
    names = ai_extract_bar_names(webs, beer_name, city)
    if not names: return []
    return verify_bars_places(names, lat, lng, radius=16093)

@st.cache_data(ttl=3600)
def find_na_venues_nearby(lat, lng, zipcode):
    if not GOOGLE_PLACES_API_KEY:
        return []
    city = city_from_zip(zipcode)
    queries = [
        f"non-alcoholic beer bar near {city}",
        f"craft non-alcoholic drinks near {zipcode}",
    ]
    names = []
    if GOOGLE_CSE_API_KEY and GOOGLE_CSE_CX:
        for q in queries:
            try:
                r = requests.get("https://www.googleapis.com/customsearch/v1",
                                 params={"key": GOOGLE_CSE_API_KEY, "cx": GOOGLE_CSE_CX,
                                         "q": q, "num": 5}, timeout=10)
                if r.status_code == 200:
                    items = r.json().get("items", [])
                    if items and processing_model:
                        summary = "\n".join(
                            f"{i+1}: {it.get('title','')} - {it.get('snippet','')}"
                            for i, it in enumerate(items[:6]))
                        prompt = (f"Extract real bar/venue names from results about non-alcoholic drinks in {city}.\n"
                                  f"{summary}\n"
                                  f'Return ONLY JSON: [{{"name":"Venue Name","confidence":"high/medium"}}] Max 6. No markdown.')
                        resp = processing_model.generate_content(prompt)
                        if resp and resp.text:
                            text = resp.text.strip()
                            if "```json" in text: text = text.split("```json")[1].split("```")[0].strip()
                            elif "```" in text:   text = text.split("```")[1].split("```")[0].strip()
                            extracted = json.loads(text)
                            if isinstance(extracted, list):
                                names.extend(extracted)
            except Exception as e:
                debug_print(f"NA venue search: {e}", "ERROR")
    if not names:
        names = [{"name": f"craft beer bar {city}"}, {"name": f"gastropub {city}"}]
    return verify_bars_places(names, lat, lng, radius=16093)

@st.cache_data(ttl=3600)
def check_beer_availability_nearby(beer_name, brand, zipcode):
    if not GOOGLE_PLACES_API_KEY:
        return []
    lat, lng = zip_to_coords(zipcode)
    if not lat:
        return []
    city = city_from_zip(zipcode) or zipcode
    radius = 16093

    results = []
    queries = [
        f"{beer_name} {brand} beer store near {city}",
        f"buy {beer_name} beer near {zipcode}",
    ]
    for q in queries:
        try:
            r = requests.post(
                "https://places.googleapis.com/v1/places:searchText",
                json={"textQuery": q,
                      "locationBias": {"circle": {"center": {"latitude": lat, "longitude": lng},
                                                   "radius": radius}},
                      "maxResultCount": 3},
                headers={"Content-Type": "application/json",
                         "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
                         "X-Goog-FieldMask": ("places.displayName,places.formattedAddress,"
                                               "places.rating,places.priceLevel,places.id,places.location")},
                timeout=10)
            if r.status_code == 200:
                for p in r.json().get("places", []):
                    pl = p.get("priceLevel")
                    entry = {
                        "name":        p.get("displayName", {}).get("text", "Unknown"),
                        "address":     p.get("formattedAddress", ""),
                        "rating":      p.get("rating", "N/A"),
                        "price_level": "$" * int(pl) if pl and str(pl).isdigit() else "$$",
                        "place_id":    p.get("id", ""),
                        "lat":         p.get("location", {}).get("latitude"),
                        "lng":         p.get("location", {}).get("longitude"),
                    }
                    if not any(x["name"] == entry["name"] for x in results):
                        results.append(entry)
        except Exception as e:
            debug_print(f"Availability check: {e}", "ERROR")
        if len(results) >= 4:
            break
    return results[:5]

# ── beer image ─────────────────────────────────────────────────────────────────
def attach_image(beer):
    raw_url = beer.get("image")
    if not raw_url:
        raw_url = cse_image_search(f"{beer.get('name','')} {beer.get('brand','')} beer bottle can")
    beer["image_bytes"] = _fetch_img_bytes(raw_url) if raw_url else None
    beer["image"]       = None
    return beer

# ── audio transcription ────────────────────────────────────────────────────────
def transcribe_audio(audio_bytes, mime_type="audio/wav"):
    if not processing_model:
        return None, "AI model not available"
    try:
        parts = [
            {"inline_data": {"mime_type": mime_type,
                             "data": base64.b64encode(audio_bytes).decode()}},
            {"text": ("Transcription assistant for a beer finder app. "
                      "The user spoke a search query. "
                      "Return ONLY the transcribed words, nothing else.")}
        ]
        resp = processing_model.generate_content(parts)
        text = resp.text.strip() if resp and resp.text else None
        if not text:
            return None, "Could not understand audio. Please try again or type your search."
        debug_print(f"Transcribed: '{text}'", "SUCCESS")
        return text, None
    except Exception as e:
        debug_print(f"Transcribe error: {e}", "ERROR")
        return None, "Voice transcription unavailable. Please type your search below."

# ── image-based beer search ────────────────────────────────────────────────────
def identify_beer_from_image(image_bytes):
    if not processing_model:
        return None, "AI model not available"
    try:
        if _PIL_AVAILABLE:
            img = _PILImage.open(io.BytesIO(image_bytes))
            img.thumbnail((800, 800), _PILImage.LANCZOS)
            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            image_bytes = buf.getvalue()
            mime = "image/jpeg"
        else:
            mime = "image/jpeg"

        encoded = base64.b64encode(image_bytes).decode()
        parts = [
            {"inline_data": {"mime_type": mime, "data": encoded}},
            {"text": (
                "You are a beer identification expert. Look at this image carefully.\n"
                "1. If this image clearly shows a beer bottle, can, glass of beer, or beer brand/label, "
                "respond ONLY with the beer name and brand in this exact format: BEER_FOUND: <beer name> <brand>\n"
                "2. If this is not a beer image, or the image is too blurry/unclear to identify a beer, "
                "respond ONLY with: NOT_BEER\n"
                "Do not add any explanation."
            )}
        ]
        resp = processing_model.generate_content(parts)
        if not resp or not resp.text:
            return None, "Could not analyze the image. Please type your search instead."
        result = resp.text.strip()
        debug_print(f"Image ID result: {result}", "INFO")
        if result.startswith("BEER_FOUND:"):
            query = result.replace("BEER_FOUND:", "").strip()
            return query, None
        else:
            return None, None
    except Exception as e:
        debug_print(f"Image identify error: {e}", "ERROR")
        return None, "Image analysis failed. Please type your search instead."

# ── JSON parse ─────────────────────────────────────────────────────────────────
def parse_beer_json(text):
    text = text.strip()
    if "```json" in text: text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:   text = text.split("```")[1].split("```")[0].strip()
    i = text.find("[")
    if i > 0: text = text[i:]
    return json.loads(text)

# ── AI recommendation wrappers ─────────────────────────────────────────────────
_BEER_SCHEMA = ('{"name":"Beer Name","brand":"Brand Name","calories":"150","abv":"5.5%","ibu":"45",'
                '"taste":"Crisp and citrusy","food_pairing":"Grilled chicken, tacos",'
                '"description":"A crisp beer","price_range":"$$","where_to_buy":"Total Wine, BevMo",'
                '"google_rating":"4.3","review_count":"2800"}')

def _call_ai(prompt):
    if not processing_model:
        st.error(f"⚠️ AI model not available: {gemini_error}"); return []
    try:
        resp  = processing_model.generate_content(prompt)
        if not resp or not resp.text: st.error("⚠️ API returned empty response"); return []
        beers = parse_beer_json(resp.text)
        if not isinstance(beers, list) or not beers: st.error("⚠️ Invalid API format"); return []
        for b in beers: attach_image(b)
        return beers
    except json.JSONDecodeError as e:
        st.error(f"⚠️ JSON parse error: {e}"); return []
    except Exception as e:
        st.error(f"⚠️ {e}"); return []

def ai_mood_recs(mood, day, taste):
    return _call_ai(
        f"Act as a beer sommelier. Suggest up to 10 beers ranked by Google review ratings based on:\n"
        f"Mood:{mood[:35]}, Day:{day[:35]}, Taste:{taste[:35]}.\n"
        f"Only include beers you are confident exist and have real Google ratings (4.0+). "
        f"Do NOT fabricate beers. Return only beers you actually know. "
        f"Sort results from highest to lowest rating. Return between 1 and 10 results.\n"
        f"Return ONLY a JSON array: [{_BEER_SCHEMA}]\nNo markdown.")

def ai_brand_recs(query):
    schema = _BEER_SCHEMA.rstrip("}") + ',"available_locally":true}'
    return _call_ai(
        f'Act as a beer sommelier. User wants "{query}".\n'
        f"Return up to 10 options ranked by Google review ratings (highest first). "
        f"Only include beers that actually exist. Do NOT fabricate beers. "
        f"Include google_rating and review_count. Return between 1 and 10 results.\n"
        f"Return ONLY a JSON array: [{schema}]\nNo markdown.")

def ai_na_recs():
    schema = _BEER_SCHEMA.replace('"5.5%"', '"0.0%"').replace('"150"', '"50"')
    return _call_ai(
        f"Act as a beer sommelier. Suggest up to 10 non-alcoholic beers ranked by Google review ratings. "
        f"Only include real non-alcoholic beers you are confident exist with verified ratings (4.0+). "
        f"Do NOT fabricate beers. Sort highest to lowest. Return between 1 and 10 results.\n"
        f"Return ONLY a JSON array: [{schema}]\nNo markdown.")

def ai_image_rec(query):
    schema = _BEER_SCHEMA.rstrip("}") + ',"available_locally":true}'
    return _call_ai(
        f'Act as a beer sommelier. The user uploaded a photo and it was identified as: "{query}".\n'
        f"Return ONLY that single specific beer. Do NOT add similar or alternative beers. "
        f"Return exactly 1 result — the beer that matches the image.\n"
        f"Return ONLY a JSON array with 1 item: [{schema}]\nNo markdown.")

# ── card rendering ─────────────────────────────────────────────────────────────
def beer_card_html(beer):
    name              = beer.get("name", "Unknown")
    brand             = beer.get("brand", "Craft Beer")
    abv               = beer.get("abv", "?")
    calories          = beer.get("calories", "?")
    price_range       = beer.get("price_range", "$")
    description       = beer.get("description", "")
    where_to_buy      = beer.get("where_to_buy", "Check Local Stores")
    ibu               = beer.get("ibu", "")
    taste             = beer.get("taste", "")
    food_pairing      = beer.get("food_pairing", "")
    available_locally = beer.get("available_locally", True)
    google_rating     = beer.get("google_rating", "")
    review_count      = beer.get("review_count", "")

    cls    = "beer-card" + ("" if available_locally else " unavailable")
    badge  = "" if available_locally else '<span class="unavailable-badge">* Not near you</span>'

    rating_html = ""
    if google_rating:
        stars = "★" * round(float(str(google_rating).replace(",", ".")))
        count_str = f" · {review_count} reviews" if review_count else ""
        rating_html = (f'<div style="text-align:center!important;margin-bottom:10px;">'
                       f'<span class="beer-rating-badge">⭐ {google_rating} {stars}{count_str} on Google</span>'
                       f'</div>')

    extras = ""
    if ibu:          extras += f'<div class="beer-detail-row"><div class="beer-detail-label">IBU — Bitterness</div><div class="beer-detail-value">{ibu}</div></div>'
    if taste:        extras += f'<div class="beer-detail-row"><div class="beer-detail-label">Taste Profile</div><div class="beer-detail-value">{taste}</div></div>'
    if food_pairing: extras += f'<div class="beer-detail-row"><div class="beer-detail-label">Food Pairing</div><div class="beer-detail-value">{food_pairing}</div></div>'

    return (
        f'<div class="{cls}">{badge}'
        f'<div class="beer-title">{name}</div><div class="beer-brand">{brand}</div>'
        f'{rating_html}'
        f'<div class="beer-metrics">'
        f'<div class="metric-box"><div class="metric-value">{abv}</div><div class="metric-label">ABV</div></div>'
        f'<div class="metric-box"><div class="metric-value">{calories}</div><div class="metric-label">Cals</div></div>'
        f'<div class="metric-box"><div class="metric-value">{price_range}</div><div class="metric-label">Price</div></div>'
        f'</div>'
        f'<div class="beer-detail-row"><div class="beer-detail-label">About</div><div class="beer-detail-value">{description}</div></div>'
        f'{extras}'
        f'<div class="beer-detail-row"><div class="beer-detail-label">📍 Where to Buy</div><div class="beer-detail-value">{where_to_buy}</div></div>'
        f'</div>'
    )

def render_bar(bar):
    if not bar.get("lat") or not bar.get("lng"):
        return
    maps = (f"https://www.google.com/maps/search/?api=1"
            f"&query={bar['lat']},{bar['lng']}&query_place_id={bar['place_id']}")
    st.markdown(
        f'<div class="bar-card">'
        f'<div class="bar-name">🍻 {bar["name"]}</div>'
        f'<div class="bar-address">📍 {bar["address"]}</div>'
        f'<div class="bar-rating">⭐ {bar["rating"]} · {bar["price_level"]}</div>'
        f'</div>', unsafe_allow_html=True)
    st.markdown(f"[📍 Open in Google Maps]({maps})")

def log_beer_selection(username, beer_name, brand, search_type, mood=None):
    pass  # HuggingFace logging removed — PostgreSQL handles persistence

def render_beer_with_zip_search(beer, beer_idx, search_type):
    ukey = f"beer_{beer_idx}_{beer.get('name','?').replace(' ','_')}"

    if beer.get("image_bytes"):
        st.image(beer["image_bytes"], use_container_width=True)
    st.markdown(beer_card_html(beer), unsafe_allow_html=True)

    # ── Save button ────────────────────────────────────────────────────────────
    saved = any(b["name"] == beer["name"] for b in st.session_state.saved_beers)
    if not saved:
        if st.button("SAVE", key=f"save_{ukey}", use_container_width=True):
            st.session_state.saved_beers.append(beer)
            log_beer_selection(
                st.session_state.user_data.get("name", "User"),
                beer.get("name","?"), beer.get("brand","?"),
                st.session_state.user_data.get("search_type","unknown"),
                st.session_state.user_data.get("mood"))
            st.rerun()
    else:
        st.button("SAVED ✓", disabled=True, key=f"saved_{ukey}", use_container_width=True)

    # ── Zip search panel ───────────────────────────────────────────────────────
    st.markdown('<div class="zip-search-panel">', unsafe_allow_html=True)
    st.markdown(f'<div class="zip-search-title">📍 Check availability near you</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    zip_key    = f"zip_input_{ukey}"
    search_key = f"zip_search_btn_{ukey}"

    col_z, col_b = st.columns([3, 1])
    with col_z:
        entered_zip = st.text_input(
            "Enter zipcode",
            placeholder="e.g. 90210",
            max_chars=5,
            key=zip_key,
            label_visibility="collapsed")
    with col_b:
        do_search = st.button("GO", key=search_key, use_container_width=True)

    result_key = f"zip_result_{ukey}"
    if do_search and entered_zip:
        ok, clean_zip = validate_zipcode(entered_zip)
        if not ok:
            st.error(f"❌ {clean_zip}")
        else:
            city_n, state_n = city_state_from_zip(clean_zip)
            loc_label = f"{city_n}, {state_n}" if city_n else clean_zip
            st.session_state[result_key] = {"zip": clean_zip, "label": loc_label, "loaded": False}

    if result_key in st.session_state:
        rdata = st.session_state[result_key]
        z     = rdata["zip"]
        label = rdata["label"]

        st.markdown(
            f'<p style="color:#ffd165;font-size:0.78rem;text-align:center!important;'
            f'font-family:Space Grotesk,sans-serif;margin:6px 0 10px;">📍 Results near {label}</p>',
            unsafe_allow_html=True)

        lat, lng = zip_to_coords(z)
        if not lat:
            st.warning("⚠️ Could not geocode that zipcode.")
        else:
            with st.spinner("🔍 Checking availability…"):
                avail = check_beer_availability_nearby(beer.get("name",""), beer.get("brand",""), z)

            if avail:
                st.markdown('<p style="color:#4ae176;font-size:0.82rem;text-align:center!important;'
                            'margin-bottom:6px;">✅ Found nearby stores/venues:</p>', unsafe_allow_html=True)
                for place in avail:
                    render_bar(place)
            else:
                st.info("🔍 No specific availability found. Try a local Total Wine, BevMo, or craft beer shop.")

            with st.expander(f"🍻 Bars within 10 miles serving {beer.get('name', 'this beer')}"):
                with st.spinner("🤖 AI agents finding bars…"):
                    if search_type == "non_alcoholic":
                        bars = find_na_venues_nearby(lat, lng, z)
                    else:
                        bars = find_bars_nearby(lat, lng, beer.get("name",""), beer.get("brand",""), z)
                if bars:
                    for bar in bars:
                        render_bar(bar)
                else:
                    st.info("🤖 No bars found for this beer in the area. Check local craft beer pubs!")

# ── Shareable list page ────────────────────────────────────────────────────────
def render_shared_list_page(token):
    """
    Renders a full-page view of a shared beer list accessible via ?list=TOKEN.
    This page is publicly viewable — no login required.
    """
    inject_mobile_css()
    render_app_bar()

    result = get_beer_list(token)
    if not result:
        st.markdown(
            '<div style="background:#121c2a;padding:40px;border-radius:16px;margin:60px 0;text-align:center;">'
            '<p style="color:#ffb4ab;font-size:1.1rem;">🍺 List not found or has expired.</p>'
            '<p style="color:#9b8f79;font-size:0.85rem;margin-top:8px;">The share link may be invalid.</p>'
            '</div>', unsafe_allow_html=True)
        if st.button("GO TO GOLDEN DRAUGHT", use_container_width=True):
            st.query_params.clear()
            st.rerun()
        return

    title, beers, username, created_at = result
    share_url = f"https://beer.dimensionunlimited.com/?list={token}"
    plain_text = format_list_as_text(beers, title, share_url)

    # Header
    st.markdown(f'<div class="big-greeting">🍺 Beer List</div>', unsafe_allow_html=True)
    st.markdown(
        f'<p style="color:#9b8f79;font-size:0.78rem;text-align:center!important;'
        f'font-family:Space Grotesk,sans-serif;margin-bottom:4px;">'
        f'Curated by {username} · {created_at.strftime("%b %d, %Y") if hasattr(created_at, "strftime") else created_at}'
        f'</p>', unsafe_allow_html=True)
    st.markdown(f'<p class="gold-text" style="font-size:0.9rem;">{title}</p>', unsafe_allow_html=True)

    st.markdown('<div style="height:16px;"></div>', unsafe_allow_html=True)

    # Beer cards (display-only, no zip search on shared view)
    for beer in beers:
        st.markdown(beer_card_html(beer), unsafe_allow_html=True)
        st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)

    # Share section
    st.markdown('<div style="height:20px;"></div>', unsafe_allow_html=True)
    st.markdown(
        '<p style="color:#ffd165;font-size:0.8rem;font-family:Space Grotesk,sans-serif;'
        'text-transform:uppercase;letter-spacing:0.1em;text-align:center!important;margin-bottom:8px;">'
        '📤 Share this list</p>', unsafe_allow_html=True)

    st.markdown(
        f'<div class="share-card">'
        f'<p style="color:#9b8f79;font-size:0.72rem;font-family:Space Grotesk,sans-serif;'
        f'text-transform:uppercase;letter-spacing:0.1em;margin-bottom:6px;">🔗 Shareable URL</p>'
        f'<div class="share-url-box">{share_url}</div>'
        f'</div>', unsafe_allow_html=True)

    st.markdown(
        '<p style="color:#9b8f79;font-size:0.72rem;font-family:Space Grotesk,sans-serif;'
        'text-transform:uppercase;letter-spacing:0.1em;text-align:center!important;margin:12px 0 6px;">'
        '📋 Copy text for SMS or Email</p>', unsafe_allow_html=True)

    st.code(plain_text, language=None)

    st.markdown(
        '<div style="height:20px;"></div>'
        '<p style="color:#9b8f79;font-size:0.72rem;text-align:center!important;">'
        'Tap & hold the text above to select all → Copy → Paste into any message or email.</p>',
        unsafe_allow_html=True)

    if st.button("🍺 DISCOVER MORE BEERS", use_container_width=True):
        st.query_params.clear()
        st.rerun()

    st.markdown('<div class="footer">© 2026 Dimension Unlimited. Drink responsibly.</div>',
                unsafe_allow_html=True)


# ── Render saved list share panel (Step 4) ─────────────────────────────────────
def render_share_panel(beers, username):
    """
    Shown inside Step 4 (My Saved Brews) after the beer list.
    Lets the user save the list to DB and get a shareable URL.
    """
    st.markdown('<div style="height:12px;"></div>', unsafe_allow_html=True)
    st.markdown(
        '<p style="color:#ffd165;font-size:0.8rem;font-family:Space Grotesk,sans-serif;'
        'text-transform:uppercase;letter-spacing:0.1em;text-align:center!important;margin-bottom:8px;">'
        '📤 Share Your Beer List</p>', unsafe_allow_html=True)

    # If already saved this session, show the existing token
    existing_token = st.session_state.get("shared_list_token")

    if existing_token:
        share_url  = f"https://beer.dimensionunlimited.com/?list={existing_token}"
        plain_text = format_list_as_text(
            beers,
            st.session_state.get("shared_list_title", f"{username}'s Beer List"),
            share_url
        )
        st.markdown(
            f'<div class="share-card">'
            f'<p style="color:#4ae176;font-size:0.85rem;font-weight:700;margin-bottom:10px;">'
            f'✅ Your list is live!</p>'
            f'<p style="color:#9b8f79;font-size:0.72rem;font-family:Space Grotesk,sans-serif;'
            f'text-transform:uppercase;letter-spacing:0.1em;margin-bottom:6px;">🔗 Shareable URL</p>'
            f'<div class="share-url-box">{share_url}</div>'
            f'<p style="color:#9b8f79;font-size:0.72rem;margin-top:8px;">'
            f'Copy the URL above and paste it into any text message or email.</p>'
            f'</div>', unsafe_allow_html=True)

        st.markdown(
            '<p style="color:#9b8f79;font-size:0.72rem;font-family:Space Grotesk,sans-serif;'
            'text-transform:uppercase;letter-spacing:0.1em;text-align:center!important;margin:12px 0 6px;">'
            '📋 Ready-to-paste text</p>', unsafe_allow_html=True)

        st.code(plain_text, language=None)

        st.markdown(
            '<p style="color:#9b8f79;font-size:0.7rem;text-align:center!important;margin-top:6px;">'
            'Tap & hold to select → Copy → Paste into Messages or Email.</p>',
            unsafe_allow_html=True)

        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔄 GENERATE NEW LINK", key="regen_share_btn", use_container_width=True):
                st.session_state.shared_list_token = None
                st.session_state.shared_list_title = None
                st.rerun()
        with col2:
            if st.button("👁 VIEW SHARE PAGE", key="view_share_btn", use_container_width=True):
                st.markdown(f'<meta http-equiv="refresh" content="0; url={share_url}">',
                            unsafe_allow_html=True)

    else:
        # Show generate button
        list_title = st.text_input(
            "List title (optional)",
            placeholder=f"{username}'s Golden Draught Picks",
            key="share_list_title_input",
            max_chars=80)

        if st.button("💾 SAVE & GET SHAREABLE LINK", key="gen_share_btn", use_container_width=True):
            if not beers:
                st.error("Add some beers to your list first!")
            else:
                title = list_title.strip() or f"{username}'s Beer List — {datetime.datetime.now().strftime('%b %d %Y')}"
                with st.spinner("Saving your list…"):
                    token, err = save_beer_list(beers, username, title)
                if err:
                    st.error(f"❌ Could not save list: {err}")
                    st.info("Make sure DATABASE_URL is set in your Railway variables.")
                else:
                    st.session_state.shared_list_token = token
                    st.session_state.shared_list_title = title
                    st.rerun()


# ── voice input widget ─────────────────────────────────────────────────────────
def render_voice_widget():
    audio_bytes = None
    mime_type   = "audio/wav"

    if MIC_RECORDER_AVAILABLE:
        st.markdown('<p class="gold-text" style="font-size:0.78rem;margin-bottom:4px;">🎤 Record your search</p>',
                    unsafe_allow_html=True)
        audio = mic_recorder(start_prompt="⏺ Record", stop_prompt="⏹ Stop", key="mic_rec")
        if audio and audio.get("bytes"):
            audio_bytes = audio["bytes"]
            mime_type   = "audio/wav"

    elif hasattr(st, "audio_input"):
        try:
            val = st.audio_input("🎤 Tap to record", key="voice_recorder")
            if val is not None:
                audio_bytes = val.read()
                mime_type   = "audio/wav"
        except Exception as e:
            debug_print(f"audio_input error: {e}", "WARNING")

    return audio_bytes, mime_type

# ── Refine search bar ──────────────────────────────────────────────────────────
def render_refine_search(search_type, label="🔄 Search for a different beer"):
    st.markdown(f'<div class="refine-bar"><div class="refine-bar-label">{label}</div></div>',
                unsafe_allow_html=True)

    ud = st.session_state.user_data

    if search_type == "non_alcoholic":
        if st.button("🔄 REFRESH NON-ALCOHOLIC PICKS", key="refine_na_btn", use_container_width=True):
            with st.spinner("Refreshing non-alcoholic recommendations…"):
                beers = ai_na_recs()
            st.session_state.rec_beers = beers
            st.rerun()

    elif search_type == "mood":
        with st.form("refine_mood_form"):
            new_mood  = st.text_input("Change vibe", value=ud.get("mood",""), placeholder="Relaxed, Hyped, Tired…", max_chars=35)
            new_day   = st.text_input("Day?", value=ud.get("day",""), placeholder="Easy day, celebratory…", max_chars=35)
            new_taste = st.text_input("Taste?", value=ud.get("taste",""), placeholder="Hoppy, Sweet, Dark…", max_chars=35)
            if st.form_submit_button("🔄 REFRESH"):
                if new_mood:
                    ud["mood"]  = new_mood
                    ud["day"]   = new_day or ud.get("day", "")
                    ud["taste"] = new_taste or ud.get("taste", "")
                    with st.spinner("Finding new recommendations…"):
                        beers = ai_mood_recs(ud["mood"], ud["day"], ud["taste"])
                    st.session_state.rec_beers = beers
                    st.rerun()

    else:
        with st.form("refine_brand_form"):
            new_query = st.text_input(
                "Search a different beer",
                value=ud.get("brand_query", "") or "",
                placeholder="Guinness, West Coast IPA…",
                max_chars=35)
            if st.form_submit_button("🔄 FIND IT"):
                if new_query.strip():
                    ud["brand_query"] = new_query.strip()
                    with st.spinner(f"Searching for {new_query}…"):
                        beers = ai_brand_recs(new_query.strip())
                    st.session_state.rec_beers = beers
                    st.rerun()

# ── Beer Games ─────────────────────────────────────────────────────────────────
def render_beer_games():
    ud   = st.session_state.user_data
    name = ud.get("name", "Player")

    gstate = st.session_state.get("game_state", {})
    active = gstate.get("active_game")

    col_back, _ = st.columns([1, 3])
    with col_back:
        if st.button("← Back", key="games_back_btn"):
            st.session_state.game_state = {}
            st.session_state.step = 1
            st.rerun()

    if active == "trivia":
        render_trivia_game(name)
    elif active == "pour_guess":
        render_pour_guess_game(name)
    elif active == "hop_hop":
        render_hop_hop_game(name)
    else:
        st.markdown('<div class="big-greeting">🎮 Beer Games</div>', unsafe_allow_html=True)
        st.markdown('<p class="gold-text" style="margin-bottom:20px;">Pick a game, earn bragging rights!</p>',
                    unsafe_allow_html=True)

        st.markdown("""
        <div class="game-card">
            <div class="game-title">🧠 Beer Trivia</div>
            <div class="game-desc">10 questions about beer history, styles & culture. Score points for each right answer!</div>
        </div>""", unsafe_allow_html=True)
        if st.button("PLAY BEER TRIVIA", key="start_trivia", use_container_width=True):
            st.session_state.game_state = {
                "active_game": "trivia", "q_idx": 0, "score": 0, "answered": False, "done": False
            }
            st.rerun()

        st.markdown("""
        <div class="game-card">
            <div class="game-title">🍺 Pour Perfect</div>
            <div class="game-desc">Guess the mystery beer ABV! Tap closer to the real number to score higher.</div>
        </div>""", unsafe_allow_html=True)
        if st.button("PLAY POUR PERFECT", key="start_pour", use_container_width=True):
            import random
            beers = [
                ("Bud Light", 4.2), ("Guinness Draught", 4.2), ("Sierra Nevada Pale Ale", 5.6),
                ("Dogfish Head 60 Min IPA", 6.0), ("Samuel Adams Boston Lager", 4.9),
                ("Blue Moon Belgian White", 5.4), ("Heineken", 5.0), ("Corona Extra", 4.6),
                ("Stone IPA", 6.9), ("Founders All Day IPA", 4.7),
            ]
            random.shuffle(beers)
            st.session_state.game_state = {
                "active_game": "pour_guess", "beers": beers, "idx": 0, "score": 0, "done": False,
                "guessed": False, "guess_val": 5.0,
            }
            st.rerun()

        st.markdown("""
        <div class="game-card">
            <div class="game-title">🌾 Hop or Not</div>
            <div class="game-desc">Swipe LEFT or RIGHT — Is it a real beer or made up? Beat 10 rounds!</div>
        </div>""", unsafe_allow_html=True)
        if st.button("PLAY HOP OR NOT", key="start_hop", use_container_width=True):
            import random
            pairs = [
                ("Pliny the Elder", True), ("Zombie Dust", True), ("King Cobra", True),
                ("Hammerhead Red", True), ("Hopzilla IPA", True), ("Tangerine Moon", False),
                ("Foggy Barrel Wheat", False), ("Purple Haze Stout", False),
                ("Electric Eel Pale Ale", False), ("Double Dragon Dark", False),
                ("Arrogant Bastard Ale", True), ("Sculpin IPA", True),
                ("Raspberry Unicorn Sour", False), ("Velvet Thunder Porter", False),
                ("Alaskan Amber", True), ("Cosmic Pilgrim Lager", False),
                ("Loose Cannon IPA", True), ("Quantum Foam Saison", False),
                ("Two Hearted Ale", True), ("Midnight Mustache Stout", False),
            ]
            random.shuffle(pairs)
            used = pairs[:10]
            st.session_state.game_state = {
                "active_game": "hop_hop", "rounds": used, "idx": 0, "score": 0, "done": False, "answered": False,
            }
            st.rerun()

# ── trivia questions ───────────────────────────────────────────────────────────
TRIVIA_QS = [
    {"q": "What gives IPA beers their bitter flavor?",
     "opts": ["Hops", "Barley", "Yeast", "Water"], "ans": 0},
    {"q": "Which country invented lager beer?",
     "opts": ["Germany", "Ireland", "Belgium", "USA"], "ans": 0},
    {"q": "What does ABV stand for?",
     "opts": ["Alcohol By Volume", "Amber Brew Variant", "Aged Barrel Value", "Ale Batch Verified"], "ans": 0},
    {"q": "Guinness is originally from which city?",
     "opts": ["Dublin", "London", "Edinburgh", "Cork"], "ans": 0},
    {"q": "Which beer style is known for its dark color and roasted malt flavors?",
     "opts": ["Stout", "Pilsner", "Hefeweizen", "Gose"], "ans": 0},
    {"q": "What is the main fermentable ingredient in beer?",
     "opts": ["Malted barley", "Corn", "Rice", "Wheat"], "ans": 0},
    {"q": "What does IBU measure?",
     "opts": ["Bitterness", "Alcohol", "Color", "Sweetness"], "ans": 0},
    {"q": "A 'growler' in beer culture refers to what?",
     "opts": ["A take-home jug of draft beer", "A grumpy bartender", "A style of glass", "A beer warmer"], "ans": 0},
    {"q": "Which US state is known as the craft beer capital?",
     "opts": ["Oregon", "Texas", "Florida", "New York"], "ans": 0},
    {"q": "Sour beers get their tartness primarily from?",
     "opts": ["Wild yeast & bacteria", "Lemon juice", "Vinegar", "Citrus hops"], "ans": 0},
]

def render_trivia_game(name):
    gs = st.session_state.game_state
    st.markdown('<div class="big-greeting">🧠 Beer Trivia</div>', unsafe_allow_html=True)

    if gs.get("done"):
        score = gs["score"]
        total = len(TRIVIA_QS)
        pct   = int(score / total * 100)
        emoji = "🏆" if pct >= 80 else "🍺" if pct >= 50 else "😅"
        st.markdown(f"""
        <div class="celebrate-box">
            <div style="font-size:3rem;">{emoji}</div>
            <div class="celebrate-name">{name}</div>
            <div style="color:#d9e3f6;font-size:1rem;margin:8px 0;">scored {score}/{total} ({pct}%)</div>
            <div class="score-badge">{'Beer Master! 🏆' if pct==100 else 'Well Played! 🍺' if pct>=70 else 'Keep Practicing! 😄'}</div>
        </div>""", unsafe_allow_html=True)
        st.markdown(_celebrate_sound(pct), unsafe_allow_html=True)
        if st.button("🔄 PLAY AGAIN", key="trivia_again", use_container_width=True):
            st.session_state.game_state = {"active_game": "trivia", "q_idx": 0, "score": 0,
                                            "answered": False, "done": False}
            st.rerun()
        if st.button("🎮 OTHER GAMES", key="trivia_hub", use_container_width=True):
            st.session_state.game_state = {}
            st.rerun()
        return

    qi = gs["q_idx"]
    q  = TRIVIA_QS[qi]
    st.markdown(
        f'<div style="background:#121c2a;border-radius:14px;padding:16px;margin:10px 0;'
        f'border:1px solid rgba(255,209,101,0.15);">'
        f'<p style="color:#9b8f79;font-size:0.7rem;font-family:Space Grotesk,sans-serif;'
        f'text-transform:uppercase;letter-spacing:0.1em;">Question {qi+1} of {len(TRIVIA_QS)}</p>'
        f'<p style="color:#d9e3f6;font-size:1rem;font-weight:600;margin-top:8px;">{q["q"]}</p>'
        f'</div>', unsafe_allow_html=True)

    st.markdown(f'<div class="score-badge">Score: {gs["score"]}</div>', unsafe_allow_html=True)

    if gs.get("answered"):
        chosen  = gs.get("chosen_idx", -1)
        correct = q["ans"]
        for i, opt in enumerate(q["opts"]):
            if i == correct:
                st.markdown(f'<div style="background:rgba(74,225,118,0.15);border:1px solid #4ae176;'
                            f'border-radius:10px;padding:12px;margin:6px 0;color:#4ae176;font-weight:600;">'
                            f'✅ {opt}</div>', unsafe_allow_html=True)
            elif i == chosen and chosen != correct:
                st.markdown(f'<div style="background:rgba(255,180,171,0.15);border:1px solid #ffb4ab;'
                            f'border-radius:10px;padding:12px;margin:6px 0;color:#ffb4ab;">'
                            f'❌ {opt}</div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div style="background:#16202e;border:1px solid rgba(255,255,255,0.06);'
                            f'border-radius:10px;padding:12px;margin:6px 0;color:#9b8f79;">'
                            f'{opt}</div>', unsafe_allow_html=True)

        if chosen == correct:
            st.markdown(_ding_sound(), unsafe_allow_html=True)
        else:
            st.markdown(_buzz_sound(), unsafe_allow_html=True)

        next_label = "FINISH" if qi + 1 >= len(TRIVIA_QS) else "NEXT QUESTION →"
        if st.button(next_label, key=f"trivia_next_{qi}", use_container_width=True):
            if qi + 1 >= len(TRIVIA_QS):
                gs["done"] = True
            else:
                gs["q_idx"]    = qi + 1
                gs["answered"] = False
            st.rerun()
    else:
        for i, opt in enumerate(q["opts"]):
            if st.button(opt, key=f"trivia_opt_{qi}_{i}", use_container_width=True):
                gs["answered"]   = True
                gs["chosen_idx"] = i
                if i == q["ans"]:
                    gs["score"] += 1
                st.rerun()


def render_pour_guess_game(name):
    gs    = st.session_state.game_state
    beers = gs["beers"]
    idx   = gs["idx"]
    st.markdown('<div class="big-greeting">🍺 Pour Perfect</div>', unsafe_allow_html=True)

    if gs.get("done"):
        score = gs["score"]
        total = len(beers)
        pct   = int(score / (total * 10) * 100)
        emoji = "🎯" if pct >= 80 else "🍺"
        st.markdown(f"""
        <div class="celebrate-box">
            <div style="font-size:3rem;">{emoji}</div>
            <div class="celebrate-name">{name}</div>
            <div style="color:#d9e3f6;font-size:1rem;margin:8px 0;">scored {score}/{total*10} pts</div>
            <div class="score-badge">{'Sharp Palate! 🎯' if pct>=70 else 'Keep Pouring! 🍺'}</div>
        </div>""", unsafe_allow_html=True)
        st.markdown(_celebrate_sound(pct), unsafe_allow_html=True)
        if st.button("🔄 PLAY AGAIN", key="pour_again", use_container_width=True):
            import random
            beers_reset = list(beers)
            random.shuffle(beers_reset)
            st.session_state.game_state = {"active_game": "pour_guess", "beers": beers_reset,
                                            "idx": 0, "score": 0, "done": False,
                                            "guessed": False, "guess_val": 5.0}
            st.rerun()
        if st.button("🎮 OTHER GAMES", key="pour_hub", use_container_width=True):
            st.session_state.game_state = {}
            st.rerun()
        return

    beer_name, real_abv = beers[idx]
    st.markdown(
        f'<div style="background:#121c2a;border-radius:14px;padding:16px;margin:10px 0;'
        f'border:1px solid rgba(255,209,101,0.15);">'
        f'<p style="color:#9b8f79;font-size:0.7rem;font-family:Space Grotesk,sans-serif;'
        f'text-transform:uppercase;letter-spacing:0.1em;">Beer {idx+1} of {len(beers)}</p>'
        f'<p style="color:#ffd165;font-size:1.2rem;font-weight:800;margin-top:6px;">{beer_name}</p>'
        f'<p style="color:#d9e3f6;font-size:0.85rem;margin-top:4px;">What\'s the ABV?</p>'
        f'</div>', unsafe_allow_html=True)

    st.markdown(f'<div class="score-badge">Score: {gs["score"]}</div>', unsafe_allow_html=True)

    if gs.get("guessed"):
        guess = gs["guess_val"]
        diff  = abs(guess - real_abv)
        pts   = max(0, 10 - int(diff * 4))
        color = "#4ae176" if diff <= 0.5 else "#ffd165" if diff <= 1.5 else "#ffb4ab"
        st.markdown(
            f'<div style="background:#16202e;border-radius:12px;padding:16px;margin:10px 0;text-align:center;">'
            f'<p style="color:{color};font-size:1rem;font-weight:700;">Your guess: {guess:.1f}% | Real: {real_abv}%</p>'
            f'<p style="color:#ffd165;font-size:0.9rem;">+{pts} points!</p>'
            f'</div>', unsafe_allow_html=True)
        if pts >= 8:
            st.markdown(_ding_sound(), unsafe_allow_html=True)
        elif pts >= 4:
            st.markdown(_tick_sound(), unsafe_allow_html=True)
        else:
            st.markdown(_buzz_sound(), unsafe_allow_html=True)

        next_label = "FINISH" if idx + 1 >= len(beers) else "NEXT BEER →"
        if st.button(next_label, key=f"pour_next_{idx}", use_container_width=True):
            if idx + 1 >= len(beers):
                gs["done"] = True
            else:
                gs["idx"]       = idx + 1
                gs["guessed"]   = False
                gs["guess_val"] = 5.0
            st.rerun()
    else:
        guess = st.slider("Your ABV guess (%)", min_value=0.0, max_value=15.0,
                          value=gs.get("guess_val", 5.0), step=0.1,
                          key=f"pour_slider_{idx}")
        gs["guess_val"] = guess
        if st.button(f"LOCK IN {guess:.1f}%", key=f"pour_lock_{idx}", use_container_width=True):
            diff = abs(guess - real_abv)
            pts  = max(0, 10 - int(diff * 4))
            gs["score"]  += pts
            gs["guessed"] = True
            st.rerun()


def render_hop_hop_game(name):
    gs     = st.session_state.game_state
    rounds = gs["rounds"]
    idx    = gs["idx"]
    st.markdown('<div class="big-greeting">🌾 Hop or Not</div>', unsafe_allow_html=True)

    if gs.get("done"):
        score = gs["score"]
        total = len(rounds)
        pct   = int(score / total * 100)
        emoji = "🌾" if pct >= 80 else "🍺"
        st.markdown(f"""
        <div class="celebrate-box">
            <div style="font-size:3rem;">{emoji}</div>
            <div class="celebrate-name">{name}</div>
            <div style="color:#d9e3f6;font-size:1rem;margin:8px 0;">{score}/{total} correct!</div>
            <div class="score-badge">{'Beer Genius! 🌾' if pct==100 else 'Hoppy Results! 🍺' if pct>=60 else 'Keep Hopping! 😄'}</div>
        </div>""", unsafe_allow_html=True)
        st.markdown(_celebrate_sound(pct), unsafe_allow_html=True)
        if st.button("🔄 PLAY AGAIN", key="hop_again", use_container_width=True):
            import random
            r2 = list(rounds)
            random.shuffle(r2)
            st.session_state.game_state = {"active_game": "hop_hop", "rounds": r2,
                                            "idx": 0, "score": 0, "done": False, "answered": False}
            st.rerun()
        if st.button("🎮 OTHER GAMES", key="hop_hub", use_container_width=True):
            st.session_state.game_state = {}
            st.rerun()
        return

    beer_name, is_real = rounds[idx]
    st.markdown(
        f'<div style="background:#121c2a;border-radius:14px;padding:20px;margin:10px 0;'
        f'border:1px solid rgba(255,209,101,0.15);text-align:center;">'
        f'<p style="color:#9b8f79;font-size:0.7rem;font-family:Space Grotesk,sans-serif;'
        f'text-transform:uppercase;letter-spacing:0.1em;">Round {idx+1} of {len(rounds)}</p>'
        f'<p style="color:#ffd165;font-size:1.4rem;font-weight:900;margin:12px 0;">{beer_name}</p>'
        f'<p style="color:#9b8f79;font-size:0.85rem;">Is this a REAL beer or MADE UP?</p>'
        f'</div>', unsafe_allow_html=True)

    st.markdown(f'<div class="score-badge">Score: {gs["score"]}</div>', unsafe_allow_html=True)

    if gs.get("answered"):
        chosen  = gs.get("chosen_real")
        correct = is_real
        result_color = "#4ae176" if chosen == correct else "#ffb4ab"
        result_text  = "✅ Correct!" if chosen == correct else "❌ Wrong!"
        fact = "This IS a real beer! 🍺" if is_real else "Totally made up! 😄"
        st.markdown(
            f'<div style="background:#16202e;border-radius:12px;padding:16px;margin:10px 0;text-align:center;">'
            f'<p style="color:{result_color};font-size:1.1rem;font-weight:700;">{result_text}</p>'
            f'<p style="color:#d9e3f6;font-size:0.85rem;margin-top:6px;">{fact}</p>'
            f'</div>', unsafe_allow_html=True)
        if chosen == correct:
            st.markdown(_ding_sound(), unsafe_allow_html=True)
        else:
            st.markdown(_buzz_sound(), unsafe_allow_html=True)

        next_label = "FINISH" if idx + 1 >= len(rounds) else "NEXT →"
        if st.button(next_label, key=f"hop_next_{idx}", use_container_width=True):
            if idx + 1 >= len(rounds):
                gs["done"] = True
            else:
                gs["idx"]      = idx + 1
                gs["answered"] = False
            st.rerun()
    else:
        c1, c2 = st.columns(2)
        with c1:
            if st.button("✅ REAL BEER", key=f"hop_real_{idx}", use_container_width=True):
                gs["answered"]    = True
                gs["chosen_real"] = True
                if is_real: gs["score"] += 1
                st.rerun()
        with c2:
            if st.button("❌ MADE UP", key=f"hop_fake_{idx}", use_container_width=True):
                gs["answered"]    = True
                gs["chosen_real"] = False
                if not is_real: gs["score"] += 1
                st.rerun()


# ── sound helpers ──────────────────────────────────────────────────────────────
def _ding_sound():
    return """
    <script>
    (function(){
        var ctx = new (window.AudioContext || window.webkitAudioContext)();
        var o = ctx.createOscillator();
        var g = ctx.createGain();
        o.connect(g); g.connect(ctx.destination);
        o.frequency.setValueAtTime(880, ctx.currentTime);
        o.frequency.exponentialRampToValueAtTime(1320, ctx.currentTime + 0.15);
        g.gain.setValueAtTime(0.3, ctx.currentTime);
        g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.5);
        o.start(ctx.currentTime); o.stop(ctx.currentTime + 0.5);
    })();
    </script>"""

def _buzz_sound():
    return """
    <script>
    (function(){
        var ctx = new (window.AudioContext || window.webkitAudioContext)();
        var o = ctx.createOscillator();
        var g = ctx.createGain();
        o.type = 'sawtooth';
        o.connect(g); g.connect(ctx.destination);
        o.frequency.setValueAtTime(150, ctx.currentTime);
        g.gain.setValueAtTime(0.3, ctx.currentTime);
        g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.4);
        o.start(ctx.currentTime); o.stop(ctx.currentTime + 0.4);
    })();
    </script>"""

def _tick_sound():
    return """
    <script>
    (function(){
        var ctx = new (window.AudioContext || window.webkitAudioContext)();
        var o = ctx.createOscillator();
        var g = ctx.createGain();
        o.frequency.setValueAtTime(660, ctx.currentTime);
        g.gain.setValueAtTime(0.2, ctx.currentTime);
        g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.2);
        o.start(ctx.currentTime); o.stop(ctx.currentTime + 0.2);
    })();
    </script>"""

def _celebrate_sound(pct):
    if pct >= 70:
        return """
        <script>
        (function(){
            var ctx = new (window.AudioContext || window.webkitAudioContext)();
            var notes = [523, 659, 784, 1047];
            notes.forEach(function(freq, i){
                var o = ctx.createOscillator();
                var g = ctx.createGain();
                o.connect(g); g.connect(ctx.destination);
                o.frequency.value = freq;
                g.gain.setValueAtTime(0.25, ctx.currentTime + i*0.18);
                g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + i*0.18 + 0.35);
                o.start(ctx.currentTime + i*0.18);
                o.stop(ctx.currentTime + i*0.18 + 0.35);
            });
        })();
        </script>"""
    else:
        return _tick_sound()

# ── session state ──────────────────────────────────────────────────────────────
def init_state():
    defaults = {
        "step": 0,
        "user_data": {"name":"","mood":"","brand_query":None,
                      "day":"","taste":"","search_type":None},
        "rec_beers":           [],
        "saved_beers":         [],
        "show_debug":          False,
        "feedback_submitted":  False,
        "game_state":          {},
        "shared_list_token":   None,
        "shared_list_title":   None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()

# ── MAIN ───────────────────────────────────────────────────────────────────────
def main():
    inject_mobile_css()
    render_app_bar()

    # ── Check for shared list URL param (?list=TOKEN) ─────────────────────────
    params = st.query_params
    if "list" in params:
        render_shared_list_page(params["list"])
        return

    if st.sidebar.button("Toggle Debug"):
        st.session_state.show_debug = not st.session_state.show_debug
        st.rerun()
    render_debug_panel()

    step = st.session_state.step
    ud   = st.session_state.user_data

    # ── nav row ────────────────────────────────────────────────────────────────
    if step > 0 and step not in (5, 6):
        if step == 3:
            cb, cl = st.columns([1, 1])
            with cb:
                if st.button("←", key="back_btn"):
                    st.session_state.step = 1
                    st.session_state.rec_beers = []
                    ud.update({"brand_query":None,"mood":"","search_type":None})
                    st.rerun()
            with cl:
                if st.session_state.saved_beers:
                    if st.button("My List", key="star_btn"):
                        st.session_state.step = 4; st.rerun()
        elif step != 6:
            c1, c2, c3 = st.columns([1, 2, 1])
            with c1:
                if st.button("←", key="back_btn"):
                    if step == 4:
                        st.session_state.step = 1; st.rerun()
                    elif step == 2 and ud.get("search_type") in ["brand","non_alcoholic"]:
                        st.session_state.step = 1
                        ud.update({"brand_query":None,"search_type":None}); st.rerun()
                    elif step == 1.5:
                        st.session_state.step = 1
                        ud.update({"brand_query":None,"search_type":None}); st.rerun()
                    else:
                        st.session_state.step = max(0, step - 1); st.rerun()
            with c3:
                if st.session_state.saved_beers and step != 4:
                    if st.button("My List", key="star_btn"):
                        st.session_state.step = 4; st.rerun()

    # =========================================================================
    # STEP 0 — Login
    # =========================================================================
    if st.session_state.step == 0:
        st.markdown('<div style="height:40px;"></div>', unsafe_allow_html=True)
        render_logo()
        st.markdown('<h1 class="big-greeting">Beer Finder</h1>', unsafe_allow_html=True)
        st.markdown('<p class="gold-text">Your pocket sommelier.</p>', unsafe_allow_html=True)
        if gemini_error:
            st.warning(f"⚠️ {gemini_error}")
        st.markdown('<div style="height:24px;"></div>', unsafe_allow_html=True)

        with st.form("login_form"):
            name_val = st.text_input("Your name? *", placeholder="Enter your name", max_chars=35)
            if st.form_submit_button("ENTER"):
                if not name_val.strip():
                    st.error("❌ Name is required")
                else:
                    ud["name"] = name_val.strip()[:35]
                    st.session_state.step = 1
                    st.rerun()

        render_bottom_nav("home")
        render_footer()

    # =========================================================================
    # STEP 1 — Search type
    # =========================================================================
    elif st.session_state.step == 1:
        greet, time_str = get_greeting()
        name = ud.get("name", "Friend")

        gif_path = os.path.join(os.path.dirname(__file__), "static", "images", "beer.gif.gif")
        enc = load_image_as_base64(gif_path)
        if enc:
            st.markdown(
                f'<div style="display:flex;justify-content:center;margin-bottom:20px;">'
                f'<img src="data:image/gif;base64,{enc}" style="width:100%;max-height:220px;'
                f'object-fit:cover;border-radius:16px;opacity:0.85;"></div>',
                unsafe_allow_html=True)
        else:
            st.markdown('<div style="text-align:center;font-size:5rem;">🍺</div>', unsafe_allow_html=True)

        st.markdown(f'<div class="big-greeting">{greet}, {name}.</div>', unsafe_allow_html=True)
        if time_str:
            st.markdown(f'<p class="gold-text">It is currently {time_str}</p>', unsafe_allow_html=True)
        st.markdown('<div style="height:20px;"></div>', unsafe_allow_html=True)
        st.markdown('<p class="gold-text" style="font-size:1rem;margin-bottom:16px;">'
                    'How would you like to search?</p>', unsafe_allow_html=True)

        c1, c2 = st.columns(2)
        with c1:
            if st.button("🎭 BY MOOD", key="mood_btn", use_container_width=True):
                ud["search_type"] = "mood"; st.session_state.step = 1.5; st.rerun()
        with c2:
            if st.button("🍺 SPECIFIC BEER", key="brand_btn", use_container_width=True):
                ud["search_type"] = "brand"; st.session_state.step = 1.5; st.rerun()
        c3, c4 = st.columns(2)
        with c3:
            if st.button("🚫🍺 NON-ALCOHOLIC", key="na_btn", use_container_width=True):
                ud["search_type"] = "non_alcoholic"; st.session_state.step = 2; st.rerun()
        with c4:
            if st.button("🎮 BEER GAMES", key="games_btn", use_container_width=True):
                st.session_state.game_state = {}
                st.session_state.step = 6; st.rerun()
        if BREWERY_SERVICE_URL:
            st.markdown(f"""
            <a href="{BREWERY_SERVICE_URL}" target="_blank" style="text-decoration:none;">
                <div style="width:100%;border-radius:14px;padding:14px 20px;
                    background:transparent;color:#ffd165;
                    border:1.5px solid rgba(255,209,101,0.32);
                    font-family:Epilogue,sans-serif;font-weight:900;
                    font-size:0.82rem;text-transform:uppercase;
                    letter-spacing:0.07em;margin-top:10px;
                    text-align:center;cursor:pointer;box-sizing:border-box;">
                    🏭 FIND A BREWERY
                </div>
            </a>
            """, unsafe_allow_html=True)

        render_bottom_nav("search")
        render_footer()

    # =========================================================================
    # STEP 1.5 — Input collection
    # =========================================================================
    elif st.session_state.step == 1.5:
        greet, _ = get_greeting()
        st.markdown(f'<div class="big-greeting">{greet}, {ud.get("name","Friend")}.</div>',
                    unsafe_allow_html=True)

        stype = ud.get("search_type")

        if stype == "mood":
            st.markdown('<div style="height:16px;"></div>', unsafe_allow_html=True)
            with st.form("mood_form"):
                mood = st.text_input("Vibe check", placeholder="Relaxed, Hyped, Tired…", max_chars=35)
                if st.form_submit_button("NEXT"):
                    if mood:
                        ud["mood"] = mood; ud["brand_query"] = None
                        st.session_state.step = 2; st.rerun()
                    else:
                        st.error("Please describe your mood")

        elif stype == "brand":
            st.markdown('<div style="height:12px;"></div>', unsafe_allow_html=True)
            st.markdown('<p class="gold-text" style="font-size:0.9rem;margin-bottom:4px;">'
                        'Type your beer, use the mic 🎤 or upload an image 📸</p>', unsafe_allow_html=True)

            with st.form("brand_form"):
                brand_query = st.text_input(
                    "Enter your beer of choice",
                    placeholder="Guinness, West Coast IPA…", max_chars=35)
                if st.form_submit_button("FIND IT"):
                    if brand_query:
                        ud["brand_query"] = brand_query; ud["mood"] = None
                        st.session_state.step = 2; st.rerun()
                    else:
                        st.error("Please enter a beer name or style")

            st.markdown('<div style="height:6px;"></div>', unsafe_allow_html=True)
            st.markdown('<p style="color:#9b8f79;font-size:0.75rem;margin:2px 0 6px;">'
                        '— or record your search —</p>', unsafe_allow_html=True)

            audio_bytes, mime_type = render_voice_widget()

            if audio_bytes:
                with st.spinner("🎤 Transcribing…"):
                    transcription, err = transcribe_audio(audio_bytes, mime_type)
                if err:
                    st.error(f"❌ {err}")
                    st.markdown('<p style="color:#9b8f79;font-size:0.82rem;">'
                                'Please type your search above.</p>', unsafe_allow_html=True)
                elif transcription:
                    st.markdown(
                        f'<div class="voice-heard-bubble">'
                        f'<div class="voice-heard-label">Searching for:</div>'
                        f'<div class="voice-heard-text">"{transcription}"</div></div>',
                        unsafe_allow_html=True)
                    with st.spinner(f"Searching for {transcription}…"):
                        beers = ai_brand_recs(transcription)
                    ud.update({"brand_query": transcription, "search_type": "brand",
                               "mood": None, "day": "Voice Search", "taste": "Voice Search"})
                    st.session_state.rec_beers = beers
                    st.session_state.step = 3
                    st.rerun()

            st.markdown('<div style="height:6px;"></div>', unsafe_allow_html=True)
            st.markdown('<p style="color:#9b8f79;font-size:0.75rem;margin:2px 0 6px;">'
                        '— or search by image 📸 —</p>', unsafe_allow_html=True)

            img_file = st.file_uploader(
                "📸 Upload a beer image",
                type=["jpg", "jpeg", "png", "webp", "heic"],
                key="beer_image_uploader")

            if img_file is not None:
                img_bytes = img_file.read()
                if _PIL_AVAILABLE:
                    preview = _PILImage.open(io.BytesIO(img_bytes))
                    st.image(preview, use_container_width=True, caption="Uploaded image")

                with st.spinner("📸 Analyzing image…"):
                    query, err = identify_beer_from_image(img_bytes)

                if err:
                    st.error(f"❌ {err}")
                elif query is None:
                    st.markdown(
                        '<div style="background:#16202e;border-radius:14px;padding:18px;'
                        'margin:12px 0;border:1px solid rgba(255,180,171,0.3);text-align:center;">'
                        '<p style="color:#ffb4ab;font-size:1rem;font-weight:700;">😕 Sorry, unable to find a match.</p>'
                        '<p style="color:#9b8f79;font-size:0.85rem;margin-top:8px;">'
                        'The image doesn\'t appear to show a beer, or it\'s not clear enough to identify. '
                        'Please try searching by typing the beer name above.</p>'
                        '</div>', unsafe_allow_html=True)
                else:
                    st.markdown(
                        f'<div class="voice-heard-bubble">'
                        f'<div class="voice-heard-label">Identified beer:</div>'
                        f'<div class="voice-heard-text">"{query}"</div></div>',
                        unsafe_allow_html=True)
                    with st.spinner(f"Looking up {query}…"):
                        beers = ai_image_rec(query)
                    ud.update({"brand_query": query, "search_type": "image",
                               "mood": None, "day": "Image Search", "taste": "Image Search"})
                    st.session_state.rec_beers = beers
                    st.session_state.step = 3
                    st.rerun()

        render_bottom_nav("search")
        render_footer()

    # =========================================================================
    # STEP 2 — Context / direct search
    # =========================================================================
    elif st.session_state.step == 2:
        stype = ud.get("search_type")

        if stype == "non_alcoholic":
            ud.update({"day":"Non-Alcoholic Search","taste":"Non-Alcoholic Search"})
            with st.spinner("Finding top-rated non-alcoholic beers…"):
                beers = ai_na_recs()
            st.session_state.rec_beers = beers
            st.session_state.step = 3; st.rerun()

        elif ud.get("brand_query"):
            ud.update({"day":"Specific Search","taste":"Specific Search"})
            with st.spinner(f"Searching for {ud['brand_query']}…"):
                beers = ai_brand_recs(ud["brand_query"])
            st.session_state.rec_beers = beers
            st.session_state.step = 3; st.rerun()

        else:
            st.markdown('<h3 class="gold-text">Tell me more…</h3>', unsafe_allow_html=True)
            with st.form("context_form"):
                day   = st.text_input("What kind of day did you have?",
                                      placeholder="Long work day, celebrating…", max_chars=35)
                taste = st.text_input("What hits right?",
                                      placeholder="Hoppy, Sweet, Dark, Surprise me…", max_chars=35)
                if st.form_submit_button("FIND MY BEER"):
                    if not day or not taste:
                        st.error("Please fill in both fields")
                    else:
                        ud.update({"day":day[:35],"taste":taste[:35]})
                        with st.spinner("Pouring top-rated recommendations…"):
                            beers = ai_mood_recs(ud["mood"], day[:35], taste[:35])
                        st.session_state.rec_beers = beers
                        st.session_state.step = 3; st.rerun()
            render_bottom_nav("search")
            render_footer()

    # =========================================================================
    # STEP 3 — Recommendations
    # =========================================================================
    elif st.session_state.step == 3:
        stype = ud.get("search_type", "brand")

        if stype != "image":
            render_refine_search(stype)

        if stype == "image":
            st.markdown('<h3 class="gold-text">📸 Beer Match</h3>', unsafe_allow_html=True)
            st.markdown(
                '<p style="color:#9b8f79;font-size:0.72rem;text-align:center!important;'
                'font-family:Space Grotesk,sans-serif;margin-bottom:12px;">'
                'Identified from your image · Enter zipcode below to check local availability</p>',
                unsafe_allow_html=True)
        else:
            st.markdown('<h3 class="gold-text">Top Picks For You</h3>', unsafe_allow_html=True)
            st.markdown(
                '<p style="color:#9b8f79;font-size:0.72rem;text-align:center!important;'
                'font-family:Space Grotesk,sans-serif;margin-bottom:12px;">'
                '⭐ Ranked by Google review ratings · Enter zipcode below each beer to check local availability</p>',
                unsafe_allow_html=True)

        if not st.session_state.rec_beers:
            st.markdown(
                '<div style="background:#121c2a;padding:30px;border-radius:16px;margin:32px 0;'
                'text-align:center;border:1px solid rgba(255,209,101,0.09);">'
                '<p style="color:#ffd165;font-size:1.1rem;">No recommendations found. Try a different search.</p>'
                '</div>', unsafe_allow_html=True)
            c1, c2 = st.columns(2)
            with c1:
                if st.button("TRY AGAIN", key="try_again_btn", use_container_width=True):
                    st.session_state.step = 1; ud["search_type"] = None
                    st.session_state.rec_beers = []; st.rerun()
            with c2:
                if st.button("GO HOME", key="go_home_btn", use_container_width=True):
                    st.session_state.step = 0
                    st.session_state.user_data = {"name": ud.get("name",""), "mood":"",
                                                   "brand_query":None,"day":"","taste":"","search_type":None}
                    st.session_state.rec_beers = []; st.rerun()
        else:
            for idx, beer in enumerate(st.session_state.rec_beers):
                render_beer_with_zip_search(beer, idx, stype)
                st.markdown('<hr style="border:none;border-top:1px solid rgba(255,209,101,0.07);margin:20px 0;">', unsafe_allow_html=True)

        render_bottom_nav("search")
        render_footer()

    # =========================================================================
    # STEP 4 — Saved beers + Share panel
    # =========================================================================
    elif st.session_state.step == 4:
        st.markdown('<h3 class="gold-text">Your Saved Brews</h3>', unsafe_allow_html=True)

        if not st.session_state.saved_beers:
            st.markdown(
                '<div style="background:#121c2a;padding:30px;border-radius:16px;margin:32px 0;'
                'text-align:center;border:1px solid rgba(255,209,101,0.09);">'
                '<p style="color:#ffd165;font-size:1.1rem;">No beers saved yet. Go back and add some!</p>'
                '</div>', unsafe_allow_html=True)
        else:
            for i, beer in enumerate(st.session_state.saved_beers):
                render_beer_with_zip_search(beer, f"sv_{i}", ud.get("search_type","brand"))
                if st.button("REMOVE", key=f"remove_sv_{i}", use_container_width=True):
                    st.session_state.saved_beers.pop(i)
                    # Reset share token if list changes
                    st.session_state.shared_list_token = None
                    st.session_state.shared_list_title = None
                    st.rerun()
                st.markdown('<hr style="border:none;border-top:1px solid rgba(255,209,101,0.07);margin:16px 0;">', unsafe_allow_html=True)

            # ── Share panel — always shown when there are saved beers ─────────
            st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)
            render_share_panel(st.session_state.saved_beers, ud.get("name", "User"))

        render_bottom_nav("saved")
        render_footer()

    # =========================================================================
    # STEP 5 — Feedback (now saves to PostgreSQL)
    # =========================================================================
    elif st.session_state.step == 5:
        st.markdown('<h3 class="gold-text">Feedback / Feature Request</h3>', unsafe_allow_html=True)

        if st.session_state.feedback_submitted:
            st.markdown(
                f'<div style="background:#121c2a;padding:30px;border-radius:16px;'
                f'margin:32px 0;text-align:center;">'
                f'<p style="color:#4ae176;font-size:1.2rem;">'
                f'✓ Thank you, {ud.get("name","User")}! Your feedback was received.</p></div>',
                unsafe_allow_html=True)
            import time; time.sleep(2)
            st.session_state.feedback_submitted = False
            st.session_state.step = 1; st.rerun()
        else:
            fb = st.text_area(
                "Share your thoughts, suggestions, or feature requests",
                placeholder="What would make Golden Draught better?",
                max_chars=3000, height=200, key="feedback_textarea")
            c1, c2, c3 = st.columns([1, 2, 1])
            with c2:
                if st.button("SUBMIT FEEDBACK", key="feedback_submit_btn", use_container_width=True):
                    if fb and fb.strip():
                        save_feedback(ud.get("name","Anonymous"), fb)
                        st.session_state.feedback_submitted = True; st.rerun()
                    else:
                        st.error("Please write some feedback before submitting.")
        render_bottom_nav("feedback")

    # =========================================================================
    # STEP 6 — Beer Games
    # =========================================================================
    elif st.session_state.step == 6:
        render_beer_games()
        render_footer()


if __name__ == "__main__":
    main()