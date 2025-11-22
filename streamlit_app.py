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
    initial_sidebar_state="collapsed"  # Better for mobile
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

# Configure Gemini
processing_model = None
if GENAI_AVAILABLE and GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        # Use a valid model name - options: gemini-1.5-pro, gemini-1.5-flash, gemini-2.0-flash
        processing_model = genai.GenerativeModel('gemini-3-pro-preview')
    except Exception as e:
        st.error(f"Failed to configure Gemini: {e}")

# --- Inject Mobile-Friendly CSS ---
def inject_css():
    st.markdown("""
    <style>
        /* Base variables */
        :root {
            --bg-primary: #0a0a0a;
            --bg-secondary: #1a1a1a;
            --bg-card: #141414;
            --text-primary: #ffffff;
            --text-secondary: #a0a0a0;
            --accent-amber: #f4c542;
            --accent-copper: #b87333;
            --accent-gold: #d4a574;
            --border-color: #2a2a2a;
        }
        
        /* Dark theme background */
        .stApp {
            background-color: var(--bg-primary) !important;
        }
        
        /* Make text readable on mobile */
        .stApp, .stMarkdown, p, span, label, .stTextInput label {
            font-size: 16px !important;
            color: var(--text-primary) !important;
        }
        
        /* Beer card styling */
        .beer-card {
            background: linear-gradient(145deg, #1a1a1a 0%, #141414 100%);
            border: 1px solid #2a2a2a;
            border-radius: 16px;
            padding: 20px;
            margin: 15px 0;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
        }
        
        .beer-name {
            font-size: 1.5rem !important;
            font-weight: 700;
            color: #f4c542 !important;
            margin-bottom: 5px;
        }
        
        .beer-brand {
            font-size: 1rem !important;
            color: #d4a574 !important;
            margin-bottom: 15px;
        }
        
        .beer-stats {
            display: flex;
            flex-wrap: wrap;
            gap: 15px;
            margin: 15px 0;
            padding: 15px;
            background: rgba(244, 197, 66, 0.1);
            border-radius: 12px;
        }
        
        .stat-item {
            flex: 1;
            min-width: 80px;
            text-align: center;
        }
        
        .stat-label {
            font-size: 0.75rem !important;
            color: #a0a0a0 !important;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        
        .stat-value {
            font-size: 1.25rem !important;
            font-weight: 600;
            color: #ffffff !important;
        }
        
        .beer-description {
            font-size: 0.95rem !important;
            color: #c0c0c0 !important;
            line-height: 1.6;
            margin: 15px 0;
        }
        
        .beer-info {
            margin-top: 15px;
            padding-top: 15px;
            border-top: 1px solid #2a2a2a;
        }
        
        .info-item {
            margin: 8px 0;
            font-size: 0.9rem !important;
        }
        
        .info-label {
            color: #d4a574 !important;
            font-weight: 600;
        }
        
        .stores-section {
            margin-top: 15px;
            padding: 15px;
            background: rgba(184, 115, 51, 0.1);
            border-radius: 12px;
        }
        
        .stores-header {
            font-size: 0.9rem !important;
            color: #d4a574 !important;
            font-weight: 600;
            margin-bottom: 10px;
        }
        
        .store-item {
            padding: 8px 0;
            border-bottom: 1px solid #2a2a2a;
        }
        
        .store-item:last-child {
            border-bottom: none;
        }
        
        .store-name {
            font-weight: 600;
            color: #ffffff !important;
        }
        
        .store-address {
            font-size: 0.85rem !important;
            color: #a0a0a0 !important;
        }
        
        /* Button styling */
        .stButton > button {
            background: linear-gradient(135deg, #f4c542 0%, #b87333 100%) !important;
            color: #0a0a0a !important;
            border: none !important;
            border-radius: 12px !important;
            font-weight: 600 !important;
            font-size: 1rem !important;
            padding: 12px 24px !important;
            transition: all 0.3s ease !important;
        }
        
        .stButton > button:hover {
            box-shadow: 0 0 25px rgba(244, 197, 66, 0.4) !important;
            transform: translateY(-2px);
        }
        
        /* Input styling */
        .stTextInput > div > div > input {
            background-color: #1a1a1a !important;
            color: #ffffff !important;
            border: 1px solid #2a2a2a !important;
            border-radius: 12px !important;
            font-size: 16px !important;
            padding: 12px !important;
        }
        
        .stTextInput > div > div > input:focus {
            border-color: #f4c542 !important;
            box-shadow: 0 0 10px rgba(244, 197, 66, 0.2) !important;
        }
        
        /* Sidebar styling */
        section[data-testid="stSidebar"] {
            background-color: #141414 !important;
        }
        
        section[data-testid="stSidebar"] .stMarkdown {
            color: #ffffff !important;
        }
        
        /* Mobile responsiveness */
        @media (max-width: 768px) {
            .beer-card {
                padding: 15px;
                margin: 10px 0;
            }
            
            .beer-name {
                font-size: 1.25rem !important;
            }
            
            .beer-stats {
                gap: 10px;
            }
            
            .stat-item {
                min-width: 70px;
            }
        }
        
        /* Hide Streamlit branding */
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        
        /* Title styling */
        h1, h2, h3 {
            color: #f4c542 !important;
        }
        
        /* Toast/success messages */
        .stSuccess, .stInfo, .stWarning, .stError {
            font-size: 14px !important;
        }
    </style>
    """, unsafe_allow_html=True)

