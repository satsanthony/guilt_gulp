import streamlit as st
import os
import json
import random
import requests

# --- Configuration & Setup ---
st.set_page_config(
    page_title="Beer Finder",
    page_icon="🍺",
    layout="wide",
    initial_sidebar_state="collapsed"
)

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

# API Keys - For HuggingFace Spaces, use Secrets
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
GOOGLE_CSE_API_KEY = os.getenv('GOOGLE_CSE_API_KEY')
GOOGLE_CSE_CX = os.getenv('GOOGLE_CSE_CX')

# Configure Gemini - Use correct model name
processing_model = None
if GENAI_AVAILABLE and GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        # Valid models: gemini-1.5-pro, gemini-1.5-flash, gemini-2.0-flash-exp
        processing_model = genai.GenerativeModel('gemini-3-pro-preview')
    except Exception as e:
        st.error(f"Failed to configure Gemini: {e}")

# --- COMPLETE CSS INJECTION ---
def inject_custom_css():
    """Inject all custom CSS directly into Streamlit."""
    st.markdown("""
    <style>
        /* === DARK THEME VARIABLES === */
        :root {
            --bg-primary: #0a0a0a;
            --bg-secondary: #1a1a1a;
            --bg-tertiary: #2a2a2a;
            --bg-card: rgba(30, 30, 30, 0.95);
            --accent-amber: #d4a574;
            --accent-gold: #f4c542;
            --accent-copper: #b87333;
            --text-primary: #f5f5f5;
            --text-secondary: #cccccc;
            --text-muted: #999999;
            --border-color: rgba(212, 165, 116, 0.2);
            --border-hover: rgba(212, 165, 116, 0.4);
        }
        
        /* === STREAMLIT OVERRIDES === */
        .stApp {
            background-color: var(--bg-primary) !important;
            background-image: 
                radial-gradient(circle at 20% 50%, rgba(212, 165, 116, 0.05) 0%, transparent 50%),
                radial-gradient(circle at 80% 80%, rgba(184, 115, 51, 0.05) 0%, transparent 50%);
        }
        
        /* Hide Streamlit elements */
        #MainMenu, footer, header {visibility: hidden;}
        .stDeployButton {display: none;}
        
        /* Make all text readable */
        .stApp, .stMarkdown, p, span, label, div {
            color: var(--text-primary) !important;
        }
        
        h1, h2, h3, h4, h5, h6 {
            color: var(--accent-gold) !important;
        }
        
        /* Input fields */
        .stTextInput > div > div > input {
            background-color: var(--bg-tertiary) !important;
            color: var(--text-primary) !important;
            border: 2px solid var(--border-color) !important;
            border-radius: 12px !important;
            font-size: 16px !important;
            padding: 14px 16px !important;
        }
        
        .stTextInput > div > div > input:focus {
            border-color: var(--accent-amber) !important;
            box-shadow: 0 0 20px rgba(212, 165, 116, 0.3) !important;
        }
        
        .stTextInput > div > div > input::placeholder {
            color: var(--text-muted) !important;
        }
        
        /* Buttons */
        .stButton > button {
            background: linear-gradient(135deg, var(--accent-amber) 0%, var(--accent-copper) 100%) !important;
            color: var(--bg-primary) !important;
            border: none !important;
            border-radius: 12px !important;
            font-weight: 600 !important;
            font-size: 1rem !important;
            padding: 14px 28px !important;
            min-height: 48px !important;
            transition: all 0.3s ease !important;
        }
        
        .stButton > button:hover {
            transform: translateY(-2px) !important;
            box-shadow: 0 0 25px rgba(244, 197, 66, 0.4) !important;
        }
        
        /* Sidebar */
        section[data-testid="stSidebar"] {
            background-color: var(--bg-secondary) !important;
        }
        
        section[data-testid="stSidebar"] * {
            color: var(--text-primary) !important;
        }
        
        /* === BEER CARD STYLES === */
        .beer-card {
            background: var(--bg-card);
            border: 2px solid var(--border-color);
            border-radius: 16px;
            padding: 20px;
            margin: 20px 0;
            transition: all 0.3s ease;
            backdrop-filter: blur(10px);
        }
        
        .beer-card:hover {
            border-color: var(--accent-amber);
            box-shadow: 0 0 30px rgba(212, 165, 116, 0.2);
            transform: translateY(-3px);
        }
        
        .beer-image {
            width: 100%;
            height: 200px;
            object-fit: cover;
            border-radius: 12px;
            margin-bottom: 15px;
            background-color: var(--bg-tertiary);
            background-size: cover;
            background-position: center;
            border: 1px solid var(--border-color);
        }
        
        .beer-image-placeholder {
            width: 100%;
            height: 200px;
            border-radius: 12px;
            margin-bottom: 15px;
            background: linear-gradient(135deg, var(--accent-amber) 0%, var(--accent-copper) 100%);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 4rem;
            color: white;
            font-weight: bold;
        }
        
        .beer-name {
            font-size: 1.5rem !important;
            font-weight: 700 !important;
            color: var(--text-primary) !important;
            margin-bottom: 5px;
        }
        
        .beer-brand {
            font-size: 1rem !important;
            color: var(--accent-gold) !important;
            margin-bottom: 15px;
            font-weight: 500;
        }
        
        .beer-stats {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin: 15px 0;
        }
        
        .stat-item {
            flex: 1;
            min-width: 80px;
            background: linear-gradient(135deg, rgba(42, 42, 42, 0.8), rgba(26, 26, 26, 0.8));
            padding: 12px;
            border-radius: 10px;
            text-align: center;
            border: 1px solid var(--border-color);
        }
        
        .stat-label {
            font-size: 0.75rem !important;
            color: var(--text-muted) !important;
            text-transform: uppercase;
            letter-spacing: 1px;
            font-weight: 600;
        }
        
        .stat-value {
            font-size: 1.2rem !important;
            font-weight: 700 !important;
            color: var(--accent-gold) !important;
            margin-top: 4px;
        }
        
        .beer-description {
            font-size: 0.95rem !important;
            color: var(--text-secondary) !important;
            line-height: 1.6;
            margin: 15px 0;
        }
        
        .beer-info {
            background: linear-gradient(135deg, rgba(42, 42, 42, 0.6), rgba(26, 26, 26, 0.6));
            padding: 15px;
            border-radius: 10px;
            margin: 15px 0;
            border: 1px solid var(--border-color);
        }
        
        .info-item {
            margin: 8px 0;
            font-size: 0.9rem !important;
            color: var(--text-secondary) !important;
        }
        
        .info-label {
            font-weight: 600 !important;
            color: var(--accent-amber) !important;
        }
        
        .stores-section {
            margin-top: 15px;
            padding: 15px;
            background: linear-gradient(135deg, rgba(42, 42, 42, 0.6), rgba(26, 26, 26, 0.6));
            border-radius: 10px;
            border-left: 4px solid var(--accent-amber);
        }
        
        .stores-header {
            font-weight: 600 !important;
            color: var(--accent-gold) !important;
            margin-bottom: 12px;
            font-size: 0.95rem !important;
        }
        
        .store-item {
            padding: 10px 0;
            border-bottom: 1px solid var(--border-color);
        }
        
        .store-item:last-child {
            border-bottom: none;
        }
        
        .store-name {
            font-weight: 600 !important;
            color: var(--text-primary) !important;
            margin-bottom: 4px;
        }
        
        .store-address {
            font-size: 0.85rem !important;
            color: var(--text-secondary) !important;
        }
        
        /* === MOBILE RESPONSIVE === */
        @media (max-width: 768px) {
            .beer-card {
                padding: 15px;
                margin: 15px 0;
            }
            
            .beer-name {
                font-size: 1.25rem !important;
            }
            
            .beer-image, .beer-image-placeholder {
                height: 180px;
            }
            
            .stat-item {
                min-width: 70px;
                padding: 10px;
            }
            
            .stat-value {
                font-size: 1rem !important;
            }
        }
        
        /* Toast messages */
        .stToast {
            background-color: var(--bg-card) !important;
            color: var(--text-primary) !important;
        }
    </style>
    """, unsafe_allow_html=True)

