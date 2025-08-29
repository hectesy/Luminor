import streamlit as st
from PIL import Image
import io
import time
import base64
import pandas as pd
import numpy as np
import json
import hashlib
from datetime import datetime, timedelta
import sqlite3
import os
from typing import Optional, Dict, List, Any
import openai

def intro_screen():
    # Styling for centered intro
    st.markdown(
        """
        <style>
        .centered {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 85vh;
        }
        .title {
            font-size: 3em;
            font-weight: bold;
            color: #4CAF50;
            animation: fadeIn 2s ease-in;
        }
        .subtitle {
            font-size: 1.2em;
            color: #888;
            margin-top: -10px;
        }
        @keyframes fadeIn {
            from {opacity: 0;}
            to {opacity: 1;}
        }
        </style>
        <div class="centered">
            <div class="title">✨ Luminor ✨</div>
            <div class="subtitle">AI Brand Intelligence</div>
        </div>
        """,
        unsafe_allow_html=True
    )

    # Play audio using st.audio
    try:
        audio_file = open("./assets/whispers_september_52sec.mp3", "rb")
        audio_bytes = audio_file.read()
        st.audio(audio_bytes, format="audio/mp3", start_time=0)
    except FileNotFoundError:
        st.error("Audio file not found. Please ensure 'assets/whispers_september_52sec.mp3' exists in your project directory.")
    except Exception as e:
        st.error(f"Failed to play audio: {str(e)}")

    # Typing effect: Searching logos...
    placeholder = st.empty()
    message = "🔍 Searching logos..."
    for i in range(len(message) + 1):
        placeholder.markdown(f"<p style='text-align:center;'>{message[:i]}</p>", unsafe_allow_html=True)
        time.sleep(0.05)

    time.sleep(0.8)
    st.success("✅ Ready to analyze your logo!")

    # Start button with single-click handling
    if st.button("🚀 Start Now", key="start_now"):
        st.session_state["show_intro"] = False
        st.write("Button clicked, transitioning to main app...")
        st.rerun()

def main_app():
    st.title("Luminor – Brand Recognition AI")
    st.write("Upload a logo to begin analysis...")

# --- Routing ---
if "show_intro" not in st.session_state:
    st.session_state["show_intro"] = True

if st.session_state["show_intro"]:
    intro_screen()
else:
    main_app()
# --- CONFIGURATION ---
# Use environment variable for OpenAI API key
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "your-openai-api-key-here")  # Replace with actual key or use env variable
st.set_page_config(
    page_title="Luminor AI",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- DATABASE SETUP ---
def init_database():
    """Initialize SQLite database for persistent storage"""
    conn = sqlite3.connect('luminor_users.db')
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            email TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP,
            remember_token TEXT,
            token_expires TIMESTAMP,
            preferences TEXT
        )
    ''')
    
    # User history table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            brand_data TEXT,
            scan_type TEXT DEFAULT 'manual',
            confidence REAL DEFAULT 0,
            image_hash TEXT,
            scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (username) REFERENCES users (username)
        )
    ''')
    
    # User favorites table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_favorites (
            username TEXT,
            brand_id TEXT,
            notes TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (username, brand_id),
            FOREIGN KEY (username) REFERENCES users (username)
        )
    ''')
    
    # Analytics table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS analytics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            action TEXT,
            data TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (username) REFERENCES users (username)
        )
    ''')
    
    conn.commit()
    conn.close()

# --- ENHANCED AUTHENTICATION ---
def hash_password(password: str) -> str:
    """Hash password securely with salt"""
    salt = "luminor_ai_salt_2024"
    return hashlib.sha256((password + salt).encode()).hexdigest()

def create_user(username: str, password: str, email: str = "") -> bool:
    """Create new user account with enhanced validation"""
    try:
        if len(username) < 3 or len(password) < 6:
            return False
            
        conn = sqlite3.connect('luminor_users.db')
        cursor = conn.cursor()
        
        password_hash = hash_password(password)
        default_prefs = json.dumps({
            'theme': 'Cyber Dark',
            'notifications': True,
            'auto_save_scans': True
        })
        
        cursor.execute(
            "INSERT INTO users (username, password_hash, email, preferences) VALUES (?, ?, ?, ?)",
            (username, password_hash, email, default_prefs)
        )
        
        conn.commit()
        conn.close()
        
        # Log user registration
        log_analytics(username, 'user_registered', {'email': email})
        return True
    except sqlite3.IntegrityError:
        return False

def authenticate_user(username: str, password: str, remember_me: bool = False) -> bool:
    """Authenticate user with enhanced security"""
    conn = sqlite3.connect('luminor_users.db')
    cursor = conn.cursor()
    
    password_hash = hash_password(password)
    cursor.execute(
        "SELECT username, preferences FROM users WHERE username = ? AND password_hash = ?",
        (username, password_hash)
    )
    
    user = cursor.fetchone()
    
    if user:
        # Update last login
        cursor.execute(
            "UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE username = ?",
            (username,)
        )
        
        # Load user preferences
        if user[1]:
            st.session_state.user_preferences = json.loads(user[1])
        else:
            st.session_state.user_preferences = {'theme': 'Cyber Dark'}
        
        if remember_me:
            # Create remember token
            token = hashlib.sha256(f"{username}{time.time()}".encode()).hexdigest()
            expires = datetime.now() + timedelta(days=30)
            cursor.execute(
                "UPDATE users SET remember_token = ?, token_expires = ? WHERE username = ?",
                (token, expires, username)
            )
            st.session_state.remember_token = token
        
        conn.commit()
        conn.close()
        
        # Log successful login
        log_analytics(username, 'user_login', {'remember_me': remember_me})
        return True
    
    conn.close()
    return False

