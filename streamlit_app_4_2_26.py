import sys
import traceback
import logging

logging.basicConfig(level=logging.DEBUG)

try:
    # paste all your existing imports here
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
    from huggingface_hub import HfApi, hf_hub_download
    # ... rest of your imports
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

# Optional: streamlit-mic-recorder (install via packages.txt on HF Spaces)
try:
    from streamlit_mic_recorder import mic_recorder
    MIC_RECORDER_AVAILABLE = True
except ImportError:
    MIC_RECORDER_AVAILABLE = False

st.set_page_config(
    page_title="Golden Draught",
    page_icon="🍺",
    layout="centered",
    initial_sidebar_state="collapsed",
)

STATIC_IMG_DIR = os.path.join(os.path.dirname(__file__), "static", "images")
LOG_DIR        = os.path.join(os.path.dirname(__file__), "log")
FEEDBACK_DIR   = os.path.join(os.path.dirname(__file__), "feedback")
for d in (STATIC_IMG_DIR, LOG_DIR, FEEDBACK_DIR):
    os.makedirs(d, exist_ok=True)

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
HF_TOKEN                 = os.getenv("HF_TOKEN")
HF_DATASET_REPO          = "mashomashi/beer_data"

# ── debug ────────────────────────────────────────────────────────────────────
def debug_print(msg, level="INFO"):
    c = {"INFO": "\033[94m", "SUCCESS": "\033[92m", "WARNING": "\033[93m",
         "ERROR": "\033[91m", "RESET": "\033[0m"}
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"{c.get(level, c['INFO'])}[{level}] [{ts}] {msg}{c['RESET']}", file=sys.stderr)

# ── logging / feedback ───────────────────────────────────────────────────────
def log_beer_selection(username, beer_name, brand, search_type, mood=None):
    if not HF_TOKEN:
        return
    try:
        import tempfile
        api = HfApi()
        ts  = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            lp = hf_hub_download(repo_id=HF_DATASET_REPO, filename="log.txt",
                                  repo_type="dataset", token=HF_TOKEN)
            with open(lp, encoding="utf-8") as f:
                existing = f.read()
        except Exception:
            existing = ""
        labels = {"mood": f"By Mood ({mood})", "non_alcoholic": "Non-Alcoholic",
                  "voice": "By Voice"}
        label = labels.get(search_type, "Specific Beer")
        if search_type == "mood" and not mood:
            label = "By Mood"
        entry = f"[{ts}] User: {username} | Beer: {beer_name} ({brand}) | Search: {label}\n"
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False, suffix=".txt") as f:
            f.write(entry + existing); tmp = f.name
        try:
            api.upload_file(path_or_fileobj=tmp, path_in_repo="log.txt",
                            repo_id=HF_DATASET_REPO, repo_type="dataset", token=HF_TOKEN)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
    except Exception as e:
        debug_print(f"Log error: {e}", "ERROR")