# --- Helper Functions ---

def google_custom_search(query, num=1):
    """Perform Google Custom Search for beer images."""
    if not GOOGLE_CSE_API_KEY or not GOOGLE_CSE_CX:
        return None
    try:
        params = {
            'key': GOOGLE_CSE_API_KEY,
            'cx': GOOGLE_CSE_CX,
            'q': query,
            'num': num,
            'searchType': 'image',
            'safe': 'active'
        }
        resp = requests.get('https://www.googleapis.com/customsearch/v1', params=params, timeout=10)
        if resp.status_code == 200:
            items = resp.json().get('items', [])
            if items:
                return items[0].get('link')
    except Exception as e:
        print(f"Image search error: {e}")
    return None

def ensure_beer_image(beer):
    """Add image URL to beer if missing."""
    if not beer.get('image'):
        query = f"{beer.get('name', '')} {beer.get('brand', '')} beer bottle"
        image_url = google_custom_search(query)
        if image_url:
            beer['image'] = image_url
    return beer

def get_ai_recommendations(query, zipcode):
    """Get beer recommendations from Gemini."""
    if not processing_model:
        st.error("⚠️ Gemini API not configured. Please set GEMINI_API_KEY.")
        return []

    prompt = f"""You are a helpful assistant specializing in healthy, low-calorie beer options.

User query: "{query}"
Target zipcode: {zipcode}

Return ONLY a valid JSON array (no markdown, no code blocks, no extra text) of exactly 3 beer objects.
Each object must have these exact fields:
- "name": string (beer name)
- "brand": string (brewery name)  
- "calories": string (e.g., "95 cal")
- "carbs": string (e.g., "2.6g")
- "abv": string (e.g., "4.2%")
- "description": string (2-3 sentences)
- "price_range": string (e.g., "$8-12 per 6-pack")
- "where_to_buy": string (general availability)
- "stores": array of objects, each with "name", "address", "distance"

Example:
[{{"name":"Michelob Ultra","brand":"Anheuser-Busch","calories":"95 cal","carbs":"2.6g","abv":"4.2%","description":"A light lager.","price_range":"$9-12","where_to_buy":"Most stores","stores":[{{"name":"Whole Foods","address":"123 Main St","distance":"0.5 mi"}}]}}]

IMPORTANT: Return ONLY the JSON array, nothing else."""

    try:
        response = processing_model.generate_content(prompt)
        text = response.text.strip()
        
        # Clean up response - remove markdown code blocks
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            parts = text.split("```")
            if len(parts) >= 2:
                text = parts[1].strip()
        
        # Remove any leading/trailing whitespace or newlines
        text = text.strip()
        
        # Parse JSON
        beers = json.loads(text)
        
        # Ensure each beer has an image
        for beer in beers:
            ensure_beer_image(beer)
            
        return beers
        
    except json.JSONDecodeError as e:
        st.error(f"❌ Failed to parse AI response as JSON")
        with st.expander("Debug: Raw Response"):
            st.code(text if 'text' in dir() else "No response text")
        return []
    except Exception as e:
        st.error(f"❌ AI Error: {str(e)}")
        return []

