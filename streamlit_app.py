import streamlit as st
import os
import json
import random
import requests
import datetime
from datetime import timedelta
import base64
from io import BytesIO
from PIL import Image

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

# Configure Gemini
processing_model = None

if GENAI_AVAILABLE and GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        # Text/Reasoning Model
        processing_model = genai.GenerativeModel('gemini-3-pro-preview') 
    except Exception as e:
        st.error(f"Failed to configure Gemini: {e}")

# --- MOBILE STYLED CSS ---
def inject_mobile_css():
    st.markdown("""
    <style>
        /* === THEME VARIABLES === */
        :root {
            --bg-app: #000000;
            --bg-card: #1a1a1a;
            --text-main: #ffffff;
            --text-sub: #b0b0b0;
            --accent: #d4a574; /* Amber */
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

        /* Gold Color Utility Class */
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
        
        /* Gold Labels */
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

        /* === CHOICE BUTTONS === */
        .choice-button {
            width: 100%;
            padding: 20px;
            margin: 10px 0;
            border-radius: 15px;
            border: 2px solid var(--accent);
            background: transparent;
            color: var(--accent);
            font-size: 1.1rem;
            font-weight: 600;
            text-transform: uppercase;
            cursor: pointer;
            transition: all 0.3s ease;
            text-align: center;
        }

        .choice-button:hover {
            background: var(--accent);
            color: #000;
        }

        .choice-subtitle {
            font-size: 0.8rem;
            color: var(--text-sub);
            margin-top: 5px;
            text-transform: none;
            font-weight: 400;
        }

        /* === BUTTONS (CENTERED) === */
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
        
        /* Form Submit Button Centering */
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

        /* Footer */
        .footer {
            margin-top: 50px;
            text-align: center;
            font-size: 0.75rem;
            color: var(--accent) !important;
            padding: 20px 0;
            border-top: 1px solid #333;
        }
    </style>
    """, unsafe_allow_html=True)

# --- Helper Functions ---

def render_logo():
    """Render logo.png instead of emoji"""
    logo_path = os.path.join(os.path.dirname(__file__), "static", "images", "logo.png")
    if os.path.exists(logo_path):
        with open(logo_path, "rb") as f:
            data = f.read()
            encoded = base64.b64encode(data).decode()
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

def get_greeting(zipcode):
    """Simple Time Greeting"""
    greeting = "Hello"
    time_str = ""
    try:
        # Heuristic timezone offset
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

def google_custom_search(query, num=1):
    if not GOOGLE_CSE_API_KEY or not GOOGLE_CSE_CX: return None
    try:
        params = {'key': GOOGLE_CSE_API_KEY, 'cx': GOOGLE_CSE_CX, 'q': query, 'num': num, 'searchType': 'image'}
        resp = requests.get('https://www.googleapis.com/customsearch/v1', params=params, timeout=5)
        if resp.status_code == 200:
            items = resp.json().get('items', [])
            if items: return items[0].get('link')
    except: pass
    return None

def ensure_beer_image(beer):
    if not beer.get('image'):
        query = f"{beer.get('name', '')} {beer.get('brand', '')} beer bottle"
        image_url = google_custom_search(query)
        if image_url: beer['image'] = image_url
    return beer

def get_ai_recommendations(zipcode, mood, day_context, taste_pref):
    if not processing_model: return []
    
    # Trim inputs to 35 chars
    s_zip = str(zipcode)[:5]
    s_mood = str(mood)[:35]
    s_day = str(day_context)[:35]
    s_taste = str(taste_pref)[:35]

    prompt = f"""
    Act as a beer sommelier. Suggest 3 beers based on:
    Zip: {s_zip}, Mood: {s_mood}, Day: {s_day}, Taste: {s_taste}.
    
    Return ONLY a valid JSON array of 3 objects:
    [{{"name": "", "brand": "", "calories": "", "abv": "", "description": "short & punchy", "price_range": "", "where_to_buy": "stores"}}]
    """
    
    try:
        response = processing_model.generate_content(prompt)
        text = response.text.strip()
        if "```" in text: text = text.split("```")[1].replace("json", "").strip()
        beers = json.loads(text)
        for beer in beers: ensure_beer_image(beer)
        return beers
    except: return []

