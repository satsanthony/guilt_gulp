---
title: Beer Explorer
emoji: 🍺
colorFrom: blue
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
---
🍺 Beer Finder AI
A sophisticated AI-powered beer recommendation system that uses multiple intelligent agents to help you discover your perfect brew and find where to drink it nearby.
🆕 Latest Updates
April 4, 2026

New Feature: 
Record voice to search beer
Upload image to search beer
Beer games
Non-Alcoholic Beer Search - Discover high-quality non-alcoholic beer options with the same intelligent recommendation system
Enhanced search options with three distinct pathways: Mood-Based, Specific Beer, and Non-Alcoholic
Improved user interface with streamlined search selection

🎯 Overview
Beer Finder AI is a personalized beer discovery application that combines multiple AI agents to:

Recommend beers based on your mood, taste preferences, and context
Search for specific beers and similar alternatives
Find non-alcoholic beer options for those seeking alcohol-free alternatives
Find bars and establishments serving your chosen beers
Provide detailed information including calories, ABV, pricing, and availability

🤖 AI Agent Architecture
The application employs a sophisticated multi-agent system where specialized AI agents work together to deliver accurate recommendations and location data:
Main Agent: Beer Recommendation Engine
The central orchestrator powered by Google's Gemini AI that:

Analyzes user mood, taste preferences, and contextual information
Generates personalized beer recommendations with detailed profiles
Provides non-alcoholic beer recommendations (0.0% ABV options)
Provides nutritional information (calories, ABV) and pricing estimates
Suggests retail locations for purchasing

Sub-Agent 1: Web Search Agent
Conducts intelligent web searches to find real-world information:

Searches multiple query variations to maximize coverage
Looks for bars, pubs, and establishments serving specific beers
Combines location-based queries with beer names and brands
Returns raw search results for further processing

Sub-Agent 2: AI Analysis Agent
Processes and extracts structured data from web search results:

Analyzes search snippets and titles using natural language understanding
Extracts actual bar and establishment names from unstructured text
Filters out irrelevant results (websites, apps, generic terms)
Assigns confidence scores to extracted locations
Returns structured JSON data for verification

Sub-Agent 3: Location Verification Agent
Validates and enriches location data using Google Places API:

Verifies extracted bar names against real business listings
Retrieves accurate addresses, ratings, and price levels
Confirms proximity to user's location using geocoding
Provides Google Maps integration with place IDs
Returns only verified, real establishments

Sub-Agent 4: Matching Agent (Orchestrator)
Coordinates the sub-agents to deliver comprehensive results:

Manages the workflow between search, analysis, and verification
Converts zipcodes to city names for better search context
Coordinates timing and data flow between agents
Ensures quality results by requiring all agents to succeed
Implements fallback strategies when data is unavailable

Agent Workflow Example
When you select a beer like "Guinness Draught":

Main Agent confirms it's a valid beer choice and provides details
Matching Agent extracts your city from zipcode (e.g., "Santa Monica")
Web Search Agent searches: "Guinness Draught bars near 90401", "where to drink Guinness in Santa Monica"
AI Analysis Agent processes results and extracts: "The Galley", "Finn McCool's Irish Pub", "Blue Plate Oysterette"
Verification Agent confirms these are real bars via Google Places API
Matching Agent returns verified results with addresses, ratings, and map links

This multi-agent approach ensures high accuracy by combining AI understanding with real-world verification.
🚀 Features

Mood-Based Search: Get beer recommendations based on your current vibe
Specific Beer Search: Find exact beers or similar alternatives
Non-Alcoholic Beer Search: Discover high-quality alcohol-free beer options
Location Intelligence: Discover bars serving your chosen beers nearby
Personal Beer List: Save your favorite selections
Feedback System: Share suggestions and feature requests
Activity Logging: Track user selections for insights (stored in HuggingFace dataset)

📋 Prerequisites
Before running the application, you need to obtain API keys from:

Google AI Studio (Gemini API)

Visit Google AI Studio
Create an API key for Gemini


Google Cloud Console (Places, Geocoding, Custom Search)

Visit Google Cloud Console
Enable the following APIs:

Places API (New)
Geocoding API
Custom Search API


Create API keys for each service


Google Programmable Search Engine

Visit Programmable Search Engine
Create a search engine
Note your Search Engine ID (CX)


Hugging Face (Optional - for logging and feedback)

Visit Hugging Face
Create an access token
Create a dataset repository for storing logs and feedback



⚙️ Installation

Clone the repository

bashgit clone https://huggingface.co/spaces/mashomashi/guilt_gulp
cd guilt_gulp

Install dependencies

