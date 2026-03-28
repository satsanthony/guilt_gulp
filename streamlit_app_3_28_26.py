import streamlit as st
import os
import json
import requests
import datetime
from datetime import timedelta
import base64
import sys
import re
from huggingface_hub import HfApi, hf_hub_download

# --- Configuration & Setup ---
st.set_page_config(
    page_title="Beer Finder AI",
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
    """Print debug messages to terminal with color coding"""
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
    """Log user's beer selection to Hugging Face dataset"""
    if not HF_TOKEN:
        debug_print("HF_TOKEN not set, skipping logging", "WARNING")
        return

    try:
        import tempfile
        api = HfApi()
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Download existing log
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

        # Create new log entry
        if search_type == 'mood' and mood:
            log_entry = f"[{timestamp}] User: {username} | Beer: {beer_name} ({brand}) | Search: By Mood ({mood})\n"
        elif search_type == 'non_alcoholic':
            log_entry = f"[{timestamp}] User: {username} | Beer: {beer_name} ({brand}) | Search: Non-Alcoholic Beer\n"
        else:
            log_entry = f"[{timestamp}] User: {username} | Beer: {beer_name} ({brand}) | Search: Specific Beer\n"

        # Combine and write
        new_content = log_entry + existing_logs

        # Save to temp file using tempfile module
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False, suffix='.txt') as f:
            f.write(new_content)
            temp_path = f.name

        try:
            # Upload to HF dataset
            api.upload_file(
                path_or_fileobj=temp_path,
                path_in_repo="log.txt",
                repo_id=HF_DATASET_REPO,
                repo_type="dataset",
                token=HF_TOKEN
            )

            debug_print(f"Logged selection to HF dataset: {beer_name}", "SUCCESS")
        finally:
            # Clean up temp file
            if os.path.exists(temp_path):
                os.remove(temp_path)

    except Exception as e:
        debug_print(f"Error logging to HF dataset: {e}", "ERROR")

def save_feedback(username, feedback_text):
    """Save user feedback to Hugging Face dataset"""
    if not HF_TOKEN:
        debug_print("HF_TOKEN not set, skipping feedback", "WARNING")
        return False

    try:
        import tempfile
        api = HfApi()
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"feedback/{username}_{timestamp}.txt"

        content = f"Feedback from: {username}\n"
        content += f"Date: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        content += "="*50 + "\n\n"
        content += feedback_text

        # Save to temp file using tempfile module
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False, suffix='.txt') as f:
            f.write(content)
            temp_path = f.name

        try:
            # Upload to HF dataset
            api.upload_file(
                path_or_fileobj=temp_path,
                path_in_repo=filename,
                repo_id=HF_DATASET_REPO,
                repo_type="dataset",
                token=HF_TOKEN
            )

            debug_print(f"Saved feedback to HF dataset", "SUCCESS")
            return True
        finally:
            # Clean up temp file
            if os.path.exists(temp_path):
                os.remove(temp_path)

    except Exception as e:
        debug_print(f"Error saving feedback to HF dataset: {e}", "ERROR")
        return False

# --- CACHED INITIALIZATION ---
@st.cache_resource(show_spinner=False)
def initialize_gemini_model():
    """Initialize Gemini model once and cache it"""
    if not GENAI_AVAILABLE:
        debug_print("google-generativeai package not installed", "ERROR")
        return None, "google-generativeai package not installed"

    if not GEMINI_API_KEY:
        debug_print("GEMINI_API_KEY not found in environment variables", "ERROR")
        return None, "GEMINI_API_KEY not found in environment variables"

    try:
        genai.configure(api_key=GEMINI_API_KEY)

        # Use gemini-3-flash-preview as requested
        try:
            debug_print("Attempting to initialize gemini-3-flash-preview...", "INFO")
            model = genai.GenerativeModel('gemini-3-flash-preview')
            debug_print("Successfully initialized gemini-3-flash-preview", "SUCCESS")
            return model, None
        except Exception as e:
            debug_print(f"Failed to initialize gemini-3-flash-preview: {str(e)}", "ERROR")
            return None, f"Failed to initialize gemini-3-flash-preview: {str(e)}"

    except Exception as e:
        debug_print(f"Failed to configure Gemini: {str(e)}", "ERROR")
        return None, f"Failed to configure Gemini: {str(e)}"

processing_model, gemini_error = initialize_gemini_model()

# --- VALIDATION FUNCTIONS ---
def validate_zipcode(zipcode):
    """Validate that input is a 5-digit zipcode"""
    if not zipcode:
        return False, "Please enter a zipcode"

    # Remove any spaces or non-digit characters
    clean_zip = ''.join(filter(str.isdigit, zipcode))

    if len(clean_zip) != 5:
        return False, "Zipcode must be exactly 5 digits"

    # Basic US zipcode range validation
    zip_int = int(clean_zip)
    if zip_int < 501 or zip_int > 99950:
        return False, "Please enter a valid US zipcode"

    return True, clean_zip