def check_remember_token() -> Optional[str]:
    """Check if user has valid remember token"""
    if 'remember_token' not in st.session_state:
        return None
    
    conn = sqlite3.connect('luminor_users.db')
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT username, preferences FROM users WHERE remember_token = ? AND token_expires > CURRENT_TIMESTAMP",
        (st.session_state.remember_token,)
    )
    
    user = cursor.fetchone()
    conn.close()
    
    if user:
        if user[1]:
            st.session_state.user_preferences = json.loads(user[1])
        return user[0]
    return None

# --- ANALYTICS & LOGGING ---
def log_analytics(username: str, action: str, data: Dict[str, Any]) -> None:
    """Log user actions for analytics"""
    try:
        conn = sqlite3.connect('luminor_users.db')
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO analytics (username, action, data) VALUES (?, ?, ?)",
            (username, action, json.dumps(data))
        )
        conn.commit()
        conn.close()
    except Exception:
        pass  # Silent fail for analytics

def get_user_statistics(username: str) -> Dict[str, Any]:
    """Get comprehensive user statistics"""
    try:
        conn = sqlite3.connect('luminor_users.db')
        cursor = conn.cursor()
        
        # Total scans
        cursor.execute("SELECT COUNT(*) FROM user_history WHERE username = ?", (username,))
        total_scans = cursor.fetchone()[0]
        
        # Unique brands
        cursor.execute("SELECT DISTINCT brand_data FROM user_history WHERE username = ?", (username,))
        unique_brands = len(set(json.loads(row[0])['id'] for row in cursor.fetchall() if json.loads(row[0])['id'] != 'unknown'))
        
        # Favorites count
        cursor.execute("SELECT COUNT(*) FROM user_favorites WHERE username = ?", (username,))
        favorites_count = cursor.fetchone()[0]
        
        # AI vs Manual scans
        cursor.execute("SELECT scan_type, COUNT(*) FROM user_history WHERE username = ? GROUP BY scan_type", (username,))
        scan_types = {row[0]: row[1] for row in cursor.fetchall()}
        
        # Average confidence
        cursor.execute("SELECT AVG(confidence) FROM user_history WHERE username = ? AND confidence > 0", (username,))
        avg_confidence = cursor.fetchone()[0] or 0
        
        conn.close()
        
        return {
            'total_scans': total_scans,
            'unique_brands': unique_brands,
            'favorites_count': favorites_count,
            'scan_types': scan_types,
            'avg_confidence': round(avg_confidence, 1)
        }
    except Exception:
        return {}

# --- ENHANCED DATA MANAGEMENT ---
def save_scan_history(username: str, brand_data: Dict, scan_type: str = 'manual', 
                     confidence: float = 0, image_hash: str = "") -> None:
    """Save scan to user history with enhanced metadata"""
    try:
        conn = sqlite3.connect('luminor_users.db')
        cursor = conn.cursor()
        
        cursor.execute(
            "INSERT INTO user_history (username, brand_data, scan_type, confidence, image_hash) VALUES (?, ?, ?, ?, ?)",
            (username, json.dumps(brand_data), scan_type, confidence, image_hash)
        )
        
        conn.commit()
        conn.close()
        
        # Log scan activity
        log_analytics(username, 'brand_scanned', {
            'brand_id': brand_data.get('id'),
            'brand_name': brand_data.get('name'),
            'scan_type': scan_type,
            'confidence': confidence
        })
    except Exception:
        pass

def load_user_history(username: str, limit: int = 50) -> List[Dict]:
    """Load user scan history with enhanced data"""
    try:
        conn = sqlite3.connect('luminor_users.db')
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT brand_data, scan_type, confidence, scanned_at FROM user_history WHERE username = ? ORDER BY scanned_at DESC LIMIT ?",
            (username, limit)
        )
        
        results = cursor.fetchall()
        conn.close()
        
        history = []
        for row in results:
            brand_data = json.loads(row[0])
            brand_data['scan_metadata'] = {
                'scan_type': row[1],
                'confidence': row[2],
                'scanned_at': row[3]
            }
            history.append(brand_data)
        
        return history
    except Exception:
        return []

def generate_image_hash(image_data: Image.Image) -> str:
    """Generate hash for image deduplication"""
    try:
        buffered = io.BytesIO()
        image_data.save(buffered, format="PNG")
        return hashlib.md5(buffered.getvalue()).hexdigest()
    except:
        return ""

