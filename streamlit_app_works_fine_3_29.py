import streamlit as st
import os
import json
import requests
import datetime
from datetime import timedelta
import base64
import io
import sys
import re
from huggingface_hub import HfApi, hf_hub_download

try:
    from PIL import Image as _PILImage
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

# --- Configuration & Setup ---
st.set_page_config(
    page_title="Golden Draught",
    page_icon="🍺",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# Setup directories
STATIC_IMG_DIR = os.path.join(os.path.dirname(__file__), "static", "images")
LOG_DIR = os.path.join(os.path.dirname(__file__), "log")
FEEDBACK_DIR = os.path.join(os.path.dirname(__file__), "feedback")
os.makedirs(STATIC_IMG_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(FEEDBACK_DIR, exist_ok=True)

# Try to import Google Generative AI
try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    genai = None

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# API Keys
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
GOOGLE_CSE_API_KEY = os.getenv('GOOGLE_CSE_API_KEY')
GOOGLE_CSE_CX = os.getenv('GOOGLE_CSE_CX')
GOOGLE_PLACES_API_KEY = os.getenv('GOOGLE_PLACES_API_KEY')
GOOGLE_GEOCODING_API_KEY = os.getenv('GOOGLE_GEOCODING_API_KEY') or GOOGLE_PLACES_API_KEY

# Initialize HF API
HF_TOKEN = os.getenv('HF_TOKEN')
HF_DATASET_REPO = "mashomashi/beer_data"

# --- Debug Helper ---
def debug_print(message, level="INFO"):
    colors = {
        "INFO": "\033[94m",
        "SUCCESS": "\033[92m",
        "WARNING": "\033[93m",
        "ERROR": "\033[91m",
        "RESET": "\033[0m"
    }
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    color = colors.get(level, colors["INFO"])
    print(f"{color}[{level}] [{timestamp}] {message}{colors['RESET']}", file=sys.stderr)

# --- LOGGING FUNCTIONS ---
def log_beer_selection(username, beer_name, brand, search_type, mood=None):
    if not HF_TOKEN:
        debug_print("HF_TOKEN not set, skipping logging", "WARNING")
        return

    try:
        import tempfile
        api = HfApi()
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            log_path = hf_hub_download(
                repo_id=HF_DATASET_REPO,
                filename="log.txt",
                repo_type="dataset",
                token=HF_TOKEN
            )
            with open(log_path, 'r', encoding='utf-8') as f:
                existing_logs = f.read()
        except:
            existing_logs = ""

        if search_type == 'mood' and mood:
            log_entry = f"[{timestamp}] User: {username} | Beer: {beer_name} ({brand}) | Search: By Mood ({mood})\n"
        elif search_type == 'non_alcoholic':
            log_entry = f"[{timestamp}] User: {username} | Beer: {beer_name} ({brand}) | Search: Non-Alcoholic Beer\n"
        elif search_type == 'voice':
            log_entry = f"[{timestamp}] User: {username} | Beer: {beer_name} ({brand}) | Search: By Voice\n"
        else:
            log_entry = f"[{timestamp}] User: {username} | Beer: {beer_name} ({brand}) | Search: Specific Beer\n"

        new_content = log_entry + existing_logs

        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False, suffix='.txt') as f:
            f.write(new_content)
            temp_path = f.name

        try:
            api.upload_file(
                path_or_fileobj=temp_path,
                path_in_repo="log.txt",
                repo_id=HF_DATASET_REPO,
                repo_type="dataset",
                token=HF_TOKEN
            )
            debug_print(f"Logged selection to HF dataset: {beer_name}", "SUCCESS")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    except Exception as e:
        debug_print(f"Error logging to HF dataset: {e}", "ERROR")

def save_feedback(username, feedback_text):
    """Save user feedback — writes locally if HF is unavailable."""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    content = (
        f"Feedback from: {username}\n"
        f"Date: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        + "=" * 50 + "\n\n"
        + feedback_text
    )

    # ── Try Hugging Face first ──
    if HF_TOKEN:
        try:
            import tempfile
            api = HfApi()
            hf_filename = f"feedback/{username}_{timestamp}.txt"

            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False, suffix='.txt') as f:
                f.write(content)
                temp_path = f.name

            try:
                api.upload_file(
                    path_or_fileobj=temp_path,
                    path_in_repo=hf_filename,
                    repo_id=HF_DATASET_REPO,
                    repo_type="dataset",
                    token=HF_TOKEN
                )
                debug_print("Saved feedback to HF dataset", "SUCCESS")
                return True
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
        except Exception as e:
            debug_print(f"HF feedback upload failed, falling back to local: {e}", "WARNING")

    # ── Fallback: save locally ──
    try:
        os.makedirs(FEEDBACK_DIR, exist_ok=True)
        local_path = os.path.join(FEEDBACK_DIR, f"{username}_{timestamp}.txt")
        with open(local_path, 'w', encoding='utf-8') as f:
            f.write(content)
        debug_print(f"Saved feedback locally: {local_path}", "SUCCESS")
        return True
    except Exception as e:
        debug_print(f"Local feedback save also failed: {e}", "ERROR")
        return True  # Return True anyway so the UI doesn't block the user


# --- CACHED INITIALIZATION ---
@st.cache_resource(show_spinner=False)
def initialize_gemini_model():
    if not GENAI_AVAILABLE:
        debug_print("google-generativeai package not installed", "ERROR")
        return None, "google-generativeai package not installed"

    if not GEMINI_API_KEY:
        debug_print("GEMINI_API_KEY not found in environment variables", "ERROR")
        return None, "GEMINI_API_KEY not found in environment variables"

    try:
        genai.configure(api_key=GEMINI_API_KEY)

        # Try models in order of preference
        for model_name in ['gemini-3.1-flash-lite-preview', 'gemini-3-flash-preview']:
            try:
                debug_print(f"Attempting to initialize {model_name}...", "INFO")
                model = genai.GenerativeModel(model_name)
                # Quick smoke test
                model.generate_content("hi")
                debug_print(f"Successfully initialized {model_name}", "SUCCESS")
                return model, None
            except Exception as e:
                debug_print(f"Failed {model_name}: {str(e)}", "WARNING")

        return None, "No Gemini model could be initialized"

    except Exception as e:
        debug_print(f"Failed to configure Gemini: {str(e)}", "ERROR")
        return None, f"Failed to configure Gemini: {str(e)}"

processing_model, gemini_error = initialize_gemini_model()

# --- VALIDATION FUNCTIONS ---
def validate_zipcode(zipcode):
    if not zipcode:
        return False, "Please enter a zipcode"

    clean_zip = ''.join(filter(str.isdigit, zipcode))

    if len(clean_zip) != 5:
        return False, "Zipcode must be exactly 5 digits"

    zip_int = int(clean_zip)
    if zip_int < 501 or zip_int > 99950:
        return False, "Please enter a valid US zipcode"

    return True, clean_zip