# --- MOBILE STYLED CSS ---
@st.cache_data
def get_mobile_css():
    """Return CSS as string - cached"""
    return """
    <style>
        :root {
            --bg-app: #000000;
            --bg-card: #1a1a1a;
            --text-main: #ffffff;
            --text-sub: #b0b0b0;
            --accent: #d4a574;
            --input-bg: #ffffff;
            --input-text: #000000;
        }
        .stApp {
            background-color: var(--bg-app);
            color: var(--text-main);
        }
        .block-container {
            max-width: 450px !important;
            padding: 2rem 1rem !important;
            margin: 0 auto;
        }
        header, footer, .stDeployButton, section[data-testid="stSidebarNav"] {
            display: none !important;
        }
        h1, h2, h3, p, div {
            text-align: center !important;
            font-family: -apple-system, sans-serif;
        }
        .big-greeting {
            font-size: 2.2rem;
            font-weight: 300;
            margin: 20px 0 10px 0;
            background: linear-gradient(90deg, #d4a574, #f0e68c);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .gold-text {
            color: var(--accent) !important;
        }
        .stTextInput > div > div {
            background-color: var(--input-bg) !important;
            border-radius: 25px !important;
            border: 2px solid transparent !important;
            padding: 0 10px !important;
        }
        .stTextInput input {
            color: var(--input-text) !important;
            background-color: transparent !important;
            text-align: center !important;
            font-weight: 500 !important;
            caret-color: black !important;
            padding: 10px 5px !important;
        }
        .stTextInput input::placeholder {
            color: #444444 !important;
            opacity: 1 !important;
        }
        .stTextInput label {
            color: var(--accent) !important;
            text-align: center !important;
            width: 100%;
            display: block;
            margin-bottom: 8px;
            font-size: 0.9rem !important;
            text-transform: uppercase;
            letter-spacing: 1px;
            font-weight: 600 !important;
        }
        .stTextInput > div > div:focus-within {
            border-color: var(--accent) !important;
        }
        .stTextArea > div > div {
            background-color: var(--input-bg) !important;
            border-radius: 15px !important;
            border: 2px solid var(--accent) !important;
        }
        .stTextArea textarea {
            color: var(--input-text) !important;
            background-color: transparent !important;
            font-weight: 500 !important;
        }
        .stTextArea label {
            color: var(--accent) !important;
            text-align: center !important;
            font-size: 0.9rem !important;
            text-transform: uppercase;
            font-weight: 600 !important;
        }
        .stButton {
            display: flex !important;
            justify-content: center !important;
            width: 100% !important;
        }
        .stButton > button {
            width: 100% !important;
            border-radius: 25px !important;
            padding: 12px 20px !important;
            background: transparent !important;
            color: var(--accent) !important;
            border: 1px solid var(--accent) !important;
            font-weight: 600 !important;
            text-transform: uppercase;
            margin-top: 10px;
            opacity: 1 !important;
        }
        .stButton > button:hover {
            background: var(--accent) !important;
            color: #000 !important;
            opacity: 1 !important;
        }
        .stButton > button:active {
            opacity: 1 !important;
        }
        .stButton > button:focus {
            opacity: 1 !important;
        }
        div[data-testid="stFormSubmitButton"] {
            display: flex !important;
            justify-content: center !important;
        }
        div[data-testid="stFormSubmitButton"] > button {
            background: var(--accent) !important;
            color: #000 !important;
            border: none !important;
            width: 100% !important;
            opacity: 1 !important;
        }
        /* Hide form helper text */
        .stForm [data-testid="InputInstructions"] {
            display: none !important;
        }
        div[class*="FormInstructions"] {
            display: none !important;
        }
        .beer-card {
            background: var(--bg-card);
            border-radius: 15px;
            padding: 20px;
            margin: 20px 0;
            box-shadow: 0 4px 15px rgba(0,0,0,0.5);
        }
        .beer-image {
            width: 100%;
            height: 180px;
            object-fit: cover;
            border-radius: 10px;
            margin-bottom: 15px;
        }
        .beer-title {
            font-size: 1.5rem;
            font-weight: 700;
            color: #fff;
            margin-bottom: 5px;
        }
        .beer-brand {
            color: var(--accent);
            font-size: 0.9rem;
            text-transform: uppercase;
            margin-bottom: 15px;
        }
        .beer-metrics {
            display: flex;
            justify-content: center;
            gap: 15px;
            margin: 15px 0;
            padding: 10px 0;
            border-top: 1px solid #333;
            border-bottom: 1px solid #333;
        }
        .metric-value {
            font-size: 1.1rem;
            font-weight: bold;
            color: #fff;
        }
        .metric-label {
            font-size: 0.7rem;
            color: #888;
            text-transform: uppercase;
        }
        .bar-card {
            background: #2a2a2a;
            padding: 15px;
            margin: 10px 0;
            border-radius: 10px;
            border-left: 3px solid var(--accent);
        }
        .bar-name {
            font-weight: bold;
            color: #fff;
            font-size: 1.1rem;
            margin-bottom: 5px;
        }
        .bar-address {
            color: #b0b0b0;
            font-size: 0.85rem;
            margin: 5px 0;
        }
        .bar-rating {
            color: var(--accent);
            margin-top: 8px;
            font-size: 0.9rem;
        }
        .footer {
            margin-top: 50px;
            text-align: center;
            font-size: 0.75rem;
            color: var(--accent) !important;
            padding: 20px 0;
            border-top: 1px solid #333;
        }
        .feedback-link-container {
            text-align: center;
            margin: 20px auto;
            width: 100%;
        }
        .feedback-link {
            display: inline-block;
            text-align: center;
            color: var(--accent) !important;
            text-decoration: none;
            font-size: 0.8rem;
            cursor: pointer;
            opacity: 1 !important;
            transition: opacity 0.3s;
        }
        .feedback-link:hover {
            opacity: 0.7 !important;
            text-decoration: underline;
        }
        .debug-panel {
            background: #1a1a1a;
            border: 1px solid #333;
            border-radius: 10px;
            padding: 15px;
            margin: 20px 0;
            font-size: 0.85rem;
            color: #888;
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
                <img src="data:image/png;base64,{encoded}" style="width: 120px; height: auto;">
            </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown('<div style="font-size: 4rem;">🍺</div>', unsafe_allow_html=True)

def render_footer():
    """Render footer with centered feedback button"""
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

@st.cache_data(ttl=86400)
def google_custom_search(query, num=1):
    if not GOOGLE_CSE_API_KEY or not GOOGLE_CSE_CX:
        debug_print("Google Custom Search API keys not configured", "WARNING")
        return None
    try:
        params = {
            'key': GOOGLE_CSE_API_KEY,
            'cx': GOOGLE_CSE_CX,
            'q': query,
            'num': num,
            'searchType': 'image'
        }
        resp = requests.get('https://www.googleapis.com/customsearch/v1', params=params, timeout=5)
        if resp.status_code == 200:
            items = resp.json().get('items', [])
            if items:
                return items[0].get('link')
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
        url = f"https://maps.googleapis.com/maps/api/geocode/json"
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
    """Extract city name from zipcode for better search results"""
    if not GOOGLE_GEOCODING_API_KEY:
        return ""
    try:
        url = f"https://maps.googleapis.com/maps/api/geocode/json"
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
    """Sub-Agent 1: Web Search Agent"""
    if not GOOGLE_CSE_API_KEY or not GOOGLE_CSE_CX:
        debug_print("Web Search Agent: Custom Search API not configured", "WARNING")
        return []

    try:
        search_queries = [
            f"{beer_name} {brand_name} bars near {zipcode}",
            f"where to drink {beer_name} in {city_name}",
            f"{beer_name} on tap {city_name}",
            f"bars serving {beer_name} {city_name}"
        ]

        all_results = []

        for query in search_queries[:2]:
            debug_print(f"Web Search Agent: Searching '{query}'", "INFO")

            params = {
                'key': GOOGLE_CSE_API_KEY,
                'cx': GOOGLE_CSE_CX,
                'q': query,
                'num': 5
            }

            resp = requests.get('https://www.googleapis.com/customsearch/v1', params=params, timeout=10)

            if resp.status_code == 200:
                items = resp.json().get('items', [])
                debug_print(f"Web Search Agent: Found {len(items)} results for query", "SUCCESS")
                all_results.extend(items)
            else:
                debug_print(f"Web Search Agent: Search failed with status {resp.status_code}", "WARNING")

        return all_results

    except Exception as e:
        debug_print(f"Web Search Agent error: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        return []

def analyze_web_results_for_bars(web_results, beer_name, city_name):
    """Sub-Agent 2: AI Analysis Agent"""
    if not processing_model or not web_results:
        debug_print("AI Analysis Agent: No model or no web results", "WARNING")
        return []

    try:
        content_summary = []
        for idx, result in enumerate(web_results[:8]):
            title = result.get('title', '')
            snippet = result.get('snippet', '')
            content_summary.append(f"Result {idx+1}: {title} - {snippet}")

        combined_content = "\n".join(content_summary)

        prompt = f"""Based on the following web search results about where to find {beer_name} in {city_name}, extract a list of actual bar names.