def render_beer_card_html(beer):
    """Generate complete HTML for a beer card - MUST BE SINGLE LINE for st.markdown."""
    
    # Handle image
    if beer.get('image'):
        image_html = f'<img src="{beer["image"]}" class="beer-image" alt="{beer.get("name", "Beer")}" onerror="this.style.display=\'none\'">'
    else:
        initial = beer.get('name', 'B')[0].upper()
        image_html = f'<div class="beer-image-placeholder">{initial}</div>'
    
    # Stats
    stats_items = []
    if beer.get('calories'):
        stats_items.append(f'<div class="stat-item"><div class="stat-label">Calories</div><div class="stat-value">{beer["calories"]}</div></div>')
    if beer.get('carbs'):
        stats_items.append(f'<div class="stat-item"><div class="stat-label">Carbs</div><div class="stat-value">{beer["carbs"]}</div></div>')
    if beer.get('abv'):
        stats_items.append(f'<div class="stat-item"><div class="stat-label">ABV</div><div class="stat-value">{beer["abv"]}</div></div>')
    stats_html = ''.join(stats_items)
    
    # Info section
    info_items = []
    if beer.get('price_range'):
        info_items.append(f'<div class="info-item"><span class="info-label">Price:</span> {beer["price_range"]}</div>')
    if beer.get('where_to_buy'):
        info_items.append(f'<div class="info-item"><span class="info-label">Where to Buy:</span> {beer["where_to_buy"]}</div>')
    info_html = ''.join(info_items)
    
    # Stores section
    stores_html = ""
    if beer.get('stores') and len(beer['stores']) > 0:
        store_items = []
        for store in beer['stores'][:3]:
            store_name = store.get('name', 'N/A')
            store_addr = store.get('address', '')
            store_dist = store.get('distance', '')
            addr_text = f" - {store_addr}" if store_addr else ""
            dist_text = f" ({store_dist})" if store_dist else ""
            store_items.append(f'<div class="store-item"><div class="store-name">{store_name}</div><div class="store-address">📍{addr_text}{dist_text}</div></div>')
        stores_html = f'<div class="stores-section"><div class="stores-header">📍 Available Nearby:</div>{"".join(store_items)}</div>'
    
    # Build complete card - ALL ON ONE LINE to prevent Streamlit from breaking it
    card_html = f'<div class="beer-card">{image_html}<div class="beer-name">{beer.get("name", "Unknown Beer")}</div><div class="beer-brand">{beer.get("brand", "Craft Beer")}</div><div class="beer-stats">{stats_html}</div><div class="beer-description">{beer.get("description", "")}</div><div class="beer-info">{info_html}</div>{stores_html}</div>'
    
    return card_html