# =============================================================
# GOLDEN DRAUGHT — CSS
# =============================================================
@st.cache_data
def get_mobile_css():
    return """
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Epilogue:wght@700;800;900&family=Plus+Jakarta+Sans:wght@400;500;600&family=Space+Grotesk:wght@500;700&display=swap');
        @import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=swap');

        :root {
            --bg-app:       #091421;
            --bg-card:      #121c2a;
            --bg-card-low:  #16202e;
            --bg-card-high: #212b39;
            --text-main:    #d9e3f6;
            --text-sub:     #d3c5ac;
            --text-muted:   #9b8f79;
            --accent:       #ffd165;
            --accent-dim:   #f7be1d;
            --accent-green: #4ae176;
            --error-color:  #ffb4ab;
            --input-bg:     #0d1928;
            --input-text:   #d9e3f6;
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

        /* ── TOP APP BAR ── */
        .app-bar {
            position: fixed;
            top: 0; left: 0; right: 0;
            background: #091421;
            border-bottom: 1px solid rgba(255,209,101,0.07);
            padding: 14px 20px;
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 999;
        }
        .app-bar-title {
            font-family: 'Epilogue', sans-serif;
            font-weight: 900;
            font-size: 1rem;
            letter-spacing: 0.2em;
            text-transform: uppercase;
            color: #ffd165;
        }

        /* ── BOTTOM NAV ── */
        .bottom-nav {
            position: fixed;
            bottom: 0; left: 0; right: 0;
            background: rgba(18,28,42,0.92);
            backdrop-filter: blur(24px);
            -webkit-backdrop-filter: blur(24px);
            height: 68px;
            display: flex;
            justify-content: space-around;
            align-items: center;
            border-radius: 24px 24px 0 0;
            box-shadow: 0 -8px 32px rgba(0,0,0,0.5);
            z-index: 998;
            padding: 0 8px 4px;
        }
        .nav-item {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 2px;
            color: rgba(217,227,246,0.4);
            padding: 4px 14px;
            font-family: 'Space Grotesk', sans-serif;
        }
        .nav-item.active {
            color: #ffd165;
            filter: drop-shadow(0 0 6px rgba(255,209,101,0.5));
        }
        .nav-icon {
            font-family: 'Material Symbols Outlined';
            font-size: 1.4rem;
            font-variation-settings: 'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 24;
            line-height: 1;
        }
        .nav-icon.filled { font-variation-settings: 'FILL' 1, 'wght' 400, 'GRAD' 0, 'opsz' 24; }
        .nav-label {
            font-size: 0.56rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.09em;
        }

        /* ── TYPOGRAPHY ── */
        h1, h2, h3, p, div {
            text-align: center !important;
            font-family: 'Plus Jakarta Sans', -apple-system, sans-serif;
        }

        .big-greeting {
            font-family: 'Epilogue', sans-serif;
            font-size: 2rem;
            font-weight: 900;
            margin: 14px 0 8px 0;
            background: linear-gradient(90deg, #ffd165, #ffdf9a);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            letter-spacing: -0.01em;
        }

        .gold-text { color: var(--accent) !important; }

        /* ── TEXT INPUTS ── */
        .stTextInput > div > div {
            background-color: var(--input-bg) !important;
            border-radius: 14px !important;
            border: 1.5px solid rgba(255,209,101,0.18) !important;
            padding: 0 10px !important;
        }
        .stTextInput input {
            color: var(--input-text) !important;
            background-color: transparent !important;
            text-align: center !important;
            font-family: 'Plus Jakarta Sans', sans-serif !important;
            font-weight: 500 !important;
            caret-color: #ffd165 !important;
            padding: 12px 5px !important;
        }
        .stTextInput input::placeholder {
            color: rgba(217,227,246,0.32) !important;
            opacity: 1 !important;
        }
        .stTextInput label {
            color: var(--accent) !important;
            font-family: 'Space Grotesk', sans-serif !important;
            font-size: 0.7rem !important;
            font-weight: 700 !important;
            text-transform: uppercase !important;
            letter-spacing: 0.12em !important;
            width: 100% !important;
            text-align: center !important;
        }
        .stTextInput > div > div:focus-within {
            border-color: rgba(255,209,101,0.55) !important;
            box-shadow: 0 0 0 3px rgba(255,209,101,0.09) !important;
        }

        /* ── TEXT AREA ── */
        .stTextArea > div > div {
            background-color: var(--input-bg) !important;
            border-radius: 14px !important;
            border: 1.5px solid rgba(255,209,101,0.18) !important;
        }
        .stTextArea textarea {
            color: var(--input-text) !important;
            font-family: 'Plus Jakarta Sans', sans-serif !important;
            background-color: transparent !important;
        }
        .stTextArea label {
            color: var(--accent) !important;
            font-family: 'Space Grotesk', sans-serif !important;
            font-size: 0.7rem !important;
            font-weight: 700 !important;
            text-transform: uppercase !important;
            letter-spacing: 0.12em !important;
            width: 100% !important;
            text-align: center !important;
        }

        /* ── BUTTONS — always centered, full width ── */
        .stButton {
            display: flex !important;
            justify-content: center !important;
            width: 100% !important;
        }
        .stButton > button {
            width: 100% !important;
            border-radius: 14px !important;
            padding: 14px 20px !important;
            background: transparent !important;
            color: var(--accent) !important;
            border: 1.5px solid rgba(255,209,101,0.32) !important;
            font-family: 'Epilogue', sans-serif !important;
            font-weight: 900 !important;
            font-size: 0.82rem !important;
            text-transform: uppercase !important;
            letter-spacing: 0.07em !important;
            margin-top: 10px;
            transition: all 0.2s ease !important;
            opacity: 1 !important;
            display: block !important;
            margin-left: auto !important;
            margin-right: auto !important;
        }
        .stButton > button:hover {
            background: linear-gradient(135deg, #ffd165, #eab308) !important;
            color: #3f2e00 !important;
            border-color: transparent !important;
            box-shadow: 0 4px 16px rgba(255,209,101,0.25) !important;
        }
        .stButton > button:active { opacity: 1 !important; }
        .stButton > button:focus  { opacity: 1 !important; }

        /* Form submit button */
        div[data-testid="stFormSubmitButton"] {
            display: flex !important;
            justify-content: center !important;
            width: 100% !important;
        }
        div[data-testid="stFormSubmitButton"] > button {
            background: linear-gradient(135deg, #ffd165, #eab308) !important;
            color: #3f2e00 !important;
            border: none !important;
            width: 100% !important;
            opacity: 1 !important;
            box-shadow: 0 4px 16px rgba(255,209,101,0.2) !important;
        }

        .stForm [data-testid="InputInstructions"] { display: none !important; }
        div[class*="FormInstructions"] { display: none !important; }

        /* Force all column children to center their buttons */
        [data-testid="column"] .stButton {
            display: flex !important;
            justify-content: center !important;
            align-items: center !important;
        }
        [data-testid="column"] .stButton > button {
            width: 100% !important;
            margin-left: auto !important;
            margin-right: auto !important;
        }

        /* ── BEER CARD ── */
        .beer-card {
            background: var(--bg-card);
            border: 1px solid rgba(255,209,101,0.09);
            border-radius: 20px;
            padding: 20px;
            margin: 16px 0;
            position: relative;
            overflow: hidden;
        }
        .beer-card.unavailable {
            border-color: rgba(255,180,171,0.22);
        }
        .unavailable-badge {
            position: absolute;
            top: 14px; right: 14px;
            background: rgba(255,180,171,0.1);
            color: #ffb4ab;
            border: 1px solid rgba(255,180,171,0.3);
            border-radius: 20px;
            padding: 4px 10px;
            font-family: 'Space Grotesk', sans-serif;
            font-size: 0.62rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }
        .beer-title {
            font-family: 'Epilogue', sans-serif;
            font-size: 1.3rem;
            font-weight: 800;
            color: #d9e3f6;
            margin-bottom: 4px;
            letter-spacing: -0.01em;
        }
        .beer-brand {
            font-family: 'Space Grotesk', sans-serif;
            color: var(--accent);
            font-size: 0.7rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.12em;
            margin-bottom: 14px;
        }

        /* ── METRICS GRID ── */
        .beer-metrics {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 8px;
            margin: 12px 0;
        }
        .metric-box {
            background: var(--bg-card-low);
            border-radius: 12px;
            padding: 10px 6px;
            text-align: center;
            border: 1px solid rgba(255,255,255,0.04);
        }
        .metric-value {
            font-family: 'Epilogue', sans-serif;
            font-size: 1.05rem;
            font-weight: 800;
            color: var(--accent);
        }
        .metric-label {
            font-family: 'Space Grotesk', sans-serif;
            font-size: 0.58rem;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.1em;
            margin-top: 2px;
        }

        /* ── DETAIL ROWS ── */
        .beer-detail-row {
            background: var(--bg-card-low);
            border-radius: 10px;
            padding: 10px 14px;
            margin: 7px 0;
            text-align: left !important;
        }
        .beer-detail-label {
            font-family: 'Space Grotesk', sans-serif;
            font-size: 0.62rem;
            font-weight: 700;
            color: var(--accent);
            text-transform: uppercase;
            letter-spacing: 0.1em;
            margin-bottom: 4px;
        }
        .beer-detail-value {
            font-family: 'Plus Jakarta Sans', sans-serif;
            font-size: 0.86rem;
            color: var(--text-sub);
            line-height: 1.5;
            text-align: left !important;
        }

        /* ── BAR CARD ── */
        .bar-card {
            background: var(--bg-card-low);
            padding: 14px;
            margin: 10px 0;
            border-radius: 12px;
            border-left: 3px solid var(--accent);
        }
        .bar-name {
            font-family: 'Epilogue', sans-serif;
            font-weight: 800;
            color: #d9e3f6;
            font-size: 1rem;
            margin-bottom: 5px;
        }
        .bar-address { color: var(--text-sub); font-size: 0.82rem; margin: 4px 0; }
        .bar-rating  { color: var(--accent); margin-top: 6px; font-size: 0.85rem; }

        /* ── AUDIO INPUT ── */
        .stAudioInput { margin: 8px 0; }
        .stAudioInput label {
            color: var(--accent) !important;
            font-family: 'Space Grotesk', sans-serif !important;
            font-size: 0.7rem !important;
            font-weight: 700 !important;
            text-transform: uppercase !important;
            letter-spacing: 0.12em !important;
        }
        .stFileUploader label {
            color: var(--accent) !important;
            font-family: 'Space Grotesk', sans-serif !important;
            font-size: 0.7rem !important;
            font-weight: 700 !important;
            text-transform: uppercase !important;
        }
        .stFileUploader [data-testid="stFileUploaderDropzone"] {
            background: var(--input-bg) !important;
            border: 1.5px dashed rgba(255,209,101,0.3) !important;
            border-radius: 14px !important;
        }

        /* ── RADIO / TOGGLE ── */
        .stRadio > label {
            color: var(--accent) !important;
            font-family: 'Space Grotesk', sans-serif !important;
            font-size: 0.7rem !important;
            font-weight: 700 !important;
            text-transform: uppercase !important;
            letter-spacing: 0.12em !important;
        }
        .stRadio [data-testid="stWidgetLabel"] {
            justify-content: center !important;
        }

        /* ── SPINNER ── */
        .stSpinner > div { border-top-color: var(--accent) !important; }

        /* ── EXPANDER ── */
        .streamlit-expanderHeader {
            background: var(--bg-card-low) !important;
            border-radius: 10px !important;
            color: var(--accent) !important;
            font-family: 'Space Grotesk', sans-serif !important;
            font-size: 0.82rem !important;
            font-weight: 700 !important;
        }

        /* ── VOICE RESULT BUBBLE ── */
        .voice-heard-bubble {
            background: #16202e;
            border-radius: 12px;
            padding: 12px 16px;
            border: 1px solid rgba(255,209,101,0.2);
            margin: 12px 0;
            text-align: center !important;
        }
        .voice-heard-label {
            font-size: 0.65rem;
            color: #ffd165;
            font-family: 'Space Grotesk', sans-serif;
            text-transform: uppercase;
            letter-spacing: 0.1em;
        }
        .voice-heard-text {
            color: #d9e3f6;
            font-size: 0.95rem;
            margin-top: 4px;
        }

        /* ── ZIPCODE INLINE BOX ── */
        .zip-inline-wrap {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            margin-bottom: 12px;
        }

        /* ── FOOTER ── */
        .footer {
            margin-top: 40px;
            text-align: center !important;
            font-family: 'Space Grotesk', sans-serif;
            font-size: 0.7rem;
            color: var(--text-muted);
            padding: 20px 0 8px;
            border-top: 1px solid rgba(255,209,101,0.07);
            letter-spacing: 0.04em;
        }

        /* ── DEBUG ── */
        .debug-panel {
            background: var(--bg-card);
            border: 1px solid #333;
            border-radius: 12px;
            padding: 14px;
            margin: 16px 0;
            font-size: 0.8rem;
            color: #888;
            text-align: left !important;
        }
    </style>
    """

