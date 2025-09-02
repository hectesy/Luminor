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

# --- CONFIGURATION ---
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY")
st.set_page_config(
    page_title="Luminor AI",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- DATABASE SETUP ---
def init_database():
    conn = sqlite3.connect('luminor_users.db')
    cursor = conn.cursor()
    
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

# --- AUTHENTICATION ---
def hash_password(password: str) -> str:
    salt = "luminor_ai_salt_2024"
    return hashlib.sha256((password + salt).encode()).hexdigest()

def create_user(username: str, password: str, email: str = "", remember_me: bool = False) -> bool:
    try:
        if len(username) < 3 or len(password) < 6:
            st.error("Username must be at least 3 characters and password at least 6 characters.")
            return False
            
        conn = sqlite3.connect('luminor_users.db')
        cursor = conn.cursor()
        
        cursor.execute("SELECT username FROM users WHERE username = ?", (username,))
        if cursor.fetchone():
            st.error("Username already exists.")
            conn.close()
            return False
            
        password_hash = hash_password(password)
        default_prefs = json.dumps({'theme': 'Cyber Dark', 'notifications': True, 'auto_save_scans': True})
        
        token = None
        expires = None
        if remember_me:
            token = hashlib.sha256(f"{username}{time.time()}".encode()).hexdigest()
            expires = datetime.now() + timedelta(days=30)
        
        cursor.execute(
            "INSERT INTO users (username, password_hash, email, preferences, remember_token, token_expires) VALUES (?, ?, ?, ?, ?, ?)",
            (username, password_hash, email, default_prefs, token, expires)
        )
        
        conn.commit()
        conn.close()
        return True
    except sqlite3.Error as e:
        st.error(f"Error saving user: {str(e)}")
        return False

def authenticate_user(username: str, password: str, remember_me: bool = False) -> bool:
    try:
        conn = sqlite3.connect('luminor_users.db')
        cursor = conn.cursor()
        
        password_hash = hash_password(password)
        cursor.execute(
            "SELECT username, preferences FROM users WHERE username = ? AND password_hash = ?",
            (username, password_hash)
        )
        
        user = cursor.fetchone()
        
        if user:
            cursor.execute(
                "UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE username = ?",
                (username,)
            )
            
            if user[1]:
                st.session_state.user_preferences = json.loads(user[1])
            else:
                st.session_state.user_preferences = {'theme': 'Cyber Dark'}
            
            if remember_me:
                token = hashlib.sha256(f"{username}{time.time()}".encode()).hexdigest()
                expires = datetime.now() + timedelta(days=30)
                cursor.execute(
                    "UPDATE users SET remember_token = ?, token_expires = ? WHERE username = ?",
                    (token, expires, username)
                )
                st.session_state.remember_token = token
            
            conn.commit()
            conn.close()
            return True
        
        conn.close()
        return False
    except sqlite3.Error:
        return False

def check_remember_token() -> Optional[str]:
    try:
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
    except sqlite3.Error:
        return None

# --- ANALYTICS ---
def log_analytics(username: str, action: str, data: Dict[str, Any]) -> None:
    try:
        conn = sqlite3.connect('luminor_users.db')
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO analytics (username, action, data) VALUES (?, ?, ?)",
            (username, action, json.dumps(data))
        )
        conn.commit()
        conn.close()
    except sqlite3.Error:
        pass

def get_user_statistics(username: str) -> Dict[str, Any]:
    try:
        conn = sqlite3.connect('luminor_users.db')
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM user_history WHERE username = ?", (username,))
        total_scans = cursor.fetchone()[0]
        
        cursor.execute("SELECT DISTINCT brand_data FROM user_history WHERE username = ?", (username,))
        unique_brands = len(set(json.loads(row[0])['id'] for row in cursor.fetchall() if json.loads(row[0])['id'] != 'unknown'))
        
        cursor.execute("SELECT COUNT(*) FROM user_favorites WHERE username = ?", (username,))
        favorites_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT AVG(confidence) FROM user_history WHERE username = ? AND confidence > 0", (username,))
        avg_confidence = cursor.fetchone()[0] or 0
        
        conn.close()
        return {
            'total_scans': total_scans,
            'unique_brands': unique_brands,
            'favorites_count': favorites_count,
            'avg_confidence': round(avg_confidence, 1)
        }
    except sqlite3.Error:
        return {}

