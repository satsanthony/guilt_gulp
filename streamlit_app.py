import streamlit as st
import os
import json
import random
import smtplib
import requests
import google.generativeai as genai
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta

# --- Configuration & Setup ---
st.set_page_config(
    page_title="Beer Finder",
    page_icon="🍺",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Load environment variables (if using python-dotenv, otherwise assumes they are set)
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))
except ImportError:
    pass

# API Keys
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
GOOGLE_CSE_API_KEY = os.getenv('GOOGLE_CSE_API_KEY')
GOOGLE_CSE_CX = os.getenv('GOOGLE_CSE_CX')

# Email Config
SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_EMAIL = os.getenv('SMTP_EMAIL', '')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '')
EMAIL_FROM_NAME = os.getenv('EMAIL_FROM_NAME', 'Beer Finder')

# Configure Gemini
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    processing_model = genai.GenerativeModel('gemini-2.5-pro') # or gemini-pro
else:
    processing_model = None

# Files
SELECTED_BEERS_FILE = 'selected_beers.json'
SYSPROMPT_PATH = os.path.join(os.path.dirname(__file__), 'sysprompt.md')

# --- Helper Functions (Adapted from app.py/login.py) ---

def send_security_code_email(email, code):
    """Send security code to user's email."""
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        return False
    
    try:
        msg = MIMEMultipart()
        msg['From'] = f"{EMAIL_FROM_NAME} <{SMTP_EMAIL}>"
        msg['To'] = email
        msg['Subject'] = "Your Beer Finder Security Code"
        
        body = f"""
        <html>
            <body style="font-family: Arial, sans-serif;">
                <h2>Beer Finder Security Code</h2>
                <p>Your code is: <b>{code}</b></p>
                <p>Valid for 10 minutes.</p>
            </body>
        </html>
        """
        msg.attach(MIMEText(body, 'html'))
        
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"Email error: {e}")
        return False

def google_custom_search(query, num=3):
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
        print(f"Search error: {e}")
    return None

def ensure_beer_image(beer):
    """Enrich beer object with an image if missing."""
    if not beer.get('image'):
        query = f"{beer.get('name', '')} {beer.get('brand', '')} beer bottle"
        image_url = google_custom_search(query)
        if image_url:
            beer['image'] = image_url
    return beer

def get_ai_recommendations(query, zipcode):
    """Get beer recommendations from Gemini."""
    if not processing_model:
        return []

    # Read system prompt
    try:
        with open(SYSPROMPT_PATH, 'r', encoding='utf-8') as f:
            sys_prompt = f.read()
    except:
        sys_prompt = "You are a helpful assistant for healthy beer options."

    prompt = f"""{sys_prompt}
    
    User query: "{query}"
    Target zipcode: {zipcode}
    
    Return ONLY valid JSON: an array of 3 objects with fields: name, brand, calories, carbs, abv, description, price_range, where_to_buy, positive_feedback, negative_feedback, stores (list of objects with name, address, distance).
    """

    try:
        response = processing_model.generate_content(prompt)
        text = response.text
        # Clean markdown code blocks if present
        if "```" in text:
            text = text.split("```")[1].replace("json", "").strip()
        
        beers = json.loads(text)
        # Ensure images
        for beer in beers:
            ensure_beer_image(beer)
        return beers
    except Exception as e:
        st.error(f"AI Error: {e}")
        return []