Web Results:
{combined_content}
Extract ONLY real bar/pub/tavern names that serve {beer_name}. Return a JSON array with this format:
[{{"name": "Bar Name", "confidence": "high/medium"}}]
Rules:
- Only include actual establishment names (not websites, apps, or general terms)
- Exclude chain restaurants unless specifically mentioned as serving this beer
- Maximum 8 bars
- Return just the JSON array, no markdown or explanation."""

        debug_print("AI Analysis Agent: Analyzing web results...", "INFO")
        response = processing_model.generate_content(prompt)

        if not response or not response.text:
            debug_print("AI Analysis Agent: Empty response", "WARNING")
            return []

        text = response.text.strip()

        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        bars = json.loads(text)

        if isinstance(bars, list):
            debug_print(f"AI Analysis Agent: Extracted {len(bars)} bar names", "SUCCESS")
            return bars

        return []

    except json.JSONDecodeError as e:
        debug_print(f"AI Analysis Agent: JSON parse error: {e}", "ERROR")
        return []
    except Exception as e:
        debug_print(f"AI Analysis Agent error: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        return []

def verify_bars_with_places_api(bar_names, lat, lng, radius=8000):
    """Sub-Agent 3: Location Verification Agent"""
    if not GOOGLE_PLACES_API_KEY or not bar_names:
        debug_print("Verification Agent: No API key or no bar names", "WARNING")
        return []

    verified_bars = []

    try:
        for bar_data in bar_names[:10]:
            bar_name = bar_data.get('name', '') if isinstance(bar_data, dict) else bar_data

            debug_print(f"Verification Agent: Searching for '{bar_name}'", "INFO")

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
                        "center": {
                            "latitude": lat,
                            "longitude": lng
                        },
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
                    if price_level:
                        try:
                            price_level = int(price_level) if isinstance(price_level, str) else price_level
                            price_str = '$' * price_level
                        except (ValueError, TypeError):
                            price_str = '$$'
                    else:
                        price_str = '$$'

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
                    debug_print(f"Verification Agent: Verified '{bar_info['name']}'", "SUCCESS")
            else:
                debug_print(f"Verification Agent: Places API error {resp.status_code} for '{bar_name}'", "WARNING")

            if len(verified_bars) >= 5:
                break

        debug_print(f"Verification Agent: Total verified: {len(verified_bars)} bars", "SUCCESS")
        return verified_bars

    except Exception as e:
        debug_print(f"Verification Agent error: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        return []

@st.cache_data(ttl=3600)
def find_bars_serving_beer(lat, lng, beer_name, brand_name, zipcode):
    """Sub-Agent 4: Matching Agent"""
    debug_print(f"Matching Agent: Starting comprehensive search for {beer_name}", "INFO")

    city_name = get_city_from_zipcode(zipcode)
    debug_print(f"Matching Agent: City identified as '{city_name}'", "INFO")

    web_results = web_search_bars_for_beer(beer_name, brand_name, zipcode, city_name)

    if not web_results:
        debug_print("Matching Agent: No web results found", "WARNING")
        return []

    bar_names = analyze_web_results_for_bars(web_results, beer_name, city_name)

    if not bar_names:
        debug_print("Matching Agent: No bar names extracted from web results", "WARNING")
        return []

    verified_bars = verify_bars_with_places_api(bar_names, lat, lng)

    if verified_bars:
        debug_print(f"Matching Agent: Successfully found {len(verified_bars)} verified bars serving {beer_name}", "SUCCESS")
        return verified_bars
    else:
        debug_print("Matching Agent: No bars verified", "WARNING")
        return []

@st.cache_data(ttl=3600)
def find_nearby_bars(lat, lng, beer_name, brand_name="", zipcode=""):
    """Legacy wrapper"""
    return find_bars_serving_beer(lat, lng, beer_name, brand_name, zipcode)

def ensure_beer_image(beer):
    if not beer.get('image'):
        query = f"{beer.get('name', '')} {beer.get('brand', '')} beer bottle"
        image_url = google_custom_search(query)
        if image_url:
            beer['image'] = image_url
    return beer

def get_ai_recommendations(zipcode, mood, day_context, taste_pref):
    """Main Agent: Beer recommendation"""
    if not processing_model:
        error_msg = f"⚠️ AI model not available: {gemini_error}"
        st.error(error_msg)
        debug_print(f"Main Agent: {error_msg}", "ERROR")
        return []

    s_zip = str(zipcode)[:5]
    s_mood = str(mood)[:35]
    s_day = str(day_context)[:35]
    s_taste = str(taste_pref)[:35]

    prompt = f"""Act as a beer sommelier. Suggest 3 beers based on:
Zip: {s_zip}, Mood: {s_mood}, Day: {s_day}, Taste: {s_taste}.
Return ONLY a valid JSON array of 3 objects with this exact format:
[{{"name": "Beer Name", "brand": "Brand Name", "calories": "150", "abv": "5.5%", "description": "A crisp and refreshing beer perfect for relaxing", "price_range": "$$", "where_to_buy": "Total Wine, BevMo"}}]
Do not include any markdown formatting, code blocks, or explanations. Just the JSON array."""

    try:
        debug_print("Main Agent: Requesting beer recommendations from AI", "INFO")
        response = processing_model.generate_content(prompt)

        if not response or not response.text:
            error_msg = "⚠️ API returned empty response"
            st.error(error_msg)
            debug_print(f"Main Agent: {error_msg}", "ERROR")
            return []

        text = response.text.strip()
        debug_print(f"Main Agent: Received response of {len(text)} characters", "INFO")

        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
            debug_print("Main Agent: Extracted JSON from markdown code block", "INFO")
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
            debug_print("Main Agent: Extracted text from code block", "INFO")

        beers = json.loads(text)

        if not isinstance(beers, list) or len(beers) == 0:
            error_msg = "⚠️ API returned invalid format (not a list or empty)"
            st.error(error_msg)
            debug_print(f"Main Agent: {error_msg}", "ERROR")
            return []

        debug_print(f"Main Agent: Successfully parsed {len(beers)} beer recommendations", "SUCCESS")

        for beer in beers:
            ensure_beer_image(beer)

        return beers

    except json.JSONDecodeError as e:
        error_msg = f"⚠️ Failed to parse AI response as JSON: {str(e)}"
        st.error(error_msg)
        debug_print(f"Main Agent: {error_msg}", "ERROR")
        debug_print(f"Main Agent: Raw response: {text[:500]}", "ERROR")
        with st.expander("See raw response"):
            st.code(text[:500])
        return []

    except Exception as e:
        error_msg = f"⚠️ Error: {type(e).__name__} - {str(e)}"
        st.error(error_msg)
        debug_print(f"Main Agent: {error_msg}", "ERROR")
        import traceback
        traceback.print_exc()
        return []

def get_brand_search_recommendations(zipcode, brand_query):
    if not processing_model:
        error_msg = f"⚠️ AI model not available: {gemini_error}"
        st.error(error_msg)
        debug_print(f"Brand Search: {error_msg}", "ERROR")
        return []

    prompt = f"""Act as a beer sommelier. The user is looking for "{brand_query}" or very similar beers available near zipcode {zipcode}.
