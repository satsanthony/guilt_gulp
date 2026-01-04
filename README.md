# 🍺 Beer Finder AI

A sophisticated AI-powered beer recommendation system that uses multiple intelligent agents to help you discover your perfect brew and find where to drink it nearby.

---
title: Beer Explorer
emoji: 🍺
colorFrom: blue
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
---

## 🎯 Overview

Beer Finder AI is a personalized beer discovery application that combines multiple AI agents to:
- Recommend beers based on your mood, taste preferences, and context
- Search for specific beers and similar alternatives
- Find bars and establishments serving your chosen beers
- Provide detailed information including calories, ABV, pricing, and availability

## 🤖 AI Agent Architecture

The application employs a sophisticated multi-agent system where specialized AI agents work together to deliver accurate recommendations and location data:

### **Main Agent: Beer Recommendation Engine**
The central orchestrator powered by Google's Gemini AI that:
- Analyzes user mood, taste preferences, and contextual information
- Generates personalized beer recommendations with detailed profiles
- Provides nutritional information (calories, ABV) and pricing estimates
- Suggests retail locations for purchasing

### **Sub-Agent 1: Web Search Agent**
Conducts intelligent web searches to find real-world information:
- Searches multiple query variations to maximize coverage
- Looks for bars, pubs, and establishments serving specific beers
- Combines location-based queries with beer names and brands
- Returns raw search results for further processing

### **Sub-Agent 2: AI Analysis Agent**
Processes and extracts structured data from web search results:
- Analyzes search snippets and titles using natural language understanding
- Extracts actual bar and establishment names from unstructured text
- Filters out irrelevant results (websites, apps, generic terms)
- Assigns confidence scores to extracted locations
- Returns structured JSON data for verification

### **Sub-Agent 3: Location Verification Agent**
Validates and enriches location data using Google Places API:
- Verifies extracted bar names against real business listings
- Retrieves accurate addresses, ratings, and price levels
- Confirms proximity to user's location using geocoding
- Provides Google Maps integration with place IDs
- Returns only verified, real establishments

### **Sub-Agent 4: Matching Agent (Orchestrator)**
Coordinates the sub-agents to deliver comprehensive results:
- Manages the workflow between search, analysis, and verification
- Converts zipcodes to city names for better search context
- Coordinates timing and data flow between agents
- Ensures quality results by requiring all agents to succeed
- Implements fallback strategies when data is unavailable

### **Agent Workflow Example**

When you select a beer like "Guinness Draught":

1. **Main Agent** confirms it's a valid beer choice and provides details
2. **Matching Agent** extracts your city from zipcode (e.g., "Santa Monica")
3. **Web Search Agent** searches: "Guinness Draught bars near 90401", "where to drink Guinness in Santa Monica"
4. **AI Analysis Agent** processes results and extracts: "The Galley", "Finn McCool's Irish Pub", "Blue Plate Oysterette"
5. **Verification Agent** confirms these are real bars via Google Places API
6. **Matching Agent** returns verified results with addresses, ratings, and map links

This multi-agent approach ensures high accuracy by combining AI understanding with real-world verification.

## 🚀 Features

- **Mood-Based Search**: Get beer recommendations based on your current vibe
- **Specific Beer Search**: Find exact beers or similar alternatives
- **Location Intelligence**: Discover bars serving your chosen beers nearby
- **Personal Beer List**: Save your favorite selections
- **Feedback System**: Share suggestions and feature requests
- **Activity Logging**: Track user selections for insights

## 📋 Prerequisites

Before running the application, you need to obtain API keys from:

1. **Google AI Studio** (Gemini API)
   - Visit [Google AI Studio](https://aistudio.google.com/)
   - Create an API key for Gemini

2. **Google Cloud Console** (Places, Geocoding, Custom Search)
   - Visit [Google Cloud Console](https://console.cloud.google.com/)
   - Enable the following APIs:
     - Places API (New)
     - Geocoding API
     - Custom Search API
   - Create API keys for each service

3. **Google Programmable Search Engine**
   - Visit [Programmable Search Engine](https://programmablesearchengine.google.com/)
   - Create a search engine
   - Note your Search Engine ID (CX)

## ⚙️ Installation

1. **Clone the repository**
```bash
git clone https://github.com/yourusername/beer-finder-ai.git
cd beer-finder-ai
```

2. **Install dependencies**
```bash
pip install -r requirements.txt
```

3. **Configure environment variables**

Create a `.env` file in the root directory with your API keys:

```env
GEMINI_API_KEY=your_gemini_api_key_here
GOOGLE_PLACES_API_KEY=your_places_api_key_here
GOOGLE_GEOCODING_API_KEY=your_geocoding_api_key_here
GOOGLE_CSE_API_KEY=your_custom_search_api_key_here
GOOGLE_CSE_CX=your_search_engine_id_here
```

**Required API Keys:**
- `GEMINI_API_KEY` - For AI-powered beer recommendations
- `GOOGLE_PLACES_API_KEY` - For finding and verifying bar locations
- `GOOGLE_GEOCODING_API_KEY` - For converting zipcodes to coordinates
- `GOOGLE_CSE_API_KEY` - For web searches to find bars
- `GOOGLE_CSE_CX` - Your Custom Search Engine ID

## 🏃‍♂️ Running the Application

### Local Development

```bash
streamlit run app.py
```

The application will open in your default browser at `http://localhost:8501`

### Docker Deployment

```bash
docker build -t beer-finder-ai .
docker run -p 7860:7860 --env-file .env beer-finder-ai
```

### Hugging Face Spaces

This application is configured for deployment on Hugging Face Spaces using Docker. Simply:
1. Create a new Space with Docker SDK
2. Add your `.env` variables to Space secrets
3. Push the repository

## 📁 Project Structure

```
beer-finder-ai/
├── app.py                 # Main application file
├── requirements.txt       # Python dependencies
├── Dockerfile            # Docker configuration
├── .env                  # API keys (create this)
├── static/
│   └── images/          # Logo and GIF assets
├── log/
│   └── log.txt          # User activity logs
└── feedback/            # User feedback submissions
```

## 🎨 Features in Detail

### Mood-Based Recommendations
Describe your current mood (relaxed, hyped, tired) along with context about your day and taste preferences. The AI agent analyzes these inputs to suggest 3 perfect beer matches.

### Specific Beer Search
Enter a beer name or style, and the AI will find exact matches or similar alternatives available in your area.

### Intelligent Bar Finder
The multi-agent system:
1. Searches the web for bars serving your beer
2. Extracts establishment names using AI
3. Verifies locations via Google Places
4. Provides ratings, addresses, and map links

### Personal Beer List
Save your favorite discoveries to build a personalized collection you can reference anytime.

## 🔒 Privacy & Data

- User feedback is stored locally in timestamped files
- Activity logs track beer selections for analytics
- No personal data is transmitted to third parties
- All API calls are made server-side

## 🛠️ Technology Stack

- **Frontend**: Streamlit with custom CSS
- **AI/ML**: Google Gemini (gemini-3-flash-preview)
- **APIs**: Google Places, Geocoding, Custom Search
- **Language**: Python 3.8+
- **Deployment**: Docker, Hugging Face Spaces

## 📝 Debug Mode

Toggle debug mode using the sidebar button to see:
- API configuration status
- Model initialization state
- Current step and session data
- Real-time agent activity

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## ⚠️ Disclaimer

Please drink responsibly. This application is for entertainment and informational purposes only. Always verify business hours and availability before visiting establishments.

## 🙏 Acknowledgments

- Google Gemini for AI capabilities
- Google Maps Platform for location services
- Streamlit for the web framework

---

**Made with 🍺 by Dimension Unlimited**

*© 2026 Dimension Unlimited. All rights reserved.*