def load_selected_beers():
    if os.path.exists(SELECTED_BEERS_FILE):
        try:
            with open(SELECTED_BEERS_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return []

def save_selected_beers(beers):
    with open(SELECTED_BEERS_FILE, 'w') as f:
        json.dump(beers, f, indent=2)

# --- Session State Initialization ---
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'login_step' not in st.session_state:
    st.session_state.login_step = 'email' # email or code
if 'email' not in st.session_state:
    st.session_state.email = ''
if 'expected_code' not in st.session_state:
    st.session_state.expected_code = ''
if 'zipcode' not in st.session_state:
    st.session_state.zipcode = '90049'

# --- UI Components ---

def login_screen():
    st.title("🍺 Beer Finder Login")
    
    col1, col2 = st.columns([1, 2])
    with col1:
        if st.session_state.login_step == 'email':
            email = st.text_input("Email Address")
            if st.button("Send Code"):
                if '@' in email:
                    code = str(random.randint(100000, 999999))
                    st.session_state.email = email
                    st.session_state.expected_code = code
                    
                    # Skip sending email for dev/testing
                    # sent = send_security_code_email(email, code)
                    
                    st.success(f"Dev Mode: Code generated: {code}")
                    st.session_state.login_step = 'code'
                    st.rerun()
                else:
                    st.error("Please enter a valid email.")
                    
        elif st.session_state.login_step == 'code':
            st.info(f"Code sent to {st.session_state.email}")
            
            # Auto-populate code for convenience
            default_code = st.session_state.get('expected_code', '')
            code_input = st.text_input("Enter 6-digit Security Code", value=default_code)
            
            zip_input = st.text_input("Enter Zipcode", value=st.session_state.zipcode)
            
            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("Verify"):
                    if code_input == st.session_state.expected_code:
                        st.session_state.authenticated = True
                        st.session_state.zipcode = zip_input
                        st.rerun()
                    else:
                        st.error("Invalid code.")
            with col_b:
                if st.button("Back"):
                    st.session_state.login_step = 'email'
                    st.rerun()


def main_app():
    # Sidebar
    with st.sidebar:
        st.header(f"Welcome, {st.session_state.email.split('@')[0]}")
        st.write(f"📍 {st.session_state.zipcode}")
        page = st.radio("Navigation", ["Find Beers", "Selected List"])
        
        st.divider()
        if st.button("Logout"):
            st.session_state.clear()
            st.rerun()

    # Page Logic
    if page == "Find Beers":
        search_page()
    else:
        selected_page()

def search_page():
    st.title("🔍 Find Healthy Beers")
    
    query = st.text_input("What are you looking for?", placeholder="e.g., low calorie IPA, gluten free lager")
    
    if st.button("Search", type="primary"):
        if not query:
            st.warning("Please enter a search term.")
            return
            
        with st.spinner("Consulting the beer sommelier..."):
            results = get_ai_recommendations(query, st.session_state.zipcode)
            st.session_state.search_results = results
    
    # Display Results
    if 'search_results' in st.session_state and st.session_state.search_results:
        st.subheader("Recommendations")
        
        for beer in st.session_state.search_results:
            with st.expander(f"{beer.get('name')} ({beer.get('calories', 'N/A')})", expanded=True):
                c1, c2 = st.columns([1, 3])
                with c1:
                    if beer.get('image'):
                        st.image(beer['image'], use_container_width=True)
                    else:
                        st.text("No Image")
                
                with c2:
                    st.markdown(f"**Brand:** {beer.get('brand')}")
                    st.markdown(f"_{beer.get('description')}_")
                    st.markdown(f"**Stats:** {beer.get('abv')} ABV | {beer.get('carbs')} Carbs")
                    st.markdown(f"**Why it fits:** {beer.get('positive_feedback')}")
                    
                    if st.button("Save to List", key=f"save_{beer.get('name')}"):
                        current_list = load_selected_beers()
                        # Check for duplicates
                        if not any(b['name'] == beer['name'] for b in current_list):
                            current_list.append(beer)
                            save_selected_beers(current_list)
                            st.toast(f"Saved {beer['name']}!")
                        else:
                            st.toast("Already in your list.")

def selected_page():
    st.title("📋 Your Selected Beers")
    
    beers = load_selected_beers()
    
    if not beers:
        st.info("No beers selected yet. Go search for some!")
        return

    for beer in beers:
        with st.container(border=True):
            c1, c2, c3 = st.columns([1, 3, 1])
            with c1:
                if beer.get('image'):
                    st.image(beer['image'], width=100)
            with c2:
                st.subheader(beer.get('name'))
                st.caption(beer.get('brand'))
                st.write(f"🛒 {beer.get('where_to_buy')}")
            with c3:
                if st.button("Remove", key=f"del_{beer.get('name')}"):
                    new_list = [b for b in beers if b['name'] != beer['name']]
                    save_selected_beers(new_list)
                    st.rerun()

# --- Main Entry Point ---
if __name__ == "__main__":
    if st.session_state.authenticated:
        main_app()
    else:
        login_screen()