# --- ENHANCED OPENAI INTEGRATION ---
def analyze_image_with_openai(image_data: Image.Image, api_key: str) -> Optional[Dict]:
    """Enhanced AI image analysis with comprehensive data"""
    try:
        client = openai.OpenAI(api_key=api_key, timeout=30.0)  # Added timeout
        
        # Convert image to base64
        buffered = io.BytesIO()
        # Resize image for API efficiency
        if image_data.size[0] > 1024 or image_data.size[1] > 1024:
            image_data.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
        
        image_data.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode()
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": """Analyze this image for brand logos and return ONLY a JSON response with comprehensive brand details:
                            {
                                "brand_detected": true/false,
                                "brand_name": "exact brand name or null",
                                "confidence": 0-100,
                                "logo_elements": ["visual elements found"],
                                "colors": ["dominant colors"],
                                "description": "brief description",
                                "category": "industry category",
                                "slogan": "brand slogan or null",
                                "authenticity_tips": "tips to verify authenticity",
                                "website": "brand website or null",
                                "founded": "founding year or null",
                                "headquarters": "headquarters location or null",
                                "market_cap": "market capitalization or null",
                                "stock_symbol": "stock symbol or null",
                                "competitors": ["list of competitors"],
                                "offers": [{"title": "offer title", "code": "offer code", "expires": "expiration date"}],
                                "stores": [{"name": "store name", "distance": "distance", "rating": rating}],
                                "similar_logos": ["brands with similar logos"],
                                "keywords": ["relevant keywords"]
                            }
                            Be conservative with brand detection and provide as much detail as possible."""
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{img_str}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=1000,
            temperature=0.1
        )
        
        content = response.choices[0].message.content.strip()
        
        # Clean up response
        if content.startswith('```json'):
            content = content.replace('```json', '').replace('```', '').strip()
        elif content.startswith('```'):
            content = content.replace('```', '').strip()
        
        result = json.loads(content)
        result['confidence'] = float(result.get('confidence', 0))
        
        return result
        
    except openai.APITimeoutError:
        st.error("AI Analysis Error: Request timed out. Please try again with a clearer image.")
        return None
    except Exception as e:
        st.error(f"AI Analysis Error: {str(e)}")
        return None

# --- MODERN THEMES ---
THEMES = {
    "Cyber Dark": {
        "primary": "#00D4FF",
        "secondary": "#FF006B", 
        "background": "#0A0A0B",
        "surface": "#1A1A1B",
        "text": "#FFFFFF",
        "success": "#00FF88",
        "warning": "#FFB700",
        "error": "#FF4444"
    },
    "Ocean Light": {
        "primary": "#0EA5E9",
        "secondary": "#06B6D4",
        "background": "#E0F2FE",
        "surface": "#F0F9FF",
        "text": "#0F172A",
        "success": "#10B981",
        "warning": "#F59E0B",
        "error": "#EF4444"
    },
    "Forest Green": {
        "primary": "#059669",
        "secondary": "#34D399",
        "background": "#064E3B",
        "surface": "#065F46",
        "text": "#ECFDF5",
        "success": "#10B981",
        "warning": "#F59E0B",
        "error": "#EF4444"
    },
    "Purple Haze": {
        "primary": "#8B5CF6",
        "secondary": "#A78BFA",
        "background": "#2D1B69",
        "surface": "#3730A3",
        "text": "#F3F4F6",
        "success": "#10B981",
        "warning": "#F59E0B",
        "error": "#EF4444"
    },
    "Neon Light": {
        "primary": "#FF3366",
        "secondary": "#33CCFF",
        "background": "#F8F9FA",
        "surface": "#FFFFFF",
        "text": "#2D3748",
        "accent": "#9F7AEA",
        "success": "#48BB78",
        "warning": "#ED8936",
        "gradient": "linear-gradient(135deg, #667eea 0%, #764ba2 100%)"
    },
    "Sunset": {
        "primary": "#F59E0B",
        "secondary": "#FB923C",
        "background": "#451A03",
        "surface": "#7C2D12",
        "text": "#FEF3C7",
        "success": "#10B981",
        "warning": "#F59E0B",
        "error": "#EF4444"
    }
}

def apply_theme(theme: Dict[str, str]) -> None:
    """Apply modern theme styling with enhanced CSS and proper backgrounds"""
    st.markdown(f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
        
        .stApp {{
            background-color: {theme['background']} !important;
            color: {theme['text']};
            font-family: 'Inter', sans-serif;
        }}
        
        /* Force background on all Streamlit elements */
        .stApp > div {{
            background-color: {theme['background']};
        }}
        
        /* Sidebar styling */
        .css-1d391kg {{
            background-color: {theme['surface']} !important;
        }}
        
        /* Main content area */
        .block-container {{
            background-color: {theme['background']} !important;
        }}
        
        /* Text inputs and selectboxes */
        .stTextInput > div > div > input,
        .stSelectbox > div > div > div,
        .stTextArea > div > div > textarea {{
            background-color: {theme['surface']} !important;
            color: {theme['text']} !important;
            border: 1px solid {theme['primary']} !important;
        }}
        
        /* Buttons */
        .stButton > button {{
            background-color: {theme['primary']} !important;
            color: white !important;
            border: none !important;
            border-radius: 10px !important;
            font-weight: 500 !important;
        }}
        
        .stButton > button:hover {{
            background-color: {theme['secondary']} !important;
            transform: translateY(-2px) !important;
            box-shadow: 0 5px 15px rgba(0,0,0,0.2) !important;
        }}
        
        /* Tabs */
        .stTabs [data-baseweb="tab-list"] {{
            background-color: {theme['surface']} !important;
        }}
        
        .stTabs [data-baseweb="tab"] {{
            color: {theme['text']} !important;
        }}
        
        .stTabs [aria-selected="true"] {{
            background-color: {theme['primary']} !important;
            color: white !important;
        }}
        
        /* Metrics */
        [data-testid="metric-container"] {{
            background-color: {theme['surface']} !important;
            border: 1px solid {theme['primary']} !important;
            border-radius: 10px !important;
            padding: 1rem !important;
        }}
        
        /* Headers and text */
        h1, h2, h3, h4, h5, h6 {{
            color: {theme['text']} !important;
        }}
        
        p, div, span {{
            color: {theme['text']} !important;
        }}
        
        /* Custom components */
        .main-header {{
            background: linear-gradient(135deg, {theme['primary']}, {theme['secondary']});
            padding: 2rem;
            border-radius: 20px;
            text-align: center;
            margin-bottom: 2rem;
            box-shadow: 0 20px 40px rgba(0,0,0,0.15);
        }}
        
        .brand-card {{
            background: {theme['surface']} !important;
            border-radius: 20px;
            padding: 2rem;
            margin: 1rem 0;
            border-left: 5px solid {theme['primary']};
            box-shadow: 0 8px 32px rgba(0,0,0,0.1);
            transition: all 0.3s ease;
        }}
        
        .brand-card:hover {{
            transform: translateY(-5px);
            box-shadow: 0 20px 40px rgba(0,0,0,0.15);
        }}
        
        .metric-card {{
            background: {theme['surface']} !important;
            border-radius: 15px;
            padding: 1.5rem;
            text-align: center;
            border: 2px solid {theme['primary']};
            margin-bottom: 1rem;
            transition: all 0.3s ease;
        }}
        
        .metric-card:hover {{
            transform: scale(1.05);
        }}
        
        .offer-badge {{
            background: linear-gradient(45deg, {theme['success']}, {theme['primary']});
            color: white;
            padding: 0.5rem 1rem;
            border-radius: 20px;
            font-size: 0.8rem;
            margin: 0.3rem;
            display: inline-block;
            font-weight: 500;
        }}
        
        .high-score {{ 
            color: {theme['success']}; 
            font-weight: 600;
        }}
        .low-score {{ 
            color: {theme['warning']};
            font-weight: 600;
        }}
        
        .confidence-bar {{
            width: 100%;
            height: 8px;
            background-color: rgba(255,255,255,0.2);
            border-radius: 4px;
            overflow: hidden;
            margin: 0.5rem 0;
        }}
        
        /* Info/warning/success boxes */
        .stAlert {{
            background-color: {theme['surface']} !important;
            border: 1px solid {theme['primary']} !important;
            color: {theme['text']} !important;
        }}
        </style>
        """, unsafe_allow_html=True)