def render_beer_card_html(beer):
    img = f'<img src="{beer.get("image")}" class="beer-image">' if beer.get("image") else ""
    return f"""
    <div class="beer-card">
        {img}
        <div class="beer-title">{beer.get("name", "Unknown")}</div>
        <div class="beer-brand">{beer.get("brand", "Craft Beer")}</div>
        <div class="beer-metrics">
            <div><div class="metric-value">{beer.get("abv", "?")}</div><div class="metric-label">ABV</div></div>
            <div><div class="metric-value">{beer.get("calories", "?")}</div><div class="metric-label">Cals</div></div>
            <div><div class="metric-value">{beer.get("price_range", "$")}</div><div class="metric-label">Price</div></div>
        </div>
        <div style="color: #ccc; font-size: 0.9rem; line-height: 1.4; margin-bottom: 10px;">{beer.get("description", "")}</div>
        <div style="color: #d4a574; font-size: 0.8rem;">📍 {beer.get("where_to_buy", "Check Local Stores")}</div>
    </div>
    """.replace('\n', '')

# --- Session & Routing ---
if 'step' not in st.session_state: st.session_state.step = 0
if 'user_data' not in st.session_state: 
    st.session_state.user_data = {
        'name': 'Sats', 
        'zipcode': '', 
        'mood': '', 
        'brand_query': None,
        'day': '', 
        'taste': '',
        'search_type': None  # Track which path user chose
    }
if 'rec_beers' not in st.session_state: st.session_state.rec_beers = []
if 'saved_beers' not in st.session_state: st.session_state.saved_beers = []