# --- DATA MANAGEMENT ---
def save_scan_history(username: str, brand_data: Dict, scan_type: str = 'manual', 
                     confidence: float = 0, image_hash: str = "") -> None:
    try:
        conn = sqlite3.connect('luminor_users.db')
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO user_history (username, brand_data, scan_type, confidence, image_hash) VALUES (?, ?, ?, ?, ?)",
            (username, json.dumps(brand_data), scan_type, confidence, image_hash)
        )
        conn.commit()
        conn.close()
        log_analytics(username, 'brand_scanned', {
            'brand_id': brand_data.get('id'),
            'brand_name': brand_data.get('name'),
            'scan_type': scan_type,
            'confidence': confidence
        })
    except sqlite3.Error:
        pass

def load_user_history(username: str, limit: Optional[int] = 50) -> List[Dict]:
    try:
        conn = sqlite3.connect('luminor_users.db')
        cursor = conn.cursor()
        sql = "SELECT brand_data, scan_type, confidence, scanned_at FROM user_history WHERE username = ? ORDER BY scanned_at DESC"
        params = (username,)
        if limit is not None:
            sql += " LIMIT ?"
            params = params + (limit,)
        cursor.execute(sql, params)
        results = cursor.fetchall()
        conn.close()
        history = []
        for row in results:
            try:
                brand_data = json.loads(row[0])
                if not isinstance(brand_data, dict) or 'id' not in brand_data:
                    continue
                brand_data['scan_metadata'] = {
                    'scan_type': row[1],
                    'confidence': row[2],
                    'scanned_at': row[3]
                }
                history.append(brand_data)
            except json.JSONDecodeError:
                continue
        return history
    except sqlite3.Error:
        return []

def generate_image_hash(image_data: Image.Image) -> str:
    try:
        buffered = io.BytesIO()
        image_data.save(buffered, format="PNG")
        return hashlib.md5(buffered.getvalue()).hexdigest()
    except:
        return ""

# --- OPENAI INTEGRATION ---
def analyze_image_with_openai(image_data: Image.Image, api_key: str) -> Optional[Dict]:
    try:
        client = openai.OpenAI(api_key=api_key)
        buffered = io.BytesIO()
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
                            "text": """Analyze this image for brand logos and return ONLY a JSON response:
                            {
                                "brand_detected": true/false,
                                "brand_name": "exact brand name or null",
                                "confidence": 0-100,
                                "logo_elements": ["list of visual elements, e.g., shapes, symbols"],
                                "colors": ["dominant colors in hex"],
                                "description": "detailed description of the brand or logo",
                                "category": "inferred industry (e.g., Fashion, Tech, Food)",
                                "sentiment_score": 0-10,
                                "sustainability_score": 0-10,
                                "founded": "year founded or null",
                                "headquarters": "location or null",
                                "market_cap": "market cap or null",
                                "competitors": ["list of potential competitors"],
                                "stores": [{"name": "store name", "distance": "distance in km", "rating": float}],
                                "similar_logos": ["brands with similar logos"],
                                "keywords": ["relevant keywords for the brand or logo"]
                            }
                            For known brands, provide precise details. For unknown brands, infer details from logo style, colors, and context. Estimate sentiment_score (0-10) based on logo aesthetics: modern, clean=8-10; cluttered, dated=3-6; generic=0-3. Estimate sustainability_score (0-10) based on colors (e.g., green=7-9) and inferred industry (e.g., eco-friendly=high). Include at least 3 competitors and 5 keywords for unknown brands. For stores, return a list of dictionaries with name, distance, and rating."""
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{img_str}"}
                        }
                    ]
                }
            ],
            max_tokens=500,
            temperature=0.2
        )
        
        content = response.choices[0].message.content.strip()
        if content.startswith('```json'):
            content = content.replace('```json', '').replace('```', '').strip()
        elif content.startswith('```'):
            content = content.replace('```', '').strip()
        
        try:
            result = json.loads(content)
            # Validate required fields
            required_fields = ['brand_detected', 'brand_name', 'confidence']
            for field in required_fields:
                if field not in result:
                    st.error(f"Invalid OpenAI response: missing '{field}' field")
                    return None
            # Normalize stores to ensure list of dictionaries
            if 'stores' in result and result['stores']:
                normalized_stores = []
                for store in result['stores']:
                    if isinstance(store, dict) and 'name' in store:
                        normalized_stores.append({
                            'name': store.get('name', 'Unknown Store'),
                            'distance': store.get('distance', 'N/A'),
                            'rating': float(store.get('rating', 0.0))
                        })
                    elif isinstance(store, str):
                        normalized_stores.append({
                            'name': store,
                            'distance': 'N/A',
                            'rating': 0.0
                        })
                result['stores'] = normalized_stores
            result['confidence'] = float(result.get('confidence', 0))
            result['sentiment_score'] = float(result.get('sentiment_score', 0))
            result['sustainability_score'] = float(result.get('sustainability_score', 0))
            return result
        except json.JSONDecodeError:
            st.error("Invalid JSON response from OpenAI")
            return None
    except Exception as e:
        st.error(f"AI Analysis Error: {str(e)}")
        return None

