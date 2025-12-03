"""
Path of Exile Awakened Gem Profit Calculator - V2 (Simplified)
Changes from V1:
- Corruption analysis is toggled OFF by default (faster loading)
- Uses poe.ninja for currency/beast prices only
- Uses trade site for all gem prices
- Default sort by ROI% (highest profit percentage first)
- Clicking gem name opens L1 Q0 trade link (when corruption off)
- No sticky analysis section when corruption is off
"""

import requests
import dash
from dash import dcc, html, Input, Output, State, dash_table, callback_context
import dash_bootstrap_components as dbc
import pandas as pd
from datetime import datetime
import threading
import time
import os

class SimplePoeAPI:
    """Simplified API client for Dash version"""
    def __init__(self, league=None):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'PoE-Gem-Profit-Calculator/2.0'
        })
        self.league = league or self.get_current_league()
    
    def get_current_league(self):
        """Auto-detect current challenge league from poe.ninja"""
        try:
            url = "https://poe.ninja/api/data/currencyoverview?league=Keepers&type=Currency"
            response = self.session.get(url, timeout=10)
            
            if response.status_code == 200:
                print("✓ Selected league: Keepers")
                return "Keepers"
            
            for league_name in ["Settlers", "Affliction", "Ancestor", "Crucible"]:
                url = f"https://poe.ninja/api/data/currencyoverview?league={league_name}&type=Currency"
                response = self.session.get(url, timeout=10)
                if response.status_code == 200:
                    print(f"✓ Selected league: {league_name}")
                    return league_name
            
            print("WARNING: No challenge league found, using Standard")
            return "Standard"
            
        except Exception as e:
            print(f"Error detecting league: {e}")
            print("Using default: Keepers")
            return "Keepers"
    
    def get_divine_chaos_rate(self):
        """Get Divine Orb price from poe.ninja"""
        try:
            url = f"https://poe.ninja/api/data/currencyoverview?league={self.league}&type=Currency"
            response = self.session.get(url, timeout=10)
            data = response.json()
            for item in data.get('lines', []):
                if item.get('currencyTypeName') == 'Divine Orb':
                    return item.get('chaosEquivalent', 100.0)
            return 100.0
        except:
            return 100.0
    
    def get_awakened_gem_list(self):
        """Get list of awakened gem names from poe.ninja (we only use this for the list, not prices)"""
        try:
            url = f"https://poe.ninja/api/data/itemoverview?league={self.league}&type=SkillGem"
            response = self.session.get(url, timeout=10)
            data = response.json()
            gems = set()
            for gem in data.get('lines', []):
                name = gem.get('name', '')
                if 'Awakened' in name:
                    gems.add(name)
            return sorted(list(gems))
        except Exception as e:
            print(f"Error getting gem list: {e}")
            return []
    
    def get_awakened_gem_prices(self):
        """Get all awakened gem price data from poe.ninja"""
        try:
            url = f"https://poe.ninja/api/data/itemoverview?league={self.league}&type=SkillGem"
            response = self.session.get(url, timeout=10)
            data = response.json()
            gems = {}
            level_quality_combos = {}  # Track what combos we see
            
            for gem in data.get('lines', []):
                name = gem.get('name', '')
                if 'Awakened' in name:
                    level = gem.get('gemLevel', 0)
                    quality = gem.get('gemQuality', 0)
                    key = f"{name}_L{level}_Q{quality}"
                    gems[key] = {
                        'name': name,
                        'level': level,
                        'quality': quality,
                        'chaos_value': gem.get('chaosValue', 0)
                    }
                    
                    # Track combos
                    combo = f"L{level}_Q{quality}"
                    level_quality_combos[combo] = level_quality_combos.get(combo, 0) + 1
            
            print(f"\nLevel/Quality combinations found on poe.ninja:")
            for combo, count in sorted(level_quality_combos.items()):
                print(f"  {combo}: {count} gems")
            
            return gems
        except Exception as e:
            print(f"Error getting gem prices: {e}")
            return {}
    
    def get_currency_prices(self):
        """Get currency and beast prices from poe.ninja"""
        try:
            url = f"https://poe.ninja/api/data/currencyoverview?league={self.league}&type=Currency"
            response = self.session.get(url, timeout=10)
            data = response.json()
            prices = {}
            currency_map = {
                "Gemcutter's Prism": 'gcp',
                "Vaal Orb": 'vaal'
            }
            for item in data.get('lines', []):
                name = item.get('currencyTypeName')
                if name in currency_map:
                    prices[currency_map[name]] = item.get('chaosEquivalent', 0)
            
            # Get beast price
            beast_url = f"https://poe.ninja/api/data/itemoverview?league={self.league}&type=Beast"
            response = self.session.get(beast_url, timeout=10)
            data = response.json()
            for item in data.get('lines', []):
                if 'Wild Brambleback' in item.get('name', ''):
                    prices['brambleback'] = item.get('chaosValue', 0)
                    break
            
            return prices
        except:
            return {'gcp': 1, 'vaal': 1, 'brambleback': 10}
    
    def get_trade_site_gem_price(self, gem_name, level, quality, corrupted=False):
        """Fetch gem price from trade site with retry logic for rate limiting"""
        max_retries = 3
        retry_delay = 1  # Start with 1 second
        
        for attempt in range(max_retries):
            try:
                search_payload = {
                    "query": {
                        "status": {"option": "available"},
                        "type": gem_name,
                        "filters": {
                            "misc_filters": {
                                "filters": {
                                    "gem_level": {"min": level, "max": level},
                                    "quality": {"min": quality, "max": quality},
                                    "corrupted": {"option": "true" if corrupted else "false"}
                                }
                            }
                        }
                    },
                    "sort": {"price": "asc"}
                }
                
                search_url = f"https://www.pathofexile.com/api/trade/search/{self.league}"
                print(f"    Sending search request to trade API...")
                search_response = self.session.post(search_url, json=search_payload, timeout=20)
                
                if search_response.status_code == 429:
                    # Rate limited - wait and retry
                    if attempt < max_retries - 1:
                        wait_time = retry_delay * (2 ** attempt)  # Exponential backoff: 1s, 2s, 4s
                        print(f"    Rate limited (429), waiting {wait_time}s before retry {attempt + 1}/{max_retries}")
                        time.sleep(wait_time)
                        continue
                    else:
                        print(f"    Rate limited after {max_retries} attempts, skipping")
                        return None
                
                if search_response.status_code != 200:
                    print(f"    Trade API returned status {search_response.status_code}")
                    return None
                
                search_data = search_response.json()
                result_ids = search_data.get('result', [])[:5]
                
                if not result_ids:
                    print(f"    No results found")
                    return None
                
                print(f"    Found {len(result_ids)} listings")
                
                # Add delay before fetch request
                time.sleep(0.3)
                
                fetch_url = f"https://www.pathofexile.com/api/trade/fetch/{','.join(result_ids[:5])}?query={search_data.get('id')}"
                print(f"    Fetching listing details...")
                fetch_response = self.session.get(fetch_url, timeout=20)
                
                if fetch_response.status_code == 429:
                    # Rate limited on fetch
                    if attempt < max_retries - 1:
                        wait_time = retry_delay * (2 ** attempt)
                        print(f"    Rate limited on fetch (429), waiting {wait_time}s before retry")
                        time.sleep(wait_time)
                        continue
                    else:
                        print(f"    Rate limited on fetch after {max_retries} attempts, skipping")
                        return None
                
                if fetch_response.status_code != 200:
                    print(f"    Fetch API returned status {fetch_response.status_code}")
                    return None
                
                fetch_data = fetch_response.json()
                results = fetch_data.get('result', [])
                
                prices = []
                for item in results:
                    listing = item.get('listing', {})
                    price_data = listing.get('price', {})
                    
                    if price_data:
                        amount = price_data.get('amount', 0)
                        currency = price_data.get('currency', '')
                        
                        if currency == 'chaos':
                            prices.append(amount)
                        elif currency == 'divine':
                            divine_rate = self.get_divine_chaos_rate()
                            prices.append(amount * divine_rate)
                
                if prices:
                    prices.sort()
                    avg_price = sum(prices[:5]) / min(5, len(prices))
                    print(f"    ✓ Average price: {avg_price:.1f}c (from {len(prices)} listings)")
                    return avg_price
                
                print(f"    No valid prices found in listings")
                return None
                
            except Exception as e:
                print(f"    ✗ Error fetching trade price: {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay * (2 ** attempt))
                    continue
                return None
        
        return None
    
    def get_trade_site_gem_price_corrupted(self, gem_name, level, quality_min, quality_max):
        """Fetch corrupted gem price from trade site (for corruption analysis)"""
        try:
            search_payload = {
                "query": {
                    "status": {"option": "available"},
                    "type": gem_name,
                    "filters": {
                        "misc_filters": {
                            "filters": {
                                "gem_level": {"min": level, "max": level},
                                "quality": {"min": quality_min, "max": quality_max},
                                "corrupted": {"option": "true"}
                            }
                        }
                    }
                },
                "sort": {"price": "asc"}
            }
            
            search_url = f"https://www.pathofexile.com/api/trade/search/{self.league}"
            search_response = self.session.post(search_url, json=search_payload, timeout=10)
            
            if search_response.status_code != 200:
                return None
            
            search_data = search_response.json()
            result_ids = search_data.get('result', [])[:10]
            
            if not result_ids:
                return None
            
            fetch_url = f"https://www.pathofexile.com/api/trade/fetch/{','.join(result_ids[:10])}?query={search_data.get('id')}"
            fetch_response = self.session.get(fetch_url, timeout=10)
            
            if fetch_response.status_code != 200:
                return None
            
            fetch_data = fetch_response.json()
            results = fetch_data.get('result', [])
            
            prices = []
            for item in results:
                listing = item.get('listing', {})
                price_data = listing.get('price', {})
                
                if price_data:
                    amount = price_data.get('amount', 0)
                    currency = price_data.get('currency', '')
                    
                    if currency == 'chaos':
                        prices.append(amount)
                    elif currency == 'divine':
                        divine_rate = self.get_divine_chaos_rate()
                        prices.append(amount * divine_rate)
            
            if prices:
                prices.sort()
                return sum(prices[:5]) / min(5, len(prices))
            
            return None
            
        except Exception as e:
            print(f"Error fetching corrupted trade price: {e}")
            return None


class GemProfitCalculator:
    """Calculate profit for awakened gem flipping"""
    def __init__(self, api):
        self.api = api
        self.currency_prices = api.get_currency_prices()
        self.divine_rate = api.get_divine_chaos_rate()
    
    def calculate_basic_profit(self, gem_name):
        """Calculate basic profit (L1 -> L5 Q20 uncorrupted) using trade site"""
        # Get prices from trade site
        print(f"  Fetching L1 price for {gem_name}...")
        l1_price = self.api.get_trade_site_gem_price(gem_name, 1, 0, False)
        print(f"  L1 price: {l1_price}")
        
        print(f"  Fetching L5 price for {gem_name}...")
        l5_price = self.api.get_trade_site_gem_price(gem_name, 5, 20, False)
        print(f"  L5 price: {l5_price}")
        
        if l1_price is None or l5_price is None:
            print(f"  ❌ Skipping {gem_name} - missing price data")
            return None
        
        # Calculate costs
        leveling_cost = 4 * self.currency_prices.get('brambleback', 10)
        quality_cost = 20 * self.currency_prices.get('gcp', 1)
        total_cost = l1_price + leveling_cost + quality_cost
        profit = l5_price - total_cost
        profit_percent = (profit / total_cost * 100) if total_cost > 0 else 0
        
        print(f"  ✓ Success - Profit: {profit:.1f}c ({profit_percent:.1f}%)")
        
        return {
            'name': gem_name,
            'l1_cost': l1_price,
            'leveling_cost': leveling_cost,
            'quality_cost': quality_cost,
            'total_cost': total_cost,
            'l5_price': l5_price,
            'profit': profit,
            'profit_percent': profit_percent
        }
    
    def calculate_corruption_ev(self, gem_name, base_data):
        """Calculate expected value for corruption (only called when toggle is ON)"""
        # Get corrupted gem prices from trade site
        l4_price = self.api.get_trade_site_gem_price(gem_name, 4, 20, True)
        l5_no_change = self.api.get_trade_site_gem_price(gem_name, 5, 20, True)
        l6_price = self.api.get_trade_site_gem_price(gem_name, 6, 20, True)
        quality_up = self.api.get_trade_site_gem_price_corrupted(gem_name, 5, 21, 23)
        quality_down = self.api.get_trade_site_gem_price_corrupted(gem_name, 5, 10, 19)
        
        # If any price is missing, return None
        if None in [l4_price, l5_no_change, l6_price, quality_up, quality_down]:
            return None
        
        vaal_cost = self.currency_prices.get('vaal', 1)
        
        # Calculate EV
        ev_price = (
            0.333 * l5_no_change +
            0.167 * l6_price +
            0.167 * l4_price +
            0.167 * quality_up +
            0.167 * quality_down
        )
        
        ev_total_cost = base_data['total_cost'] + vaal_cost
        ev_profit = ev_price - ev_total_cost
        ev_percent = (ev_profit / ev_total_cost * 100) if ev_total_cost > 0 else 0
        
        return {
            'vaal_cost': vaal_cost,
            'ev_price': ev_price,
            'ev_total_cost': ev_total_cost,
            'ev_profit': ev_profit,
            'ev_percent': ev_percent,
            'base_profit': base_data['profit'],
            'outcomes': {
                'l4': l4_price,
                'l5_no_change': l5_no_change,
                'l6': l6_price,
                'quality_up': quality_up,
                'quality_down': quality_down
            }
        }


# Initialize
api = SimplePoeAPI()
calculator = GemProfitCalculator(api)

# Progress tracking
loading_progress = {'current': 0, 'total': 0, 'status': 'Loading...', 'complete': False, 'phase': 'ninja'}

def load_gem_prices():
    """Two-phase loading: poe.ninja first, then trade site for top 10"""
    global profits_data, loading_progress, ninja_data, all_ninja_profits
    
    # Phase 1: Get all gems from poe.ninja and calculate rough profits
    loading_progress['phase'] = 'ninja'
    loading_progress['status'] = 'Fetching prices from poe.ninja...'
    print("Phase 1: Fetching all gem prices from poe.ninja...")
    
    ninja_gems = api.get_awakened_gem_prices()
    print(f"Found {len(ninja_gems)} gem entries on poe.ninja")
    print(f"Sample entries: {list(ninja_gems.keys())[:5]}")
    
    # Calculate profit estimates for all gems using poe.ninja
    ninja_profits = {}
    for key, gem_data in ninja_gems.items():
        name = gem_data['name']
        level = gem_data['level']
        quality = gem_data['quality']
        
        # We need L1 Q0 and L5 Q20
        if level == 1 and quality == 0:
            if name not in ninja_profits:
                ninja_profits[name] = {'name': name}
            ninja_profits[name]['l1'] = gem_data['chaos_value']
            print(f"  Found L1 Q0: {name} = {gem_data['chaos_value']}c")
        elif level == 5 and quality == 20:
            if name not in ninja_profits:
                ninja_profits[name] = {'name': name}
            ninja_profits[name]['l5'] = gem_data['chaos_value']
            print(f"  Found L5 Q20: {name} = {gem_data['chaos_value']}c")
    
    print(f"\nGems with L1 data: {len([g for g in ninja_profits.values() if 'l1' in g])}")
    print(f"Gems with L5 data: {len([g for g in ninja_profits.values() if 'l5' in g])}")
    print(f"Gems with both L1 and L5: {len([g for g in ninja_profits.values() if 'l1' in g and 'l5' in g])}")
    
    # Calculate ROI% for gems with both L1 and L5 data
    estimated_profits = []
    excluded_gems = ['Awakened Enlighten Support', 'Awakened Empower Support', 'Awakened Enhance Support']
    
    for name, data in ninja_profits.items():
        # Skip excluded gems unless we're loading all
        if data['name'] in excluded_gems:
            continue
            
        if 'l1' in data and 'l5' in data:
            l1_cost = data['l1']
            l5_price = data['l5']
            leveling_cost = 4 * calculator.currency_prices.get('brambleback', 10)
            quality_cost = 20 * calculator.currency_prices.get('gcp', 1)
            total_cost = l1_cost + leveling_cost + quality_cost
            profit = l5_price - total_cost
            profit_percent = (profit / total_cost * 100) if total_cost > 0 else 0
            
            estimated_profits.append({
                'name': data['name'],
                'profit_percent': profit_percent,
                'estimated_profit': profit
            })
    
    print(f"\nTotal gems with complete data for profit calculation: {len(estimated_profits)}")
    
    # Store all ninja profits globally for "Load All" feature
    all_ninja_profits = ninja_profits
    
    # Sort by profit % and get top 5
    estimated_profits.sort(key=lambda x: x['profit_percent'], reverse=True)
    top_5 = estimated_profits[:5]
    
    print(f"\nTop 5 gems by estimated ROI%:")
    for i, gem in enumerate(top_5, 1):
        print(f"  {i}. {gem['name']}: {gem['profit_percent']:.1f}% ({gem['estimated_profit']:.1f}c)")
    
    # Wait before starting trade site requests to avoid rate limiting
    print("\nWaiting 5 seconds before fetching from trade site...")
    time.sleep(5)
    
    # Phase 2: Get trade site prices for top 5 only
    loading_progress['phase'] = 'trade_top5'
    loading_progress['total'] = len(top_5)
    loading_progress['status'] = 'Fetching trade prices for top 5 gems...'
    print("\nPhase 2: Fetching trade site prices for top 5 gems...")
    
    profits_data = []
    for i, gem_estimate in enumerate(top_5, 1):
        loading_progress['current'] = i
        gem_name = gem_estimate['name']
        loading_progress['status'] = f"Processing top gem {i}/5: {gem_name}"
        print(f"\n=== Processing {i}/5: {gem_name} ===")
        
        profit = calculator.calculate_basic_profit(gem_name)
        if profit:
            print(f"✓ Successfully added {gem_name}")
            profit['from_trade'] = True  # Mark as trade site data
            profits_data.append(profit)
        else:
            print(f"✗ Failed to get prices for {gem_name}")
        
        print(f"Waiting 8 seconds before next gem...")
        time.sleep(8)  # Rate limiting - 8 seconds to be safe
    
    print(f"\n=== Phase 2 Complete ===")
    print(f"Successfully loaded {len(profits_data)} out of {len(top_5)} gems")
    
    # Sort by actual ROI% from trade site
    if profits_data:
        profits_data.sort(key=lambda x: x['profit_percent'], reverse=True)
    
    loading_progress['complete'] = True
    loading_progress['status'] = f"Complete! Loaded top {len(profits_data)} gems"
    
    # Set initial timestamp
    global last_refresh_time
    last_refresh_time = datetime.now().strftime('%H:%M:%S')
    
    print(f"Final: Successfully loaded top {len(profits_data)} gems with trade site prices")
    print(f"Initial timestamp set to: {last_refresh_time}")

# Store ninja data and all gem names for "Load All" feature
ninja_data = {}
all_ninja_profits = {}

# Cache for corruption data to avoid re-fetching
corruption_cache = {}
current_analysis_gem = None  # Track which gem is currently displayed in footer

# Store last refresh timestamp
last_refresh_time = None

# Initialize profit data
profits_data = []

# Only start loading thread if not running under gunicorn
# Gunicorn sets SERVER_SOFTWARE env variable
if not os.environ.get('SERVER_SOFTWARE', '').startswith('gunicorn'):
    print("Starting initial gem price loading...")
    loading_thread = threading.Thread(target=load_gem_prices, daemon=True)
    loading_thread.start()
else:
    print("Running under gunicorn - skipping initial load. Will load on first page visit.")
    loading_thread = None

# Initialize Dash app
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.DARKLY])
app.title = "PoE Gem Profit Calculator"
server = app.server