# --- ENHANCED BRAND DATABASE ---
BRAND_DATABASE = {
    'nike': {
        'id': 'nike', 'name': 'Nike', 'industry': 'Athletic Footwear & Apparel',
        'logo': '👟', 'slogan': 'Just Do It',
        'sustainability_score': 7.8, 'sentiment_score': 8.2,
        'authenticity_tips': 'Check for swoosh alignment, quality stitching, official Nike tags, holographic labels, and verify on Nike SNKRS app',
        'description': 'Global leader in athletic footwear, apparel, and sports equipment with innovative technology.',
        'founded': '1964', 'headquarters': 'Beaverton, Oregon, USA',
        'market_cap': '$196.5B', 'stock_symbol': 'NKE',
        'competitors': ['Adidas', 'Puma', 'Under Armour', 'Reebok'],
        'website': 'https://www.nike.com',
        'offers': [
            {'title': '20% Off Running Shoes', 'code': 'RUN20', 'expires': '2024-12-31'},
            {'title': 'Free Shipping Orders $50+', 'code': 'FREESHIP', 'expires': '2024-12-31'},
            {'title': 'Student Discount 10%', 'code': 'STUDENT10', 'expires': 'Ongoing'}
        ],
        'stores': [
            {'name': 'Nike Store Victoria Island', 'distance': '2.1 km', 'rating': 4.7},
            {'name': 'Nike Outlet Ikeja', 'distance': '5.3 km', 'rating': 4.4}
        ],
        'similar_logos': ['Puma', 'Adidas'],
        'brand_colors': ['#000000', '#FFFFFF'],
        'keywords': ['swoosh', 'just do it', 'athletic', 'sports']
    },
    'apple': {
        'id': 'apple', 'name': 'Apple', 'industry': 'Consumer Electronics',
        'logo': '🍎', 'slogan': 'Think Different',
        'sustainability_score': 8.9, 'sentiment_score': 8.7,
        'authenticity_tips': 'Verify serial numbers on Apple website, check build quality, authentic packaging, Apple Care eligibility',
        'description': 'Multinational technology company specializing in consumer electronics, software, and online services.',
        'founded': '1976', 'headquarters': 'Cupertino, California, USA',
        'market_cap': '$2.8T', 'stock_symbol': 'AAPL',
        'competitors': ['Samsung', 'Google', 'Microsoft', 'Huawei'],
        'website': 'https://www.apple.com',
        'offers': [
            {'title': 'Education Discount 10%', 'code': 'EDU10', 'expires': '2024-12-31'},
            {'title': 'Trade-in Program', 'code': 'TRADE', 'expires': 'Ongoing'}
        ],
        'stores': [
            {'name': 'Apple Store Ikeja City Mall', 'distance': '3.8 km', 'rating': 4.8},
            {'name': 'iStore Victoria Island', 'distance': '1.9 km', 'rating': 4.6}
        ],
        'similar_logos': ['Samsung', 'LG'],
        'brand_colors': ['#007AFF', '#000000', '#FFFFFF'],
        'keywords': ['apple', 'iphone', 'mac', 'ipad', 'bitten apple']
    },
    'coca-cola': {
        'id': 'coca-cola', 'name': 'Coca-Cola', 'industry': 'Beverages',
        'logo': '🥤', 'slogan': 'Taste the Feeling',
        'sustainability_score': 6.4, 'sentiment_score': 7.8,
        'authenticity_tips': 'Check bottle shape, label quality, taste authenticity, expiration dates, and purchase from authorized retailers',
        'description': 'World\'s largest beverage company, known for Coca-Cola and other refreshing soft drinks.',
        'founded': '1886', 'headquarters': 'Atlanta, Georgia, USA',
        'market_cap': '$268B', 'stock_symbol': 'KO',
        'competitors': ['Pepsi', 'Dr Pepper', 'Monster Energy'],
        'website': 'https://www.coca-cola.com',
        'offers': [
            {'title': 'Buy 2 Get 1 Free', 'code': 'BUY2GET1', 'expires': '2024-11-30'},
            {'title': 'Happy Hour 20% Off', 'code': 'HAPPY20', 'expires': '2024-12-31'}
        ],
        'stores': [
            {'name': 'Coca-Cola Store Lagos', 'distance': '1.5 km', 'rating': 4.3},
            {'name': 'ShopRite Supermarket', 'distance': '0.8 km', 'rating': 4.5}
        ],
        'similar_logos': ['Pepsi', 'Dr Pepper'],
        'brand_colors': ['#FF0000', '#FFFFFF'],
        'keywords': ['coca cola', 'coke', 'red', 'script']
    },
    'adidas': {
        'id': 'adidas', 'name': 'Adidas', 'industry': 'Athletic Footwear & Apparel',
        'logo': '👕', 'slogan': 'Impossible is Nothing',
        'sustainability_score': 7.5, 'sentiment_score': 8.0,
        'authenticity_tips': 'Check three stripes alignment, quality materials, official tags, and verify on Adidas Confirmed app',
        'description': 'German multinational corporation that designs and manufactures shoes, clothing and accessories.',
        'founded': '1949', 'headquarters': 'Herzogenaurach, Germany',
        'market_cap': '$45B', 'stock_symbol': 'ADS',
        'competitors': ['Nike', 'Puma', 'Under Armour'],
        'website': 'https://www.adidas.com',
        'offers': [
            {'title': 'Up to 50% Off Sale Items', 'code': 'SALE50', 'expires': '2024-12-31'},
            {'title': 'Free Returns 30 Days', 'code': 'RETURNS', 'expires': 'Ongoing'}
        ],
        'stores': [
            {'name': 'Adidas Store VI', 'distance': '2.8 km', 'rating': 4.6}
        ],
        'similar_logos': ['Nike', 'Puma'],
        'brand_colors': ['#000000', '#FFFFFF'],
        'keywords': ['three stripes', 'trefoil', 'performance']
    },
    'samsung': {
        'id': 'samsung', 'name': 'Samsung', 'industry': 'Consumer Electronics',
        'logo': '📱', 'slogan': 'Do What You Can\'t',
        'sustainability_score': 7.2, 'sentiment_score': 7.9,
        'authenticity_tips': 'Verify IMEI on Samsung website, check build quality, official warranty, Samsung Members app registration',
        'description': 'South Korean multinational conglomerate, world leader in smartphones and electronics.',
        'founded': '1938', 'headquarters': 'Seoul, South Korea',
        'market_cap': '$310B', 'stock_symbol': '005930.KS',
        'competitors': ['Apple', 'Huawei', 'Xiaomi', 'LG'],
        'website': 'https://www.samsung.com',
        'offers': [
            {'title': 'Trade-in Discount up to ₦100,000', 'code': 'TRADEIN', 'expires': '2024-12-31'},
            {'title': 'Student Discount 5%', 'code': 'STUDENT5', 'expires': 'Ongoing'}
        ],
        'stores': [
            {'name': 'Samsung Store Ikeja', 'distance': '4.2 km', 'rating': 4.5}
        ],
        'similar_logos': ['LG', 'Huawei'],
        'brand_colors': ['#1428A0', '#FFFFFF'],
        'keywords': ['samsung', 'galaxy', 'smartphone']
    },
    'starbucks': {
        'id': 'starbucks', 'name': 'Starbucks', 'industry': 'Coffee & Beverages',
        'logo': '☕', 'slogan': 'To inspire and nurture the human spirit',
        'sustainability_score': 7.1, 'sentiment_score': 8.3,
        'authenticity_tips': 'Check for the official siren logo, cup quality, and purchase from authorized Starbucks locations',
        'description': 'World\'s largest coffeehouse chain, known for premium coffee and cozy atmosphere.',
        'founded': '1971', 'headquarters': 'Seattle, Washington, USA',
        'market_cap': '$105B', 'stock_symbol': 'SBUX',
        'competitors': ['Dunkin\' Donuts', 'Costa Coffee', 'Peet\'s Coffee'],
        'website': 'https://www.starbucks.com',
        'offers': [
            {'title': 'Free Drink on Your Birthday', 'code': 'BIRTHDAY', 'expires': 'Ongoing'},
            {'title': 'Stars Rewards Program', 'code': 'STARS', 'expires': 'Ongoing'}
        ],
        'stores': [
            {'name': 'Starbucks Ikeja City Mall', 'distance': '3.8 km', 'rating': 4.7},
            {'name': 'Starbucks Victoria Island', 'distance': '2.1 km', 'rating': 4.6}
        ],
        'similar_logos': ['Costa Coffee', 'Coffee Bean'],
        'brand_colors': ['#006241', '#FFFFFF'],
        'keywords': ['starbucks', 'coffee', 'siren', 'green']
    },
    'microsoft': {
        'id': 'microsoft', 'name': 'Microsoft', 'industry': 'Software & Technology',
        'logo': '💻', 'slogan': 'Be what\'s next',
        'sustainability_score': 8.2, 'sentiment_score': 8.1,
        'authenticity_tips': 'Verify product keys, check holographic labels, and purchase from authorized retailers',
        'description': 'Global technology company known for Windows, Office, Xbox, and cloud services.',
        'founded': '1975', 'headquarters': 'Redmond, Washington, USA',
        'market_cap': '$3.1T', 'stock_symbol': 'MSFT',
        'competitors': ['Apple', 'Google', 'Amazon', 'Oracle'],
        'website': 'https://www.microsoft.com',
        'offers': [
            {'title': 'Student Discount on Office 365', 'code': 'STUDENTOFFICE', 'expires': '2024-12-31'},
            {'title': 'Free OneDrive Storage', 'code': 'ONEDRIVE', 'expires': 'Ongoing'}
        ],
        'stores': [
            {'name': 'Microsoft Experience Center', 'distance': '5.2 km', 'rating': 4.5}
        ],
        'similar_logos': ['IBM', 'HP'],
        'brand_colors': ['#0078D4', '#737373', '#FFFFFF'],
        'keywords': ['microsoft', 'windows', 'office', 'xbox']
    },
    'amazon': {
        'id': 'amazon', 'name': 'Amazon', 'industry': 'E-commerce & Cloud Computing',
        'logo': '📦', 'slogan': 'Work hard. Have fun. Make history.',
        'sustainability_score': 6.8, 'sentiment_score': 7.5,
        'authenticity_tips': 'Check for official Amazon packaging, seller ratings, and purchase from Amazon directly',
        'description': 'Global e-commerce giant and cloud computing provider with diverse product offerings.',
        'founded': '1994', 'headquarters': 'Seattle, Washington, USA',
        'market_cap': '$1.8T', 'stock_symbol': 'AMZN',
        'competitors': ['eBay', 'Walmart', 'Alibaba', 'Google Cloud'],
        'website': 'https://www.amazon.com',
        'offers': [
            {'title': 'Prime Membership Free Trial', 'code': 'PRIMETRIAL', 'expires': '2024-12-31'},
            {'title': 'Free Shipping on Orders Over $25', 'code': 'FREESHIP', 'expires': 'Ongoing'}
        ],
        'stores': [
            {'name': 'Amazon Hub Locker', 'distance': '1.2 km', 'rating': 4.3}
        ],
        'similar_logos': ['eBay', 'Alibaba'],
        'brand_colors': ['#FF9900', '#000000'],
        'keywords': ['amazon', 'smile', 'prime', 'shopping']
    },
    'unknown': {
        'id': 'unknown', 'name': 'Unknown Brand', 'industry': 'Unknown',
        'logo': '❓', 'slogan': 'N/A',
        'sustainability_score': 0, 'sentiment_score': 0,
        'authenticity_tips': 'Cannot verify unknown brand - research thoroughly before purchase',
        'description': 'Brand not recognized in our database. Please verify authenticity independently.',
        'competitors': [], 'offers': [], 'stores': [], 'similar_logos': [],
        'keywords': []
    }
}