Return 3 relevant options (the specific beer if available, or closest matches).
Return ONLY a valid JSON array of 3 objects with this exact format:
[{{"name": "Beer Name", "brand": "Brand Name", "calories": "150", "abv": "5.5%", "description": "A crisp and refreshing beer", "price_range": "$$", "where_to_buy": "Total Wine, BevMo"}}]
Do not include any markdown formatting, code blocks, or explanations. Just the JSON array."""

    try:
        debug_print(f"Brand Search: Looking for '{brand_query}' near {zipcode}", "INFO")
        response = processing_model.generate_content(prompt)

        if not response or not response.text:
            error_msg = "⚠️ API returned empty response"
            st.error(error_msg)
            debug_print(f"Brand Search: {error_msg}", "ERROR")
            return []

        text = response.text.strip()
        debug_print(f"Brand Search: Received response of {len(text)} characters", "INFO")

        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
            debug_print("Brand Search: Extracted JSON from markdown code block", "INFO")
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
            debug_print("Brand Search: Extracted text from code block", "INFO")

        beers = json.loads(text)

        if not isinstance(beers, list) or len(beers) == 0:
            error_msg = "⚠️ API returned invalid or empty results"
            st.error(error_msg)
            debug_print(f"Brand Search: {error_msg}", "ERROR")
            return []

        debug_print(f"Brand Search: Successfully parsed {len(beers)} beer recommendations", "SUCCESS")

        for beer in beers:
            ensure_beer_image(beer)

        return beers

    except json.JSONDecodeError as e:
        error_msg = f"⚠️ Failed to parse AI response: {str(e)}"
        st.error(error_msg)
        debug_print(f"Brand Search: JSON parse error: {e}", "ERROR")
        debug_print(f"Brand Search: Raw response: {text[:500]}", "ERROR")
        with st.expander("See raw response"):
            st.code(text[:500])
        return []

    except Exception as e:
        error_msg = f"⚠️ Error: {type(e).__name__} - {str(e)}"
        st.error(error_msg)
        debug_print(f"Brand Search: {error_msg}", "ERROR")
        import traceback
        traceback.print_exc()
        return []

def get_non_alcoholic_recommendations(zipcode):
    if not processing_model:
        error_msg = f"⚠️ AI model not available: {gemini_error}"
        st.error(error_msg)
        debug_print(f"Non-Alcoholic Search: {error_msg}", "ERROR")
        return []

    prompt = f"""Act as a beer sommelier. The user is looking for non-alcoholic beers available near zipcode {zipcode}.
