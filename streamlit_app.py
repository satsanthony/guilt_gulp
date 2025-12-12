import streamlit as st
import os
import json
import requests
import datetime
from datetime import timedelta
import base64

# --- Configuration & Setup ---
st.set_page_config(
    page_title="Beer Finder AI",
    page_icon="🍺",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# Setup directories
STATIC_IMG_DIR = os.path.join(os.path.dirname(__file__), "static", "images")
os.makedirs(STATIC_IMG_DIR, exist_ok=True)

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

# --- CACHED INITIALIZATION ---
@st.cache_resource(show_spinner=False)
def initialize_gemini_model():
    """Initialize Gemini model once and cache it - OPTIMIZED"""
    if not GENAI_AVAILABLE:
        return None, "google-generativeai package not installed"
    
    if not GEMINI_API_KEY:
        return None, "GEMINI_API_KEY not found in environment variables"
    
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        
        # Try models in order - NO TEST API CALL (this was slowing things down!)
        model_options = [
            'gemini-3-pro-preview',
            'gemini-2.5-pro'
            'gemini-1.5-pro-latest'
        ]
        
        for model_name in model_options:
            try:
                model = genai.GenerativeModel(model_name)
                return model, None  # Return immediately on success
            except Exception:
                continue
        
        return None, "Could not initialize any Gemini model"
        
    except Exception as e:
        return None, f"Failed to configure Gemini: {str(e)}"

# Initialize model (cached)
processing_model, gemini_error = initialize_gemini_model()

# --- MOBILE STYLED CSS (CACHED) ---
@st.cache_data
def get_mobile_css():
    """Return CSS as string - cached to avoid recomputation"""
    return """
    <style>
        /* === THEME VARIABLES === */
        :root {
            --bg-app: #000000;
            --bg-card: #1a1a1a;
            --text-main: #ffffff;
            --text-sub: #b0b0b0;
            --accent: #d4a574;
            --input-bg: #ffffff;
            --input-text: #000000;
        }

        /* === APP CONTAINER === */
        .stApp {
            background-color: var(--bg-app);
            color: var(--text-main);
        }
        
        .block-container {
            max-width: 450px !important;
            padding: 2rem 1rem !important;
            margin: 0 auto;
        }

        /* Hide Default Elements */
        header, footer, .stDeployButton, section[data-testid="stSidebarNav"] { 
            display: none !important; 
        }

        /* === TYPOGRAPHY === */
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

        /* === INPUT FIELDS === */
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

        /* === BUTTONS === */
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
        }

        .stButton > button:hover {
            background: var(--accent) !important;
            color: #000 !important;
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
        }

        /* === CARDS & IMAGES === */
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

        .beer-title { font-size: 1.5rem; font-weight: 700; color: #fff; margin-bottom: 5px; }
        .beer-brand { color: var(--accent); font-size: 0.9rem; text-transform: uppercase; margin-bottom: 15px; }
        
        .beer-metrics {
            display: flex;
            justify-content: center;
            gap: 15px;
            margin: 15px 0;
            padding: 10px 0;
            border-top: 1px solid #333;
            border-bottom: 1px solid #333;
        }
        
        .metric-value { font-size: 1.1rem; font-weight: bold; color: #fff; }
        .metric-label { font-size: 0.7rem; color: #888; text-transform: uppercase; }

        .footer {
            margin-top: 50px;
            text-align: center;
            font-size: 0.75rem;
            color: var(--accent) !important;
            padding: 20px 0;
            border-top: 1px solid #333;
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
    """Inject cached CSS"""
    st.markdown(get_mobile_css(), unsafe_allow_html=True)

# --- Helper Functions ---

@st.cache_data
def load_image_as_base64(image_path):
    """Cache image loading to avoid repeated disk reads"""
    if os.path.exists(image_path):
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return None

def render_logo():
    """Render logo with cached image loading"""
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
    st.markdown("""
        <div class="footer">
            © 2025 Dimension Unlimited. All rights reserved. Drink responsibly.
        </div>
    """, unsafe_allow_html=True)

def render_debug_panel():
    """Show debug information"""
    if st.session_state.get('show_debug', False):
        debug_info = f"""
        <div class="debug-panel">
            <strong>🔧 Debug Info:</strong><br>
            • Gemini Available: {GENAI_AVAILABLE}<br>
            • API Key Set: {'Yes' if GEMINI_API_KEY else 'No'}<br>
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
    """Cached greeting calculation - TTL 1 hour"""
    greeting = "Hello"
    time_str = ""
    try:
        first_digit = int(str(zipcode)[0])
        if first_digit in [0, 1, 2, 3]: offset = -5
        elif first_digit in [4, 5, 6]: offset = -6
        elif first_digit == 7: offset = -7
        else: offset = -8
            
        utc_now = datetime.datetime.utcnow()
        local_time = utc_now + timedelta(hours=offset)
        hour = local_time.hour
        
        if 5 <= hour < 12: greeting = "Good Morning"
        elif 12 <= hour < 17: greeting = "Good Afternoon"
        elif 17 <= hour < 22: greeting = "Good Evening"
        else: greeting = "Hey Night Owl"
        
        time_str = local_time.strftime("%I:%M %p")
    except:
        pass

    return greeting, time_str

@st.cache_data(ttl=86400)
def google_custom_search(query, num=1):
    """Cached image search - TTL 24 hours"""
    if not GOOGLE_CSE_API_KEY or not GOOGLE_CSE_CX: 
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
    except Exception as e:
        print(f"Image search error: {e}")
    return None

def ensure_beer_image(beer):
    """Add image to beer if missing"""
    if not beer.get('image'):
        query = f"{beer.get('name', '')} {beer.get('brand', '')} beer bottle"
        image_url = google_custom_search(query)
        if image_url: 
            beer['image'] = image_url
    return beer

def get_ai_recommendations(zipcode, mood, day_context, taste_pref):
    """Get AI recommendations - optimized error handling"""
    
    if not processing_model:
        st.error(f"⚠️ AI model not available: {gemini_error}")
        return []
    
    # Trim inputs
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
        response = processing_model.generate_content(prompt)
        
        if not response or not response.text:
            st.error("⚠️ API returned empty response")
            return []
        
        text = response.text.strip()
        
        # Clean markdown
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        
        beers = json.loads(text)
        
        if not isinstance(beers, list) or len(beers) == 0:
            st.error("⚠️ API returned invalid format")
            return []
        
        # Add images
        for beer in beers:
            ensure_beer_image(beer)
        
        return beers
        
    except json.JSONDecodeError:
        st.error(f"⚠️ Failed to parse AI response as JSON")
        with st.expander("See raw response"):
            st.code(text[:500])
        return []
        
    except Exception as e:
        st.error(f"⚠️ Error: {type(e).__name__} - {str(e)}")
        return []

def get_brand_search_recommendations(zipcode, brand_query):
    """Search for specific beer brands"""
    
    if not processing_model:
        st.error(f"⚠️ AI model not available: {gemini_error}")
        return []
    
    prompt = f"""Act as a beer sommelier. The user is looking for "{brand_query}" or very similar beers available near zipcode {zipcode}.

Return 3 relevant options (the specific beer if available, or closest matches).

Return ONLY a valid JSON array of 3 objects with this exact format:
[{{"name": "Beer Name", "brand": "Brand Name", "calories": "150", "abv": "5.5%", "description": "A crisp and refreshing beer", "price_range": "$$", "where_to_buy": "Total Wine, BevMo"}}]

Do not include any markdown formatting, code blocks, or explanations. Just the JSON array."""
    
    try:
        response = processing_model.generate_content(prompt)
        
        if not response or not response.text:
            st.error("⚠️ API returned empty response")
            return []
        
        text = response.text.strip()
        
        # Clean markdown
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        
        beers = json.loads(text)
        
        if not isinstance(beers, list) or len(beers) == 0:
            st.error("⚠️ API returned invalid or empty results")
            return []
        
        for beer in beers:
            ensure_beer_image(beer)
        
        return beers
        
    except json.JSONDecodeError:
        st.error(f"⚠️ Failed to parse AI response")
        with st.expander("See raw response"):
            st.code(text[:500])
        return []
        
    except Exception as e:
        st.error(f"⚠️ Error: {type(e).__name__} - {str(e)}")
        return []

@st.cache_data
def render_beer_card_html(name, brand, image, abv, calories, price_range, description, where_to_buy):
    """Cached beer card rendering - pass individual params for better caching"""
    img = f'<img src="{image}" class="beer-image">' if image else ""
    return f"""
    <div class="beer-card">
        {img}
        <div class="beer-title">{name}</div>
        <div class="beer-brand">{brand}</div>
        <div class="beer-metrics">
            <div><div class="metric-value">{abv}</div><div class="metric-label">ABV</div></div>
            <div><div class="metric-value">{calories}</div><div class="metric-label">Cals</div></div>
            <div><div class="metric-value">{price_range}</div><div class="metric-label">Price</div></div>
        </div>
        <div style="color: #ccc; font-size: 0.9rem; line-height: 1.4; margin-bottom: 10px;">{description}</div>
        <div style="color: #d4a574; font-size: 0.8rem;">📍 {where_to_buy}</div>
    </div>
    """.replace('\n', '')

# --- Session State Initialization ---
if 'step' not in st.session_state: 
    st.session_state.step = 0
if 'user_data' not in st.session_state: 
    st.session_state.user_data = {
        'name': 'Sats', 
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

def main():
    inject_mobile_css()
    
    # Debug toggle
    if st.sidebar.button("Toggle Debug"):
        st.session_state.show_debug = not st.session_state.show_debug
        st.rerun()
    
    render_debug_panel()
    
    # Header Nav
    if st.session_state.step > 0:
        c1, c2, c3 = st.columns([1, 2, 1])
        with c1:
            if st.button("←"):
                if st.session_state.step == 3:
                    st.session_state.step = 1
                    st.session_state.rec_beers = []
                    st.session_state.user_data['brand_query'] = None
                    st.session_state.user_data['mood'] = ''
                    st.session_state.user_data['search_type'] = None
                    st.rerun()
                elif st.session_state.step == 2 and st.session_state.user_data.get('search_type') == 'brand':
                    st.session_state.step = 1
                    st.session_state.user_data['brand_query'] = None
                    st.session_state.user_data['search_type'] = None
                    st.rerun()
                else:
                    st.session_state.step = max(0, st.session_state.step - 1)
                    st.rerun()
        with c3:
            if st.session_state.saved_beers and st.session_state.step != 4:
                if st.button("★"):
                    st.session_state.step = 4
                    st.rerun()

    # Step 0: Welcome
    if st.session_state.step == 0:
        st.markdown('<div style="height: 60px;"></div>', unsafe_allow_html=True)
        render_logo()
        st.markdown('<h1 class="big-greeting">Beer Finder</h1>', unsafe_allow_html=True)
        st.markdown('<p class="gold-text">Your pocket sommelier.</p>', unsafe_allow_html=True)
        
        if gemini_error:
            st.warning(f"⚠️ {gemini_error}")
            st.info("The app may not work correctly. Please check your API configuration.")
        
        st.markdown('<div style="height: 30px;"></div>', unsafe_allow_html=True)
        
        name_val = st.text_input("YOUR NAME", value="Sats", placeholder="Enter your name", max_chars=35)
        zip_val = st.text_input("ZIP CODE", placeholder="e.g. 90210", max_chars=5)
        
        if st.button("ENTER"):
            if len(zip_val) == 5:
                st.session_state.user_data['name'] = name_val[:35]
                st.session_state.user_data['zipcode'] = zip_val
                st.session_state.step = 1
                st.rerun()
            else:
                st.error("Please enter a valid 5-digit zip.")
        
        render_footer()

    # Step 1: Choose Search Type
    elif st.session_state.step == 1:
        greet, time = get_greeting(st.session_state.user_data['zipcode'])
        name = st.session_state.user_data.get('name', 'Friend')
        
        # Display GIF with caching
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
        
        col1, col2 = st.columns(2)
        
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
        
        render_footer()

    # Step 1.5: Input
    elif st.session_state.step == 1.5:
        greet, time = get_greeting(st.session_state.user_data['zipcode'])
        name = st.session_state.user_data.get('name', 'Friend')
        
        st.markdown(f'<div class="big-greeting">{greet}, {name}.</div>', unsafe_allow_html=True)
        
        search_type = st.session_state.user_data.get('search_type')
        
        if search_type == 'mood':
            st.markdown('<div style="height: 20px;"></div>', unsafe_allow_html=True)
            with st.form("mood_form"):
                mood = st.text_input("HOW IS YOUR MOOD?", placeholder="Relaxed, Hyped, Tired...", max_chars=35)
                
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
            with st.form("brand_form"):
                brand_query = st.text_input("ENTER YOUR BEER OF CHOICE", placeholder="Guinness, West Coast IPA...", max_chars=35)
                
                if st.form_submit_button("FIND IT"):
                    if brand_query:
                        st.session_state.user_data['brand_query'] = brand_query
                        st.session_state.user_data['mood'] = None
                        st.session_state.step = 2
                        st.rerun()
                    else:
                        st.error("Please enter a beer name or style")
        
        render_footer()

    # Step 2: Context or Search
    elif st.session_state.step == 2:
        if st.session_state.user_data.get('brand_query'):
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
            with st.form("context"):
                day = st.text_input("HOW WAS YOUR DAY?", placeholder="Long work day, celebrating...", max_chars=35)
                taste = st.text_input("TASTE PREFERENCE?", placeholder="Hoppy, Sweet, Dark, Surprise me...", max_chars=35)
                
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

    # Step 3: Results
    elif st.session_state.step == 3:
        st.markdown('<h3 class="gold-text">Top Picks For You</h3>', unsafe_allow_html=True)
        
        if not st.session_state.rec_beers:
            st.error("No beers found. This might be due to API issues.")
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("TRY AGAIN"):
                    st.session_state.step = 1
                    st.session_state.user_data['search_type'] = None
                    st.session_state.rec_beers = []
                    st.rerun()
            
            with col2:
                if st.button("GO HOME"):
                    st.session_state.step = 0
                    st.session_state.user_data = {
                        'name': 'Sats', 
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
            for beer in st.session_state.rec_beers:
                # Use cached rendering with individual parameters
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
                
                saved = any(b['name'] == beer['name'] for b in st.session_state.saved_beers)
                if not saved:
                    if st.button(f"SAVE", key=beer['name']):
                        st.session_state.saved_beers.append(beer)
                        st.rerun()
                else:
                    st.button("SAVED ✓", disabled=True, key=beer['name'])
        
        render_footer()

    # Step 4: Saved
    elif st.session_state.step == 4:
        st.markdown('<h3 class="gold-text">Your Saved Brews</h3>', unsafe_allow_html=True)
        
        if not st.session_state.saved_beers:
            st.info("No saved beers yet. Find some recommendations first!")
            if st.button("FIND BEERS"):
                st.session_state.step = 1
                st.rerun()
        else:
            for i, beer in enumerate(st.session_state.saved_beers):
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
                if st.button("REMOVE", key=f"rem_{i}"):
                    st.session_state.saved_beers.pop(i)
                    st.rerun()
        
        render_footer()

if __name__ == "__main__":
    main()