# Currency display mode state
currency_mode = 'chaos'  # Can be 'chaos' or 'divine'

def format_price(chaos_value, mode='chaos'):
    """Format price based on display mode"""
    if mode == 'divine':
        divine_rate = calculator.divine_rate
        divine_value = chaos_value / divine_rate
        return f"{divine_value:.2f}d"
    else:
        return f"{chaos_value:.1f}c"

def create_table_data(include_corruption=False):
    """Create table data"""
    table_data = []
    
    for gem in profits_data:
        short_name = gem['name'].replace('Awakened ', '').replace(' Support', '')
        
        # Different button text based on data source
        if gem.get('from_trade', True):
            button_text = 'Gamba?'
        else:
            button_text = 'Trade Price'
        
        row = {
            'gem_name': gem['name'],  # Hidden but used for callbacks
            'Gem': short_name,
            'L1': format_price(gem['l1_cost'], currency_mode),
            'Level': format_price(gem['leveling_cost'], currency_mode),
            'Quality': format_price(gem['quality_cost'], currency_mode),
            'Total': format_price(gem['total_cost'], currency_mode),
            'L5': format_price(gem['l5_price'], currency_mode),
            'Profit': format_price(gem['profit'], currency_mode),
            'ROI%': f"{gem['profit_percent']:.1f}%",
            'Corrupt': button_text,
            'from_ninja': 'true' if not gem.get('from_trade', True) else 'false'  # For styling
        }
        
        table_data.append(row)
    
    return table_data