Return 3 high-quality non-alcoholic beer options.
Return ONLY a valid JSON array of 3 objects with this exact format:
[{{"name": "Beer Name", "brand": "Brand Name", "calories": "50", "abv": "0.0%", "description": "A refreshing non-alcoholic option", "price_range": "$$", "where_to_buy": "Total Wine, Whole Foods"}}]
Do not include any markdown formatting, code blocks, or explanations. Just the JSON array."""

    try:
        debug_print(f"Non-Alcoholic Search: Looking for non-alcoholic beers near {zipcode}", "INFO")
        response = processing_model.generate_content(prompt)

        if not response or not response.text:
            error_msg = "⚠️ API returned empty response"
            st.error(error_msg)
            debug_print(f"Non-Alcoholic Search: {error_msg}", "ERROR")
            return []

        text = response.text.strip()
        debug_print(f"Non-Alcoholic Search: Received response of {len(text)} characters", "INFO")

        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
            debug_print("Non-Alcoholic Search: Extracted JSON from markdown code block", "INFO")
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
            debug_print("Non-Alcoholic Search: Extracted text from code block", "INFO")

        beers = json.loads(text)

        if not isinstance(beers, list) or len(beers) == 0:
            error_msg = "⚠️ API returned invalid or empty results"
            st.error(error_msg)
            debug_print(f"Non-Alcoholic Search: {error_msg}", "ERROR")
            return []

        debug_print(f"Non-Alcoholic Search: Successfully parsed {len(beers)} beer recommendations", "SUCCESS")

        for beer in beers:
            ensure_beer_image(beer)

        return beers

    except json.JSONDecodeError as e:
        error_msg = f"⚠️ Failed to parse AI response: {str(e)}"
        st.error(error_msg)
        debug_print(f"Non-Alcoholic Search: JSON parse error: {e}", "ERROR")
        debug_print(f"Non-Alcoholic Search: Raw response: {text[:500]}", "ERROR")
        with st.expander("See raw response"):
            st.code(text[:500])
        return []

    except Exception as e:
        error_msg = f"⚠️ Error: {type(e).__name__} - {str(e)}"
        st.error(error_msg)
        debug_print(f"Non-Alcoholic Search: {error_msg}", "ERROR")
        import traceback
        traceback.print_exc()
        return []

@st.cache_data
def render_beer_card_html(name, brand, image, abv, calories, price_range, description, where_to_buy):
    img = f'<img src="{image}" class="beer-image">' if image else ""
    return f"""<div class="beer-card">{img}<div class="beer-title">{name}</div><div class="beer-brand">{brand}</div><div class="beer-metrics"><div><div class="metric-value">{abv}</div><div class="metric-label">ABV</div></div><div><div class="metric-value">{calories}</div><div class="metric-label">Cals</div></div><div><div class="metric-value">{price_range}</div><div class="metric-label">Price</div></div></div><div style="color: #ccc; font-size: 0.9rem; line-height: 1.4; margin-bottom: 10px;">{description}</div><div style="color: #d4a574; font-size: 0.8rem;">📍 {where_to_buy}</div></div>"""

def render_bar_card(bar):
    google_maps_link = f"https://www.google.com/maps/search/?api=1&query={bar['lat']},{bar['lng']}&query_place_id={bar['place_id']}"

    st.markdown(f"""
    <div class="bar-card">
        <div class="bar-name">🍻 {bar['name']}</div>
        <div class="bar-address">📍 {bar['address']}</div>
        <div class="bar-rating">⭐ {bar['rating']} • {bar['price_level']}</div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(f"[📍 Open in Google Maps]({google_maps_link})", unsafe_allow_html=True)

def render_beer_with_bars(beer, zipcode, unique_key):
    card_html = render_beer_card_html(
        beer.get("name", "Unknown"),
        beer.get("brand", "Craft Beer"),
        beer.get("image"),
        beer.get("abv", "?"),
        beer.get("calories", "?"),
        beer.get("price_range", "$"),
        beer.get("description", ""),
        beer.get("where_to_buy", "Check Local Stores")
    )
    st.markdown(card_html, unsafe_allow_html=True)

    with st.expander(f"🍻 Bars near you serving {beer.get('name')}"):
        lat, lng = zipcode_to_coords(zipcode)

        if lat and lng:
            with st.spinner("🤖 AI agents researching bars that serve this beer..."):
                bars = find_bars_serving_beer(
                    lat,
                    lng,
                    beer.get('name'),
                    beer.get('brand', ''),
                    zipcode
                )

            if bars:
                st.markdown(f'<p style="color: #d4a574; font-size: 0.9rem; margin-bottom: 15px;">🎯 Bars serving {beer.get("name")} near you:</p>', unsafe_allow_html=True)
                for idx, bar in enumerate(bars):
                    with st.container():
                        render_bar_card(bar)
            else:
                st.info("🤖 Our AI agents couldn't find bars serving this specific beer nearby. Try checking the 'Where to Buy' section above for retail options.")
        else:
            st.warning("Unable to locate bars for this zipcode. Please ensure your Google Geocoding API is enabled and configured.")

# --- Session State ---
if 'step' not in st.session_state:
    st.session_state.step = 0
if 'user_data' not in st.session_state:
    st.session_state.user_data = {
        'name': '',
        'zipcode': '',
        'mood': '',
        'brand_query': None,
        'day': '',
        'taste': '',
        'search_type': None
    }
if 'rec_beers' not in st.session_state:
    st.session_state.rec_beers = []
if 'saved_beers' not in st.session_state:
    st.session_state.saved_beers = []
if 'show_debug' not in st.session_state:
    st.session_state.show_debug = False
if 'feedback_submitted' not in st.session_state:
    st.session_state.feedback_submitted = False