# --- Session State ---
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'login_step' not in st.session_state:
    st.session_state.login_step = 'email'
if 'email' not in st.session_state:
    st.session_state.email = ''
if 'expected_code' not in st.session_state:
    st.session_state.expected_code = ''
if 'zipcode' not in st.session_state:
    st.session_state.zipcode = '90049'
if 'selected_beers' not in st.session_state:
    st.session_state.selected_beers = []
if 'search_results' not in st.session_state:
    st.session_state.search_results = []
if 'current_page' not in st.session_state:
    st.session_state.current_page = 'search'

# --- Pages ---

def login_screen():
    inject_custom_css()
    
    st.title("🍺 Beer Finder")
    st.markdown("*Find healthy, low-calorie beers near you*")
    st.markdown("---")
    
    if st.session_state.login_step == 'email':
        email = st.text_input("📧 Email Address", placeholder="your@email.com")
        
        if st.button("Send Code", type="primary", use_container_width=True):
            if '@' in email and '.' in email:
                code = str(random.randint(100000, 999999))
                st.session_state.email = email
                st.session_state.expected_code = code
                st.success(f"🔐 Demo Mode - Your code: **{code}**")
                st.session_state.login_step = 'code'
                st.rerun()
            else:
                st.error("Please enter a valid email address.")
                
    elif st.session_state.login_step == 'code':
        st.info(f"📬 Code sent to: **{st.session_state.email}**")
        
        code_input = st.text_input("🔢 Enter 6-digit Code", value=st.session_state.expected_code, max_chars=6)
        zip_input = st.text_input("📍 Your Zipcode", value=st.session_state.zipcode)
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ Verify", type="primary", use_container_width=True):
                if code_input == st.session_state.expected_code:
                    st.session_state.authenticated = True
                    st.session_state.zipcode = zip_input
                    st.rerun()
                else:
                    st.error("Invalid code.")
        with col2:
            if st.button("⬅️ Back", use_container_width=True):
                st.session_state.login_step = 'email'
                st.rerun()