def create_columns(include_corruption=False):
    """Create column definitions"""
    base_columns = [
        {'name': 'Gem', 'id': 'Gem'},
        {'name': 'L1', 'id': 'L1'},
        {'name': 'Level Up', 'id': 'Level'},
        {'name': 'Quality', 'id': 'Quality'},
        {'name': 'Total', 'id': 'Total'},
        {'name': 'L5', 'id': 'L5'},
        {'name': 'Profit', 'id': 'Profit'},
        {'name': 'ROI%', 'id': 'ROI%'},
        {'name': 'Corrupt', 'id': 'Corrupt'}
    ]
    
    return base_columns

# Layout
app.layout = dbc.Container([
    # Startup trigger for gunicorn deployment
    dcc.Interval(id='startup-trigger', interval=1000, n_intervals=0, max_intervals=1),
    
    # Hidden interval component for updating progress
    dcc.Interval(id='progress-interval', interval=500, n_intervals=0, disabled=False),
    
    # Auto-refresh interval component (default 20 minutes = 1,200,000 ms)
    dcc.Interval(id='auto-refresh-interval', interval=1200000, n_intervals=0, disabled=False),
    
    # Loading overlay
    dbc.Modal([
        dbc.ModalHeader("Loading Gem Prices"),
        dbc.ModalBody([
            html.Div(id='loading-status', className="text-center mb-3"),
            dbc.Progress(id='loading-progress', striped=True, animated=True, className="mb-3"),
            html.Small("Phase 1: Analyzing all gems via poe.ninja...", 
                      className="text-muted d-block text-center"),
            html.Small("Phase 2: Fetching trade prices for top 5 gems (~30 seconds)", 
                      className="text-muted d-block text-center mt-1")
        ])
    ], id='loading-modal', is_open=True, backdrop='static', keyboard=False),
    
    # Button action loading modal
    dbc.Modal([
        dbc.ModalHeader("Fetching Data"),
        dbc.ModalBody([
            html.Div(id='button-loading-status', className="text-center mb-3"),
            dbc.Progress(value=100, striped=True, animated=True, className="mb-3"),
            html.Small("Please wait...", className="text-muted d-block text-center")
        ])
    ], id='button-loading-modal', is_open=False, backdrop='static', keyboard=False),
    
    # Loading overlay for immediate feedback
    html.Div([
        html.Div([
            dbc.Spinner(color="primary", size="lg"),
            html.H4("Loading...", className="mt-3 text-white")
        ], style={
            'display': 'flex',
            'flexDirection': 'column',
            'alignItems': 'center',
            'justifyContent': 'center',
            'height': '100%'
        })
    ], id='instant-loading-overlay', style={
        'display': 'none',
        'position': 'fixed',
        'top': '0',
        'left': '0',
        'width': '100%',
        'height': '100%',
        'backgroundColor': 'rgba(0, 0, 0, 0.7)',
        'zIndex': '9999'
    }),
    
    # JavaScript to show loading overlay on button click
    html.Script("""
        document.addEventListener('DOMContentLoaded', function() {
            // Add click listener to the table
            const observer = new MutationObserver(function() {
                const table = document.querySelector('#gem-table');
                if (table) {
                    table.addEventListener('click', function(e) {
                        const cell = e.target.closest('td');
                        if (cell) {
                            const columnId = cell.getAttribute('data-dash-column');
                            if (columnId === 'Corrupt') {
                                // Show loading overlay
                                document.getElementById('instant-loading-overlay').style.display = 'block';
                                
                                // Hide after callback completes (10 seconds max)
                                setTimeout(function() {
                                    document.getElementById('instant-loading-overlay').style.display = 'none';
                                }, 10000);
                            }
                        }
                    });
                    observer.disconnect();
                }
            });
            observer.observe(document.body, { childList: true, subtree: true });
        });
    """),
    
    dbc.Row([
        dbc.Col([
            html.H2([
                html.Img(src="https://web.poecdn.com/gen/image/WzI1LDE0LHsiZiI6IjJESXRlbXMvR2Vtcy9TdXBwb3J0L1N1cHBvcnRQbHVzL0VubGlnaHRlbnBsdXMiLCJ3IjoxLCJoIjoxLCJzY2FsZSI6MX1d/7ec7d0544d/Enlightenplus.png",
                        height="30px", className="me-2"),
                "PoE Awakened Gem Profit Calculator",
                html.Img(src="https://web.poecdn.com/gen/image/WzI1LDE0LHsiZiI6IjJESXRlbXMvR2Vtcy9TdXBwb3J0L1N1cHBvcnRQbHVzL0VubGlnaHRlbnBsdXMiLCJ3IjoxLCJoIjoxLCJzY2FsZSI6MX1d/7ec7d0544d/Enlightenplus.png",
                        height="30px", className="ms-2")
            ], className="text-center mb-3"),
            html.Hr()
        ])
    ]),
    
    # Controls row
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.Div([
                        html.Small("Currency Prices (poe.ninja):", className="text-muted d-block mb-2"),
                        html.Span(f"{calculator.api.league}", className="me-1"),
                        html.Span(" | ", className="mx-1"),
                        html.Span(f"Divine: {format_price(calculator.divine_rate, currency_mode)}", className="me-1"),
                        html.Span(" | ", className="mx-1"),
                        html.Span(f"GCP: {format_price(calculator.currency_prices.get('gcp', 1), currency_mode)}", className="me-1"),
                        html.Span(" | ", className="mx-1"),
                        html.Span(f"Brambleback: {format_price(calculator.currency_prices.get('brambleback', 10), currency_mode)}", className="me-1"),
                        html.Span(" | ", className="mx-1"),
                        html.Span(f"Vaal: {format_price(calculator.currency_prices.get('vaal', 1), currency_mode)}"),
                    ]),
                    html.Hr(className="my-2"),
                    dbc.Row([
                        dbc.Col([
                            dbc.Button("🔄 Refresh Prices", id="refresh-button", color="primary", size="sm", className="me-2"),
                            dbc.Button([
                                html.Img(src="https://web.poecdn.com/gen/image/WzI1LDE0LHsiZiI6IjJESXRlbXMvR2Vtcy9TdXBwb3J0L1N1cHBvcnRQbHVzL011bHRpcGxlQXR0YWNrc1BsdXMiLCJ3IjoxLCJoIjoxLCJzY2FsZSI6MX1d/c32ddc2121/MultipleAttacksPlus.png",
                                        height="20px", className="me-1"),
                                "Load All Gems"
                            ], id="load-all-button", color="success", size="sm", className="me-2", 
                            style={'backgroundColor': '#1e7e34', 'borderColor': '#1c7430', 'transition': 'all 0.15s ease-in-out'}),
                            dbc.Button([
                                html.Img(id="currency-icon",
                                        src="https://web.poecdn.com/gen/image/WzI1LDE0LHsiZiI6IjJESXRlbXMvQ3VycmVuY3kvQ3VycmVuY3lNb2RWYWx1ZXMiLCJzY2FsZSI6MX1d/ec48896769/CurrencyModValues.png",
                                        height="20px", className="me-1"),
                                html.Span("Show Divine", id="currency-text")
                            ], id="currency-toggle", size="sm", className="me-2",
                            style={'backgroundColor': '#5a6268', 'borderColor': '#545b62', 'color': 'white', 'transition': 'all 0.15s ease-in-out'}),
                            html.Small("Last updated: Never", 
                                     className="text-muted ms-2", id="last-update")
                        ], width=12)
                    ]),
                    html.Hr(className="my-2"),
                    dbc.Row([
                        dbc.Col([
                            html.Small("⚠️ Load All Gems will populate remaining gems using poe.ninja prices only (may be less accurate)", 
                                      className="text-warning fst-italic")
                        ], width=12)
                    ]),
                    html.Hr(className="my-2"),
                    dbc.Row([
                        dbc.Col([
                            html.Div([
                                dbc.Checklist(
                                    id='auto-refresh-toggle',
                                    options=[{'label': ' Auto-refresh prices', 'value': 'enabled'}],
                                    value=['enabled'],  # ON by default
                                    switch=True,
                                    inline=True,
                                    className='d-inline-block me-2'
                                ),
                                html.Span("every ", className="text-muted me-1"),
                                dbc.Input(
                                    id='refresh-interval-input',
                                    type='number',
                                    value=20,
                                    min=1,
                                    max=1440,
                                    step=1,
                                    size='sm',
                                    style={'width': '70px', 'display': 'inline-block'}
                                ),
                                html.Span(" minutes", className="text-muted ms-1")
                            ], className="d-flex align-items-center")
                        ], width=12)
                    ])
                ])
            ], color="dark", className="mb-3")
        ])
    ]),
    
    # Table row
    dbc.Row([
        dbc.Col([
            html.Div([
                html.Span("Showing: ", className="text-muted me-2"),
                html.Span(id='gems-shown-status', children="Top 10 gems", className="text-info fw-bold")
            ], className="mb-2"),
            dash_table.DataTable(
                id='gem-table',
                columns=create_columns(False),
                data=create_table_data(False),
                style_table={'overflowX': 'auto'},
                style_cell={
                    'backgroundColor': '#2b3e50',
                    'color': 'white',
                    'textAlign': 'center',  # Center all columns
                    'padding': '10px 10px 10px 25px',  # Increased left padding from 20 to 25
                    'fontFamily': 'monospace'
                },
                style_header={
                    'backgroundColor': '#1a252f',
                    'fontWeight': 'bold',
                    'textAlign': 'center',  # Center all headers
                    'padding': '10px 10px 10px 25px'  # Match cell padding for alignment
                },
                style_header_conditional=[
                    {
                        'if': {'column_id': 'Corrupt'},
                        'textAlign': 'center'
                    }
                ],
                css=[{
                    'selector': '.dash-spreadsheet td.focused',
                    'rule': 'background-color: #dc3545 !important;'  # Keep red when active
                }, {
                    'selector': '.dash-spreadsheet td.focused:hover',
                    'rule': 'background-color: #dc3545 !important;'  # Stay red on hover, don't turn white
                }, {
                    'selector': '.previous-next-container',
                    'rule': 'background-color: #2b3e50 !important; border-radius: 4px; padding: 5px;'
                }, {
                    'selector': '.previous-next-container button',
                    'rule': 'background-color: #1a252f !important; color: white !important; border: 1px solid #375a7f !important; border-radius: 4px; padding: 5px 10px; margin: 0 3px;'
                }, {
                    'selector': '.previous-next-container button:hover',
                    'rule': 'background-color: #375a7f !important; cursor: pointer;'
                }, {
                    'selector': '.previous-next-container button:disabled',
                    'rule': 'background-color: #1a252f !important; color: #6c757d !important; opacity: 0.5; cursor: not-allowed;'
                }],
                style_data_conditional=[
                    {
                        'if': {'column_id': 'Gem'},
                        'cursor': 'pointer',
                        'color': 'white'
                    },
                    {
                        'if': {'column_id': 'Corrupt'},
                        'cursor': 'pointer',
                        'textAlign': 'center',
                        'backgroundColor': '#0d6776',  # Darker cyan/teal for Gamba
                        'color': 'white',
                        'fontWeight': 'bold',
                        'borderRadius': '4px'
                    },
                    {
                        'if': {
                            'filter_query': '{Corrupt} = "Trade Price"',
                            'column_id': 'Corrupt'
                        },
                        'backgroundColor': '#d97706',  # Amber/orange for Trade Price
                        'cursor': 'pointer',
                        'textAlign': 'center',
                        'color': 'white',
                        'fontWeight': 'bold',
                        'borderRadius': '4px'
                    },
                    {
                        'if': {
                            'filter_query': '{Profit} contains "-"',
                            'column_id': 'Profit'
                        },
                        'color': '#ff6b6b'
                    },
                    {
                        'if': {
                            'filter_query': '{Profit} contains "+"',
                            'column_id': 'Profit'
                        },
                        'color': '#51cf66'
                    },
                    # Different background for poe.ninja gems
                    {
                        'if': {
                            'filter_query': '{from_ninja} = "true"'
                        },
                        'backgroundColor': '#1e2a35'  # Darker background for ninja gems
                    }
                ],
                page_size=20,
                sort_action='native'
            )
        ])
    ]),
    
    # Spacer to push content up when footer is visible
    html.Div(id='footer-spacer', style={'height': '0px', 'transition': 'height 0.3s ease-in-out'}),
    
    # Analysis section (sticky footer for Gamba results)
    dbc.Row([
        dbc.Col([
            html.Div([
                # Close button (always exists, positioned in top-right of footer)
                dbc.Button("✕", id="close-analysis-btn", color="link", size="sm",
                          style={
                              'position': 'absolute',
                              'top': '10px',
                              'right': '15px',
                              'color': 'white',
                              'textDecoration': 'none',
                              'fontSize': '24px',
                              'zIndex': '1001',
                              'display': 'none'  # Hidden by default
                          }),
                # Analysis content
                html.Div(id='gem-analysis', className="mt-3")
            ], style={
                'position': 'fixed',
                'bottom': '-50vh',  # Start hidden below screen
                'left': '0',
                'right': '0',
                'zIndex': '1000',
                'backgroundColor': '#1a252f',
                'padding': '15px',
                'paddingRight': '60px',  # Extra space on right so close button isn't over gray
                'boxShadow': '0 -2px 10px rgba(0,0,0,0.3)',
                'maxHeight': '35vh',
                'overflowY': 'auto',
                'transition': 'bottom 0.3s ease-in-out'  # Smooth animation
            }, id='gem-analysis-footer')
        ])
    ]),
    
    # Show Analysis button (appears after footer is dismissed)
    html.Div([
        dbc.Button("Show Analysis ↑", id="show-analysis-btn", color="info", size="sm")
    ], id='show-analysis-container', style={
        'position': 'fixed',
        'bottom': '20px',
        'left': '50%',
        'transform': 'translateX(-50%)',
        'zIndex': '999',
        'display': 'none'
    })
    
], fluid=True, className="p-4", id='main-content', style={
    'paddingBottom': '20px',
    'transition': 'padding-bottom 0.3s ease-in-out'  # Smooth animation for content shift
})