def main():
    inject_mobile_css()

    if st.sidebar.button("Toggle Debug"):
        st.session_state.show_debug = not st.session_state.show_debug
        st.rerun()

    render_debug_panel()

    if st.session_state.step > 0 and st.session_state.step != 5:
        c1, c2, c3 = st.columns([1, 2, 1])
        with c1:
            if st.button("←", key="back_btn"):
                if st.session_state.step == 3:
                    st.session_state.step = 1
                    st.session_state.rec_beers = []
                    st.session_state.user_data['brand_query'] = None
                    st.session_state.user_data['mood'] = ''
                    st.session_state.user_data['search_type'] = None
                    st.rerun()
                elif st.session_state.step == 4:
                    st.session_state.step = 1
                    st.rerun()
                elif st.session_state.step == 2 and st.session_state.user_data.get('search_type') in ['brand', 'non_alcoholic']:
                    st.session_state.step = 1
                    st.session_state.user_data['brand_query'] = None
                    st.session_state.user_data['search_type'] = None
                    st.rerun()
                else:
                    st.session_state.step = max(0, st.session_state.step - 1)
                    st.rerun()
        with c3:
            if st.session_state.saved_beers and st.session_state.step != 4:
                if st.button("My List", key="star_btn"):
                    st.session_state.step = 4
                    st.rerun()

    # STEP 0: Login Screen
    if st.session_state.step == 0:
        st.markdown('<div style="height: 60px;"></div>', unsafe_allow_html=True)
        render_logo()
        st.markdown('<h1 class="big-greeting">Beer Finder</h1>', unsafe_allow_html=True)
        st.markdown('<p class="gold-text">Your pocket sommelier.</p>', unsafe_allow_html=True)

        if gemini_error:
            st.warning(f"⚠️ {gemini_error}")
            st.info("The app may not work correctly. Please check your API configuration.")

        st.markdown('<div style="height: 30px;"></div>', unsafe_allow_html=True)

        with st.form("login_form", clear_on_submit=False):
            name_val = st.text_input("Your name? *", placeholder="Enter your name", max_chars=35)
            zip_val = st.text_input("Where ya at? *", placeholder="e.g. 90210", max_chars=5)

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
                        st.session_state.user_data['name'] = name_val.strip()[:35]
                        st.session_state.user_data['zipcode'] = result
                        st.session_state.step = 1
                        st.rerun()

        render_footer()

    # STEP 1: Search Selection
    elif st.session_state.step == 1:
        greet, time = get_greeting(st.session_state.user_data['zipcode'])
        name = st.session_state.user_data.get('name', 'Friend')

        gif_path = os.path.join(os.path.dirname(__file__), "static", "images", "beer.gif.gif")
        encoded = load_image_as_base64(gif_path)

        if encoded:
            st.markdown(f"""
                <div style="display: flex; justify-content: center; margin-bottom: 20px;">
                    <img src="data:image/gif;base64,{encoded}"
                         style="width: 100%; max-height: 250px; object-fit: cover; border-radius: 15px; opacity: 0.8;">
                </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown('<div style="display: flex; justify-content: center; margin-bottom: 20px;"><div style="font-size: 5rem;">🍺</div></div>', unsafe_allow_html=True)

        st.markdown(f'<div class="big-greeting">{greet}, {name}.</div>', unsafe_allow_html=True)
        if time:
            st.markdown(f'<p class="gold-text">It is currently {time}</p>', unsafe_allow_html=True)

        st.markdown('<div style="height: 30px;"></div>', unsafe_allow_html=True)
        st.markdown('<p class="gold-text" style="font-size: 1.1rem; margin-bottom: 20px;">How would you like to search?</p>', unsafe_allow_html=True)

        col1, col2, col3 = st.columns(3)

        with col1:
            if st.button("🎭 BY MOOD", key="mood_btn", use_container_width=True):
                st.session_state.user_data['search_type'] = 'mood'
                st.session_state.step = 1.5
                st.rerun()

        with col2:
            if st.button("🍺 SPECIFIC BEER", key="brand_btn", use_container_width=True):
                st.session_state.user_data['search_type'] = 'brand'
                st.session_state.step = 1.5
                st.rerun()

        with col3:
            if st.button("🚫🍺 NON-ALCOHOLIC", key="non_alc_btn", use_container_width=True):
                st.session_state.user_data['search_type'] = 'non_alcoholic'
                st.session_state.step = 2
                st.rerun()

        render_footer()

    # STEP 1.5: Input Collection
    elif st.session_state.step == 1.5:
        greet, time = get_greeting(st.session_state.user_data['zipcode'])
        name = st.session_state.user_data.get('name', 'Friend')

        st.markdown(f'<div class="big-greeting">{greet}, {name}.</div>', unsafe_allow_html=True)

        search_type = st.session_state.user_data.get('search_type')

        if search_type == 'mood':
            st.markdown('<div style="height: 20px;"></div>', unsafe_allow_html=True)
            with st.form("mood_form", clear_on_submit=False):
                mood = st.text_input("Vibe check", placeholder="Relaxed, Hyped, Tired...", max_chars=35, label_visibility="visible")

                if st.form_submit_button("NEXT"):
                    if mood:
                        st.session_state.user_data['mood'] = mood
                        st.session_state.user_data['brand_query'] = None
                        st.session_state.step = 2
                        st.rerun()
                    else:
                        st.error("Please describe your mood")

        elif search_type == 'brand':
            st.markdown('<div style="height: 20px;"></div>', unsafe_allow_html=True)
            with st.form("brand_form", clear_on_submit=False):
                brand_query = st.text_input("ENTER YOUR BEER OF CHOICE", placeholder="Guinness, West Coast IPA...", max_chars=35, label_visibility="visible")

                if st.form_submit_button("FIND IT"):
                    if brand_query:
                        st.session_state.user_data['brand_query'] = brand_query
                        st.session_state.user_data['mood'] = None
                        st.session_state.step = 2
                        st.rerun()
                    else:
                        st.error("Please enter a beer name or style")

        render_footer()

    # STEP 2: Additional Context or Direct Search
    elif st.session_state.step == 2:
        if st.session_state.user_data.get('search_type') == 'non_alcoholic':
            st.session_state.user_data.update({'day': 'Non-Alcoholic Search', 'taste': 'Non-Alcoholic Search'})

            with st.spinner("Finding non-alcoholic beers..."):
                beers = get_non_alcoholic_recommendations(
                    st.session_state.user_data['zipcode']
                )
                st.session_state.rec_beers = beers
                st.session_state.step = 3
                st.rerun()
        elif st.session_state.user_data.get('brand_query'):
            brand = st.session_state.user_data.get('brand_query')
            st.session_state.user_data.update({'day': 'Specific Brand Search', 'taste': 'Specific Brand Search'})

            with st.spinner(f"Finding {brand}..."):
                beers = get_brand_search_recommendations(
                    st.session_state.user_data['zipcode'],
                    brand
                )
                st.session_state.rec_beers = beers
                st.session_state.step = 3
                st.rerun()
        else:
            st.markdown('<h3 class="gold-text">Tell me more...</h3>', unsafe_allow_html=True)
            with st.form("context", clear_on_submit=False):
                day = st.text_input("What kind of day did you have?", placeholder="Long work day, celebrating...", max_chars=35, label_visibility="visible")
                taste = st.text_input("What hits right?", placeholder="Hoppy, Sweet, Dark, Surprise me...", max_chars=35, label_visibility="visible")

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

            render_footer()

    # STEP 3: Beer Recommendations
    elif st.session_state.step == 3:
        st.markdown('<h3 class="gold-text">Top Picks For You</h3>', unsafe_allow_html=True)

        if not st.session_state.rec_beers:
            st.markdown("""
                <div style="background: #1a1a1a; padding: 30px; border-radius: 15px; margin: 40px 0; text-align: center;">
                    <p style="color: #d4a574; font-size: 1.2rem; margin-bottom: 20px;">
                        No recommendations available. Please try searching again.
                    </p>
                </div>
            """, unsafe_allow_html=True)

            col1, col2 = st.columns(2)
            with col1:
                if st.button("TRY AGAIN", key="try_again_btn"):
                    st.session_state.step = 1
                    st.session_state.user_data['search_type'] = None
                    st.session_state.rec_beers = []
                    st.rerun()

            with col2:
                if st.button("GO HOME", key="go_home_btn"):
                    st.session_state.step = 0
                    st.session_state.user_data = {
                        'name': '',
                        'zipcode': '',
                        'mood': '',
                        'brand_query': None,
                        'day': '',
                        'taste': '',
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
                    if st.button(f"SAVE", key=f"save_{unique_key}"):
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
                    st.button("SAVED ✓", disabled=True, key=f"saved_{unique_key}")

        render_footer()

    # STEP 4: Saved Beers
    elif st.session_state.step == 4:
        st.markdown('<h3 class="gold-text">Your Saved Brews</h3>', unsafe_allow_html=True)

        if not st.session_state.saved_beers:
            st.markdown("""
                <div style="background: #1a1a1a; padding: 30px; border-radius: 15px; margin: 40px 0; text-align: center;">
                    <p style="color: #d4a574; font-size: 1.2rem; margin-bottom: 20px;">
                        You do not have any selections, click the back button to select more beers
                    </p>
                </div>
            """, unsafe_allow_html=True)
        else:
            for i, beer in enumerate(st.session_state.saved_beers):
                unique_key = f"saved_{i}_{beer.get('name', 'unknown').replace(' ', '_')}"

                render_beer_with_bars(beer, st.session_state.user_data['zipcode'], unique_key)
                if st.button("REMOVE", key=f"remove_{unique_key}"):
                    st.session_state.saved_beers.pop(i)
                    st.rerun()

        render_footer()

    # STEP 5: Feedback Page
    elif st.session_state.step == 5:
        st.markdown('<h3 class="gold-text">Feedback / Feature Request</h3>', unsafe_allow_html=True)

        if st.session_state.feedback_submitted:
            username = st.session_state.user_data.get('name', 'User')
            st.markdown(f"""
                <div style="background: #1a1a1a; padding: 30px; border-radius: 15px; margin: 40px 0; text-align: center;">
                    <p style="color: #d4a574; font-size: 1.3rem;">
                        ✓ Thank you for your submission, {username}
                    </p>
                </div>
            """, unsafe_allow_html=True)

            import time
            time.sleep(3)
            st.session_state.feedback_submitted = False
            st.session_state.step = 1
            st.rerun()
        else:
            with st.form("feedback_form", clear_on_submit=False):
                feedback_text = st.text_area(
                    "Provide feedback / Feature request",
                    placeholder="Share your thoughts, suggestions, or feature requests...",
                    max_chars=3000,
                    height=200,
                    label_visibility="visible"
                )

                submitted = st.form_submit_button("SUBMIT")

                if submitted:
                    if feedback_text and feedback_text.strip():
                        username = st.session_state.user_data.get('name', 'Anonymous')
                        if save_feedback(username, feedback_text):
                            st.session_state.feedback_submitted = True
                            st.rerun()
                        else:
                            st.error("Failed to save feedback. Please try again.")
                    else:
                        st.error("Please provide some feedback before submitting")

if __name__ == "__main__":
    main()