# --- Helper Functions ---

def google_custom_search(query, num=1):
    """Perform Google Custom Search for images."""
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
        st.error("Gemini API not configured. Please set GEMINI_API_KEY in Secrets.")
        return []

    prompt = f"""You are a helpful assistant specializing in healthy, low-calorie beer options.

User query: "{query}"
Target zipcode: {zipcode}

Return ONLY valid JSON (no markdown, no code blocks): an array of 3 beer objects with these exact fields:
- name: string (beer name)
- brand: string (brewery/brand name)  
- calories: string (e.g., "95 cal")
- carbs: string (e.g., "2.6g")
- abv: string (e.g., "4.2%")
- description: string (2-3 sentences about the beer)
- price_range: string (e.g., "$8-12 per 6-pack")
- where_to_buy: string (general availability info)
- stores: array of objects with name, address, distance (nearby stores)

Example format:
[{{"name": "Beer Name", "brand": "Brand", "calories": "95 cal", "carbs": "2.6g", "abv": "4.2%", "description": "Description here.", "price_range": "$8-12", "where_to_buy": "Most grocery stores", "stores": [{{"name": "Store", "address": "123 Main St", "distance": "0.5 mi"}}]}}]
"""

    try:
        response = processing_model.generate_content(prompt)
        text = response.text.strip()
        
        # Clean markdown code blocks if present
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        
        beers = json.loads(text)
        
        # Ensure images for each beer
        for beer in beers:
            ensure_beer_image(beer)
            
        return beers
    except json.JSONDecodeError as e:
        st.error(f"Failed to parse AI response: {e}")
        st.code(text if 'text' in dir() else "No response")
        return []
    except Exception as e:
        st.error(f"AI Error: {e}")
        return []

def render_beer_card(beer, index, show_save=True, show_remove=False):
    """Render a beer card using Streamlit components for reliability."""
    
    with st.container():
        # Card HTML
        stats_html = ""
        if beer.get('calories'):
            stats_html += f'<div class="stat-item"><div class="stat-label">Calories</div><div class="stat-value">{beer["calories"]}</div></div>'
        if beer.get('carbs'):
            stats_html += f'<div class="stat-item"><div class="stat-label">Carbs</div><div class="stat-value">{beer["carbs"]}</div></div>'
        if beer.get('abv'):
            stats_html += f'<div class="stat-item"><div class="stat-label">ABV</div><div class="stat-value">{beer["abv"]}</div></div>'
        
        stores_html = ""
        if beer.get('stores'):
            store_items = ""
            for store in beer['stores'][:3]:  # Limit to 3 stores
                store_items += f'''
                <div class="store-item">
                    <div class="store-name">{store.get("name", "N/A")}</div>
                    <div class="store-address">📍 {store.get("address", "")} ({store.get("distance", "")})</div>
                </div>
                '''
            stores_html = f'''
            <div class="stores-section">
                <div class="stores-header">📍 Available Nearby:</div>
                {store_items}
            </div>
            '''
        
        card_html = f'''
        <div class="beer-card">
            <div class="beer-name">{beer.get("name", "Unknown Beer")}</div>
            <div class="beer-brand">{beer.get("brand", "Craft Beer")}</div>
            <div class="beer-stats">{stats_html}</div>
            <div class="beer-description">{beer.get("description", "")}</div>
            <div class="beer-info">
                {"<div class='info-item'><span class='info-label'>Price:</span> " + beer["price_range"] + "</div>" if beer.get("price_range") else ""}
                {"<div class='info-item'><span class='info-label'>Where to Buy:</span> " + beer["where_to_buy"] + "</div>" if beer.get("where_to_buy") else ""}
            </div>
            {stores_html}
        </div>
        '''
        
        st.markdown(card_html, unsafe_allow_html=True)
        
        # Action buttons
        col1, col2, col3 = st.columns([1, 1, 2])
        with col1:
            if show_save:
                if st.button("💾 Save", key=f"save_{index}_{beer.get('name', '')}"):
                    save_beer(beer)
        with col2:
            if show_remove:
                if st.button("🗑️ Remove", key=f"remove_{index}_{beer.get('name', '')}"):
                    remove_beer(beer)
                    st.rerun()