def save_feedback(username, feedback_text):
    ts      = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    content = (f"Feedback from: {username}\n"
               f"Date: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
               + "=" * 50 + "\n\n" + feedback_text)
    if HF_TOKEN:
        try:
            import tempfile
            api = HfApi()
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False, suffix=".txt") as f:
                f.write(content); tmp = f.name
            try:
                api.upload_file(path_or_fileobj=tmp,
                                path_in_repo=f"feedback/{username}_{ts}.txt",
                                repo_id=HF_DATASET_REPO, repo_type="dataset", token=HF_TOKEN)
                return True
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)
        except Exception as e:
            debug_print(f"HF feedback failed, local fallback: {e}", "WARNING")
    try:
        os.makedirs(FEEDBACK_DIR, exist_ok=True)
        with open(os.path.join(FEEDBACK_DIR, f"{username}_{ts}.txt"), "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        debug_print(f"Local feedback failed: {e}", "ERROR")
    return True  # always succeed from UI perspective

# ── Gemini init — required model order ──────────────────────────────────────
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

# ── validation ───────────────────────────────────────────────────────────────
def validate_zipcode(zipcode):
    if not zipcode:
        return False, "Please enter a zipcode"
    clean = "".join(filter(str.isdigit, zipcode))
    if len(clean) != 5:
        return False, "Zipcode must be exactly 5 digits"
    if not (501 <= int(clean) <= 99950):
        return False, "Please enter a valid US zipcode"
    return True, clean

# ── CSS ──────────────────────────────────────────────────────────────────────
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

        /* ── BAR CARD ── */
        .bar-card {
            background: var(--bg-card-low); padding: 14px; margin: 10px 0;
            border-radius: 12px; border-left: 3px solid var(--accent);
        }
        .bar-name { font-family: 'Epilogue', sans-serif; font-weight: 800; color: #d9e3f6; font-size: 1rem; margin-bottom: 5px; }
        .bar-address { color: var(--text-sub); font-size: 0.82rem; margin: 4px 0; }
        .bar-rating  { color: var(--accent); margin-top: 6px; font-size: 0.85rem; }

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

# ── image helpers ─────────────────────────────────────────────────────────────
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
    st.markdown(f"""
    <div class="debug-panel">
        <strong>🔧 Debug</strong><br>
        • Gemini: {GENAI_AVAILABLE} | Key: {'✓' if GEMINI_API_KEY else '✗'} |
          Places: {'✓' if GOOGLE_PLACES_API_KEY else '✗'} |
          Model: {'✓' if processing_model else '✗'}<br>
        • Error: {gemini_error or 'None'}<br>
        • Step: {st.session_state.step} | Search: {st.session_state.user_data.get('search_type','—')}<br>
        • mic_recorder: {MIC_RECORDER_AVAILABLE} | audio_input: {hasattr(st,'audio_input')}
    </div>""", unsafe_allow_html=True)

# ── DST-aware greeting — NOT cached so time is always live ───────────────────
def get_greeting(zipcode):
    """
    Returns (greeting, time_str) for the given US zip.
    Applies US DST rule (2nd Sun March → 1st Sun November) to avoid
    the 1-hour-behind bug that occurred with a fixed standard offset.
    """
    greeting = "Hello"
    time_str  = ""
    try:
        first = int(str(zipcode)[0])
        # Standard (winter) UTC offset by zip prefix
        if   first in [0, 1, 2, 3]: std = -5   # Eastern
        elif first in [4, 5, 6]:    std = -6   # Central
        elif first == 7:             std = -7   # Mountain
        else:                        std = -8   # Pacific

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

# ── geocoding / image ─────────────────────────────────────────────────────────
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
    """Returns (city, state_abbr) for display below the zip input."""
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
    """Legacy wrapper used by bar agents (city name only)."""
    city, _ = city_state_from_zip(zipcode)
    return city

# ── bar-finding agents ────────────────────────────────────────────────────────
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

def verify_bars_places(bar_names, lat, lng, radius=8000):
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
def find_bars(lat, lng, beer_name, brand, zipcode):
    city  = city_from_zip(zipcode)
    webs  = web_search_bars(beer_name, brand, zipcode, city)
    if not webs: return []
    names = ai_extract_bar_names(webs, beer_name, city)
    if not names: return []
    return verify_bars_places(names, lat, lng)

# ── beer image ────────────────────────────────────────────────────────────────
def attach_image(beer):
    raw_url = beer.get("image")
    if not raw_url:
        raw_url = cse_image_search(f"{beer.get('name','')} {beer.get('brand','')} beer bottle can")
    beer["image_bytes"] = _fetch_img_bytes(raw_url) if raw_url else None
    beer["image"]       = None
    return beer

# ── audio transcription ───────────────────────────────────────────────────────
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

# ── JSON parse ────────────────────────────────────────────────────────────────
def parse_beer_json(text):
    text = text.strip()
    if "```json" in text: text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:   text = text.split("```")[1].split("```")[0].strip()
    i = text.find("[")
    if i > 0: text = text[i:]
    return json.loads(text)

# ── AI recommendation wrappers ────────────────────────────────────────────────
_BEER_SCHEMA = ('{"name":"Beer Name","brand":"Brand Name","calories":"150","abv":"5.5%","ibu":"45",'
                '"taste":"Crisp and citrusy","food_pairing":"Grilled chicken, tacos",'
                '"description":"A crisp beer","price_range":"$$","where_to_buy":"Total Wine, BevMo"}')

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

def ai_mood_recs(zipcode, mood, day, taste):
    return _call_ai(
        f"Act as a beer sommelier. Suggest 3 beers based on:\n"
        f"Zip:{zipcode[:5]}, Mood:{mood[:35]}, Day:{day[:35]}, Taste:{taste[:35]}.\n"
        f"Return ONLY a JSON array of 3: [{_BEER_SCHEMA}]\nNo markdown.")

def ai_brand_recs(zipcode, query):
    schema = _BEER_SCHEMA.rstrip("}") + ',"available_locally":true}'
    return _call_ai(
        f'Act as a beer sommelier. User wants "{query}" near {zipcode}.\n'
        f"Return 3 options. Unavailable locally → available_locally:false.\n"
        f"Return ONLY a JSON array of 3: [{schema}]\nNo markdown.")

def ai_na_recs(zipcode):
    schema = _BEER_SCHEMA.replace('"5.5%"', '"0.0%"').replace('"150"', '"50"')
    return _call_ai(
        f"Act as a beer sommelier. User wants non-alcoholic beers near {zipcode}.\n"
        f"Return ONLY a JSON array of 3: [{schema}]\nNo markdown.")

# ── card rendering ────────────────────────────────────────────────────────────
def beer_card_html(beer):
    name             = beer.get("name", "Unknown")
    brand            = beer.get("brand", "Craft Beer")
    abv              = beer.get("abv", "?")
    calories         = beer.get("calories", "?")
    price_range      = beer.get("price_range", "$")
    description      = beer.get("description", "")
    where_to_buy     = beer.get("where_to_buy", "Check Local Stores")
    ibu              = beer.get("ibu", "")
    taste            = beer.get("taste", "")
    food_pairing     = beer.get("food_pairing", "")
    available_locally = beer.get("available_locally", True)

    cls    = "beer-card" + ("" if available_locally else " unavailable")
    badge  = "" if available_locally else '<span class="unavailable-badge">* Not near you</span>'
    extras = ""
    if ibu:         extras += f'<div class="beer-detail-row"><div class="beer-detail-label">IBU — Bitterness</div><div class="beer-detail-value">{ibu}</div></div>'
    if taste:       extras += f'<div class="beer-detail-row"><div class="beer-detail-label">Taste Profile</div><div class="beer-detail-value">{taste}</div></div>'
    if food_pairing:extras += f'<div class="beer-detail-row"><div class="beer-detail-label">Food Pairing</div><div class="beer-detail-value">{food_pairing}</div></div>'
    return (
        f'<div class="{cls}">{badge}'
        f'<div class="beer-title">{name}</div><div class="beer-brand">{brand}</div>'
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
    maps = (f"https://www.google.com/maps/search/?api=1"
            f"&query={bar['lat']},{bar['lng']}&query_place_id={bar['place_id']}")
    st.markdown(
        f'<div class="bar-card">'
        f'<div class="bar-name">🍻 {bar["name"]}</div>'
        f'<div class="bar-address">📍 {bar["address"]}</div>'
        f'<div class="bar-rating">⭐ {bar["rating"]} · {bar["price_level"]}</div>'
        f'</div>', unsafe_allow_html=True)
    st.markdown(f"[📍 Open in Google Maps]({maps})")

def render_beer_with_bars(beer, zipcode, key):
    if beer.get("image_bytes"):
        st.image(beer["image_bytes"], use_container_width=True)
    st.markdown(beer_card_html(beer), unsafe_allow_html=True)
    with st.expander(f"🍻 Bars near you serving {beer.get('name')}"):
        lat, lng = zip_to_coords(zipcode)
        if lat and lng:
            with st.spinner("🤖 AI agents researching bars…"):
                bars = find_bars(lat, lng, beer.get("name"), beer.get("brand",""), zipcode)
            if bars:
                st.markdown(f'<p style="color:#ffd165;font-size:0.88rem;margin-bottom:12px;">'
                            f'🎯 Bars serving {beer.get("name")} near you:</p>', unsafe_allow_html=True)
                for bar in bars:
                    render_bar(bar)
            else:
                st.info("🤖 Couldn't find bars serving this beer nearby. Check 'Where to Buy' above.")
        else:
            st.warning("Unable to locate bars for this zipcode.")

# ── voice input widget — works on local + HF Spaces ──────────────────────────
def render_voice_widget():
    """
    Returns (audio_bytes, mime_type) or (None, None).
    Priority:
      1. streamlit-mic-recorder  (best for HF Spaces / all browsers)
      2. st.audio_input          (Streamlit ≥ 1.43, works on Safari/HTTPS)
      3. st.file_uploader        (universal fallback)
    """
    audio_bytes = None
    mime_type   = "audio/wav"

    if MIC_RECORDER_AVAILABLE:
        st.markdown('<p class="gold-text" style="font-size:0.78rem;margin-bottom:4px;">🎤 Record your search</p>',
                    unsafe_allow_html=True)
        audio = mic_recorder(
            start_prompt="⏺ Record",
            stop_prompt="⏹ Stop",
            key="mic_rec",
        )
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

    # Always show file-upload fallback alongside mic widget
    if audio_bytes is None:
        up = st.file_uploader(
            "📎 Or upload audio (WAV · MP3 · M4A · OGG · WEBM)",
            type=["wav","mp3","m4a","ogg","webm"],
            key="voice_uploader",
        )
        if up:
            audio_bytes = up.read()
            mime_type   = up.type or "audio/wav"

    return audio_bytes, mime_type

# ── session state ─────────────────────────────────────────────────────────────
def init_state():
    defaults = {
        "step": 0,
        "user_data": {"name":"","zipcode":"","mood":"","brand_query":None,
                      "day":"","taste":"","search_type":None},
        "rec_beers":          [],
        "saved_beers":        [],
        "show_debug":         False,
        "feedback_submitted": False,
        "zip_location_label": "",   # e.g. "Santa Monica, CA"
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    inject_mobile_css()
    render_app_bar()

    if st.sidebar.button("Toggle Debug"):
        st.session_state.show_debug = not st.session_state.show_debug
        st.rerun()
    render_debug_panel()

    step = st.session_state.step
    ud   = st.session_state.user_data

    # ── nav row ───────────────────────────────────────────────────────────────
    if step > 0 and step != 5:
        if step == 3:
            cb, cz, cl = st.columns([1, 3, 1])
            with cb:
                if st.button("←", key="back_btn"):
                    st.session_state.step = 1
                    st.session_state.rec_beers = []
                    ud.update({"brand_query":None,"mood":"","search_type":None})
                    st.rerun()
            with cz:
                nz = st.text_input("zip", placeholder="Change zip", max_chars=5,
                                   key="zip_change_field", label_visibility="collapsed")
                cur_label = st.session_state.get("zip_location_label", "")
                if cur_label:
                    st.markdown(
                        f'<p style="color:#ffd165;font-size:0.65rem;text-align:center;'
                        f'font-family:Space Grotesk,sans-serif;letter-spacing:0.06em;'
                        f'margin:2px 0 0 0;">&#128205; {cur_label}</p>',
                        unsafe_allow_html=True)
                if nz and len(nz.strip()) == 5:
                    ok, clean = validate_zipcode(nz)
                    if ok and clean != ud["zipcode"]:
                        city_n, state_n = city_state_from_zip(clean)
                        lbl = (f"{city_n}, {state_n}" if city_n and state_n
                               else city_n if city_n else clean)
                        st.session_state.zip_location_label = lbl
                        ud["zipcode"] = clean
                        st.session_state.rec_beers = []
                        stype = ud.get("search_type")
                        with st.spinner(f"Searching in {lbl}..."):
                            if stype == "non_alcoholic":
                                beers = ai_na_recs(clean)
                            elif ud.get("brand_query"):
                                beers = ai_brand_recs(clean, ud["brand_query"])
                            else:
                                beers = ai_mood_recs(clean, ud.get("mood",""),
                                                     ud.get("day",""), ud.get("taste",""))
                        st.session_state.rec_beers = beers
                        st.rerun()
            with cl:
                if st.session_state.saved_beers:
                    if st.button("My List", key="star_btn"):
                        st.session_state.step = 4; st.rerun()
        else:
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
            zip_val  = st.text_input("Where ya at? *", placeholder="e.g. 90210", max_chars=5)
            if st.form_submit_button("ENTER"):
                if not name_val.strip():
                    st.error("❌ Name is required")
                else:
                    ok, result = validate_zipcode(zip_val)
                    if not ok:
                        st.error(f"❌ {result}")
                    else:
                        ud["name"]    = name_val.strip()[:35]
                        ud["zipcode"] = result
                        # Pre-populate location label for the results screen
                        city_n, state_n = city_state_from_zip(result)
                        lbl = (f"{city_n}, {state_n}" if city_n and state_n
                               else city_n if city_n else result)
                        st.session_state.zip_location_label = lbl
                        st.session_state.step = 1
                        st.rerun()

        render_bottom_nav("home")
        render_footer()

    # =========================================================================
    # STEP 1 — Search type
    # =========================================================================
    elif st.session_state.step == 1:
        greet, time_str = get_greeting(ud["zipcode"])   # live, no cache
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

        render_bottom_nav("search")
        render_footer()

    # =========================================================================
    # STEP 1.5 — Input collection
    # =========================================================================
    elif st.session_state.step == 1.5:
        greet, _ = get_greeting(ud["zipcode"])
        st.markdown(f'<div class="big-greeting">{greet}, {ud.get("name","Friend")}.</div>',
                    unsafe_allow_html=True)

        stype = ud.get("search_type")

        # ── MOOD ──────────────────────────────────────────────────────────────
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

        # ── SPECIFIC BEER — text box + mic below, no toggle buttons ──────────
        elif stype == "brand":
            st.markdown('<div style="height:12px;"></div>', unsafe_allow_html=True)
            st.markdown('<p class="gold-text" style="font-size:0.9rem;margin-bottom:4px;">'
                        'Type your beer or use the mic 🎤 below</p>', unsafe_allow_html=True)

            # Text search form
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

            # Voice input — always visible below text box, no toggle
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
                        beers = ai_brand_recs(ud["zipcode"], transcription)
                    ud.update({"brand_query": transcription, "search_type": "brand",
                               "mood": None, "day": "Voice Search", "taste": "Voice Search"})
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
            with st.spinner("Finding non-alcoholic beers…"):
                beers = ai_na_recs(ud["zipcode"])
            st.session_state.rec_beers = beers
            st.session_state.step = 3; st.rerun()

        elif ud.get("brand_query"):
            ud.update({"day":"Specific Search","taste":"Specific Search"})
            with st.spinner(f"Searching for {ud['brand_query']}…"):
                beers = ai_brand_recs(ud["zipcode"], ud["brand_query"])
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
                        with st.spinner("Pouring recommendations…"):
                            beers = ai_mood_recs(ud["zipcode"], ud["mood"], day[:35], taste[:35])
                        st.session_state.rec_beers = beers
                        st.session_state.step = 3; st.rerun()
            render_bottom_nav("search")
            render_footer()

    # =========================================================================
    # STEP 3 — Recommendations
    # =========================================================================
    elif st.session_state.step == 3:
        st.markdown('<h3 class="gold-text">Top Picks For You</h3>', unsafe_allow_html=True)

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
                    st.session_state.user_data = {"name":"","zipcode":"","mood":"",
                                                   "brand_query":None,"day":"","taste":"","search_type":None}
                    st.session_state.rec_beers = []; st.rerun()
        else:
            for idx, beer in enumerate(st.session_state.rec_beers):
                ukey  = f"rec_{idx}_{beer.get('name','?').replace(' ','_')}"
                render_beer_with_bars(beer, ud["zipcode"], ukey)
                saved = any(b["name"] == beer["name"] for b in st.session_state.saved_beers)
                if not saved:
                    if st.button("SAVE", key=f"save_{ukey}", use_container_width=True):
                        st.session_state.saved_beers.append(beer)
                        log_beer_selection(ud["name"], beer.get("name","?"), beer.get("brand","?"),
                                           ud.get("search_type","unknown"), ud.get("mood"))
                        st.rerun()
                else:
                    st.button("SAVED ✓", disabled=True, key=f"saved_{ukey}", use_container_width=True)

        render_bottom_nav("search")
        render_footer()

    # =========================================================================
    # STEP 4 — Saved beers
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
                ukey = f"saved_{i}_{beer.get('name','?').replace(' ','_')}"
                render_beer_with_bars(beer, ud["zipcode"], ukey)
                if st.button("REMOVE", key=f"remove_{ukey}", use_container_width=True):
                    st.session_state.saved_beers.pop(i); st.rerun()
        render_bottom_nav("saved")
        render_footer()

    # =========================================================================
    # STEP 5 — Feedback
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


if __name__ == "__main__":
    main()