bashpip install -r requirements.txt

Configure environment variables

Create a .env file in the root directory with your API keys:
envGEMINI_API_KEY=your_gemini_api_key_here
GOOGLE_PLACES_API_KEY=your_places_api_key_here
GOOGLE_GEOCODING_API_KEY=your_geocoding_api_key_here
GOOGLE_CSE_API_KEY=your_custom_search_api_key_here
GOOGLE_CSE_CX=your_search_engine_id_here
HF_TOKEN=your_huggingface_token_here
Required API Keys:

GEMINI_API_KEY - For AI-powered beer recommendations
GOOGLE_PLACES_API_KEY - For finding and verifying bar locations
GOOGLE_GEOCODING_API_KEY - For converting zipcodes to coordinates
GOOGLE_CSE_API_KEY - For web searches to find bars
GOOGLE_CSE_CX - Your Custom Search Engine ID
HF_TOKEN - (Optional) For logging selections and feedback to HuggingFace dataset

🏃‍♂️ Running the Application
Local Development
bashstreamlit run app.py
The application will open in your default browser at http://localhost:8501
Docker Deployment
bashdocker build -t beer-finder-ai .
docker run -p 7860:7860 --env-file .env beer-finder-ai
Hugging Face Spaces
This application is configured for deployment on Hugging Face Spaces using Docker. Simply:

Create a new Space with Docker SDK
Add your .env variables to Space secrets
Push the repository

📁 Project Structure
beer-finder-ai/
├── app.py                 # Main application file
├── requirements.txt       # Python dependencies
├── Dockerfile            # Docker configuration
├── .env                  # API keys (create this)
├── static/
│   └── images/          # Logo and GIF assets
│       ├── logo.png     # Application logo
│       └── beer.gif.gif # Animated greeting GIF
├── log/
│   └── log.txt          # User activity logs (local backup)
└── feedback/            # User feedback submissions (local backup)
🎨 Features in Detail
Mood-Based Recommendations
Describe your current mood (relaxed, hyped, tired) along with context about your day and taste preferences. The AI agent analyzes these inputs to suggest 3 perfect beer matches.
Specific Beer Search
Enter a beer name or style, and the AI will find exact matches or similar alternatives available in your area.
Non-Alcoholic Beer Search
Looking for alcohol-free options? Select the non-alcoholic search to discover high-quality 0.0% ABV beers. Perfect for:

Designated drivers
Health-conscious individuals
Pregnant/nursing individuals
Those taking a break from alcohol
Anyone seeking flavorful non-alcoholic alternatives

Intelligent Bar Finder
The multi-agent system:

Searches the web for bars serving your beer
Extracts establishment names using AI
Verifies locations via Google Places
Provides ratings, addresses, and map links

Personal Beer List
Save your favorite discoveries to build a personalized collection you can reference anytime.
Feedback System
Share your thoughts, suggestions, or feature requests directly through the app. All feedback is stored in the HuggingFace dataset for review.
🔒 Privacy & Data

User feedback is stored in HuggingFace dataset with timestamps
Activity logs track beer selections for analytics and improvements
Logs include: username, beer selection, search type, and timestamp
No sensitive personal data is collected
All API calls are made server-side for security

🛠️ Technology Stack

Frontend: Streamlit with custom mobile-optimized CSS
AI/ML: Google Gemini (gemini-3-flash-preview)
APIs: Google Places API (New), Geocoding API, Custom Search API
Data Storage: HuggingFace Hub for logs and feedback
Language: Python 3.8+
Deployment: Docker, Hugging Face Spaces

📝 Debug Mode
Toggle debug mode using the sidebar button to see:

API configuration status
Model initialization state
Current step and session data
Search type and recommendations count
Real-time agent activity
Error messages and diagnostics

🎯 Search Types
The application supports three distinct search pathways:

By Mood (🎭): AI-powered recommendations based on your emotional state, daily context, and taste preferences
Specific Beer (🍺): Search for a particular beer brand or style
Non-Alcoholic (🚫🍺): Discover quality alcohol-free beer options

🤝 Contributing
Contributions are welcome! Please feel free to submit a Pull Request.
📄 License
This project is licensed under the MIT License - see the LICENSE file for details.
⚠️ Disclaimer
Please drink responsibly. This application is for entertainment and informational purposes only. Always verify business hours and availability before visiting establishments.
🙏 Acknowledgments

Google Gemini for AI capabilities
Google Maps Platform for location services
Streamlit for the web framework
HuggingFace for data storage and hosting


Made with 🍺 by Dimension Unlimited
© 2026 Dimension Unlimited. All rights reserved.