@app.callback(
    Output('loading-progress', 'value'),
    Output('loading-progress', 'label'),
    Output('loading-status', 'children'),
    Output('loading-modal', 'is_open'),
    Output('progress-interval', 'disabled'),
    Input('progress-interval', 'n_intervals')
)
def update_progress(n):
    """Update loading progress bar"""
    if loading_progress['total'] == 0:
        return 0, "0%", "Initializing...", True, False
    
    percent = (loading_progress['current'] / loading_progress['total']) * 100
    label = f"{loading_progress['current']}/{loading_progress['total']} ({percent:.0f}%)"
    
    status = html.Div([
        html.H5(loading_progress['status'], className="mb-2"),
        html.P(f"Gem {loading_progress['current']} of {loading_progress['total']}", className="text-muted mb-0")
    ])
    
    # Close modal when complete and disable interval to stop polling
    is_open = not loading_progress['complete']
    interval_disabled = loading_progress['complete']  # Disable when complete
    
    return percent, label, status, is_open, interval_disabled


@app.callback(
    Output('load-all-button', 'children'),
    Output('load-all-button', 'disabled'),
    Output('gems-shown-status', 'children'),
    Input('load-all-button', 'n_clicks'),
    prevent_initial_call=True
)
def load_all_gems(n_clicks):
    """Toggle between showing all gems (with poe.ninja) and only trade site gems"""
    global profits_data
    
    if not n_clicks or not loading_progress['complete']:
        return [
            html.Img(src="https://web.poecdn.com/gen/image/WzI1LDE0LHsiZiI6IjJESXRlbXMvR2Vtcy9TdXBwb3J0L1N1cHBvcnRQbHVzL011bHRpcGxlQXR0YWNrc1BsdXMiLCJ3IjoxLCJoIjoxLCJzY2FsZSI6MX1d/c32ddc2121/MultipleAttacksPlus.png",
                    height="20px", className="me-1"),
            "Load All Gems"
        ], False, f"Top {len(profits_data)} gems"
    
    # Check if we currently have poe.ninja gems loaded
    has_ninja_gems = any(not g.get('from_trade', True) for g in profits_data)
    
    if has_ninja_gems:
        # Hide poe.ninja gems - keep only trade site gems
        profits_data = [g for g in profits_data if g.get('from_trade', True)]
        profits_data.sort(key=lambda x: x['profit_percent'], reverse=True)
        print(f"Hiding poe.ninja gems, showing only {len(profits_data)} trade site gems")
        return [
            html.Img(src="https://web.poecdn.com/gen/image/WzI1LDE0LHsiZiI6IjJESXRlbXMvR2Vtcy9TdXBwb3J0L1N1cHBvcnRQbHVzL011bHRpcGxlQXR0YWNrc1BsdXMiLCJ3IjoxLCJoIjoxLCJzY2FsZSI6MX1d/c32ddc2121/MultipleAttacksPlus.png",
                    height="20px", className="me-1"),
            "Load All Gems"
        ], False, f"Top {len(profits_data)} gems"
    else:
        # Show all gems - add poe.ninja gems
        loaded_gems = {gem['name'] for gem in profits_data}
        added_count = 0
        
        for name, data in all_ninja_profits.items():
            if name not in loaded_gems and 'l1' in data and 'l5' in data:
                l1_cost = data['l1']
                l5_price = data['l5']
                leveling_cost = 4 * calculator.currency_prices.get('brambleback', 10)
                quality_cost = 20 * calculator.currency_prices.get('gcp', 1)
                total_cost = l1_cost + leveling_cost + quality_cost
                profit = l5_price - total_cost
                profit_percent = (profit / total_cost * 100) if total_cost > 0 else 0
                
                profits_data.append({
                    'name': data['name'],
                    'l1_cost': l1_cost,
                    'leveling_cost': leveling_cost,
                    'quality_cost': quality_cost,
                    'total_cost': total_cost,
                    'l5_price': l5_price,
                    'profit': profit,
                    'profit_percent': profit_percent,
                    'from_trade': False  # Mark as poe.ninja data
                })
                added_count += 1
        
        # Re-sort by ROI%
        profits_data.sort(key=lambda x: x['profit_percent'], reverse=True)
        
        print(f"Added {added_count} gems from poe.ninja data")
        print(f"Total gems now: {len(profits_data)}")
        
        return [
            html.Img(src="https://web.poecdn.com/gen/image/WzI1LDE0LHsiZiI6IjJESXRlbXMvR2Vtcy9TdXBwb3J0L1N1cHBvcnRQbHVzL011bHRpcGxlQXR0YWNrc1BsdXMiLCJ3IjoxLCJoIjoxLCJzY2FsZSI6MX1d/c32ddc2121/MultipleAttacksPlus.png",
                    height="20px", className="me-1"),
            "Hide Extra Gems"
        ], False, f"All {len(profits_data)} gems"