def save_beer(beer):
    """Save beer to selected list."""
    if 'selected_beers' not in st.session_state:
        st.session_state.selected_beers = []
    
    # Check for duplicates
    if not any(b.get('name') == beer.get('name') for b in st.session_state.selected_beers):
        st.session_state.selected_beers.append(beer)
        st.toast(f"✅ Saved {beer.get('name')}!")
    else:
        st.toast("Already in your list!")

def remove_beer(beer):
    """Remove beer from selected list."""
    if 'selected_beers' in st.session_state:
        st.session_state.selected_beers = [
            b for b in st.session_state.selected_beers 
            if b.get('name') != beer.get('name')
        ]
        st.toast(f"Removed {beer.get('name')}")

# --- Session State Initialization ---
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

# --- Pages ---

def login_screen():
    inject_css()
    
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
                st.success(f"🔐 Your code: **{code}** (Demo mode)")
                st.session_state.login_step = 'code'
                st.rerun()
            else:
                st.error("Please enter a valid email address.")
                
    elif st.session_state.login_step == 'code':
        st.info(f"📬 Code sent to: {st.session_state.email}")
        
        code_input = st.text_input(
            "🔢 Enter 6-digit Code", 
            value=st.session_state.expected_code,  # Auto-fill for demo
            max_chars=6
        )
        
        zip_input = st.text_input(
            "📍 Your Zipcode", 
            value=st.session_state.zipcode
        )
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ Verify", type="primary", use_container_width=True):
                if code_input == st.session_state.expected_code:
                    st.session_state.authenticated = True
                    st.session_state.zipcode = zip_input
                    st.rerun()
                else:
                    st.error("Invalid code. Please try again.")
        with col2:
            if st.button("⬅️ Back", use_container_width=True):
                st.session_state.login_step = 'email'
                st.rerun()

def main_app():
    inject_css()
    
    # Sidebar
    with st.sidebar:
        st.markdown(f"### 👋 Welcome!")
        st.markdown(f"**{st.session_state.email.split('@')[0]}**")
        st.markdown(f"📍 {st.session_state.zipcode}")
        
        st.markdown("---")
        
        page = st.radio(
            "Navigation",
            ["🔍 Find Beers", "📋 My List"],
            label_visibility="collapsed"
        )
        
        st.markdown("---")
        
        if st.button("🚪 Logout", use_container_width=True):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
    
    # Main content
    if page == "🔍 Find Beers":
        search_page()
    else:
        selected_page()

def search_page():
    st.title("🔍 Find Healthy Beers")
    
    query = st.text_input(
        "What are you looking for?",
        placeholder="e.g., low calorie IPA, gluten free lager, light beer"
    )
    
    if st.button("🍺 Search", type="primary", use_container_width=True):
        if not query:
            st.warning("Please enter a search term.")
        elif not processing_model:
            st.error("⚠️ Gemini API not configured. Add GEMINI_API_KEY to your Hugging Face Secrets.")
        else:
            with st.spinner("🔍 Finding the best beers for you..."):
                results = get_ai_recommendations(query, st.session_state.zipcode)
                st.session_state.search_results = results
    
    # Display Results
    if st.session_state.search_results:
        st.markdown("---")
        st.subheader(f"Found {len(st.session_state.search_results)} recommendations")
        
        for i, beer in enumerate(st.session_state.search_results):
            render_beer_card(beer, i, show_save=True, show_remove=False)
    elif not processing_model:
        st.info("👆 Configure your Gemini API key to start searching!")

def selected_page():
    st.title("📋 Your Selected Beers")
    
    if not st.session_state.selected_beers:
        st.info("No beers saved yet. Go find some! 🍺")
        return
    
    st.markdown(f"**{len(st.session_state.selected_beers)} beer(s) saved**")
    st.markdown("---")
    
    for i, beer in enumerate(st.session_state.selected_beers):
        render_beer_card(beer, i, show_save=False, show_remove=True)

# --- Main Entry Point ---
if __name__ == "__main__":
    if st.session_state.authenticated:
        main_app()
    else:
        login_screen()