# --- UTILITY FUNCTIONS ---
def find_brand_by_name(name: str) -> Dict:
    """Find brand by name with fuzzy matching"""
    name_lower = name.lower()
    
    # Direct name match
    for brand in BRAND_DATABASE.values():
        if brand['id'] != 'unknown' and name_lower in brand['name'].lower():
            return brand
    
    # Keyword match
    for brand in BRAND_DATABASE.values():
        if brand['id'] != 'unknown':
            for keyword in brand.get('keywords', []):
                if keyword in name_lower:
                    return brand
    
    return BRAND_DATABASE['unknown']

def add_to_favorites(username: str, brand_id: str) -> bool:
    """Add brand to user favorites"""
    try:
        conn = sqlite3.connect('luminor_users.db')
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO user_favorites (username, brand_id) VALUES (?, ?)",
            (username, brand_id)
        )
        conn.commit()
        conn.close()
        log_analytics(username, 'brand_favorited', {'brand_id': brand_id})
        return True
    except:
        return False

def remove_from_favorites(username: str, brand_id: str) -> bool:
    """Remove brand from user favorites"""
    try:
        conn = sqlite3.connect('luminor_users.db')
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM user_favorites WHERE username = ? AND brand_id = ?",
            (username, brand_id)
        )
        conn.commit()
        conn.close()
        log_analytics(username, 'brand_unfavorited', {'brand_id': brand_id})
        return True
    except:
        return False