@app.callback(
    Output('startup-trigger', 'disabled'),
    Input('startup-trigger', 'n_intervals')
)
def start_loading_on_first_visit(n):
    """Start loading gem prices on first page visit (for gunicorn/Render)"""
    global loading_thread
    if n > 0 and loading_thread is None:
        print("🚀 First page visit - starting gem price loading...")
        loading_thread = threading.Thread(target=load_gem_prices, daemon=True)
        loading_thread.start()
    return True


@app.callback(
    Output('currency-icon', 'src'),
    Output('currency-text', 'children'),
    Input('currency-toggle', 'n_clicks'),
    prevent_initial_call=True
)
def toggle_currency_mode(n_clicks):
    """Toggle between chaos and divine display"""
    global currency_mode
    
    if currency_mode == 'chaos':
        currency_mode = 'divine'
        # Showing divine mode, so button should show chaos icon with "Show Chaos" text
        return "https://web.poecdn.com/gen/image/WzI1LDE0LHsiZiI6IjJESXRlbXMvQ3VycmVuY3kvQ3VycmVuY3lSZXJvbGxSYXJlIiwic2NhbGUiOjF9XQ/46a2347805/CurrencyRerollRare.png", "Show Chaos"
    else:
        currency_mode = 'chaos'
        # Showing chaos mode, so button should show divine icon with "Show Divine" text
        return "https://web.poecdn.com/gen/image/WzI1LDE0LHsiZiI6IjJESXRlbXMvQ3VycmVuY3kvQ3VycmVuY3lNb2RWYWx1ZXMiLCJzY2FsZSI6MX1d/ec48896769/CurrencyModValues.png", "Show Divine"