# --- THEMES ---
THEMES = {
    "Cyber Dark": {
        "primary": "#00D4FF", "secondary": "#FF006B", "background": "#0A0A0B",
        "surface": "#1A1A1B", "text": "#FFFFFF", "success": "#00FF88",
        "warning": "#FFB700", "error": "#FF4444"
    },
    "Ocean Light": {
        "primary": "#0EA5E9", "secondary": "#06B6D4", "background": "#E0F2FE",
        "surface": "#F0F9FF", "text": "#0F172A", "success": "#10B981",
        "warning": "#F59E0B", "error": "#EF4444"
    }
}

def apply_theme(theme: Dict[str, str]) -> None:
    st.markdown(f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
        .stApp {{
            background-color: {theme['background']} !important;
            color: {theme['text']};
            font-family: 'Inter', sans-serif;
        }}
        .stApp > div, .block-container {{
            background-color: {theme['background']};
        }}
        .css-1d391kg {{
            background-color: {theme['surface']} !important;
        }}
        .stTextInput > div > div > input, .stSelectbox > div > div > div, .stTextArea > div > div > textarea {{
            background-color: {theme['surface']} !important;
            color: {theme['text']} !important;
            border: 1px solid {theme['primary']} !important;
        }}
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
        .stTabs [data-baseweb="tab-list"], .stTabs [data-baseweb="tab"] {{
            background-color: {theme['surface']} !important;
            color: {theme['text']} !important;
        }}
        .stTabs [aria-selected="true"] {{
            background-color: {theme['primary']} !important;
            color: white !important;
        }}
        [data-testid="metric-container"] {{
            background-color: {theme['surface']} !important;
            border: 1px solid {theme['primary']} !important;
            border-radius: 10px !important;
            padding: 1rem !important;
        }}
        h1, h2, h3, h4, h5, h6, p, div, span {{
            color: {theme['text']} !important;
        }}
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
        }}
        .metric-card:hover {{
            transform: scale(1.05);
        }}
        .high-score {{ color: {theme['success']}; font-weight: 600; }}
        .low-score {{ color: {theme['warning']}; font-weight: 600; }}
        .confidence-bar {{
            width: 100%;
            height: 8px;
            background-color: rgba(255,255,255,0.2);
            border-radius: 4px;
            overflow: hidden;
            margin: 0.5rem 0;
        }}
        .stAlert {{
            background-color: {theme['surface']} !important;
            border: 1px solid {theme['primary']} !important;
            color: {theme['text']} !important;
        }}
        </style>
        """, unsafe_allow_html=True)

# --- BRAND DATABASE ---
BRAND_DATABASE = {
    'nike': {
        'id': 'nike', 'name': 'Nike', 'industry': 'Athletic Footwear & Apparel', 'logo': '👟', 'slogan': 'Just Do It',
        'sustainability_score': 7.8, 'sentiment_score': 8.2, 'authenticity_tips': 'Check swoosh alignment, quality stitching, official tags.',
        'description': 'Global leader in athletic footwear and apparel.', 'founded': '1964', 'headquarters': 'Beaverton, OR, USA',
        'market_cap': '$196.5B', 'stock_symbol': 'NKE', 'competitors': ['Adidas', 'Puma', 'Under Armour'],
        'website': 'https://www.nike.com',
        'stores': [{'name': 'Nike Store VI', 'distance': '2.1 km', 'rating': 4.7}],
        'similar_logos': ['Puma', 'Adidas'],
        'brand_colors': ['#000000', '#FFFFFF'], 'keywords': ['swoosh', 'athletic', 'sports']
    },
    'apple': {
        'id': 'apple', 'name': 'Apple', 'industry': 'Consumer Electronics', 'logo': '🍎', 'slogan': 'Think Different',
        'sustainability_score': 8.9, 'sentiment_score': 8.7, 'authenticity_tips': 'Verify serial numbers on Apple website.',
        'description': 'Multinational technology company.', 'founded': '1976', 'headquarters': 'Cupertino, CA, USA',
        'market_cap': '$2.8T', 'stock_symbol': 'AAPL', 'competitors': ['Samsung', 'Google', 'Microsoft'],
        'website': 'https://www.apple.com',
        'stores': [{'name': 'Apple Store Ikeja', 'distance': '3.8 km', 'rating': 4.8}],
        'similar_logos': ['Samsung', 'LG'],
        'brand_colors': ['#007AFF', '#000000', '#FFFFFF'], 'keywords': ['iphone', 'mac', 'ipad']
    },
    'unknown': {
        'id': 'unknown', 'name': 'Unknown Brand', 'industry': 'Unknown', 'logo': '❓', 'slogan': 'N/A',
        'sustainability_score': 0, 'sentiment_score': 0, 'authenticity_tips': 'Research thoroughly before purchase.',
        'description': 'Brand not recognized in our database.', 'competitors': [], 'stores': [], 'similar_logos': [],
        'keywords': []
    }
}

# --- UTILITY FUNCTIONS ---
def find_brand_by_name(name: str) -> Dict:
    name_lower = name.lower()
    for brand in BRAND_DATABASE.values():
        if brand['id'] != 'unknown' and name_lower in brand['name'].lower():
            return brand
    for brand in BRAND_DATABASE.values():
        if brand['id'] != 'unknown':
            for keyword in brand.get('keywords', []):
                if keyword in name_lower:
                    return brand
    return BRAND_DATABASE['unknown']

def clean_invalid_favorites(username: str) -> None:
    try:
        conn = sqlite3.connect('luminor_users.db')
        cursor = conn.cursor()
        cursor.execute("SELECT brand_id FROM user_favorites WHERE username = ?", (username,))
        favorite_ids = [row[0] for row in cursor.fetchall()]
        history = load_user_history(username, limit=None)
        for brand_id in favorite_ids:
            if brand_id not in BRAND_DATABASE and not any(b['id'] == brand_id for b in history):
                cursor.execute("DELETE FROM user_favorites WHERE username = ? AND brand_id = ?", (username, brand_id))
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        st.error(f"Error cleaning favorites: {str(e)}")

def add_to_favorites(username: str, brand_id: str) -> bool:
    try:
        conn = sqlite3.connect('luminor_users.db')
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO user_favorites (username, brand_id, notes) VALUES (?, ?, ?)", (username, brand_id, ""))
        affected_rows = cursor.rowcount
        conn.commit()
        conn.close()
        if affected_rows > 0:
            log_analytics(username, 'brand_favorited', {'brand_id': brand_id})
            return True
        return False
    except sqlite3.Error as e:
        st.error(f"Error adding to favorites: {str(e)}")
        return False

def remove_from_favorites(username: str, brand_id: str) -> bool:
    try:
        conn = sqlite3.connect('luminor_users.db')
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_favorites WHERE username = ? AND brand_id = ?", (username, brand_id))
        affected_rows = cursor.rowcount
        conn.commit()
        conn.close()
        if affected_rows > 0:
            log_analytics(username, 'brand_unfavorited', {'brand_id': brand_id})
            return True
        return False
    except sqlite3.Error as e:
        st.error(f"Error removing from favorites: {str(e)}")
        return False

def get_user_favorites(username: str) -> List[str]:
    try:
        conn = sqlite3.connect('luminor_users.db')
        cursor = conn.cursor()
        cursor.execute("SELECT brand_id FROM user_favorites WHERE username = ?", (username,))
        results = cursor.fetchall()
        conn.close()
        return [row[0] for row in results]
    except sqlite3.Error as e:
        st.error(f"Error fetching favorites: {str(e)}")
        return []

def is_favorite(username: str, brand_id: str) -> bool:
    return brand_id in get_user_favorites(username)

# --- INTRO SCREEN ---
def intro_screen():
    st.markdown(
        """
        <style>
        .centered { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 85vh; }
        .title { font-size: 3em; font-weight: bold; color: #4CAF50; animation: fadeIn 2s ease-in; }
        .subtitle { font-size: 1.2em; color: #888; margin-top: -10px; }
        @keyframes fadeIn { from {opacity: 0;} to {opacity: 1;} }
        </style>
        <div class="centered">
            <div class="title">✨ Luminor ✨</div>
            <div class="subtitle">AI Brand Intelligence</div>
        </div>
        """,
        unsafe_allow_html=True
    )
    placeholder = st.empty()
    message = "🔍 Searching logos..."
    for i in range(len(message) + 1):
        placeholder.markdown(f"<p style='text-align:center;'>{message[:i]}</p>", unsafe_allow_html=True)
        time.sleep(0.05)
    time.sleep(0.8)
    st.success("✅ Ready to analyze your logo!")
    if st.button("🚀 Start Now", key="start_now"):
        st.session_state.show_intro = False
        st.rerun()

# --- UI COMPONENTS ---
def render_confidence_bar(confidence: float) -> None:
    st.markdown(f"""
    <div class="confidence-bar">
        <div style="width: {confidence}%; height: 100%; background: linear-gradient(90deg, #FFB700, #00FF88); border-radius: 4px;"></div>
    </div>
    <small>Confidence: {confidence:.1f}%</small>
    """, unsafe_allow_html=True)

def render_brand_card(brand: Dict, username: Optional[str] = None) -> None:
    theme = THEMES[st.session_state.selected_theme]
    st.markdown(f"""
    <div class="brand-card">
        <div style="display: flex; align-items: center; margin-bottom: 1rem;">
            <div style="font-size: 3rem; margin-right: 1rem;">{brand['logo']}</div>
            <div>
                <h2 style="margin: 0; color: {theme['primary']};">{brand['name']}</h2>
                <p style="margin: 0; opacity: 0.8;">{brand['industry']}</p>
                <small style="opacity: 0.6;">"{brand['slogan']}"</small>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    if 'scan_metadata' in brand:
        metadata = brand['scan_metadata']
        st.caption(f"Scanned: {metadata['scanned_at']} | Type: {metadata['scan_type']}")
        if metadata['confidence'] > 0:
            render_confidence_bar(metadata['confidence'])
    
    if username:
        col1, col2 = st.columns([1, 4])
        with col1:
            is_fav = is_favorite(username, brand['id'])
            button_label = "❤️ Remove from Favorites" if is_fav else "🤍 Add to Favorites"
            if st.button(button_label, key=f"fav_{brand['id']}"):
                if is_fav:
                    if remove_from_favorites(username, brand['id']):
                        st.success("Removed from favorites!")
                    else:
                        st.error("Failed to remove from favorites")
                else:
                    if add_to_favorites(username, brand['id']):
                        st.success("Added to favorites!")
                    else:
                        st.error("Failed to add to favorites")
                st.rerun()
    
    col1, col2, col3 = st.columns(3)
    with col1:
        score = brand.get('sustainability_score', 0)
        st.markdown(f"""
        <div class="metric-card">
            <h4>Sustainability</h4>
            <div class="{'high-score' if score > 7 else 'low-score' if score > 0 else ''}">{score}/10</div>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        score = brand.get('sentiment_score', 0)
        st.markdown(f"""
        <div class="metric-card">
            <h4>Sentiment</h4>
            <div class="{'high-score' if score > 7 else 'low-score' if score > 0 else ''}">{score}/10</div>
        </div>
        """, unsafe_allow_html=True)
    with col3:
        if 'market_cap' in brand and brand['market_cap']:
            st.markdown(f"""
            <div class="metric-card">
                <h4>Market Cap</h4>
                <div>{brand['market_cap']}</div>
            </div>
            """, unsafe_allow_html=True)
    
    tab1, tab2, tab3 = st.tabs(["ℹ️ Info", "🔍 Authenticity", "🏪 Stores"])
    with tab1:
        st.write(f"**Description:** {brand['description']}")
        if 'founded' in brand and brand['founded']:
            st.write(f"**Founded:** {brand['founded']}")
        if 'headquarters' in brand and brand['headquarters']:
            st.write(f"**Headquarters:** {brand['headquarters']}")
        if 'competitors' in brand and brand['competitors']:
            st.write(f"**Main Competitors:** {', '.join(brand['competitors'])}")
        if 'website' in brand and brand['website']:
            st.write(f"**Website:** [Visit Official Site]({brand['website']})")
        if 'colors' in brand and brand['colors']:
            st.write(f"**Brand Colors:** {', '.join(brand['colors'])}")
        if 'logo_elements' in brand and brand['logo_elements']:
            st.write(f"**Logo Elements:** {', '.join(brand['logo_elements'])}")
        if 'keywords' in brand and brand['keywords']:
            st.write(f"**Keywords:** {', '.join(brand['keywords'])}")
    with tab2:
        st.write("**How to verify authenticity:**")
        st.info(brand['authenticity_tips'])
        if 'similar_logos' in brand and brand['similar_logos']:
            st.warning(f"⚠️ **Be careful of similar logos from:** {', '.join(brand['similar_logos'])}")
    with tab3:
        if 'stores' in brand and brand['stores']:
            st.write("**Nearby stores:**")
            for store in brand['stores']:
                if isinstance(store, dict):
                    st.write(f"📍 **{store.get('name', 'Unknown Store')}** - {store.get('distance', 'N/A')} away ⭐ {store.get('rating', 0.0)}")
                elif isinstance(store, str):
                    st.write(f"📍 **{store}** - Distance: N/A ⭐ Rating: N/A")
                else:
                    st.warning("Invalid store format detected.")
        else:
            st.info("No nearby stores found.")

# --- AUTH UI ---
def render_login_form():
    st.markdown('<div class="main-header"><h1>🔍 Luminor AI</h1><p>Advanced Brand Recognition & Analysis</p></div>', unsafe_allow_html=True)
    tab1, tab2 = st.tabs(["🔐 Login", "📝 Register"])
    
    with tab1:
        st.subheader("Welcome back!")
        with st.form("login_form"):
            username = st.text_input("Username", placeholder="Enter your username", key="login_username")
            password = st.text_input("Password", type="password", placeholder="Enter your password", key="login_password")
            remember_me = st.checkbox("Remember me for 30 days", key="login_remember")
            if st.form_submit_button("Login", use_container_width=True):
                if username and password:
                    if authenticate_user(username, password, remember_me):
                        st.session_state.authenticated = True
                        st.session_state.username = username
                        st.session_state.show_intro = False
                        st.success("✅ Login successful!")
                        st.rerun()
                    else:
                        st.error("❌ Invalid credentials")
                else:
                    st.error("Please fill all fields")
    
    with tab2:
        st.subheader("Join Luminor AI")
        with st.form("register_form"):
            new_username = st.text_input("Username", placeholder="Choose a username (min 3 characters)", key="register_username")
            new_email = st.text_input("Email", placeholder="Enter your email (optional)", key="register_email")
            new_password = st.text_input("Password", type="password", placeholder="Choose a password (min 6 characters)", key="register_password")
            confirm_password = st.text_input("Confirm Password", type="password", placeholder="Confirm your password", key="register_confirm_password")
            remember_me = st.checkbox("Remember me for 30 days", key="register_remember")
            if st.form_submit_button("Create Account", use_container_width=True):
                if new_username and new_password and confirm_password:
                    if len(new_username) < 3:
                        st.error("Username must be at least 3 characters")
                    elif len(new_password) < 6:
                        st.error("Password must be at least 6 characters")
                    elif new_password != confirm_password:
                        st.error("Passwords don't match")
                    else:
                        if create_user(new_username, new_password, new_email, remember_me):
                            st.session_state.authenticated = True
                            st.session_state.username = new_username
                            st.session_state.show_intro = False
                            if remember_me:
                                st.session_state.remember_token = hashlib.sha256(f"{new_username}{time.time()}".encode()).hexdigest()
                            st.success(f"✅ Account created and logged in as {new_username}!")
                            st.rerun()
                        else:
                            st.error("❌ Username already exists or registration failed")
                else:
                    st.error("Please fill all required fields")

# --- USER DASHBOARD ---
def render_user_dashboard():
    username = st.session_state.username
    stats = get_user_statistics(username)
    st.markdown(f'<div class="main-header"><h1>Welcome back, {username}! 👋</h1></div>', unsafe_allow_html=True)
    
    if stats:
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Scans", stats.get('total_scans', 0))
        with col2:
            st.metric("Unique Brands", stats.get('unique_brands', 0))
        with col3:
            st.metric("Favorites", stats.get('favorites_count', 0))
        with col4:
            st.metric("Avg Confidence", f"{stats.get('avg_confidence', 0)}%")

# --- MAIN APPLICATION ---
def main():
    init_database()
    
    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False
        st.session_state.username = None
        st.session_state.selected_theme = 'Cyber Dark'
        st.session_state.user_preferences = {'theme': 'Cyber Dark'}
        st.session_state.show_intro = True
        
        remembered_user = check_remember_token()
        if remembered_user:
            st.session_state.authenticated = True
            st.session_state.username = remembered_user
            st.session_state.show_intro = False
    
    apply_theme(THEMES[st.session_state.selected_theme])
    
    if st.session_state.show_intro:
        intro_screen()
        return
    
    if not st.session_state.authenticated:
        render_login_form()
        return
    
    with st.sidebar:
        st.markdown(f"### 👤 {st.session_state.username}")
        theme_choice = st.selectbox(
            "🎨 Theme",
            list(THEMES.keys()),
            index=list(THEMES.keys()).index(st.session_state.selected_theme),
            key="theme_selector"
        )
        if theme_choice != st.session_state.selected_theme:
            st.session_state.selected_theme = theme_choice
            st.session_state.user_preferences['theme'] = theme_choice
            try:
                conn = sqlite3.connect('luminor_users.db')
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE users SET preferences = ? WHERE username = ?",
                    (json.dumps(st.session_state.user_preferences), st.session_state.username)
                )
                conn.commit()
                conn.close()
            except sqlite3.Error:
                pass
            st.rerun()
        
        st.divider()
        page = st.selectbox("Navigate", [
            "🏠 Dashboard", "🔍 Brand Scanner", "📷 AI Image Analysis",
            "⭐ Favorites", "📊 History", "⚙️ Settings"
        ], key="nav_selector")
        st.divider()
        if st.button("🚪 Logout", use_container_width=True, key="logout_button"):
            try:
                conn = sqlite3.connect('luminor_users.db')
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE users SET remember_token = NULL, token_expires = NULL WHERE username = ?",
                    (st.session_state.username,)
                )
                conn.commit()
                conn.close()
            except sqlite3.Error:
                pass
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
    
    if page == "🏠 Dashboard":
        render_user_dashboard()
        st.subheader("Recent Activity")
        history = load_user_history(st.session_state.username, limit=5)
        if history:
            for brand in history:
                render_brand_card(brand, st.session_state.username)
        else:
            st.info("No recent activity. Start scanning some brands!")
    
    elif page == "🔍 Brand Scanner":
        st.markdown('<div class="main-header"><h1>🔍 Brand Scanner</h1><p>Search and analyze brands</p></div>', unsafe_allow_html=True)
        search_query = st.text_input("🔎 Search for a brand:", placeholder="Enter brand name...", key="brand_search")
        if search_query:
            brand = find_brand_by_name(search_query)
            if brand['id'] != 'unknown':
                render_brand_card(brand, st.session_state.username)
                save_scan_history(st.session_state.username, brand, 'manual')
            else:
                st.warning(f"Brand '{search_query}' not found in our database.")
                st.info("Try the AI Image Analysis feature to identify brands from images!")
    
    elif page == "📷 AI Image Analysis":
        st.markdown('<div class="main-header"><h1>📷 AI Brand Recognition</h1><p>Upload an image to identify brands</p></div>', unsafe_allow_html=True)
        uploaded_file = st.file_uploader("Choose an image...", type=['png', 'jpg', 'jpeg'], key="image_uploader")
        if uploaded_file is not None:
            image = Image.open(uploaded_file)
            col1, col2 = st.columns([1, 1])
            with col1:
                st.image(image, caption="Uploaded Image", use_container_width=True)
            with col2:
                if st.button("🔍 Analyze Image", use_container_width=True, key="analyze_image"):
                    with st.spinner("Analyzing image with AI..."):
                        result = analyze_image_with_openai(image, OPENAI_API_KEY)
                        if result:
                            if result.get('brand_detected', False):
                                brand_name = result.get('brand_name', '')
                                confidence = result.get('confidence', 0)
                                brand = find_brand_by_name(brand_name)
                                if brand['id'] != 'unknown':
                                    st.success(f"✅ Brand detected: {brand['name']} (Confidence: {confidence}%)")
                                    render_confidence_bar(confidence)
                                    render_brand_card(brand, st.session_state.username)
                                    image_hash = generate_image_hash(image)
                                    save_scan_history(
                                        st.session_state.username, brand, 'ai_image', confidence, image_hash
                                    )
                                else:
                                    st.warning(f"Brand '{brand_name}' detected but not in our database")
                                    render_confidence_bar(confidence)
                                    temp_brand = {
                                        'id': 'unknown_' + hashlib.md5(brand_name.encode()).hexdigest()[:8] if brand_name else 'unknown',
                                        'name': brand_name or 'Unknown Brand',
                                        'industry': result.get('category', 'Unknown'),
                                        'logo': '❓',
                                        'slogan': result.get('slogan', 'N/A'),
                                        'sustainability_score': result.get('sustainability_score', 0),
                                        'sentiment_score': result.get('sentiment_score', 0),
                                        'authenticity_tips': result.get('authenticity_tips', 'Research thoroughly before purchase'),
                                        'description': result.get('description', 'Brand not recognized in our database.'),
                                        'founded': result.get('founded', None),
                                        'headquarters': result.get('headquarters', None),
                                        'market_cap': result.get('market_cap', None),
                                        'stock_symbol': result.get('stock_symbol', None),
                                        'competitors': result.get('competitors', []),
                                        'website': result.get('website', None),
                                        'stores': result.get('stores', []),
                                        'similar_logos': result.get('similar_logos', []),
                                        'brand_colors': result.get('colors', []),
                                        'keywords': result.get('keywords', []),
                                        'logo_elements': result.get('logo_elements', []),
                                        'scan_metadata': {
                                            'scan_type': 'ai_image',
                                            'confidence': confidence,
                                            'scanned_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                        }
                                    }
                                    render_brand_card(temp_brand, st.session_state.username)
                                    image_hash = generate_image_hash(image)
                                    save_scan_history(
                                        st.session_state.username, temp_brand, 'ai_image', confidence, image_hash
                                    )
                            else:
                                st.info("No recognizable brand detected in the image")
                                if result.get('description'):
                                    st.write(f"**Description:** {result['description']}")
                        else:
                            st.error("Failed to analyze image")
    
    elif page == "⭐ Favorites":
        st.markdown('<div class="main-header"><h1>⭐ Your Favorites</h1><p>Brands you love</p></div>', unsafe_allow_html=True)
        clean_invalid_favorites(st.session_state.username)
        favorites = get_user_favorites(st.session_state.username)
        if favorites:
            for brand_id in favorites:
                brand = BRAND_DATABASE.get(brand_id, None)
                if brand:
                    render_brand_card(brand, st.session_state.username)
                else:
                    history = load_user_history(st.session_state.username, limit=None)
                    temp_brand = next((b for b in history if b['id'] == brand_id), None)
                    if temp_brand:
                        render_brand_card(temp_brand, st.session_state.username)
                    else:
                        st.warning(f"Brand with ID {brand_id} not found.")
        else:
            st.info("No favorites yet! Add some brands to your favorites list.")
    
    elif page == "📊 History":
        st.markdown('<div class="main-header"><h1>📊 Scan History</h1><p>Your brand discovery journey</p></div>', unsafe_allow_html=True)
        history = load_user_history(st.session_state.username, limit=20)
        if history:
            col1, col2 = st.columns(2)
            with col1:
                scan_type_filter = st.selectbox("Filter by scan type:", ["All", "manual", "ai_image"], key="history_filter_type")
            with col2:
                brand_filter = st.text_input("Filter by brand name:", key="history_filter_name")
            filtered_history = history
            if scan_type_filter != "All":
                filtered_history = [h for h in filtered_history if h.get('scan_metadata', {}).get('scan_type') == scan_type_filter]
            if brand_filter:
                filtered_history = [h for h in filtered_history if brand_filter.lower() in h.get('name', '').lower()]
            for brand in filtered_history:
                render_brand_card(brand, st.session_state.username)
        else:
            st.info("No scan history yet. Start exploring brands!")
    
    elif page == "⚙️ Settings":
        st.markdown('<div class="main-header"><h1>⚙️ Settings</h1><p>Customize your experience</p></div>', unsafe_allow_html=True)
        stats = get_user_statistics(st.session_state.username)
        if stats:
            st.subheader("Account Statistics")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Scans", stats.get('total_scans', 0))
            with col2:
                st.metric("Unique Brands", stats.get('unique_brands', 0))
            with col3:
                st.metric("Average Confidence", f"{stats.get('avg_confidence', 0)}%")
        st.divider()
        st.subheader("Preferences")
        notifications = st.checkbox("Enable Notifications", value=st.session_state.user_preferences.get('notifications', True), key="pref_notifications")
        auto_save = st.checkbox("Auto-save Scans", value=st.session_state.user_preferences.get('auto_save_scans', True), key="pref_auto_save")
        if st.button("Save Preferences", key="save_prefs"):
            st.session_state.user_preferences.update({'notifications': notifications, 'auto_save_scans': auto_save})
            try:
                conn = sqlite3.connect('luminor_users.db')
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE users SET preferences = ? WHERE username = ?",
                    (json.dumps(st.session_state.user_preferences), st.session_state.username)
                )
                conn.commit()
                conn.close()
                st.success("✅ Preferences saved!")
            except sqlite3.Error:
                st.error("❌ Failed to save preferences")
        st.divider()
        st.subheader("Data Management")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Clear Scan History", type="secondary", key="clear_history"):
                try:
                    conn = sqlite3.connect('luminor_users.db')
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM user_history WHERE username = ?", (st.session_state.username,))
                    conn.commit()
                    conn.close()
                    st.success("✅ Scan history cleared!")
                except sqlite3.Error:
                    st.error("❌ Failed to clear history")
        with col2:
            if st.button("Clear Favorites", type="secondary", key="clear_favorites"):
                try:
                    conn = sqlite3.connect('luminor_users.db')
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM user_favorites WHERE username = ?", (st.session_state.username,))
                    conn.commit()
                    conn.close()
                    st.success("✅ Favorites cleared!")
                except sqlite3.Error:
                    st.error("❌ Failed to clear favorites")

if __name__ == "__main__":
    main()
