"""Flask backend for healthy beer finder application."""

import os
import json
import requests
import os
import google.generativeai as genai
from langsmith import traceable
from langsmith import Client
from flask import Flask, render_template, request, jsonify, send_from_directory, session
from flask_cors import CORS
# import google.generativeai as genai
import anthropic
from werkzeug.utils import secure_filename
from login import init_login, require_auth
from flask import Flask, render_template, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from flask import session

langsmith_client = None
if os.getenv('LANGCHAIN_API_KEY'):
    langsmith_client = Client()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'dev-secret-key-change-in-production')  # Added this
CORS(app)

# Initialize login system
init_login(app)

# Configure API Keys
# GEMINI_API_KEY = None
ANTHROPIC_API_KEY = None
TAVILY_API_KEY = None
GOOGLE_CSE_API_KEY = None
GOOGLE_CSE_CX = None

# Try to load from .env file in parent directory first
try:
    from dotenv import load_dotenv
    # Load from parent directory .env file
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))
    # GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
    #ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
    TAVILY_API_KEY = os.getenv('TAVILY_API_KEY')
    GOOGLE_CSE_API_KEY = os.getenv('GOOGLE_CSE_API_KEY')
    GOOGLE_CSE_CX = os.getenv('GOOGLE_CSE_CX')
except:
    pass

# Fallback to environment variables
# if not GEMINI_API_KEY:
#     GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
#if not ANTHROPIC_API_KEY:
#    ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
if not TAVILY_API_KEY:
    TAVILY_API_KEY = os.getenv('TAVILY_API_KEY')
if not GOOGLE_CSE_API_KEY:
    GOOGLE_CSE_API_KEY = os.getenv('GOOGLE_CSE_API_KEY')
if not GOOGLE_CSE_CX:
    GOOGLE_CSE_CX = os.getenv('GOOGLE_CSE_CX')

if not GOOGLE_CSE_API_KEY or not GOOGLE_CSE_CX:
    print("Warning: GOOGLE_CSE_API_KEY or GOOGLE_CSE_CX not found. Set them in .env or environment.")
else:
    # Basic validation: API keys typically start with 'AIza', CSE cx should NOT
    if GOOGLE_CSE_CX.startswith('AIza'):
        print("Error: GOOGLE_CSE_CX appears to be an API key. It must be your Custom Search Engine ID (cx), not the API key.")

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
# Initialize Gemini for processing search results
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    processing_model = genai.GenerativeModel('gemini-2.5-pro')
else:
    processing_model = None
    print("Warning: GEMINI_API_KEY not found. Processing capabilities will be limited.")

# if ANTHROPIC_API_KEY:
#     processing_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
# else:
#     processing_client = None
#     print("Warning: ANTHROPIC_API_KEY not found. Processing capabilities will be limited.")

# Storage for selected beers (in production, use a database)
# Storage for selected beers (in production, use a database)
selected_beers_file = 'selected_beers.json'
visitor_count_file = 'visitor_count.json'

def get_visitor_count():
    """Get current visitor count."""
    if os.path.exists(visitor_count_file):
        try:
            with open(visitor_count_file, 'r') as f:
                data = json.load(f)
                return data.get('count', 0)
        except:
            return 0
    return 0

def increment_visitor_count():
    """Increment and return visitor count."""
    count = get_visitor_count()
    count += 1
    try:
        with open(visitor_count_file, 'w') as f:
            json.dump({'count': count}, f)
    except Exception as e:
        print(f"Error saving visitor count: {e}")
    return count

_brand_image_cache = {}

_http_headers = {
    'User-Agent': 'BeerFinder/1.0 (+no-reply@example.com)'
}

def _get_text(url, timeout=10):
    try:
        resp = requests.get(url, headers=_http_headers, timeout=timeout)
        resp.raise_for_status()
        return resp.text
    except Exception:
        return None