def main():
    inject_mobile_css()
    
    # Header Nav
    if st.session_state.step > 0:
        c1, c2, c3 = st.columns([1, 2, 1])
        with c1:
            if st.button("←"):
                # Smart back navigation
                if st.session_state.step == 3:
                    st.session_state.step = 1
                    st.session_state.rec_beers = []
                    st.session_state.user_data['brand_query'] = None
                    st.session_state.user_data['mood'] = ''
                    st.session_state.user_data['search_type'] = None
                    st.rerun()
                elif st.session_state.step == 2 and st.session_state.user_data.get('search_type') == 'brand':
                    # If came from brand path, go back to step 1
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

    # Step 0: Welcome / Name / Zip
    if st.session_state.step == 0:
        st.markdown('<div style="height: 60px;"></div>', unsafe_allow_html=True)
        render_logo()
        st.markdown('<h1 class="big-greeting">Beer Finder</h1>', unsafe_allow_html=True)
        st.markdown('<p class="gold-text">Your pocket sommelier.</p>', unsafe_allow_html=True)
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

    # Step 1: Choose Search Type (NEW APPROACH)
    elif st.session_state.step == 1:
        greet, time = get_greeting(st.session_state.user_data['zipcode'])
        name = st.session_state.user_data.get('name', 'Friend')
        
        # Display Beer Pour GIF
        gif_path = os.path.join(os.path.dirname(__file__), "static", "images", "beer.gif.gif")
        if os.path.exists(gif_path):
            with open(gif_path, "rb") as f:
                data = f.read()
                encoded = base64.b64encode(data).decode()
            st.markdown(f"""
                <div style="display: flex; justify-content: center; margin-bottom: 20px;">
                    <img src="data:image/gif;base64,{encoded}" 
                         style="width: 100%; max-height: 250px; object-fit: cover; border-radius: 15px; opacity: 0.8;">
                </div>
            """, unsafe_allow_html=True)
        else:
             st.markdown('<div style="display: flex; justify-content: center; margin-bottom: 20px;"><div style="font-size: 5rem;">🍺</div></div>', unsafe_allow_html=True)
        
        welcome_msg = f"{greet}, {name}."
        
        st.markdown(f'<div class="big-greeting">{welcome_msg}</div>', unsafe_allow_html=True)
        if time:
            st.markdown(f'<p class="gold-text">It is currently {time}</p>', unsafe_allow_html=True)
        
        st.markdown('<div style="height: 30px;"></div>', unsafe_allow_html=True)
        st.markdown('<p class="gold-text" style="font-size: 1.1rem; margin-bottom: 20px;">How would you like to search?</p>', unsafe_allow_html=True)
        
        # Two clear button choices
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("🎭 BY MOOD", key="mood_btn", use_container_width=True):
                st.session_state.user_data['search_type'] = 'mood'
                st.session_state.step = 1.5  # Intermediate step for mood input
                st.rerun()
        
        with col2:
            if st.button("🍺 SPECIFIC BEER", key="brand_btn", use_container_width=True):
                st.session_state.user_data['search_type'] = 'brand'
                st.session_state.step = 1.5  # Intermediate step for brand input
                st.rerun()
        
        render_footer()

    # Step 1.5: Input based on choice
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
        
        render_footer()

    # Step 2: Context or Direct Search
    elif st.session_state.step == 2:
        if st.session_state.user_data.get('brand_query'):
             # Auto-search for specific brand
             brand = st.session_state.user_data.get('brand_query')
             st.session_state.user_data.update({'day': 'Specific Brand Search', 'taste': 'Specific Brand Search'})
             
             search_prompt = f"""
             Act as a beer sommelier. The user is looking specifically for "{brand}" or very similar beers available near zipcode {st.session_state.user_data['zipcode']}.
             Return 3 relevant options (the specific beer if available, or closest matches).
             
             Return ONLY a valid JSON array of 3 objects:
             [{{"name": "", "brand": "", "calories": "", "abv": "", "description": "short & punchy", "price_range": "", "where_to_buy": "stores"}}]
             """
             
             with st.spinner(f"Finding {brand}..."):
                try:
                    response = processing_model.generate_content(search_prompt)
                    text = response.text.strip()
                    if "```" in text: text = text.split("```")[1].replace("json", "").strip()
                    beers = json.loads(text)
                    for beer in beers: ensure_beer_image(beer)
                    st.session_state.rec_beers = beers
                except:
                    st.session_state.rec_beers = []
                    
                st.session_state.step = 3
                st.rerun()
        else:
            # Mood path - ask for context
            st.markdown('<h3 class="gold-text">Tell me more...</h3>', unsafe_allow_html=True)
            with st.form("context"):
                day = st.text_input("HOW WAS YOUR DAY?", placeholder="Long work day, celebrating...", max_chars=35)
                taste = st.text_input("TASTE PREFERENCE?", placeholder="Hoppy, Sweet, Dark, Surprise me...", max_chars=35)
                
                if st.form_submit_button("FIND MY BEER"):
                    st.session_state.user_data.update({'day': day[:35], 'taste': taste[:35]})
                    with st.spinner("Pouring recommendations..."):
                        st.session_state.rec_beers = get_ai_recommendations(
                            st.session_state.user_data['zipcode'],
                            st.session_state.user_data['mood'],
                            day[:35],
                            taste[:35]
                        )
                        st.session_state.step = 3
                        st.rerun()
            
            render_footer()

    # Step 3: Results
    elif st.session_state.step == 3:
        st.markdown('<h3 class="gold-text">Top Picks For You</h3>', unsafe_allow_html=True)
        
        if not st.session_state.rec_beers:
            st.error("Nothing found. Try again.")
            if st.button("RETRY"): 
                st.session_state.step = 1
                st.session_state.user_data['search_type'] = None
                st.rerun()
            
        for beer in st.session_state.rec_beers:
            st.markdown(render_beer_card_html(beer), unsafe_allow_html=True)
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
        for i, beer in enumerate(st.session_state.saved_beers):
            st.markdown(render_beer_card_html(beer), unsafe_allow_html=True)
            if st.button("REMOVE", key=f"rem_{i}"):
                st.session_state.saved_beers.pop(i)
                st.rerun()
        
        render_footer()

if __name__ == "__main__":
    main()