def inject_mobile_css():
    st.markdown(get_mobile_css(), unsafe_allow_html=True)

# --- Helper Functions ---
@st.cache_data
def load_image_as_base64(image_path):
    if os.path.exists(image_path):
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return None

def render_logo():
    logo_path = os.path.join(os.path.dirname(__file__), "static", "images", "logo.png")
    encoded = load_image_as_base64(logo_path)

    if encoded:
        st.markdown(f"""
            <div style="display: flex; justify-content: center; margin-bottom: 20px;">
                <img src="data:image/png;base64,{encoded}"
                     style="width: 80px; height: 80px; border-radius: 50%;
                            border: 2px solid #ffd165;
                            box-shadow: 0 0 20px rgba(255,209,101,0.25);">
            </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown('<div style="font-size: 4rem; text-align: center;">🍺</div>', unsafe_allow_html=True)

def render_app_bar():
    st.markdown("""
        <div class="app-bar">
            <span class="app-bar-title">Golden Draught</span>
        </div>
    """, unsafe_allow_html=True)

def render_bottom_nav(active="home"):
    items = [
        ("home",     "home",       "Home",     active == "home"),
        ("search",   "document_scanner", "Search", active == "search"),
        ("saved",    "bookmarks",  "Saved",    active == "saved"),
        ("feedback", "rate_review","Feedback", active == "feedback"),
    ]
    nav_html = '<div class="bottom-nav">'
    for _, icon, label, is_active in items:
        cls = "nav-item active" if is_active else "nav-item"
        icon_cls = "nav-icon filled" if is_active else "nav-icon"
        nav_html += f"""
            <span class="{cls}">
                <span class="{icon_cls}">{icon}</span>
                <span class="nav-label">{label}</span>
            </span>"""
    nav_html += '</div>'
    st.markdown(nav_html, unsafe_allow_html=True)

def render_footer():
    if st.session_state.step not in [5]:
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            if st.button("📝 Give us your feedback", key="feedback_link_btn", use_container_width=True):
                st.session_state.step = 5
                st.rerun()

    st.markdown("""
        <div class="footer">
            © 2026 Dimension Unlimited. All rights reserved. Drink responsibly.
        </div>
    """, unsafe_allow_html=True)

def render_debug_panel():
    if st.session_state.get('show_debug', False):
        debug_info = f"""
        <div class="debug-panel">
            <strong>🔧 Debug Info:</strong><br>
            • Gemini Available: {GENAI_AVAILABLE}<br>
            • API Key Set: {'Yes' if GEMINI_API_KEY else 'No'}<br>
            • Places API Set: {'Yes' if GOOGLE_PLACES_API_KEY else 'No'}<br>
            • Geocoding API Set: {'Yes' if GOOGLE_GEOCODING_API_KEY else 'No'}<br>
            • Model Initialized: {'Yes' if processing_model else 'No'}<br>
            • Error: {gemini_error or 'None'}<br>
            • Step: {st.session_state.step}<br>
            • Search Type: {st.session_state.user_data.get('search_type', 'None')}<br>
            • Recommendations: {len(st.session_state.rec_beers)}<br>
        </div>
        """
        st.markdown(debug_info, unsafe_allow_html=True)

@st.cache_data(ttl=3600)
def get_greeting(zipcode):
    greeting = "Hello"
    time_str = ""
    try:
        first_digit = int(str(zipcode)[0])
        if first_digit in [0, 1, 2, 3]:
            offset = -5
        elif first_digit in [4, 5, 6]:
            offset = -6
        elif first_digit == 7:
            offset = -7
        else:
            offset = -8

        utc_now = datetime.datetime.utcnow()
        local_time = utc_now + timedelta(hours=offset)
        hour = local_time.hour

        if 5 <= hour < 12:
            greeting = "Good Morning"
        elif 12 <= hour < 17:
            greeting = "Good Afternoon"
        elif 17 <= hour < 22:
            greeting = "Good Evening"
        else:
            greeting = "Hey Night Owl"

        time_str = local_time.strftime("%I:%M %p")
    except:
        pass

    return greeting, time_str

_BLOCKED_IMAGE_DOMAINS = (
    'lookaside.fbsbx.com', 'fbcdn.net', 'facebook.com', 'fb.com',
    'instagram.com', 'cdninstagram.com',
    'twimg.com', 'twitter.com', 'x.com',
    'tiktok.com', 'redd.it', 'reddit.com',
    'pinterest.com', 'pinimg.com',
    'snapchat.com',
)

def _is_safe_image_domain(url: str) -> bool:
    return not any(d in url for d in _BLOCKED_IMAGE_DOMAINS)

@st.cache_data(ttl=86400)
def _fetch_resized_image_bytes(image_url: str):
    try:
        headers = {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/124.0.0.0 Safari/537.36'
            ),
            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
        }
        resp = requests.get(image_url, headers=headers, timeout=7)
        ct = resp.headers.get('Content-Type', '')
        if resp.status_code != 200 or 'image' not in ct:
            return None
        raw = resp.content
        if len(raw) < 200:
            return None

        if _PIL_AVAILABLE:
            img = _PILImage.open(io.BytesIO(raw))
            img.thumbnail((400, 400), _PILImage.LANCZOS)
            if img.mode in ('RGBA', 'LA', 'P'):
                img = img.convert('RGB')
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=82, optimize=True)
            return buf.getvalue()
        else:
            return raw if len(raw) <= 150_000 else None
    except Exception as e:
        debug_print(f"Image proxy error ({image_url[:60]}...): {e}", "WARNING")
    return None

@st.cache_data(ttl=86400)
def google_custom_search(query, num=6):
    if not GOOGLE_CSE_API_KEY or not GOOGLE_CSE_CX:
        debug_print("Google Custom Search API keys not configured", "WARNING")
        return None
    try:
        params = {
            'key': GOOGLE_CSE_API_KEY,
            'cx': GOOGLE_CSE_CX,
            'q': query,
            'num': num,
            'searchType': 'image',
            'imgType': 'photo',
            'safe': 'active',
        }
        resp = requests.get('https://www.googleapis.com/customsearch/v1', params=params, timeout=5)
        if resp.status_code == 200:
            for item in resp.json().get('items', []):
                url = item.get('link', '')
                if url and _is_safe_image_domain(url):
                    return url
        else:
            debug_print(f"Custom Search API returned status {resp.status_code}", "WARNING")
    except Exception as e:
        debug_print(f"Image search error: {e}", "ERROR")
    return None

@st.cache_data(ttl=86400)
def zipcode_to_coords(zipcode):
    if not GOOGLE_GEOCODING_API_KEY:
        debug_print("Geocoding API key not configured", "ERROR")
        return None, None
    try:
        url = "https://maps.googleapis.com/maps/api/geocode/json"
        params = {
            'address': zipcode,
            'key': GOOGLE_GEOCODING_API_KEY
        }
        resp = requests.get(url, params=params, timeout=5)
        if resp.status_code == 200:
            results = resp.json().get('results', [])
            if results:
                location = results[0]['geometry']['location']
                debug_print(f"Geocoded {zipcode} to {location['lat']}, {location['lng']}", "SUCCESS")
                return location['lat'], location['lng']
            else:
                debug_print(f"No geocoding results for zipcode {zipcode}", "WARNING")
        else:
            debug_print(f"Geocoding API returned status {resp.status_code}: {resp.text}", "ERROR")
    except Exception as e:
        debug_print(f"Geocoding error: {e}", "ERROR")
    return None, None

def get_city_from_zipcode(zipcode):
    if not GOOGLE_GEOCODING_API_KEY:
        return ""
    try:
        url = "https://maps.googleapis.com/maps/api/geocode/json"
        params = {
            'address': zipcode,
            'key': GOOGLE_GEOCODING_API_KEY
        }
        resp = requests.get(url, params=params, timeout=5)
        if resp.status_code == 200:
            results = resp.json().get('results', [])
            if results:
                for component in results[0].get('address_components', []):
                    if 'locality' in component.get('types', []):
                        return component.get('long_name', '')
    except Exception as e:
        debug_print(f"City extraction error: {e}", "ERROR")
    return ""

# --- AI AGENT FUNCTIONS ---
@st.cache_data(ttl=3600)
def web_search_bars_for_beer(beer_name, brand_name, zipcode, city_name):
    if not GOOGLE_CSE_API_KEY or not GOOGLE_CSE_CX:
        debug_print("Web Search Agent: Custom Search API not configured", "WARNING")
        return []

    try:
        search_queries = [
            f"{beer_name} {brand_name} bars near {zipcode}",
            f"where to drink {beer_name} in {city_name}",
        ]
        all_results = []
        for query in search_queries:
            params = {
                'key': GOOGLE_CSE_API_KEY,
                'cx': GOOGLE_CSE_CX,
                'q': query,
                'num': 5
            }
            resp = requests.get('https://www.googleapis.com/customsearch/v1', params=params, timeout=10)
            if resp.status_code == 200:
                items = resp.json().get('items', [])
                debug_print(f"Web Search Agent: Found {len(items)} results", "SUCCESS")
                all_results.extend(items)
        return all_results
    except Exception as e:
        debug_print(f"Web Search Agent error: {e}", "ERROR")
        return []

def analyze_web_results_for_bars(web_results, beer_name, city_name):
    if not processing_model or not web_results:
        return []
    try:
        content_summary = []
        for idx, result in enumerate(web_results[:8]):
            title = result.get('title', '')
            snippet = result.get('snippet', '')
            content_summary.append(f"Result {idx+1}: {title} - {snippet}")

        combined_content = "\n".join(content_summary)
        prompt = f"""Based on these web search results about where to find {beer_name} in {city_name}, extract real bar names.

Web Results:
{combined_content}

Return ONLY a JSON array: [{{"name": "Bar Name", "confidence": "high/medium"}}]
Maximum 8 bars. No markdown. Just the JSON array."""

        response = processing_model.generate_content(prompt)
        if not response or not response.text:
            return []

        text = response.text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        bars = json.loads(text)
        return bars if isinstance(bars, list) else []

    except Exception as e:
        debug_print(f"AI Analysis Agent error: {e}", "ERROR")
        return []

def verify_bars_with_places_api(bar_names, lat, lng, radius=8000):
    if not GOOGLE_PLACES_API_KEY or not bar_names:
        return []

    verified_bars = []
    try:
        for bar_data in bar_names[:10]:
            bar_name = bar_data.get('name', '') if isinstance(bar_data, dict) else bar_data

            url = "https://places.googleapis.com/v1/places:searchText"
            headers = {
                "Content-Type": "application/json",
                "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
                "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.rating,places.priceLevel,places.id,places.location"
            }
            data = {
                "textQuery": f"{bar_name} near {lat},{lng}",
                "locationBias": {
                    "circle": {
                        "center": {"latitude": lat, "longitude": lng},
                        "radius": radius
                    }
                },
                "maxResultCount": 1
            }

            resp = requests.post(url, json=data, headers=headers, timeout=10)
            if resp.status_code == 200:
                places = resp.json().get('places', [])
                if places:
                    place = places[0]
                    price_level = place.get('priceLevel')
                    price_str = '$' * int(price_level) if price_level and str(price_level).isdigit() else '$$'

                    bar_info = {
                        'name': place.get('displayName', {}).get('text', bar_name),
                        'address': place.get('formattedAddress', 'Address not available'),
                        'rating': place.get('rating', 'N/A'),
                        'price_level': price_str,
                        'place_id': place.get('id', ''),
                        'lat': place.get('location', {}).get('latitude'),
                        'lng': place.get('location', {}).get('longitude')
                    }
                    verified_bars.append(bar_info)

            if len(verified_bars) >= 5:
                break

        return verified_bars
    except Exception as e:
        debug_print(f"Verification Agent error: {e}", "ERROR")
        return []

@st.cache_data(ttl=3600)
def find_bars_serving_beer(lat, lng, beer_name, brand_name, zipcode):
    city_name = get_city_from_zipcode(zipcode)
    web_results = web_search_bars_for_beer(beer_name, brand_name, zipcode, city_name)
    if not web_results:
        return []
    bar_names = analyze_web_results_for_bars(web_results, beer_name, city_name)
    if not bar_names:
        return []
    return verify_bars_with_places_api(bar_names, lat, lng)

def ensure_beer_image(beer):
    raw_url = beer.get('image')
    if not raw_url:
        query = f"{beer.get('name', '')} {beer.get('brand', '')} beer bottle can"
        raw_url = google_custom_search(query)

    beer['image_bytes'] = None
    beer['image'] = None

    if raw_url:
        img_bytes = _fetch_resized_image_bytes(raw_url)
        beer['image_bytes'] = img_bytes

    return beer

# =============================================================
# AUDIO TRANSCRIPTION
# =============================================================
def transcribe_audio_with_gemini(audio_bytes, mime_type="audio/wav"):
    """Transcribe audio using Gemini. Falls back gracefully on errors."""
    if not processing_model:
        return None, "AI model not available"

    try:
        import google.generativeai as genai_inner

        # Upload as a temporary file via the Files API (more reliable than inline b64)
        with io.BytesIO(audio_bytes) as buf:
            buf.seek(0)
            # Use inline base64 approach with a fresh model call
            audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')

        prompt_parts = [
            {
                "inline_data": {
                    "mime_type": mime_type,
                    "data": audio_b64
                }
            },
            {
                "text": (
                    "You are a transcription assistant for a beer finder app. "
                    "The user spoke a search query. Transcribe exactly what they said. "
                    "Return ONLY the transcribed words with no additional commentary, "
                    "punctuation marks, or formatting."
                )
            }
        ]

        response = processing_model.generate_content(prompt_parts)
        transcription = response.text.strip() if response and response.text else None

        if not transcription:
            return None, "Could not understand the audio. Please try again or type your search."

        debug_print(f"Audio transcribed: '{transcription}'", "SUCCESS")
        return transcription, None

    except Exception as e:
        debug_print(f"Audio transcription error: {e}", "ERROR")
        # Return a helpful message instead of a raw exception
        return None, "Voice transcription is temporarily unavailable. Please type your search below."

# =============================================================
# AI RECOMMENDATION FUNCTIONS
# =============================================================
def _parse_beer_json(text):
    """Robustly extract a JSON list from model output."""
    text = text.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    # Try to find the first '[' in case of stray preamble
    bracket = text.find('[')
    if bracket > 0:
        text = text[bracket:]
    return json.loads(text)

def get_ai_recommendations(zipcode, mood, day_context, taste_pref):
    if not processing_model:
        st.error(f"⚠️ AI model not available: {gemini_error}")
        return []

    prompt = f"""Act as a beer sommelier. Suggest 3 beers based on:
Zip: {str(zipcode)[:5]}, Mood: {str(mood)[:35]}, Day: {str(day_context)[:35]}, Taste: {str(taste_pref)[:35]}.

Return ONLY a valid JSON array of 3 objects:
[{{"name": "Beer Name", "brand": "Brand Name", "calories": "150", "abv": "5.5%", "ibu": "45", "taste": "Crisp and citrusy with a hoppy finish", "food_pairing": "Grilled chicken, spicy tacos, sharp cheddar", "description": "A crisp and refreshing beer perfect for relaxing", "price_range": "$$", "where_to_buy": "Total Wine, BevMo"}}]

No markdown, no code blocks, no explanations. Just the JSON array."""

    try:
        response = processing_model.generate_content(prompt)
        if not response or not response.text:
            st.error("⚠️ API returned empty response")
            return []

        beers = _parse_beer_json(response.text)
        if not isinstance(beers, list) or len(beers) == 0:
            st.error("⚠️ API returned invalid format")
            return []

        for beer in beers:
            ensure_beer_image(beer)
        return beers

    except json.JSONDecodeError as e:
        st.error(f"⚠️ Failed to parse AI response as JSON: {str(e)}")
        return []
    except Exception as e:
        st.error(f"⚠️ Error: {type(e).__name__} - {str(e)}")
        return []

def get_brand_search_recommendations(zipcode, brand_query):
    if not processing_model:
        st.error(f"⚠️ AI model not available: {gemini_error}")
        return []

    prompt = f"""Act as a beer sommelier. The user is looking for "{brand_query}" or similar beers near zipcode {zipcode}.

Return 3 relevant options. If the exact beer is unlikely locally, still include it with "available_locally": false. For locally available alternatives set "available_locally": true.

Return ONLY a valid JSON array of 3 objects:
[{{"name": "Beer Name", "brand": "Brand Name", "calories": "150", "abv": "5.5%", "ibu": "45", "taste": "Crisp and citrusy with a hoppy finish", "food_pairing": "Pizza, burgers, spicy wings", "description": "A crisp and refreshing beer", "price_range": "$$", "where_to_buy": "Total Wine, BevMo", "available_locally": true}}]

No markdown, no code blocks, no explanations. Just the JSON array."""

    try:
        response = processing_model.generate_content(prompt)
        if not response or not response.text:
            st.error("⚠️ API returned empty response")
            return []

        beers = _parse_beer_json(response.text)
        if not isinstance(beers, list) or len(beers) == 0:
            st.error("⚠️ API returned invalid or empty results")
            return []

        for beer in beers:
            ensure_beer_image(beer)
        return beers

    except json.JSONDecodeError as e:
        st.error(f"⚠️ Failed to parse AI response: {str(e)}")
        return []
    except Exception as e:
        st.error(f"⚠️ Error: {type(e).__name__} - {str(e)}")
        return []

def get_non_alcoholic_recommendations(zipcode):
    if not processing_model:
        st.error(f"⚠️ AI model not available: {gemini_error}")
        return []

    prompt = f"""Act as a beer sommelier. The user wants non-alcoholic beers near zipcode {zipcode}.

Return ONLY a valid JSON array of 3 objects:
[{{"name": "Beer Name", "brand": "Brand Name", "calories": "50", "abv": "0.0%", "ibu": "20", "taste": "Light and refreshing with subtle malt sweetness", "food_pairing": "Salads, grilled fish, light appetizers", "description": "A refreshing non-alcoholic option", "price_range": "$$", "where_to_buy": "Total Wine, Whole Foods"}}]

No markdown, no code blocks, no explanations. Just the JSON array."""

    try:
        response = processing_model.generate_content(prompt)
        if not response or not response.text:
            st.error("⚠️ API returned empty response")
            return []

        beers = _parse_beer_json(response.text)
        if not isinstance(beers, list) or len(beers) == 0:
            st.error("⚠️ API returned invalid or empty results")
            return []

        for beer in beers:
            ensure_beer_image(beer)
        return beers

    except json.JSONDecodeError as e:
        st.error(f"⚠️ Failed to parse AI response: {str(e)}")
        return []
    except Exception as e:
        st.error(f"⚠️ Error: {type(e).__name__} - {str(e)}")
        return []

# =============================================================
# BEER CARD RENDERING
# =============================================================
def render_beer_card_html(name, brand, abv, calories, price_range,
                          description, where_to_buy,
                          ibu="", taste="", food_pairing="",
                          available_locally=True):
    unavailable_class = "" if available_locally else " unavailable"
    unavailable_badge = (
        "" if available_locally
        else '<span class="unavailable-badge">* Not near you</span>'
    )

    ibu_html = (f'<div class="beer-detail-row"><div class="beer-detail-label">IBU — Bitterness</div>'
                f'<div class="beer-detail-value">{ibu}</div></div>') if ibu else ""
    taste_html = (f'<div class="beer-detail-row"><div class="beer-detail-label">Taste Profile</div>'
                  f'<div class="beer-detail-value">{taste}</div></div>') if taste else ""
    food_html = (f'<div class="beer-detail-row"><div class="beer-detail-label">Food Pairing</div>'
                 f'<div class="beer-detail-value">{food_pairing}</div></div>') if food_pairing else ""

    return (
        f'<div class="beer-card{unavailable_class}">'
        f'{unavailable_badge}'
        f'<div class="beer-title">{name}</div>'
        f'<div class="beer-brand">{brand}</div>'
        f'<div class="beer-metrics">'
        f'<div class="metric-box"><div class="metric-value">{abv}</div><div class="metric-label">ABV</div></div>'
        f'<div class="metric-box"><div class="metric-value">{calories}</div><div class="metric-label">Cals</div></div>'
        f'<div class="metric-box"><div class="metric-value">{price_range}</div><div class="metric-label">Price</div></div>'
        f'</div>'
        f'<div class="beer-detail-row"><div class="beer-detail-label">About</div><div class="beer-detail-value">{description}</div></div>'
        f'{ibu_html}'
        f'{taste_html}'
        f'{food_html}'
        f'<div class="beer-detail-row"><div class="beer-detail-label">📍 Where to Buy</div><div class="beer-detail-value">{where_to_buy}</div></div>'
        f'</div>'
    )

def render_bar_card(bar):
    google_maps_link = (
        f"https://www.google.com/maps/search/?api=1"
        f"&query={bar['lat']},{bar['lng']}"
        f"&query_place_id={bar['place_id']}"
    )
    st.markdown(f"""
    <div class="bar-card">
        <div class="bar-name">🍻 {bar['name']}</div>
        <div class="bar-address">📍 {bar['address']}</div>
        <div class="bar-rating">⭐ {bar['rating']} · {bar['price_level']}</div>
    </div>
    """, unsafe_allow_html=True)
    st.markdown(f"[📍 Open in Google Maps]({google_maps_link})")

def render_beer_with_bars(beer, zipcode, unique_key):
    img_bytes = beer.get("image_bytes")
    if img_bytes:
        st.image(img_bytes, use_container_width=True)

    card_html = render_beer_card_html(
        beer.get("name", "Unknown"),
        beer.get("brand", "Craft Beer"),
        beer.get("abv", "?"),
        beer.get("calories", "?"),
        beer.get("price_range", "$"),
        beer.get("description", ""),
        beer.get("where_to_buy", "Check Local Stores"),
        ibu=beer.get("ibu", ""),
        taste=beer.get("taste", ""),
        food_pairing=beer.get("food_pairing", ""),
        available_locally=beer.get("available_locally", True),
    )
    st.markdown(card_html, unsafe_allow_html=True)

    with st.expander(f"🍻 Bars near you serving {beer.get('name')}"):
        lat, lng = zipcode_to_coords(zipcode)
        if lat and lng:
            with st.spinner("🤖 AI agents researching bars that serve this beer..."):
                bars = find_bars_serving_beer(lat, lng, beer.get('name'), beer.get('brand', ''), zipcode)

            if bars:
                st.markdown(
                    f'<p style="color:#ffd165;font-size:0.88rem;margin-bottom:12px;">'
                    f'🎯 Bars serving {beer.get("name")} near you:</p>',
                    unsafe_allow_html=True
                )
                for bar in bars:
                    with st.container():
                        render_bar_card(bar)
            else:
                st.info("🤖 Our AI agents couldn't find bars serving this specific beer nearby. Check 'Where to Buy' above for retail options.")
        else:
            st.warning("Unable to locate bars for this zipcode. Please ensure your Google Geocoding API is configured.")

# =============================================================
# SESSION STATE
# =============================================================
def init_session_state():
    defaults = {
        'step': 0,
        'user_data': {
            'name': '', 'zipcode': '', 'mood': '',
            'brand_query': None, 'day': '', 'taste': '',
            'search_type': None
        },
        'rec_beers': [],
        'saved_beers': [],
        'show_debug': False,
        'feedback_submitted': False,
        'voice_transcription': '',
        'voice_search_mode': False,   # True when voice tab selected inside brand screen
        'zip_change_input': '',
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_session_state()

# =============================================================
# MAIN
# =============================================================
def main():
    inject_mobile_css()
    render_app_bar()

    if st.sidebar.button("Toggle Debug"):
        st.session_state.show_debug = not st.session_state.show_debug
        st.rerun()

    render_debug_panel()

    # ── Back / My List / Change Zipcode navigation row ──────
    if st.session_state.step > 0 and st.session_state.step != 5:
        if st.session_state.step == 3:
            # Results screen — back + change zipcode
            col_back, col_zip, col_list = st.columns([1, 3, 1])
            with col_back:
                if st.button("←", key="back_btn"):
                    st.session_state.step = 1
                    st.session_state.rec_beers = []
                    st.session_state.user_data['brand_query'] = None
                    st.session_state.user_data['mood'] = ''
                    st.session_state.user_data['search_type'] = None
                    st.session_state.voice_transcription = ""
                    st.rerun()

            with col_zip:
                new_zip = st.text_input(
                    "Change zipcode",
                    placeholder="Enter new zip",
                    max_chars=5,
                    key="zip_change_field",
                    label_visibility="collapsed"
                )
                if new_zip and len(new_zip.strip()) == 5:
                    is_valid, clean = validate_zipcode(new_zip)
                    if is_valid and clean != st.session_state.user_data['zipcode']:
                        st.session_state.user_data['zipcode'] = clean
                        st.session_state.rec_beers = []
                        # Re-run the same search with new zip
                        search_type = st.session_state.user_data.get('search_type')
                        with st.spinner("Searching with new zipcode..."):
                            if search_type == 'non_alcoholic':
                                beers = get_non_alcoholic_recommendations(clean)
                            elif st.session_state.user_data.get('brand_query'):
                                beers = get_brand_search_recommendations(clean, st.session_state.user_data['brand_query'])
                            else:
                                beers = get_ai_recommendations(
                                    clean,
                                    st.session_state.user_data.get('mood', ''),
                                    st.session_state.user_data.get('day', ''),
                                    st.session_state.user_data.get('taste', '')
                                )
                        st.session_state.rec_beers = beers
                        st.rerun()

            with col_list:
                if st.session_state.saved_beers:
                    if st.button("My List", key="star_btn"):
                        st.session_state.step = 4
                        st.rerun()

        else:
            # All other steps — simple back + optional My List
            c1, c2, c3 = st.columns([1, 2, 1])
            with c1:
                if st.button("←", key="back_btn"):
                    if st.session_state.step == 4:
                        st.session_state.step = 1
                        st.rerun()
                    elif st.session_state.step == 2 and st.session_state.user_data.get('search_type') in ['brand', 'non_alcoholic']:
                        st.session_state.step = 1
                        st.session_state.user_data['brand_query'] = None
                        st.session_state.user_data['search_type'] = None
                        st.session_state.voice_transcription = ""
                        st.rerun()
                    elif st.session_state.step == 1.5:
                        st.session_state.step = 1
                        st.session_state.user_data['brand_query'] = None
                        st.session_state.user_data['search_type'] = None
                        st.session_state.voice_transcription = ""
                        st.session_state.voice_search_mode = False
                        st.rerun()
                    else:
                        st.session_state.step = max(0, st.session_state.step - 1)
                        st.rerun()

            with c3:
                if st.session_state.saved_beers and st.session_state.step != 4:
                    if st.button("My List", key="star_btn"):
                        st.session_state.step = 4
                        st.rerun()

    # ===========================================================
    # STEP 0: Login
    # ===========================================================
    if st.session_state.step == 0:
        st.markdown('<div style="height: 40px;"></div>', unsafe_allow_html=True)
        render_logo()
        st.markdown('<h1 class="big-greeting">Beer Finder</h1>', unsafe_allow_html=True)
        st.markdown('<p class="gold-text">Your pocket sommelier.</p>', unsafe_allow_html=True)

        if gemini_error:
            st.warning(f"⚠️ {gemini_error}")
            st.info("The app may not work correctly. Please check your API configuration.")

        st.markdown('<div style="height: 24px;"></div>', unsafe_allow_html=True)

        with st.form("login_form", clear_on_submit=False):
            name_val = st.text_input("Your name? *", placeholder="Enter your name", max_chars=35)
            zip_val  = st.text_input("Where ya at? *", placeholder="e.g. 90210", max_chars=5)
            submitted = st.form_submit_button("ENTER")

            if submitted:
                if not name_val or not name_val.strip():
                    st.error("❌ Name is required")
                elif not zip_val or not zip_val.strip():
                    st.error("❌ Zipcode is required")
                else:
                    is_valid, result = validate_zipcode(zip_val)
                    if not is_valid:
                        st.error(f"❌ {result}")
                    else:
                        st.session_state.user_data['name']    = name_val.strip()[:35]
                        st.session_state.user_data['zipcode'] = result
                        st.session_state.step = 1
                        st.rerun()

        render_bottom_nav("home")
        render_footer()

    # ===========================================================
    # STEP 1: Search Type Selection
    # ===========================================================
    elif st.session_state.step == 1:
        greet, time_str = get_greeting(st.session_state.user_data['zipcode'])
        name = st.session_state.user_data.get('name', 'Friend')

        gif_path = os.path.join(os.path.dirname(__file__), "static", "images", "beer.gif.gif")
        encoded = load_image_as_base64(gif_path)

        if encoded:
            st.markdown(f"""
                <div style="display: flex; justify-content: center; margin-bottom: 20px;">
                    <img src="data:image/gif;base64,{encoded}"
                         style="width: 100%; max-height: 220px; object-fit: cover;
                                border-radius: 16px; opacity: 0.85;">
                </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown('<div style="text-align:center;font-size:5rem;">🍺</div>', unsafe_allow_html=True)

        st.markdown(f'<div class="big-greeting">{greet}, {name}.</div>', unsafe_allow_html=True)
        if time_str:
            st.markdown(f'<p class="gold-text">It is currently {time_str}</p>', unsafe_allow_html=True)

        st.markdown('<div style="height: 20px;"></div>', unsafe_allow_html=True)
        st.markdown('<p class="gold-text" style="font-size: 1rem; margin-bottom: 16px;">How would you like to search?</p>', unsafe_allow_html=True)

        col1, col2 = st.columns(2)
        with col1:
            if st.button("🎭 BY MOOD", key="mood_btn", use_container_width=True):
                st.session_state.user_data['search_type'] = 'mood'
                st.session_state.step = 1.5
                st.rerun()

        with col2:
            if st.button("🍺 SPECIFIC BEER", key="brand_btn", use_container_width=True):
                st.session_state.user_data['search_type'] = 'brand'
                st.session_state.voice_search_mode = False
                st.session_state.step = 1.5
                st.rerun()

        # Only one row for the remaining option
        col3, col4 = st.columns(2)
        with col3:
            if st.button("🚫🍺 NON-ALCOHOLIC", key="non_alc_btn", use_container_width=True):
                st.session_state.user_data['search_type'] = 'non_alcoholic'
                st.session_state.step = 2
                st.rerun()
        # col4 intentionally left blank (voice removed from top level)

        render_bottom_nav("search")
        render_footer()

    # ===========================================================
    # STEP 1.5: Input Collection
    # ===========================================================
    elif st.session_state.step == 1.5:
        greet, _ = get_greeting(st.session_state.user_data['zipcode'])
        name = st.session_state.user_data.get('name', 'Friend')
        st.markdown(f'<div class="big-greeting">{greet}, {name}.</div>', unsafe_allow_html=True)

        search_type = st.session_state.user_data.get('search_type')

        # ── Mood input ──────────────────────────────────────
        if search_type == 'mood':
            st.markdown('<div style="height: 16px;"></div>', unsafe_allow_html=True)
            with st.form("mood_form", clear_on_submit=False):
                mood = st.text_input("Vibe check", placeholder="Relaxed, Hyped, Tired...", max_chars=35)
                if st.form_submit_button("NEXT"):
                    if mood:
                        st.session_state.user_data['mood'] = mood
                        st.session_state.user_data['brand_query'] = None
                        st.session_state.step = 2
                        st.rerun()
                    else:
                        st.error("Please describe your mood")

        # ── Specific Beer — with inline voice option ─────────
        elif search_type == 'brand':
            st.markdown('<div style="height: 12px;"></div>', unsafe_allow_html=True)

            # Toggle between type and voice
            mode = st.session_state.voice_search_mode

            col_type, col_voice = st.columns(2)
            with col_type:
                if st.button(
                    "⌨️ TYPE" if mode else "⌨️ TYPE ✓",
                    key="mode_type_btn",
                    use_container_width=True
                ):
                    st.session_state.voice_search_mode = False
                    st.rerun()
            with col_voice:
                if st.button(
                    "🎤 VOICE ✓" if mode else "🎤 VOICE",
                    key="mode_voice_btn",
                    use_container_width=True
                ):
                    st.session_state.voice_search_mode = True
                    st.rerun()

            st.markdown('<div style="height: 12px;"></div>', unsafe_allow_html=True)

            # ── TYPE mode ──
            if not st.session_state.voice_search_mode:
                with st.form("brand_form", clear_on_submit=False):
                    brand_query = st.text_input(
                        "Enter your beer of choice",
                        placeholder="Guinness, West Coast IPA...",
                        max_chars=35
                    )
                    if st.form_submit_button("FIND IT"):
                        if brand_query:
                            st.session_state.user_data['brand_query'] = brand_query
                            st.session_state.user_data['mood'] = None
                            st.session_state.step = 2
                            st.rerun()
                        else:
                            st.error("Please enter a beer name or style")

            # ── VOICE mode ──
            else:
                st.markdown(
                    '<p class="gold-text" style="margin-bottom:8px;">Tap the mic and speak your beer query</p>',
                    unsafe_allow_html=True
                )

                audio_value = None
                audio_bytes = None
                audio_mime  = "audio/wav"

                # st.audio_input available in Streamlit >= 1.43
                has_audio_input = hasattr(st, 'audio_input')

                if has_audio_input:
                    try:
                        audio_value = st.audio_input(
                            "Speak your search (e.g. 'light IPA' or 'something hoppy')",
                            key="voice_recorder"
                        )
                        if audio_value is not None:
                            audio_bytes = audio_value.read()
                            audio_mime  = "audio/wav"
                    except Exception as e:
                        debug_print(f"audio_input widget error: {e}", "WARNING")
                        has_audio_input = False

                if not has_audio_input:
                    uploaded = st.file_uploader(
                        "Upload audio file (WAV, MP3, M4A, OGG, WEBM)",
                        type=["wav", "mp3", "m4a", "ogg", "webm"],
                        key="voice_uploader"
                    )
                    if uploaded:
                        audio_bytes = uploaded.read()
                        audio_mime  = uploaded.type or "audio/wav"

                # Auto-transcribe as soon as audio is received
                if audio_bytes:
                    with st.spinner("🎤 Transcribing your voice..."):
                        transcription, err = transcribe_audio_with_gemini(audio_bytes, mime_type=audio_mime)

                    if err:
                        st.error(f"❌ {err}")
                        st.markdown(
                            '<p style="color:#9b8f79;font-size:0.82rem;margin-top:6px;">'
                            'You can also switch to ⌨️ TYPE mode above.</p>',
                            unsafe_allow_html=True
                        )
                    elif transcription:
                        # Show what was heard
                        st.markdown(f"""
                            <div class="voice-heard-bubble">
                                <div class="voice-heard-label">Searching for:</div>
                                <div class="voice-heard-text">"{transcription}"</div>
                            </div>
                        """, unsafe_allow_html=True)

                        # Immediately run the search
                        with st.spinner(f"Searching for {transcription}..."):
                            beers = get_brand_search_recommendations(
                                st.session_state.user_data['zipcode'],
                                transcription
                            )
                        st.session_state.user_data['brand_query'] = transcription
                        st.session_state.user_data['search_type'] = 'brand'
                        st.session_state.user_data['mood'] = None
                        st.session_state.user_data['day'] = 'Voice Search'
                        st.session_state.user_data['taste'] = 'Voice Search'
                        st.session_state.rec_beers = beers
                        st.session_state.voice_search_mode = False
                        st.session_state.step = 3
                        st.rerun()
                else:
                    st.markdown(
                        '<p style="color:#9b8f79;font-size:0.82rem;margin-top:8px;">'
                        'Press the microphone button above to start recording.</p>',
                        unsafe_allow_html=True
                    )

        render_bottom_nav("search")
        render_footer()

    # ===========================================================
    # STEP 2: Context / Direct Search
    # ===========================================================
    elif st.session_state.step == 2:
        if st.session_state.user_data.get('search_type') == 'non_alcoholic':
            st.session_state.user_data.update({'day': 'Non-Alcoholic Search', 'taste': 'Non-Alcoholic Search'})
            with st.spinner("Finding non-alcoholic beers..."):
                beers = get_non_alcoholic_recommendations(st.session_state.user_data['zipcode'])
                st.session_state.rec_beers = beers
                st.session_state.step = 3
                st.rerun()

        elif st.session_state.user_data.get('brand_query'):
            brand = st.session_state.user_data.get('brand_query')
            st.session_state.user_data.update({'day': 'Specific Search', 'taste': 'Specific Search'})
            with st.spinner(f"Searching for {brand}..."):
                beers = get_brand_search_recommendations(st.session_state.user_data['zipcode'], brand)
                st.session_state.rec_beers = beers
                st.session_state.step = 3
                st.rerun()

        else:
            st.markdown('<h3 class="gold-text">Tell me more...</h3>', unsafe_allow_html=True)
            with st.form("context", clear_on_submit=False):
                day   = st.text_input("What kind of day did you have?", placeholder="Long work day, celebrating...", max_chars=35)
                taste = st.text_input("What hits right?", placeholder="Hoppy, Sweet, Dark, Surprise me...", max_chars=35)

                if st.form_submit_button("FIND MY BEER"):
                    if not day or not taste:
                        st.error("Please fill in both fields")
                    else:
                        st.session_state.user_data.update({'day': day[:35], 'taste': taste[:35]})
                        with st.spinner("Pouring recommendations..."):
                            beers = get_ai_recommendations(
                                st.session_state.user_data['zipcode'],
                                st.session_state.user_data['mood'],
                                day[:35],
                                taste[:35]
                            )
                            st.session_state.rec_beers = beers
                            st.session_state.step = 3
                            st.rerun()

            render_bottom_nav("search")
            render_footer()

    # ===========================================================
    # STEP 3: Recommendations
    # ===========================================================
    elif st.session_state.step == 3:
        st.markdown('<h3 class="gold-text">Top Picks For You</h3>', unsafe_allow_html=True)

        if not st.session_state.rec_beers:
            st.markdown("""
                <div style="background:#121c2a;padding:30px;border-radius:16px;
                            margin:32px 0;text-align:center;
                            border:1px solid rgba(255,209,101,0.09);">
                    <p style="color:#ffd165;font-size:1.1rem;margin-bottom:16px;">
                        No recommendations found. Please try a different search.
                    </p>
                </div>
            """, unsafe_allow_html=True)

            col1, col2 = st.columns(2)
            with col1:
                if st.button("TRY AGAIN", key="try_again_btn", use_container_width=True):
                    st.session_state.step = 1
                    st.session_state.user_data['search_type'] = None
                    st.session_state.rec_beers = []
                    st.rerun()
            with col2:
                if st.button("GO HOME", key="go_home_btn", use_container_width=True):
                    st.session_state.step = 0
                    st.session_state.user_data = {
                        'name': '', 'zipcode': '', 'mood': '',
                        'brand_query': None, 'day': '', 'taste': '',
                        'search_type': None
                    }
                    st.session_state.rec_beers = []
                    st.rerun()
        else:
            for idx, beer in enumerate(st.session_state.rec_beers):
                unique_key = f"rec_{idx}_{beer.get('name', 'unknown').replace(' ', '_')}"
                render_beer_with_bars(beer, st.session_state.user_data['zipcode'], unique_key)

                saved = any(b['name'] == beer['name'] for b in st.session_state.saved_beers)
                if not saved:
                    if st.button(f"SAVE", key=f"save_{unique_key}", use_container_width=True):
                        st.session_state.saved_beers.append(beer)
                        log_beer_selection(
                            st.session_state.user_data['name'],
                            beer.get('name', 'Unknown'),
                            beer.get('brand', 'Unknown'),
                            st.session_state.user_data.get('search_type', 'unknown'),
                            st.session_state.user_data.get('mood')
                        )
                        st.rerun()
                else:
                    st.button("SAVED ✓", disabled=True, key=f"saved_{unique_key}", use_container_width=True)

        render_bottom_nav("search")
        render_footer()

    # ===========================================================
    # STEP 4: Saved Beers
    # ===========================================================
    elif st.session_state.step == 4:
        st.markdown('<h3 class="gold-text">Your Saved Brews</h3>', unsafe_allow_html=True)

        if not st.session_state.saved_beers:
            st.markdown("""
                <div style="background:#121c2a;padding:30px;border-radius:16px;
                            margin:32px 0;text-align:center;
                            border:1px solid rgba(255,209,101,0.09);">
                    <p style="color:#ffd165;font-size:1.1rem;margin-bottom:16px;">
                        No beers saved yet. Go back and add some!
                    </p>
                </div>
            """, unsafe_allow_html=True)
        else:
            for i, beer in enumerate(st.session_state.saved_beers):
                unique_key = f"saved_{i}_{beer.get('name', 'unknown').replace(' ', '_')}"
                render_beer_with_bars(beer, st.session_state.user_data['zipcode'], unique_key)
                if st.button("REMOVE", key=f"remove_{unique_key}", use_container_width=True):
                    st.session_state.saved_beers.pop(i)
                    st.rerun()

        render_bottom_nav("saved")
        render_footer()

    # ===========================================================
    # STEP 5: Feedback
    # ===========================================================
    elif st.session_state.step == 5:
        st.markdown('<h3 class="gold-text">Feedback / Feature Request</h3>', unsafe_allow_html=True)

        if st.session_state.feedback_submitted:
            username = st.session_state.user_data.get('name', 'User')
            st.markdown(f"""
                <div style="background:#121c2a;padding:30px;border-radius:16px;
                            margin:32px 0;text-align:center;">
                    <p style="color:#4ae176;font-size:1.2rem;">
                        ✓ Thank you, {username}! Your feedback was received.
                    </p>
                </div>
            """, unsafe_allow_html=True)

            import time
            time.sleep(2)
            st.session_state.feedback_submitted = False
            st.session_state.step = 1
            st.rerun()
        else:
            feedback_text = st.text_area(
                "Share your thoughts, suggestions, or feature requests",
                placeholder="What would make Golden Draught better?",
                max_chars=3000,
                height=200,
                key="feedback_textarea"
            )

            col1, col2, col3 = st.columns([1, 2, 1])
            with col2:
                if st.button("SUBMIT FEEDBACK", key="feedback_submit_btn", use_container_width=True):
                    if feedback_text and feedback_text.strip():
                        username = st.session_state.user_data.get('name', 'Anonymous')
                        save_feedback(username, feedback_text)   # always returns True now
                        st.session_state.feedback_submitted = True
                        st.rerun()
                    else:
                        st.error("Please write some feedback before submitting.")

        render_bottom_nav("feedback")


if __name__ == "__main__":
    main()