def get_user_favorites(username: str) -> List[Dict]:
    """Get user's favorite brands"""
    try:
        conn = sqlite3.connect('luminor_users.db')
        cursor = conn.cursor()
        cursor.execute(
            "SELECT brand_id FROM user_favorites WHERE username = ?",
            (username,)
        )
        favorites = [row[0] for row in cursor.fetchall()]
        conn.close()
        return [BRAND_DATABASE.get(brand_id, BRAND_DATABASE['unknown']) for brand_id in favorites]
    except:
        return []

# --- UI COMPONENTS ---
def display_brand_card(brand: Dict, username: str = None, show_favorite: bool = True) -> None:
    """Display brand information in a modern card format"""
    col1, col2 = st.columns([1, 3])
    
    with col1:
        st.markdown(f"<h1 style='font-size: 3rem; text-align: center;'>{brand.get('logo', '❓')}</h1>", unsafe_allow_html=True)
    
    with col2:
        st.markdown(f"<h2 style='margin-bottom: 0;'>{brand['name']}</h2>", unsafe_allow_html=True)
        st.markdown(f"<p style='color: #888; margin-top: 0;'>{brand['industry']}</p>", unsafe_allow_html=True)
    
    # Metrics row
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if brand['sustainability_score'] > 0:
            score_class = "high-score" if brand['sustainability_score'] >= 7 else "low-score"
            st.metric("Sustainability", f"{brand['sustainability_score']}/10", delta=None, 
                     help="Environmental and social responsibility score")
    
    with col2:
        if brand['sentiment_score'] > 0:
            score_class = "high-score" if brand['sentiment_score'] >= 7 else "low-score"
            st.metric("Brand Sentiment", f"{brand['sentiment_score']}/10", delta=None,
                     help="Customer satisfaction and brand perception")
    
    with col3:
        if username and show_favorite:
            favorites = get_user_favorites(username)
            is_favorite = any(fav['id'] == brand['id'] for fav in favorites)
            
            if is_favorite:
                if st.button("★ Remove from Favorites", key=f"remove_{brand['id']}"):
                    remove_from_favorites(username, brand['id'])
                    st.rerun()
            else:
                if st.button("☆ Add to Favorites", key=f"add_{brand['id']}"):
                    add_to_favorites(username, brand['id'])
                    st.rerun()
    
    # Additional information
    with st.expander("📋 Brand Details"):
        cols = st.columns(2)
        
        with cols[0]:
            if brand.get('founded'):
                st.write(f"**Founded:** {brand['founded']}")
            if brand.get('headquarters'):
                st.write(f"**Headquarters:** {brand['headquarters']}")
            if brand.get('market_cap'):
                st.write(f"**Market Cap:** {brand['market_cap']}")
            if brand.get('stock_symbol'):
                st.write(f"**Stock Symbol:** {brand['stock_symbol']}")
        
        with cols[1]:
            if brand.get('website'):
                st.write(f"**Website:** [{brand['website']}]({brand['website']})")
            if brand.get('slogan'):
                st.write(f"**Slogan:** \"{brand['slogan']}\"")
    
    # Authenticity tips
    if brand.get('authenticity_tips'):
        st.info(f"🔍 **Authenticity Tips:** {brand['authenticity_tips']}")
    
    # Competitors
    if brand.get('competitors'):
        st.write(f"**Main Competitors:** {', '.join(brand['competitors'])}")
    
    # Offers
    if brand.get('offers') and brand['id'] != 'unknown':
        st.subheader("🎁 Current Offers")
        for offer in brand['offers']:
            st.markdown(f"""
                <div class="offer-badge">
                    {offer['title']} - Code: <strong>{offer['code']}</strong> (Expires: {offer['expires']})
                </div>
            """, unsafe_allow_html=True)
    
    # Nearby stores
    if brand.get('stores') and brand['id'] != 'unknown':
        st.subheader("📍 Nearby Stores")
        for store in brand['stores']:
            st.write(f"**{store['name']}** - {store['distance']} away ⭐ {store['rating']}")