@app.callback(
    Output('auto-refresh-interval', 'interval'),
    Output('auto-refresh-interval', 'disabled'),
    Input('auto-refresh-toggle', 'value'),
    Input('refresh-interval-input', 'value')
)
def update_auto_refresh_settings(toggle_value, interval_minutes):
    """Update auto-refresh interval and enable/disable state"""
    is_enabled = 'enabled' in toggle_value if toggle_value else False
    
    # Convert minutes to milliseconds
    if interval_minutes and interval_minutes > 0:
        interval_ms = interval_minutes * 60 * 1000
    else:
        interval_ms = 1200000  # Default 20 minutes
    
    return interval_ms, not is_enabled


@app.callback(
    Output('gem-table', 'data'),
    Output('gem-table', 'columns'),
    Output('last-update', 'children'),
    Output('gems-shown-status', 'children', allow_duplicate=True),
    Input('refresh-button', 'n_clicks'),
    Input('auto-refresh-interval', 'n_intervals'),
    Input('progress-interval', 'n_intervals'),
    Input('currency-toggle', 'n_clicks'),  # Add currency toggle as trigger
    prevent_initial_call=True
)
def update_table_and_analysis(n_clicks, auto_refresh_intervals, progress_intervals, currency_clicks):
    """Update table based on refresh triggers"""
    global corruption_cache, last_refresh_time
    
    # Get which input triggered the callback
    ctx = callback_context
    triggered_id = ctx.triggered[0]['prop_id'].split('.')[0] if ctx.triggered else None
    
    # Clear corruption cache and reload data when refresh button clicked or auto-refresh triggers
    if triggered_id == 'refresh-button' or triggered_id == 'auto-refresh-interval':
        source = "Auto-refresh" if triggered_id == 'auto-refresh-interval' else "Manual refresh"
        print(f"🔄 {source} triggered - reloading gem prices...")
        corruption_cache = {}
        profits_data.clear()  # Clear existing data
        # Fully reset the loading progress
        loading_progress['complete'] = False
        loading_progress['current'] = 0
        loading_progress['total'] = 0
        loading_progress['status'] = 'Starting refresh...'
        loading_progress['phase'] = 'ninja'
        print(f"Reset loading_progress: {loading_progress}")
        # Start a new loading thread
        loading_thread = threading.Thread(target=load_gem_prices, daemon=True)
        loading_thread.start()
        print("Started new loading thread")
        return [], create_columns(False), "Last updated: Refreshing...", "Refreshing..."
    
    # Wait until data is loaded
    if not loading_progress['complete'] or not profits_data:
        return [], create_columns(False), "Last updated: Loading...", "Loading..."
    
    # Only update timestamp on actual data refresh (not currency toggle or progress interval after loading)
    if triggered_id not in ['currency-toggle', 'progress-interval']:
        last_refresh_time = datetime.now().strftime('%H:%M:%S')
        print(f"Updated timestamp to: {last_refresh_time} (triggered by {triggered_id})")
    
    # Use the stored timestamp
    timestamp = f"Last updated: {last_refresh_time}" if last_refresh_time else "Last updated: Never"
    
    # Update status
    gems_status = f"Top {len(profits_data)} gems" if len(profits_data) <= 5 else f"All {len(profits_data)} gems"
    
    return create_table_data(False), create_columns(False), timestamp, gems_status