def extract_og_image(url):
    """Extract OpenGraph image URL from a web page."""
    html = _get_text(url)
    if not html:
        return None
    try:
        import re
        match = re.search(r'<meta[^>]+(?:property|name)=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if match:
            return match.group(1)
        match2 = re.search(r'<meta[^>]+(?:property|name)=["\']og:image:url["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if match2:
            return match2.group(1)
    except Exception:
        return None
    return None

def _hostname(url):
    try:
        from urllib.parse import urlparse
        return urlparse(url).hostname or ''
    except Exception:
        return ''

def _looks_official(url, brand):
    host = (_hostname(url) or '').lower()
    brand_token = (brand or '').lower().replace(' ', '')
    if not host:
        return False
    blocked = (
        'wikipedia.org', 'wikidata.org', 'wikimedia.org', 'facebook.com', 'twitter.com',
        'x.com', 'instagram.com', 'untappd.com', 'ratebeer.com', 'beeradvocate.com',
        'walmart.com', 'amazon.com', 'target.com', 'drizly.com', 'instacart.com',
        'totalwine.com', 'bevmo.com', 'doordash.com', 'ubereats.com', 'postmates.com',
        'yelp.com', 'tripadvisor.com', 'reddit.com', 'pinterest.com', 'youtube.com'
    )
    if any(b in host for b in blocked):
        return False
    return brand_token and brand_token in host

def wikidata_p18_image(wikidata_url):
    """Given a Wikidata entity URL, fetch P18 image and return a thumbnail URL."""
    try:
        import re
        m = re.search(r'/entity/(Q\d+)', wikidata_url)
        if not m:
            return None
        qid = m.group(1)
        entity_resp = requests.get(
            f'https://www.wikidata.org/wiki/Special:EntityData/{qid}.json',
            headers=_http_headers, timeout=8
        )
        entity_resp.raise_for_status()
        edata = entity_resp.json()
        entities = edata.get('entities', {})
        entity = entities.get(qid, {})
        claims = entity.get('claims', {})
        p18 = claims.get('P18')
        if not p18:
            return None
        filename = p18[0].get('mainsnak', {}).get('datavalue', {}).get('value')
        if not filename:
            return None
        commons_params = {
            'action': 'query',
            'prop': 'imageinfo',
            'titles': f'File:{filename}',
            'iiprop': 'url',
            'iiurlwidth': 600,
            'format': 'json'
        }
        c_resp = requests.get('https://commons.wikimedia.org/w/api.php', params=commons_params, headers=_http_headers, timeout=8)
        c_resp.raise_for_status()
        cdata = c_resp.json()
        pages = cdata.get('query', {}).get('pages', {})
        for _pid, page in pages.items():
            infos = page.get('imageinfo')
            if infos:
                info = infos[0]
                return info.get('thumburl') or info.get('url')
    except Exception:
        return None
    return None

@traceable(name="google_find_image_for_beer")
def google_find_image_for_beer(beer):
    """Use Google CSE to find an authentic image from official pages or Wikidata.
    
    Returns tuple (image_url, source_url) or (None, None) if not found.
    """
    if not GOOGLE_CSE_API_KEY or not GOOGLE_CSE_CX:
        return None, None
    brand = (beer.get('brand') or '').strip()
    name = (beer.get('name') or '').strip()
    queries = []
    if brand and name:
        queries.append(f"{name} {brand} official site")
        queries.append(f"{name} {brand} beer official website")
    if brand:
        queries.append(f"{brand} brewery official site")
        queries.append(f"{brand} beer official site")
    if name:
        queries.append(f"{name} beer official site")

    candidate_urls = []
    wikidata_urls = []
    try:
        for q in queries:
            res = google_custom_search(q, num=5)
            for r in res.get('results', []):
                url = r.get('url') or ''
                if not url:
                    continue
                if 'wikidata.org' in url:
                    wikidata_urls.append(url)
                if _looks_official(url, brand):
                    candidate_urls.append(url)
            if candidate_urls:
                break
    except Exception:
        pass

    for url in candidate_urls:
        img = extract_og_image(url)
        if img:
            return img, url

    for wd_url in wikidata_urls:
        img = wikidata_p18_image(wd_url)
        if img:
            return img, wd_url

    return None, None


def resolve_beer_image_url(beer):
    """Resolve and return image URL and source URL for a beer using Google Custom Search API only.

    Returns tuple (image_url, source_url).
    
    Order:
    1) Cache
    2) Google CSE official page OpenGraph image
    3) Wikidata P18 (via Google-found entity)
    """
    brand = (beer.get('brand') or '').strip()
    name = (beer.get('name') or '').strip()

    # If already provided, keep it
    if beer.get('image'):
        return beer['image'], beer.get('image_source', None)

    # Try cache by brand then name
    cache_key = f"brand:{brand}" if brand else f"name:{name}"
    if cache_key in _brand_image_cache:
        cached = _brand_image_cache[cache_key]
        if isinstance(cached, tuple):
            return cached
        return cached, None

    # Use Google CSE to find official page image
    image_url, source_url = google_find_image_for_beer(beer)
    
    # If no image found via official pages, try Google Image Search as fallback
    if not image_url and GOOGLE_CSE_API_KEY and GOOGLE_CSE_CX:
        try:
            query = f"{name} {brand} beer bottle label" if (name and brand) else (f"{brand} beer" if brand else f"{name} beer")
            params = {
                'key': GOOGLE_CSE_API_KEY,
                'cx': GOOGLE_CSE_CX,
                'q': query,
                'searchType': 'image',
                'num': 3,
                'imgSize': 'medium',
                'safe': 'active'
            }
            resp = requests.get('https://www.googleapis.com/customsearch/v1', 
                              params=params, 
                              headers=_http_headers, 
                              timeout=12)
            resp.raise_for_status()
            data = resp.json()
            items = data.get('items', [])
            if items:
                image_url = items[0].get('link')
                source_url = items[0].get('image', {}).get('contextLink') or items[0].get('displayLink', '')
        except Exception as e:
            print(f"Google Image Search fallback error: {e}")

    # Cache result (including None) to avoid repeated lookups
    _brand_image_cache[cache_key] = (image_url, source_url)
    return image_url, source_url

def ensure_beer_image(beer):
    """Ensure the beer dict has an 'image' and 'image_source' key populated if possible."""
    try:
        if not beer.get('image'):
            img, source = resolve_beer_image_url(beer)
            if img:
                beer['image'] = img
            if source:
                beer['image_source'] = source
    except Exception:
        # Best-effort enrichment only
        pass
    return beer

def load_selected_beers():
    """Load selected beers from file."""
    if os.path.exists(selected_beers_file):
        try:
            with open(selected_beers_file, 'r', encoding='utf-8') as f:
                beers = json.load(f)
            # Best-effort backfill of missing images
            updated = False
            for beer in beers:
                before = beer.get('image')
                ensure_beer_image(beer)
                if beer.get('image') and beer.get('image') != before:
                    updated = True
            if updated:
                try:
                    with open(selected_beers_file, 'w', encoding='utf-8') as f:
                        json.dump(beers, f, ensure_ascii=False, indent=2)
                except Exception:
                    pass
            return beers
        except:
            return []
    return []

def save_selected_beer(beer):
    """Save a selected beer to file."""
    beers = load_selected_beers()
    # Enrich with image if missing
    beer = ensure_beer_image(beer)
    # Check if beer already exists
    existing_index = next((i for i, b in enumerate(beers) if b.get('name') == beer.get('name')), None)
    if existing_index is None:
        beers.append(beer)
        with open(selected_beers_file, 'w', encoding='utf-8') as f:
            json.dump(beers, f, ensure_ascii=False, indent=2)
    else:
        # Upsert: merge fields, prefer existing when present except image (fill if missing)
        existing = beers[existing_index]
        merged = {
            **existing,
            **{k: v for k, v in beer.items() if v not in (None, '', [])}
        }
        # If existing image missing and new has one, use it
        if (not existing.get('image')) and beer.get('image'):
            merged['image'] = beer['image']
        beers[existing_index] = merged
        with open(selected_beers_file, 'w', encoding='utf-8') as f:
            json.dump(beers, f, ensure_ascii=False, indent=2)
    return beers

@traceable(name="google_custom_search")
def google_custom_search(query, num=10):
    """Perform Google Custom Search and return mapped results."""
    if not GOOGLE_CSE_API_KEY or not GOOGLE_CSE_CX:
        raise ValueError("Google CSE not configured (GOOGLE_CSE_API_KEY/GOOGLE_CSE_CX)")

    params = {
        'key': GOOGLE_CSE_API_KEY,
        'cx': GOOGLE_CSE_CX,
        'q': query,
        'num': min(max(num, 1), 10),
        'safe': 'active',
        'searchType': 'image'
    }
    resp = requests.get('https://www.googleapis.com/customsearch/v1', params=params, headers=_http_headers, timeout=12)
    resp.raise_for_status()
    data = resp.json()

    # Map to the format expected by extract_beer_info_from_search
    items = data.get('items', []) or []
    results = []
    for it in items:
        results.append({
            'title': it.get('title'),
            'content': it.get('snippet'),
            'url': it.get('link'),  # This will be the IMAGE URL in image search
            'image': it.get('link'),
            'score': None
        })
    # keep 'answer' key empty to avoid confusing downstream
    return {'results': results, 'answer': None}

def validate_beer_query(query):
    """Validate that the query is related to beer.
    
    Returns: (is_valid, error_message)
    """
    query_lower = query.lower().strip()
    
    # Beer-related keywords
    beer_keywords = [
        'beer', 'ale', 'lager', 'ipa', 'stout', 'pilsner', 'wheat beer',
        'porter', 'amber', 'blonde', 'hefeweizen', 'saison', 'kolsch',
        'bock', 'barleywine', 'gose', 'sour', 'tripel', 'dubbel',
        'brew', 'brewery', 'craft beer', 'microbrew', 'pale ale',
        'session', 'hazy', 'neipa', 'brown ale', 'red ale', 'malt'
    ]
    
    # Check if query contains any beer-related keywords
    has_beer_keyword = any(keyword in query_lower for keyword in beer_keywords)
    
    if not has_beer_keyword:
        return False, "⚠️ This search is limited to beer only. Please enter a beer-related query."
    
    return True, None

@traceable(name="extract_beer_info_from_search")
def extract_beer_info_from_search(query, zipcode='90049'):
    """Generate healthy beer options using Gemini with system prompt from sysprompt.md."""

    def create_fallback_beers():
        """Fallback using Google search snippets when Gemini unavailable."""
        beers = []
        try:
            results = google_custom_search(f"{query} healthy beer low calorie", num=5)
        except Exception:
            results = {'results': []}
        for result in results.get('results', [])[:3]:
            beers.append({
                'name': result.get('title', 'Unknown Beer'),
                'brand': 'See description',
                'calories': 'N/A',
                'carbs': 'N/A',
                'abv': 'N/A',
                'description': result.get('content', ''),
                'price_range': 'N/A',
                'where_to_buy': result.get('url', ''),
                'image': None,
                'positive_feedback': 'N/A',
                'negative_feedback': 'N/A',
                'stores': []
            })
        return beers

    if not processing_model:
        beers = create_fallback_beers()
        for beer in beers:
            ensure_beer_image(beer)
        return beers

    # Load system prompt from sysprompt.md file
    try:
        sysprompt_path = os.path.join(os.path.dirname(__file__), 'sysprompt.md')
        with open(sysprompt_path, 'r', encoding='utf-8') as f:
            sys_prompt = f.read()
    except FileNotFoundError:
        print("Warning: sysprompt.md not found. Using default prompt.")
        sys_prompt = "You are a helpful assistant that provides information about healthy beer options."
    
    processing_prompt = f"""{sys_prompt}

User query: "{query}"
Target zipcode: {zipcode}

Using your own knowledge, list EXACTLY 3 healthy beer options that fit the intent. Focus on beers that are low calorie, low carb, low alcohol, gluten-free, or otherwise health-forward.

Return ONLY valid JSON: an array of 3 objects. Each object must include:
{{
    "name": "Beer name",
    "brand": "Brand name",
    "calories": "Calories per serving (or 'N/A')",
    "carbs": "Carbohydrates grams (or 'N/A')",
    "abv": "Alcohol by volume (or 'N/A')",
    "description": "One sentence highlighting why it fits the query",
    "price_range": "Approximate price (e.g., '$3-5 per bottle' or 'N/A')",
    "where_to_buy": "A likely retailer or category (e.g., 'Whole Foods', 'Total Wine', 'Online craft beer shops')",
    "positive_feedback": "One health-related benefit",
    "negative_feedback": "One potential drawback",
    "stores": [
        {{
            "name": "Store name",
            "address": "Street address in zipcode {zipcode} (or 'N/A')",
            "hours": "Operating hours (or 'N/A')",
            "distance": "Approx distance from zipcode {zipcode} (e.g., '2.3 miles' or 'N/A')"
        }}
    ]
}}

Guidelines:
- If specific data is unknown, respond with 'N/A'.
- Tailor the recommendations to the query when possible.
- Stores should be plausible locations near zipcode {zipcode}; if unsure, provide reasonable placeholders with 'N/A' for unknown fields.
- Return JSON only, no commentary.
"""
    
    try:
        # Gemini API call
        response = processing_model.generate_content(processing_prompt)
        response_text = response.text  # Gemini uses .text directly
        
    except Exception as gemini_error:
        print(f"Gemini processing error: {gemini_error}")
        print("Using fallback beer extraction...")
        beers = create_fallback_beers()
        for beer in beers:
            ensure_beer_image(beer)
        return beers
    
    # Parse response
    if response_text.startswith('```'):
        response_text = response_text.split('```')[1]
        if response_text.startswith('json'):
            response_text = response_text[4:]
        response_text = response_text.strip()

    try:
        beers = json.loads(response_text)
        beers = beers[:3]
    except json.JSONDecodeError:
        import re
        json_match = re.search(r'\[.*\]', response_text, re.DOTALL)
        if json_match:
            beers = json.loads(json_match.group())
            beers = beers[:3]
        else:
            raise ValueError("Could not parse JSON from Gemini response")

    for beer in beers:
        if 'image' not in beer:
            beer['image'] = None
        if 'positive_feedback' not in beer:
            beer['positive_feedback'] = 'N/A'
        if 'negative_feedback' not in beer:
            beer['negative_feedback'] = 'N/A'
        if 'stores' not in beer or not isinstance(beer['stores'], list):
            beer['stores'] = []
        ensure_beer_image(beer)

    return beers

@app.route('/')
@require_auth
def index():
    """Render main search page."""
    return render_template('index.html')

@app.route('/selected')
@require_auth
def selected():
    """Render selected beers page."""
    return render_template('selected.html')

@app.route('/api/search', methods=['POST'])
@require_auth
@traceable(name="search_beers_endpoint")
def search_beers():
    """Search for healthy beers with validation."""
    try:
        data = request.get_json()
        query = data.get('query', 'healthy beers low calorie low carb')
        zipcode = data.get('zipcode') or session.get('zipcode', '90049')
        
        # Validate that query is beer-related
        is_valid, error_message = validate_beer_query(query)
        if not is_valid:
            return jsonify({
                'error': error_message,
                'error_type': 'validation'
            }), 400
        
        # Log for debugging
        print(f"Searching with query: {query}, zipcode: {zipcode}")
        
        # Generate beer information
        beers = extract_beer_info_from_search(query, zipcode)
        
        return jsonify({'beers': beers})
        
    except requests.exceptions.RequestException as e:
        print(f"Google CSE Search API Error: {e}")
        return jsonify({'error': f'Google CSE error: {str(e)}'}), 500
    except Exception as e:
        print(f"Error in search: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/selected', methods=['GET'])
@require_auth
def get_selected_beers():
    """Get all selected beers."""
    beers = load_selected_beers()
    return jsonify({'beers': beers})

@app.route('/api/selected', methods=['POST'])
@require_auth
def add_selected_beer():
    """Add a beer to selected list."""
    try:
        beer = request.get_json()
        beers = save_selected_beer(beer)
        return jsonify({'success': True, 'beers': beers})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/selected/<beer_name>', methods=['DELETE'])
@require_auth
def remove_selected_beer(beer_name):
    """Remove a beer from selected list."""
    try:
        beers = load_selected_beers()
        beers = [b for b in beers if b.get('name') != beer_name]
        with open(selected_beers_file, 'w', encoding='utf-8') as f:
            json.dump(beers, f, ensure_ascii=False, indent=2)
        return jsonify({'success': True, 'beers': beers})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/visitor-count', methods=['GET'])
def get_visitor_count_api():
    """Get current visitor count."""
    count = get_visitor_count()
    return jsonify({'count': count})

@app.route('/api/visitor-count/increment', methods=['POST'])
def increment_visitor_count_api():
    """Increment visitor count."""
    count = increment_visitor_count()
    return jsonify({'count': count})


if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=7860)