def display_ai_analysis_results(analysis: Dict, username: str = None) -> None:
    """Display AI analysis results in a user-friendly format"""
    if not analysis:
        st.error("No analysis results available.")
        return
    
    # Confidence indicator
    confidence = analysis.get('confidence', 0)
    st.progress(confidence / 100)
    st.caption(f"AI Confidence: {confidence}%")
    
    if analysis.get('brand_detected', False):
        brand_name = analysis.get('brand_name', '').lower()
        brand = find_brand_by_name(brand_name)
        
        if brand['id'] != 'unknown':
            st.success(f"✅ Brand identified: **{brand['name']}**")
            display_brand_card(brand, username)
            
            # Save to history
            if username:
                save_scan_history(username, brand, 'ai', confidence, "")
        else:
            # Create a detailed brand profile from AI analysis
            st.success(f"✅ **{analysis.get('brand_name', 'Brand')}** identified")
            
            # Create a comprehensive brand profile from AI data
            ai_brand = {
                'id': f"ai_{hashlib.md5(analysis.get('brand_name', '').encode()).hexdigest()[:8]}",
                'name': analysis.get('brand_name', 'Detected Brand'),
                'industry': analysis.get('category', 'Various Industries'),
                'logo': '🏢',
                'slogan': analysis.get('slogan', 'No slogan available'),
                'sustainability_score': 6.0,  # Default score for AI-detected brands
                'sentiment_score': 7.0,       # Default score for AI-detected brands
                'authenticity_tips': analysis.get('authenticity_tips', 'Verify through official channels and authorized retailers'),
                'description': analysis.get('description', 'A brand detected through AI analysis.'),
                'founded': analysis.get('founded', 'Unknown'),
                'headquarters': analysis.get('headquarters', 'Unknown'),
                'market_cap': analysis.get('market_cap', 'Unknown'),
                'stock_symbol': analysis.get('stock_symbol', 'Unknown'),
                'competitors': analysis.get('competitors', []),
                'website': analysis.get('website', None),
                'offers': analysis.get('offers', []),
                'stores': analysis.get('stores', []),
                'similar_logos': analysis.get('similar_logos', []),
                'brand_colors': analysis.get('colors', []),
                'keywords': analysis.get('keywords', []),
                'logo_elements': analysis.get('logo_elements', [])
            }
            
            # Display the AI-generated brand profile
            display_brand_card(ai_brand, username)
            
            # Save to history
            if username:
                save_scan_history(username, ai_brand, 'ai', confidence, "")
    else:
        st.warning("❌ No recognizable brand detected")
        st.write(f"**Analysis:** {analysis.get('description', 'No specific brand elements detected')}")
    
    # Additional AI insights
    if analysis.get('logo_elements'):
        with st.expander("🔍 Logo Analysis Details"):
            st.write("**Visual Elements Detected:**")
            for element in analysis.get('logo_elements', []):
                st.write(f"- {element}")
            
            if analysis.get('colors'):
                st.write("**Dominant Colors:**")
                colors_html = " ".join([
                    f'<span style="display:inline-block; width:20px; height:20px; background-color:{color}; margin:0 5px; border-radius:3px;" title="{color}"></span>'
                    for color in analysis.get('colors', [])
                ])
                st.markdown(colors_html, unsafe_allow_html=True)
    
    if analysis.get('similar_logos'):
        st.write("**Similar Logos:**")
        st.write(", ".join(analysis.get('similar_logos', [])))