@app.callback(
    Output('gem-analysis', 'children'),
    Output('gem-table', 'data', allow_duplicate=True),
    Input('gem-table', 'active_cell'),
    Input('currency-toggle', 'n_clicks'),
    State('gem-table', 'data'),
    prevent_initial_call=True
)
def display_gem_details(active_cell, currency_clicks, table_data):
    """Handle cell clicks - Gem opens trade link, Trade Price upgrades data, Gamba shows analysis"""
    global corruption_cache, profits_data, current_analysis_gem
    
    ctx = callback_context
    if not ctx.triggered:
        return html.Div(), dash.no_update
    
    triggered_id = ctx.triggered[0]['prop_id'].split('.')[0]
    
    # If currency toggle triggered, regenerate analysis for current gem
    if triggered_id == 'currency-toggle':
        if not current_analysis_gem:
            return dash.no_update, dash.no_update
        # Use the stored gem name to regenerate analysis
        gem_name = current_analysis_gem
        # Find the gem data
        gem_data = next((g for g in profits_data if g['name'] == gem_name), None)
        if not gem_data or not gem_data.get('from_trade', True):
            return dash.no_update, dash.no_update
        # Skip to the corruption analysis section below
    else:
        # Normal cell click handling
        if not active_cell:
            return html.Div(), dash.no_update
        
        clicked_row = table_data[active_cell['row']]
        gem_name = clicked_row['gem_name']
        
        # Handle Gem column - open trade link using HTML/JS
        if active_cell['column_id'] == 'Gem':
            trade_url = f"https://www.pathofexile.com/trade/search/{calculator.api.league}?q={{%22query%22:{{%22status%22:{{%22option%22:%22available%22}},%22type%22:%22{gem_name}%22,%22filters%22:{{%22misc_filters%22:{{%22filters%22:{{%22gem_level%22:{{%22min%22:1,%22max%22:1}},%22quality%22:{{%22min%22:0,%22max%22:0}},%22corrupted%22:{{%22option%22:%22false%22}}}}}}}}}}}}"
            return html.Div([
                dcc.Location(id='dummy-location', refresh=False),
                html.Iframe(
                    srcDoc=f'<script>window.open("{trade_url}", "_blank"); window.parent.postMessage("close", "*");</script>',
                    style={'display': 'none'}
                )
            ]), dash.no_update
        
        # Handle Corrupt column
        if active_cell['column_id'] != 'Corrupt':
            return html.Div(), dash.no_update
        
        # Find profit data for this gem
        gem_data = next((g for g in profits_data if g['name'] == gem_name), None)
        if not gem_data:
            return html.Div("Gem not found", className="text-danger"), dash.no_update
        
        # Check if this is a "Trade Price" button (poe.ninja gem)
        if not gem_data.get('from_trade', True):
            # Fetch trade site prices and upgrade the gem data
            print(f"Upgrading {gem_name} from poe.ninja to trade site prices...")
            
            # Fetch trade prices
            trade_profit = calculator.calculate_basic_profit(gem_name)
            
            if trade_profit:
                # Update the gem in profits_data
                for i, gem in enumerate(profits_data):
                    if gem['name'] == gem_name:
                        trade_profit['from_trade'] = True
                        profits_data[i] = trade_profit
                        print(f"✓ Upgraded {gem_name} to trade site data")
                        break
                
                # Re-sort by ROI%
                profits_data.sort(key=lambda x: x['profit_percent'], reverse=True)
                
                # Return success message and updated table
                success_msg = dbc.Alert(
                    f"✓ Updated {gem_name} with trade site prices! Button now shows 'Gamba?' for corruption analysis.",
                    color="success",
                    dismissable=True,
                    duration=4000
                )
                return success_msg, create_table_data(False)
            else:
                # Failed to fetch trade prices
                error_msg = dbc.Alert(
                    f"✗ Could not fetch trade site prices for {gem_name}. Try again in a moment.",
                    color="danger",
                    dismissable=True,
                    duration=4000
                )
                return error_msg, dash.no_update
    
    # This is a "Gamba?" button - show corruption analysis
    # Check cache first
    if gem_name in corruption_cache:
        print(f"Using cached corruption data for {gem_name}")
        corruption_data = corruption_cache[gem_name]
    else:
        # Calculate corruption EV and cache it
        print(f"Fetching corruption data for {gem_name}")
        corruption_data = calculator.calculate_corruption_ev(gem_name, gem_data)
        
        if not corruption_data:
            return dbc.Alert("Could not fetch corruption prices from trade site. Try again in a moment.", color="warning"), dash.no_update
        
        # Cache the data
        corruption_cache[gem_name] = corruption_data
    
    # Calculate comparison
    comparison = corruption_data['ev_profit'] - corruption_data['base_profit']
    comparison_text = f"+{comparison:.1f}c" if comparison > 0 else f"{comparison:.1f}c"
    comparison_color = '#00ff00' if comparison > 0 else '#ff0000'
    
    # Calculate comparison
    comparison = corruption_data['ev_profit'] - corruption_data['base_profit']
    comparison_text = f"+{comparison:.1f}c" if comparison > 0 else f"{comparison:.1f}c"
    comparison_color = '#00ff00' if comparison > 0 else '#ff0000'
    
    # Create analysis card
    analysis_card = dbc.Card([
        dbc.CardHeader([
            html.H6(f"🎰 Corruption Analysis: {gem_name}", className="mb-0")
        ]),
        dbc.CardBody([
            dbc.Row([
                # Corruption Analysis (full width, aligned left)
                dbc.Col([
                    html.H6("🔮 Corruption EV", className="mb-2"),
                    html.Div([
                        html.Div([
                            html.Span("• No Effect (33%): ", style={'fontSize': '0.9em'}),
                            html.Span(format_price(corruption_data['outcomes']['l5_no_change'], currency_mode), 
                                     style={'fontSize': '0.9em', 'fontWeight': 'bold'}),
                            html.Span("  ", style={'marginRight': '10px'}),
                            html.Span("• +1 Lvl (17%): ", style={'fontSize': '0.9em'}),
                            html.Span(format_price(corruption_data['outcomes']['l6'], currency_mode), 
                                     style={'fontSize': '0.9em', 'fontWeight': 'bold'}),
                            html.Span("  ", style={'marginRight': '10px'}),
                            html.Span("• -1 Lvl (17%): ", style={'fontSize': '0.9em'}),
                            html.Span(format_price(corruption_data['outcomes']['l4'], currency_mode), 
                                     style={'fontSize': '0.9em', 'fontWeight': 'bold'}),
                            html.Span("  ", style={'marginRight': '10px'}),
                            html.Span("• Q+ (17%): ", style={'fontSize': '0.9em'}),
                            html.Span(format_price(corruption_data['outcomes']['quality_up'], currency_mode), 
                                     style={'fontSize': '0.9em', 'fontWeight': 'bold'}),
                            html.Span("  ", style={'marginRight': '10px'}),
                            html.Span("• Q- (17%): ", style={'fontSize': '0.9em'}),
                            html.Span(format_price(corruption_data['outcomes']['quality_down'], currency_mode), 
                                     style={'fontSize': '0.9em', 'fontWeight': 'bold'})
                        ], className="mb-2"),
                        html.Hr(className="my-2"),
                        html.Div([
                            html.B("EV: ", style={'fontSize': '0.9em', 'color': '#00ff00' if corruption_data['ev_profit'] > 0 else '#ff0000'}),
                            html.B(f"{format_price(corruption_data['ev_profit'], currency_mode)} ({corruption_data['ev_percent']:.1f}%)", 
                                   style={'fontSize': '0.9em', 'color': '#00ff00' if corruption_data['ev_profit'] > 0 else '#ff0000'}),
                            html.Br(),
                            html.Small(f"vs Base: {comparison_text}", style={'fontSize': '0.85em', 'color': comparison_color})
                        ])
                    ])
                ], width=12)
            ]),
            html.Hr(),
            dbc.Row([
                dbc.Col([
                    html.Small("Uncorrupted:", className="text-muted d-inline me-2"),
                    html.A("🔍 L1 Q0", 
                           href=f"https://www.pathofexile.com/trade/search/{calculator.api.league}?q={{%22query%22:{{%22status%22:{{%22option%22:%22available%22}},%22type%22:%22{gem_name}%22,%22filters%22:{{%22misc_filters%22:{{%22filters%22:{{%22gem_level%22:{{%22min%22:1,%22max%22:1}},%22quality%22:{{%22min%22:0,%22max%22:0}},%22corrupted%22:{{%22option%22:%22false%22}}}}}}}}}}}}",
                           target="_blank", className="me-2"),
                    html.A("🔍 L5 Q20",
                           href=f"https://www.pathofexile.com/trade/search/{calculator.api.league}?q={{%22query%22:{{%22status%22:{{%22option%22:%22available%22}},%22type%22:%22{gem_name}%22,%22filters%22:{{%22misc_filters%22:{{%22filters%22:{{%22gem_level%22:{{%22min%22:5,%22max%22:5}},%22quality%22:{{%22min%22:20,%22max%22:20}},%22corrupted%22:{{%22option%22:%22false%22}}}}}}}}}}}}",
                           target="_blank", className="me-3"),
                    html.Span("| ", className="text-muted me-2"),
                    html.Small("Corrupted:", className="text-muted d-inline me-2"),
                    html.A("🔍 L5 Q20", 
                           href=f"https://www.pathofexile.com/trade/search/{calculator.api.league}?q={{%22query%22:{{%22status%22:{{%22option%22:%22available%22}},%22type%22:%22{gem_name}%22,%22filters%22:{{%22misc_filters%22:{{%22filters%22:{{%22gem_level%22:{{%22min%22:5,%22max%22:5}},%22quality%22:{{%22min%22:20,%22max%22:20}},%22corrupted%22:{{%22option%22:%22true%22}}}}}}}}}}}}",
                           target="_blank", className="me-2"),
                    html.A("🔍 L6 Q20",
                           href=f"https://www.pathofexile.com/trade/search/{calculator.api.league}?q={{%22query%22:{{%22status%22:{{%22option%22:%22available%22}},%22type%22:%22{gem_name}%22,%22filters%22:{{%22misc_filters%22:{{%22filters%22:{{%22gem_level%22:{{%22min%22:6,%22max%22:6}},%22quality%22:{{%22min%22:20,%22max%22:20}},%22corrupted%22:{{%22option%22:%22true%22}}}}}}}}}}}}",
                           target="_blank")
                ], width=12)
            ], className="mt-2")
        ])
    ], color="dark", outline=True)
    
    # Store which gem is currently displayed for currency toggle updates
    current_analysis_gem = gem_name
    
    return analysis_card, dash.no_update