def main_app():
    inject_custom_css()
    
    # Initialize page state
    if 'current_page' not in st.session_state:
        st.session_state.current_page = 'search'
    
    # TOP NAVIGATION BAR (visible on all screen sizes)
    st.markdown(f"""
    <div style="display: flex; justify-content: space-between; align-items: center; padding: 10px 0; margin-bottom: 10px; border-bottom: 2px solid rgba(212, 165, 116, 0.2);">
        <div style="color: var(--accent-gold); font-weight: 600;">👋 {st.session_state.email.split('@')[0]} | 📍 {st.session_state.zipcode}</div>
    </div>
    """, unsafe_allow_html=True)
    
    # Navigation buttons in main content area
    nav_col1, nav_col2, nav_col3 = st.columns([2, 2, 1])
    
    with nav_col1:
        if st.button("🔍 Find Beers", use_container_width=True, type="primary" if st.session_state.current_page == 'search' else "secondary"):
            st.session_state.current_page = 'search'
            st.rerun()
    
    with nav_col2:
        # Show count of saved beers
        saved_count = len(st.session_state.selected_beers)
        btn_label = f"📋 My List ({saved_count})" if saved_count > 0 else "📋 My List"
        if st.button(btn_label, use_container_width=True, type="primary" if st.session_state.current_page == 'selected' else "secondary"):
            st.session_state.current_page = 'selected'
            st.rerun()
    
    with nav_col3:
        if st.button("🚪 Logout", use_container_width=True):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
    
    st.markdown("---")
    
    # Sidebar (optional, for larger screens)
    with st.sidebar:
        st.markdown(f"### 👋 Welcome!")
        st.markdown(f"**{st.session_state.email.split('@')[0]}**")
        st.markdown(f"📍 Zipcode: {st.session_state.zipcode}")
        st.markdown("---")
        st.markdown(f"**Saved Beers:** {len(st.session_state.selected_beers)}")
    
    # Page content based on current_page state
    if st.session_state.current_page == 'search':
        search_page()
    else:
        selected_page()

def search_page():
    st.title("🔍 Find Healthy Beers")
    
    query = st.text_input("What are you looking for?", placeholder="e.g., low calorie IPA, gluten free lager")
    
    if st.button("🍺 Search", type="primary", use_container_width=True):
        if not query:
            st.warning("Please enter a search term.")
        elif not processing_model:
            st.error("⚠️ Gemini API not configured. Add GEMINI_API_KEY to Secrets.")
        else:
            with st.spinner("🔍 Finding the best beers for you..."):
                results = get_ai_recommendations(query, st.session_state.zipcode)
                st.session_state.search_results = results
    
    # Display Results
    if st.session_state.search_results:
        st.markdown("---")
        st.subheader(f"🍺 Found {len(st.session_state.search_results)} recommendations")
        
        for i, beer in enumerate(st.session_state.search_results):
            # Render the HTML card
            st.markdown(render_beer_card_html(beer), unsafe_allow_html=True)
            
            # Save button (Streamlit native)
            if st.button(f"💾 Save to My List", key=f"save_{i}"):
                if not any(b.get('name') == beer.get('name') for b in st.session_state.selected_beers):
                    st.session_state.selected_beers.append(beer)
                    st.toast(f"✅ Saved {beer.get('name')}!")
                else:
                    st.toast("Already in your list!")

def selected_page():
    st.title("📋 Your Selected Beers")
    
    if not st.session_state.selected_beers:
        st.info("🍺 No beers saved yet. Go search for some!")
        return
    
    st.markdown(f"**{len(st.session_state.selected_beers)} beer(s) saved**")
    st.markdown("---")
    
    for i, beer in enumerate(st.session_state.selected_beers):
        st.markdown(render_beer_card_html(beer), unsafe_allow_html=True)
        
        if st.button(f"🗑️ Remove", key=f"remove_{i}"):
            st.session_state.selected_beers = [b for b in st.session_state.selected_beers if b.get('name') != beer.get('name')]
            st.rerun()

# --- Main ---
if __name__ == "__main__":
    if st.session_state.authenticated:
        main_app()
    else:
        login_screen()