# --- MAIN APPLICATION ---
def main():
    # Initialize database
    init_database()
    
    # Check for remember token
    if 'username' not in st.session_state:
        remembered_user = check_remember_token()
        if remembered_user:
            st.session_state.username = remembered_user
            st.session_state.logged_in = True
    
    # Apply theme
    if 'user_preferences' in st.session_state:
        theme_name = st.session_state.user_preferences.get('theme', 'Cyber Dark')
        apply_theme(THEMES[theme_name])
    else:
        apply_theme(THEMES['Cyber Dark'])
    
    # Main header
    st.markdown("""
        <div class="main-header">
            <h1 style="color: white; margin: 0;">🔍 Luminor AI</h1>
            <p style="color: white; opacity: 0.9; margin: 0;">Advanced Brand Detection & Authentication Platform</p>
        </div>
    """, unsafe_allow_html=True)
    
    # Navigation
    if 'logged_in' in st.session_state and st.session_state.logged_in:
        tabs = st.tabs(["🏠 Home", "📸 Scan", "📊 Dashboard", "⭐ Favorites", "⚙️ Settings"])
        
        with tabs[0]:
            st.header(f"Welcome back, {st.session_state.username}! 👋")
            
            # User statistics
            stats = get_user_statistics(st.session_state.username)
            if stats:
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    st.markdown("""
                        <div class="metric-card">
                            <h3>Total Scans</h3>
                            <h2>{total_scans}</h2>
                        </div>
                    """.format(**stats), unsafe_allow_html=True)
                
                with col2:
                    st.markdown("""
                        <div class="metric-card">
                            <h3>Unique Brands</h3>
                            <h2>{unique_brands}</h2>
                        </div>
                    """.format(**stats), unsafe_allow_html=True)
                
                with col3:
                    st.markdown("""
                        <div class="metric-card">
                            <h3>Favorites</h3>
                            <h2>{favorites_count}</h2>
                        </div>
                    """.format(**stats), unsafe_allow_html=True)
                
                with col4:
                    st.markdown("""
                        <div class="metric-card">
                            <h3>Avg Confidence</h3>
                            <h2>{avg_confidence}%</h2>
                        </div>
                    """.format(**stats), unsafe_allow_html=True)
            
            # Recent scans
            st.subheader("📋 Recent Scans")
            history = load_user_history(st.session_state.username, 5)
            if history:
                for item in history:
                    display_brand_card(item, st.session_state.username, show_favorite=False)
            else:
                st.info("No scan history yet. Upload an image to get started!")
        
        with tabs[1]:
            st.header("📸 Brand Scanner")
            
            upload_col, manual_col = st.columns(2)
            
            with upload_col:
                st.subheader("AI-Powered Scan")
                uploaded_file = st.file_uploader("Upload an image with a brand logo", type=['jpg', 'jpeg', 'png'])
                
                if uploaded_file is not None:
                    image = Image.open(uploaded_file)
                    st.image(image, caption="Uploaded Image", use_container_width=True)
                    
                    if st.button("🔍 Analyze with AI", type="primary"):
                        with st.spinner("Analyzing image with AI..."):
                            analysis = analyze_image_with_openai(image, OPENAI_API_KEY)
                            if analysis:
                                display_ai_analysis_results(analysis, st.session_state.username)
            
            with manual_col:
                st.subheader("Manual Brand Lookup")
                search_term = st.text_input("Enter brand name")
                
                if search_term:
                    brand = find_brand_by_name(search_term)
                    display_brand_card(brand, st.session_state.username)
        
        with tabs[2]:
            st.header("📊 User Dashboard")
            
            # Advanced statistics
            stats = get_user_statistics(st.session_state.username)
            if stats:
                col1, col2 = st.columns(2)
                
                with col1:
                    st.subheader("Scan Distribution")
                    scan_data = pd.DataFrame({
                        'Type': list(stats['scan_types'].keys()),
                        'Count': list(stats['scan_types'].values())
                    })
                    st.bar_chart(scan_data.set_index('Type'))
                
                with col2:
                    st.subheader("Performance Metrics")
                    st.metric("Average Confidence", f"{stats['avg_confidence']}%")
                    st.metric("Detection Rate", f"{(stats['unique_brands'] / stats['total_scans'] * 100):.1f}%" if stats['total_scans'] > 0 else "0%")
            
            # Full history
            st.subheader("Full Scan History")
            full_history = load_user_history(st.session_state.username, 20)
            if full_history:
                for item in full_history:
                    display_brand_card(item, st.session_state.username, show_favorite=False)
            else:
                st.info("No scan history available.")
        
        with tabs[3]:
            st.header("⭐ Favorite Brands")
            
            favorites = get_user_favorites(st.session_state.username)
            if favorites:
                for brand in favorites:
                    display_brand_card(brand, st.session_state.username)
            else:
                st.info("No favorite brands yet. Add some by clicking the star icon on brand cards!")
        
        with tabs[4]:
            st.header("⚙️ Settings")
            
            # Theme selection
            current_theme = st.session_state.user_preferences.get('theme', 'Cyber Dark')
            new_theme = st.selectbox(
                "Select Theme",
                options=list(THEMES.keys()),
                index=list(THEMES.keys()).index(current_theme)
            )
            
            if new_theme != current_theme:
                st.session_state.user_preferences['theme'] = new_theme
                
                # Save to database
                try:
                    conn = sqlite3.connect('luminor_users.db')
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE users SET preferences = ? WHERE username = ?",
                        (json.dumps(st.session_state.user_preferences), st.session_state.username)
                    )
                    conn.commit()
                    conn.close()
                    st.success("Theme updated successfully!")
                    st.rerun()
                except:
                    st.error("Failed to save preferences")
            
            # Account management
            st.subheader("Account")
            if st.button("🚪 Logout"):
                st.session_state.clear()
                st.rerun()
            
            if st.button("🗑️ Delete Account", type="secondary"):
                st.warning("This action cannot be undone. All your data will be permanently deleted.")
                if st.button("Confirm Deletion"):
                    try:
                        conn = sqlite3.connect('luminor_users.db')
                        cursor = conn.cursor()
                        cursor.execute("DELETE FROM users WHERE username = ?", (st.session_state.username,))
                        cursor.execute("DELETE FROM user_history WHERE username = ?", (st.session_state.username,))
                        cursor.execute("DELETE FROM user_favorites WHERE username = ?", (st.session_state.username,))
                        cursor.execute("DELETE FROM analytics WHERE username = ?", (st.session_state.username,))
                        conn.commit()
                        conn.close()
                        st.session_state.clear()
                        st.success("Account deleted successfully")
                        st.rerun()
                    except:
                        st.error("Failed to delete account")
    
    else:
        # Authentication interface
        auth_tab, register_tab = st.tabs(["🔐 Login", "📝 Register"])
        
        with auth_tab:
            st.header("Login to Luminor AI")
            
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            remember_me = st.checkbox("Remember me")
            
            if st.button("Login", type="primary"):
                if authenticate_user(username, password, remember_me):
                    st.session_state.username = username
                    st.session_state.logged_in = True
                    st.success("Login successful!")
                    st.rerun()
                else:
                    st.error("Invalid username or password")
        
        with register_tab:
            st.header("Create Account")
            
            new_username = st.text_input("Choose Username", key="reg_user")
            new_email = st.text_input("Email (optional)", key="reg_email")
            new_password = st.text_input("Create Password", type="password", key="reg_pass")
            confirm_password = st.text_input("Confirm Password", type="password", key="reg_confirm")
            
            if st.button("Create Account", type="primary"):
                if new_password != confirm_password:
                    st.error("Passwords do not match")
                elif len(new_username) < 3:
                    st.error("Username must be at least 3 characters")
                elif len(new_password) < 6:
                    st.error("Password must be at least 6 characters")
                else:
                    if create_user(new_username, new_password, new_email):
                        st.success("Account created successfully! Please login.")
                    else:
                        st.error("Username already exists")

if __name__ == "__main__":
    main()