# Clientside callback to handle footer show/hide animations
app.clientside_callback(
    """
    function(analysis_content, close_clicks, show_clicks) {
        const footer = document.getElementById('gem-analysis-footer');
        const mainContent = document.getElementById('main-content');
        const spacer = document.getElementById('footer-spacer');
        const showBtn = document.getElementById('show-analysis-container');
        const closeBtn = document.getElementById('close-analysis-btn');
        
        if (!footer || !mainContent || !spacer || !showBtn || !closeBtn) {
            return window.dash_clientside.no_update;
        }
        
        // Determine which button was clicked
        const ctx = window.dash_clientside.callback_context;
        if (!ctx.triggered.length) {
            return window.dash_clientside.no_update;
        }
        
        const triggeredId = ctx.triggered[0].prop_id.split('.')[0];
        
        // If close button clicked, hide footer
        if (triggeredId === 'close-analysis-btn') {
            footer.style.bottom = '-50vh';
            spacer.style.height = '0px';
            showBtn.style.display = 'block';
            closeBtn.style.display = 'none';
            return window.dash_clientside.no_update;
        }
        
        // If show button clicked, show footer
        if (triggeredId === 'show-analysis-btn') {
            footer.style.bottom = '0';
            spacer.style.height = '35vh';
            showBtn.style.display = 'none';
            closeBtn.style.display = 'block';
            return window.dash_clientside.no_update;
        }
        
        // If gem-analysis content changed (new analysis), show footer
        if (triggeredId === 'gem-analysis' && analysis_content && analysis_content.props && analysis_content.props.children) {
            footer.style.bottom = '0';
            spacer.style.height = '35vh';
            showBtn.style.display = 'none';
            closeBtn.style.display = 'block';
        }
        
        return window.dash_clientside.no_update;
    }
    """,
    Output('gem-analysis-footer', 'style', allow_duplicate=True),
    Input('gem-analysis', 'children'),
    Input('close-analysis-btn', 'n_clicks'),
    Input('show-analysis-btn', 'n_clicks'),
    prevent_initial_call=True
)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))  # Render uses port 10000 by default
    print(f"Starting PoE Gem Profit Calculator...")
    print(f"Listening on port {port}")
    app.run_server(host='0.0.0.0', port=port, debug=False)
