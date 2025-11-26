"""
Path of Exile Awakened Gem Profit Calculator - Dash Web Version
Calculates profit for leveling awakened support gems using Wild Brambleback beasts
"""

import requests
import dash
from dash import dcc, html, Input, Output, State, dash_table, callback_context
import dash_bootstrap_components as dbc
import pandas as pd
from datetime import datetime
import threading
import time

# Import the existing backend logic
# Note: Make sure poe_gem_profit_calculator.py is in the same directory
import sys
sys.path.append('.')

# We'll extract just the calculator classes inline since they're embedded in GUI file
# For now, using simplified version - in production, extract to separate file

class SimplePoeAPI:
    """Simplified API client for Dash version"""
    def __init__(self, league=None):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'PoE-Gem-Profit-Calculator/1.0'
        })
        self.league = league or self.get_current_league()
    
    def get_current_league(self):
        """Auto-detect current challenge league from poe.ninja"""
        try:
            # Try to get league from the currency API endpoint
            # poe.ninja uses lowercase league names in API
            url = "https://poe.ninja/api/data/currencyoverview?league=Keepers&type=Currency"
            response = self.session.get(url, timeout=10)
            
            # If Keepers works, use it
            if response.status_code == 200:
                print("✓ Selected league: Keepers")
                return "Keepers"
            
            # Fallback: try common league names
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
            return "Keepers"  # Default to Keepers since we know it exists
    
    def get_divine_chaos_rate(self):
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
    
    def get_awakened_gem_prices(self):
        try:
            url = f"https://poe.ninja/api/data/itemoverview?league={self.league}&type=SkillGem"
            response = self.session.get(url, timeout=10)
            data = response.json()
            gems = {}
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
            return gems
        except Exception as e:
            print(f"Error: {e}")
            return {}
    
    def get_currency_prices(self):
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
    
    def get_trade_site_gem_price_corrupted(self, gem_name, level, quality_min, quality_max):
        """Fetch corrupted gem price from trade site"""
        try:
            # Build search query
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
            result_ids = search_data.get('result', [])[:10]  # Get top 10
            
            if not result_ids:
                return None
            
            # Fetch the actual listings
            fetch_url = f"https://www.pathofexile.com/api/trade/fetch/{','.join(result_ids)}?query={search_data.get('id')}"
            time.sleep(0.5)  # Rate limit
            
            fetch_response = self.session.get(fetch_url, timeout=10)
            
            if fetch_response.status_code != 200:
                return None
            
            fetch_data = fetch_response.json()
            
            # Extract prices
            prices = []
            for item in fetch_data.get('result', []):
                listing = item.get('listing', {})
                price_info = listing.get('price', {})
                
                if price_info:
                    amount = price_info.get('amount', 0)
                    currency = price_info.get('currency', '')
                    
                    # Skip mirror prices (joke listings)
                    if currency == 'mirror':
                        continue
                    
                    if currency == 'chaos':
                        prices.append(amount)
                    elif currency == 'divine':
                        divine_rate = self.get_divine_chaos_rate()
                        chaos_price = amount * divine_rate
                        prices.append(chaos_price)
            
            if prices:
                avg_price = sum(prices) / len(prices)
                return avg_price
            
            return None
            
        except Exception as e:
            print(f"Error fetching corrupted gem price: {e}")
            return None
    
    def get_trade_site_gem_price_uncorrupted(self, gem_name, level, quality):
        """Fetch uncorrupted gem price from trade site"""
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
                                "corrupted": {"option": "false"}
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
            
            fetch_url = f"https://www.pathofexile.com/api/trade/fetch/{','.join(result_ids)}?query={search_data.get('id')}"
            time.sleep(0.5)
            
            fetch_response = self.session.get(fetch_url, timeout=10)
            
            if fetch_response.status_code != 200:
                return None
            
            fetch_data = fetch_response.json()
            
            prices = []
            for item in fetch_data.get('result', []):
                listing = item.get('listing', {})
                price_info = listing.get('price', {})
                
                if price_info:
                    amount = price_info.get('amount', 0)
                    currency = price_info.get('currency', '')
                    
                    if currency == 'mirror':
                        continue
                    
                    if currency == 'chaos':
                        prices.append(amount)
                    elif currency == 'divine':
                        divine_rate = self.get_divine_chaos_rate()
                        chaos_price = amount * divine_rate
                        prices.append(chaos_price)
            
            if prices:
                return sum(prices) / len(prices)
            
            return None
            
        except Exception as e:
            print(f"Error fetching uncorrupted gem price: {e}")
            return None

class SimpleCalculator:
    """Simplified calculator for Dash version"""
    def __init__(self, league="Settlers"):
        self.api = SimplePoeAPI(league)
        self.corruption_cache = {}  # Cache corruption data
        self.trade_price_cache = {}  # Cache for live trade prices
    
    def calculate_profit_with_trade_prices(self, gem_name, base_profit_data):
        """Calculate profit using live trade site prices (L1 and L5)"""
        cache_key = f"{gem_name}_trade_prices"
        if cache_key in self.trade_price_cache:
            cached_time, cached_data = self.trade_price_cache[cache_key]
            if time.time() - cached_time < 300:  # 5 min cache
                return cached_data
        
        try:
            print(f"Fetching live trade prices for {gem_name}...")
            
            # Get L1 Q0 price
            time.sleep(0.3)
            l1_trade_price = self.api.get_trade_site_gem_price_uncorrupted(gem_name, 1, 0)
            l1_cost = l1_trade_price if l1_trade_price else base_profit_data['l1_cost']
            
            # Get L5 Q20 price
            time.sleep(0.3)
            l5_trade_price = self.api.get_trade_site_gem_price_uncorrupted(gem_name, 5, 20)
            l5_price = l5_trade_price if l5_trade_price else base_profit_data['l5_price']
            
            # Recalculate with trade prices
            leveling_cost = base_profit_data['leveling_cost']
            quality_cost = base_profit_data['quality_cost']
            total_cost = l1_cost + leveling_cost + quality_cost
            profit = l5_price - total_cost
            profit_percent = (profit / total_cost * 100) if total_cost > 0 else 0
            
            result = {
                'l1_cost': l1_cost,
                'l5_price': l5_price,
                'leveling_cost': leveling_cost,
                'quality_cost': quality_cost,
                'total_cost': total_cost,
                'profit': profit,
                'profit_percent': profit_percent,
                'from_trade': True,
                'l1_from_trade': l1_trade_price is not None,
                'l5_from_trade': l5_trade_price is not None
            }
            
            self.trade_price_cache[cache_key] = (time.time(), result)
            print(f"  L1: {l1_cost:.1f}c, L5: {l5_price:.1f}c, Profit: {profit:.1f}c")
            return result
            
        except Exception as e:
            print(f"Error fetching trade prices: {e}")
            return None
        
    def calculate_corruption_ev_estimate(self, gem_name, base_profit_data):
        """Quick estimate of corruption EV using multipliers (for table display)"""
        try:
            vaal_cost = self.api.get_currency_prices().get('vaal', 1)
            total_cost = base_profit_data['total_cost'] + vaal_cost
            l5_price = base_profit_data['l5_price']
            
            # Use estimated multipliers (fast, no API calls)
            outcomes = {
                'l5_no_change': l5_price * 0.95,
                'l6': l5_price * 1.5,
                'l4': l5_price * 0.4,
                'quality_up': l5_price * 1.1,
                'quality_down': l5_price * 0.6
            }
            
            # Calculate EV
            ev_revenue = (
                0.3333 * outcomes['l5_no_change'] +
                0.1667 * outcomes['l6'] +
                0.1667 * outcomes['l4'] +
                0.1667 * outcomes['quality_up'] +
                0.1667 * outcomes['quality_down']
            )
            
            ev_profit = ev_revenue - total_cost
            ev_percent = (ev_profit / total_cost * 100) if total_cost > 0 else 0
            
            return {
                'ev_profit': ev_profit,
                'ev_percent': ev_percent,
                'is_estimate': True
            }
        except:
            return None
    
    def calculate_corruption_ev(self, gem_name, base_profit_data):
        """Calculate expected value for corrupting a gem using real trade prices"""
        # Check cache first
        cache_key = f"{gem_name}_corruption"
        if cache_key in self.corruption_cache:
            cached_time, cached_data = self.corruption_cache[cache_key]
            if time.time() - cached_time < 300:  # 5 min cache
                return cached_data
        
        try:
            print(f"Fetching corruption prices for {gem_name}...")
            
            vaal_cost = self.api.get_currency_prices().get('vaal', 1)
            total_cost = base_profit_data['total_cost'] + vaal_cost
            l5_price = base_profit_data['l5_price']
            
            # Fetch real prices from trade site
            outcomes = {}
            
            # 1. L4 Q20 corrupted
            time.sleep(0.3)
            l4_price = self.api.get_trade_site_gem_price_corrupted(gem_name, 4, 20, 20)
            outcomes['l4'] = l4_price if l4_price else l5_price * 0.4
            
            # 2. L5 Q20 corrupted (no effect)
            time.sleep(0.3)
            l5_corrupted = self.api.get_trade_site_gem_price_corrupted(gem_name, 5, 20, 20)
            outcomes['l5_no_change'] = l5_corrupted if l5_corrupted else l5_price * 0.95
            
            # 3. L5 Q10-19 corrupted (quality down)
            time.sleep(0.3)
            quality_down = self.api.get_trade_site_gem_price_corrupted(gem_name, 5, 10, 19)
            outcomes['quality_down'] = quality_down if quality_down else l5_price * 0.6
            
            # 4. L5 Q21-23 corrupted (quality up)
            time.sleep(0.3)
            quality_up = self.api.get_trade_site_gem_price_corrupted(gem_name, 5, 21, 23)
            outcomes['quality_up'] = quality_up if quality_up else l5_price * 1.1
            
            # 5. L6 Q20 corrupted
            time.sleep(0.3)
            l6_price = self.api.get_trade_site_gem_price_corrupted(gem_name, 6, 20, 20)
            outcomes['l6'] = l6_price if l6_price else l5_price * 1.5
            
            print(f"  L4: {outcomes['l4']:.1f}c, L5: {outcomes['l5_no_change']:.1f}c, L6: {outcomes['l6']:.1f}c")
            
            # Calculate EV with correct probabilities
            ev_revenue = (
                0.3333 * outcomes['l5_no_change'] +  # No effect
                0.1667 * outcomes['l6'] +             # +1 level
                0.1667 * outcomes['l4'] +             # -1 level
                0.1667 * outcomes['quality_up'] +     # Quality up
                0.1667 * outcomes['quality_down']     # Quality down
            )
            
            ev_profit = ev_revenue - total_cost
            ev_percent = (ev_profit / total_cost * 100) if total_cost > 0 else 0
            
            result = {
                'vaal_cost': vaal_cost,
                'total_cost': total_cost,
                'outcomes': outcomes,
                'ev_revenue': ev_revenue,
                'ev_profit': ev_profit,
                'ev_percent': ev_percent,
                'base_profit': base_profit_data['profit']
            }
            
            # Cache result
            self.corruption_cache[cache_key] = (time.time(), result)
            print(f"  EV: {ev_profit:.1f}c ({ev_percent:.1f}%)")
            return result
            
        except Exception as e:
            print(f"Error calculating corruption EV: {e}")
            return None
        
    def calculate_all_profits(self, target_quality=20):
        gems_data = self.api.get_awakened_gem_prices()
        currency_prices = self.api.get_currency_prices()
        divine_rate = self.api.get_divine_chaos_rate()
        
        # Get unique gem names
        gem_names = set()
        for key in gems_data.keys():
            name = gems_data[key]['name']
            gem_names.add(name)
        
        profits = []
        for gem_name in gem_names:
            result = self.calculate_profit(gem_name, gems_data, currency_prices, target_quality, divine_rate)
            if result:
                profits.append(result)
        
        profits.sort(key=lambda x: x['profit_percent'], reverse=True)
        return profits, currency_prices, divine_rate
    
    def calculate_profit(self, gem_name, gems_data, currency_prices, target_quality, divine_rate):
        l1_key = f"{gem_name}_L1_Q0"
        l5_key = f"{gem_name}_L5_Q{target_quality}"
        
        if l1_key not in gems_data or l5_key not in gems_data:
            return None
        
        l1_cost = gems_data[l1_key]['chaos_value']
        revenue = gems_data[l5_key]['chaos_value']
        leveling_cost = currency_prices.get('brambleback', 10)
        quality_cost = currency_prices.get('gcp', 1) * target_quality
        
        total_cost = l1_cost + leveling_cost + quality_cost
        profit = revenue - total_cost
        profit_percent = (profit / total_cost * 100) if total_cost > 0 else 0
        
        return {
            'name': gem_name,
            'l1_cost': l1_cost,
            'l5_price': revenue,
            'leveling_cost': leveling_cost,
            'quality_cost': quality_cost,
            'total_cost': total_cost,
            'revenue': revenue,
            'profit': profit,
            'profit_percent': profit_percent,
            'target_quality': target_quality
        }

# Initialize calculator (auto-detects current league)
calculator = SimpleCalculator(league=None)

# Initialize the Dash app
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.DARKLY])
app.title = "PoE Gem Profit Calculator"
server = app.server

# Allow callbacks to components created by other callbacks
app.config.suppress_callback_exceptions = True

# Disable all dev tools to prevent validation warnings
app.enable_dev_tools(
    debug=False,
    dev_tools_ui=False,
    dev_tools_props_check=False,
    dev_tools_serve_dev_bundles=False,
    dev_tools_hot_reload=False,
    dev_tools_silence_routes_logging=False
)

profits_data = []
currency_prices = {}
divine_rate = 0
last_update = "Never"
corruption_data = {}
formatted_table_cache = {}  # Cache formatted table data: {currency_mode: (timestamp, df)}

def format_price(value, display_mode='chaos'):
    """Format price based on display mode"""
    if display_mode == 'divine' and divine_rate > 0:
        divine_value = value / divine_rate
        if divine_value >= 1:
            result = f"{divine_value:.2f}d"
            if value > 10000:  # Only debug for large values to avoid spam
                print(f"DEBUG format_price: {value}c -> {result} (divine_rate={divine_rate})")
            return result
        else:
            return f"{value:.1f}c"
    return f"{value:.1f}c"

def fetch_data():
    """Fetch gem and currency data"""
    global profits_data, currency_prices, divine_rate, last_update
    try:
        profits, currencies, rate = calculator.calculate_all_profits(target_quality=20)
        profits_data = profits
        currency_prices = currencies
        divine_rate = rate
        last_update = datetime.now().strftime('%H:%M:%S')
        return True
    except Exception as e:
        print(f"Error fetching data: {e}")
        return False

# Initial data fetch
fetch_data()

# App layout
app.layout = dbc.Container([
    # Header
    dbc.Row([
        dbc.Col([
            html.H3("PoE - Awakened Gem Profit Calculator", className="text-center mb-1"),
            html.Small("Leveling L1 Q0 → L5 Q20 with Wild Brambleback", 
                   className="text-center text-muted d-block")
        ])
    ], className="mt-2 mb-2"),
    
    # Controls
    dbc.Row([
        dbc.Col([
            dbc.Button("🔄 Refresh", id="refresh-btn", color="primary", size="sm", className="me-2"),
            dbc.Button("Clear", id="clear-trade-btn", color="secondary", size="sm"),
        ], width=4),
        dbc.Col([
            html.Small(id="status-message", className="text-muted")
        ], width=5),
        dbc.Col([
            dbc.RadioItems(
                id="currency-toggle",
                options=[
                    {"label": "Chaos", "value": "chaos"},
                    {"label": "Divine", "value": "divine"}
                ],
                value="chaos",
                inline=True,
                className="float-end"
            )
        ], width=3)
    ], className="mb-2"),
    
    # Currency Info Bar (more compact)
    dbc.Row([
        dbc.Col([
            html.Small(id="currency-info", className="text-center text-muted d-block")
        ])
    ], className="mb-2"),
    
    # Main Data Table
    dbc.Row([
        dbc.Col([
            html.Div(id="data-table-container")
        ])
    ]),
    
    # Trade Results Area (sticky at bottom)
    html.Div([
        html.Div(id="trade-results", className="mt-3")
    ], style={
        'position': 'fixed',
        'bottom': '0',
        'left': '0',
        'right': '0',
        'backgroundColor': '#222',
        'borderTop': '2px solid #444',
        'padding': '10px',
        'maxHeight': '380px',  # Increased from 370px
        'overflowY': 'auto',
        'zIndex': '1000'
    }),
    
    
    # Hidden divs for storing state
    dcc.Store(id="expanded-gems", data=[]),
    dcc.Store(id="corruption-cache", data={}),
    dcc.Store(id="current-trade-gem", data=None),
    
    # Auto-refresh interval (5 minutes)
    dcc.Interval(id="auto-refresh", interval=300000, n_intervals=0)
    
], fluid=True, className="p-3", style={'paddingBottom': '400px'})  # Increased padding for taller sticky footer

@app.callback(
    [Output("data-table-container", "children"),
     Output("currency-info", "children"),
     Output("status-message", "children")],
    [Input("refresh-btn", "n_clicks"),
     Input("auto-refresh", "n_intervals"),
     Input("currency-toggle", "value")]
)
def update_table(n_clicks, n_intervals, currency_mode):
    """Update the main data table"""
    try:
        global formatted_table_cache
        
        ctx = callback_context
        
        trigger = ctx.triggered[0]['prop_id'] if ctx.triggered else 'initial'
        print(f"DEBUG: update_table called by {trigger}, currency_mode={currency_mode}")
        
        # Refresh data if refresh button clicked or auto-refresh triggered
        if ctx.triggered and (ctx.triggered[0]['prop_id'] == 'refresh-btn.n_clicks' or 
                              ctx.triggered[0]['prop_id'] == 'auto-refresh.n_intervals'):
            if ctx.triggered[0]['prop_id'] == 'refresh-btn.n_clicks':
                fetch_data()
                # Clear cache when data refreshes
                formatted_table_cache = {}
        
        # Check cache first
        if currency_mode in formatted_table_cache:
            cache_time, cached_df = formatted_table_cache[currency_mode]
            # Use cache if less than 5 minutes old
            if time.time() - cache_time < 300:
                print(f"DEBUG: Using cached table for {currency_mode}")
                df = cached_df
            else:
                df = None
        else:
            df = None
        
        # Build table data if not cached
        if df is None:
            print(f"DEBUG: Building new table for {currency_mode}")
            # Prepare table data - rebuild from scratch to ensure Dash sees changes
            table_data = []
            timestamp = time.time()  # Add timestamp to force update detection
            for gem in profits_data:
                # Use quick estimate for table (no trade API calls)
                corruption_ev_data = calculator.calculate_corruption_ev_estimate(gem['name'], gem)
                
                row = {
                    'Gem': gem['name'].replace('Awakened ', ''),
                    'L1 Cost': format_price(gem['l1_cost'], currency_mode),
                    'Level Cost': format_price(gem['leveling_cost'], currency_mode),
                    'Quality Cost': format_price(gem['quality_cost'], currency_mode),
                    'Total Cost': format_price(gem['total_cost'], currency_mode),
                    'L5 Price': format_price(gem['l5_price'], currency_mode),
                    'Profit': format_price(gem['profit'], currency_mode),
                    'Profit %': f"{gem['profit_percent']:.1f}%",
                    'Corrupt EV': format_price(corruption_ev_data['ev_profit'], currency_mode) if corruption_ev_data else '--',
                    'Corrupt %': f"{corruption_ev_data['ev_percent']:.1f}%" if corruption_ev_data else '--',
                    'gem_name': gem['name'],  # Hidden column for lookups
                    '_timestamp': timestamp  # Hidden column to force update detection
                }
                table_data.append(row)
            
            df = pd.DataFrame(table_data)
            
            print(f"DEBUG: DataFrame created, first row L1 Cost from df = {df.iloc[0]['L1 Cost'] if len(df) > 0 else 'empty'}")
            
            # Cache the result
            formatted_table_cache[currency_mode] = (time.time(), df)
    
        # Pre-sort the dataframe to match the default visual sort (by Profit % descending)
        # This ensures the row indices match between visual display and callback data
        df = df.sort_values('Profit %', ascending=False, key=lambda x: x.str.rstrip('%').astype(float))
    
        # Currency info
        currency_info = html.Div([
            f"Divine Orb: {divine_rate:.0f}c | ",
            f"GCP: {currency_prices.get('gcp', 0):.0f}c | ",
            f"Vaal Orb: {currency_prices.get('vaal', 0):.1f}c | ",
            f"Wild Brambleback: {currency_prices.get('brambleback', 0):.0f}c"
        ])
    
        # Status message
        status = html.Div([
            f"League: {calculator.api.league} | ",
            f"Last updated: {last_update} | ",
            f"Displaying {len(profits_data)} gems | ",
            html.Small("Table uses PoE.Ninja prices (click gem for trade prices)", className="text-muted")
        ], className="text-muted")
    
        # Prepare columns for table (exclude hidden columns)
        columns = [
            {'name': col, 'id': col} 
            for col in df.columns if col not in ['gem_name', '_timestamp']
        ]
    
        # Prepare style conditional
        style_conditional = [
            # Color code by profit
            {
                'if': {
                    'filter_query': '{Profit} contains "-"',
                },
                'backgroundColor': '#4d1515',
            },
            {
                'if': {
                    'filter_query': '{Profit %} > 50',
                },
                'backgroundColor': '#2d5016',
            },
            {
                'if': {
                    'filter_query': '{Profit %} > 20 && {Profit %} <= 50',
                },
                'backgroundColor': '#3d3d15',
            }
        ]
    
        # Debug: Print first row to see what we're returning
        records = df.to_dict('records')
        if records:
            print(f"DEBUG: First row L1 Cost = {records[0].get('L1 Cost', 'missing')}")
    
        # Create complete table with all styling
        table = dash_table.DataTable(
            id='gem-table',
            columns=[{'name': col, 'id': col} for col in df.columns if col not in ['gem_name', '_timestamp']],
            data=records,
            sort_action='native',
            sort_mode='single',
            sort_by=[{'column_id': 'Profit %', 'direction': 'desc'}],
            style_table={'overflowX': 'auto'},
            style_header={
                'backgroundColor': '#2b3e50',
                'color': 'white',
                'fontWeight': 'bold',
                'textAlign': 'center'
            },
            style_cell={
                'textAlign': 'center',
                'padding': '10px',
                'backgroundColor': '#1a1a1a',
                'color': 'white'
            },
            style_data_conditional=style_conditional,
            page_size=50,
            style_as_list_view=True
        )
    
        print(f"DEBUG: About to return table with {len(records)} rows")
        return table, currency_info, status
    
    except Exception as e:
        print(f"ERROR in update_table: {e}")
        import traceback
        traceback.print_exc()
        # Return empty table on error
        return dash_table.DataTable(id='gem-table'), html.Div("Error loading currency info"), html.Div("Error")

@app.callback(
    Output("trade-results", "children"),
    [Input("gem-table", "active_cell"),
     Input("clear-trade-btn", "n_clicks"),
     Input("currency-toggle", "value")],
    [State("gem-table", "derived_virtual_data")],
    prevent_initial_call=True
)
def show_trade_results(active_cell, clear_clicks, currency_mode, table_data):
    """Show trade price check results when a gem is clicked"""
    ctx = callback_context
    
    # Clear results if clear button clicked
    if ctx.triggered and ctx.triggered[0]['prop_id'] == 'clear-trade-btn.n_clicks':
        return None
    
    # If currency toggled but no gem selected, don't show anything
    if not active_cell:
        return None
    
    if not table_data:
        return None
    
    # Get clicked gem from the actual displayed/sorted table data
    row_idx = active_cell['row']
    
    # Debug output
    print(f"DEBUG: Clicked row {row_idx}")
    print(f"DEBUG: Table has {len(table_data)} rows")
    
    if row_idx >= len(table_data):
        print(f"ERROR: Row index {row_idx} out of range")
        return None
    
    clicked_row = table_data[row_idx]
    print(f"DEBUG: Clicked row data: {clicked_row}")
    
    # Get gem name from the clicked row - prefer gem_name if available
    if 'gem_name' in clicked_row:
        gem_name = clicked_row['gem_name']
    else:
        # Reconstruct from short name
        short_name = clicked_row.get('Gem', '')
        gem_name = f"Awakened {short_name}" if short_name and not short_name.startswith('Awakened') else short_name
    
    if not gem_name:
        print("ERROR: Could not determine gem name")
        return html.Div("Could not determine gem name", className="text-danger")
    
    print(f"DEBUG: Using gem name: {gem_name}")
    
    # Find profit data for this gem
    gem_data = next((g for g in profits_data if g['name'] == gem_name), None)
    if not gem_data:
        return html.Div("Gem not found", className="text-danger")
    
    # Fetch live trade prices for L1 and L5
    trade_prices = calculator.calculate_profit_with_trade_prices(gem_name, gem_data)
    
    # Use trade prices if available, otherwise use poe.ninja
    if trade_prices:
        display_data = trade_prices
        price_source = "🔴 Live Trade Prices"  # Red indicator for trade prices
        l1_style = {'color': '#ff6b6b', 'fontWeight': 'bold'} if trade_prices.get('l1_from_trade') else {}
        l5_style = {'color': '#ff6b6b', 'fontWeight': 'bold'} if trade_prices.get('l5_from_trade') else {}
    else:
        display_data = gem_data
        price_source = "⚪ poe.ninja Estimates"
        l1_style = {}
        l5_style = {}
    
    # Calculate corruption EV using the updated profit data
    corruption_data = calculator.calculate_corruption_ev(gem_name, display_data)
    
    # Calculate comparison if corruption data exists
    if corruption_data:
        comparison = corruption_data['ev_profit'] - corruption_data['base_profit']
        comparison_text = f"+{comparison:.1f}c" if comparison > 0 else f"{comparison:.1f}c"
        comparison_color = '#00ff00' if comparison > 0 else '#ff0000'
    
    # Create trade results card with side-by-side layout
    trade_card = dbc.Card([
        dbc.CardHeader([
            html.H6(f"📊 {gem_name}", className="mb-0", style={'display': 'inline-block'}),
            html.Small(f" | {price_source}", className="text-muted ms-2")
        ]),
        dbc.CardBody([
            dbc.Row([
                # Left side: Basic Profit Analysis
                dbc.Col([
                    html.H6("💰 Base Profit", className="mb-2"),
                    html.Div([
                        html.Div([
                            html.Span("L1 Cost: ", style=l1_style),
                            html.Span(format_price(display_data['l1_cost'], currency_mode), style=l1_style), 
                            " + ",
                            f"Level: {format_price(display_data['leveling_cost'], currency_mode)}", 
                            " + ",
                            f"Quality: {format_price(display_data['quality_cost'], currency_mode)}",
                            html.Br(),
                            html.B(f"= Total: {format_price(display_data['total_cost'], currency_mode)}")
                        ], style={'fontSize': '0.9em'}),
                        html.Hr(className="my-2"),
                        html.Div([
                            html.Span("L5 Price: ", style=l5_style),
                            html.Span(format_price(display_data['l5_price'], currency_mode), style=l5_style),
                            html.Br(),
                            html.B("Profit: ", style={'color': '#00ff00' if display_data['profit'] > 0 else '#ff0000'}),
                            html.B(f"{format_price(display_data['profit'], currency_mode)} ({display_data['profit_percent']:.1f}%)", 
                                   style={'color': '#00ff00' if display_data['profit'] > 0 else '#ff0000'})
                        ], style={'fontSize': '0.9em'})
                    ])
                ], width=6),
                
                # Right side: Corruption Analysis
                dbc.Col([
                    html.H6("🔮 Corruption EV", className="mb-2"),
                    html.Div([
                        html.Small(f"Vaal: {format_price(corruption_data['vaal_cost'], currency_mode)}", style={'fontSize': '0.85em'}),
                        html.Div([
                            # Row 1: No Effect + L6
                            html.Div([
                                html.Span("• No Effect (33%): ", style={'fontSize': '0.9em'}),
                                html.Span(format_price(corruption_data['outcomes']['l5_no_change'], currency_mode), 
                                         style={'fontSize': '0.9em', 'fontWeight': 'bold'}),
                                html.Span("  ", style={'marginRight': '10px'}),
                                html.Span("• +1 Lvl (17%): ", style={'fontSize': '0.9em'}),
                                html.Span(format_price(corruption_data['outcomes']['l6'], currency_mode), 
                                         style={'fontSize': '0.9em', 'fontWeight': 'bold'})
                            ], className="mb-1"),
                            # Row 2: L4 + Q+
                            html.Div([
                                html.Span("• -1 Lvl (17%): ", style={'fontSize': '0.9em'}),
                                html.Span(format_price(corruption_data['outcomes']['l4'], currency_mode), 
                                         style={'fontSize': '0.9em', 'fontWeight': 'bold'}),
                                html.Span("  ", style={'marginRight': '10px'}),
                                html.Span("• Q+ (17%): ", style={'fontSize': '0.9em'}),
                                html.Span(format_price(corruption_data['outcomes']['quality_up'], currency_mode), 
                                         style={'fontSize': '0.9em', 'fontWeight': 'bold'})
                            ], className="mb-1"),
                            # Row 3: Q- (centered)
                            html.Div([
                                html.Span("• Q- (17%): ", style={'fontSize': '0.9em'}),
                                html.Span(format_price(corruption_data['outcomes']['quality_down'], currency_mode), 
                                         style={'fontSize': '0.9em', 'fontWeight': 'bold'})
                            ], className="mb-1")
                        ], className="mt-1 mb-1"),
                        html.Hr(className="my-2"),
                        html.Div([
                            html.B("EV: ", style={'fontSize': '0.9em', 'color': '#00ff00' if corruption_data['ev_profit'] > 0 else '#ff0000'}),
                            html.B(f"{format_price(corruption_data['ev_profit'], currency_mode)} ({corruption_data['ev_percent']:.1f}%)", 
                                   style={'fontSize': '0.9em', 'color': '#00ff00' if corruption_data['ev_profit'] > 0 else '#ff0000'}),
                            html.Br(),
                            html.Small(f"vs Base: {comparison_text}", style={'fontSize': '0.85em', 'color': comparison_color})
                        ])
                    ])
                ], width=6) if corruption_data else html.Div()
            ]),
            html.Hr(),
            dbc.Row([
                dbc.Col([
                    html.Small("Uncorrupted:", className="text-muted d-block mb-1"),
                    html.A("🔍 L1 Q0", 
                           href=f"https://www.pathofexile.com/trade/search/{calculator.api.league}?q={{%22query%22:{{%22status%22:{{%22option%22:%22online%22}},%22type%22:%22{gem_name}%22,%22filters%22:{{%22misc_filters%22:{{%22filters%22:{{%22gem_level%22:{{%22min%22:1,%22max%22:1}},%22quality%22:{{%22min%22:0,%22max%22:0}},%22corrupted%22:{{%22option%22:%22false%22}}}}}}}}}}}}",
                           target="_blank", className="me-2"),
                    html.A("🔍 L5 Q20",
                           href=f"https://www.pathofexile.com/trade/search/{calculator.api.league}?q={{%22query%22:{{%22status%22:{{%22option%22:%22online%22}},%22type%22:%22{gem_name}%22,%22filters%22:{{%22misc_filters%22:{{%22filters%22:{{%22gem_level%22:{{%22min%22:5,%22max%22:5}},%22quality%22:{{%22min%22:20,%22max%22:20}},%22corrupted%22:{{%22option%22:%22false%22}}}}}}}}}}}}",
                           target="_blank")
                ], width=6),
                dbc.Col([
                    html.Small("Corrupted:", className="text-muted d-block mb-1"),
                    html.A("🔍 L5 Q20", 
                           href=f"https://www.pathofexile.com/trade/search/{calculator.api.league}?q={{%22query%22:{{%22status%22:{{%22option%22:%22online%22}},%22type%22:%22{gem_name}%22,%22filters%22:{{%22misc_filters%22:{{%22filters%22:{{%22gem_level%22:{{%22min%22:5,%22max%22:5}},%22quality%22:{{%22min%22:20,%22max%22:20}},%22corrupted%22:{{%22option%22:%22true%22}}}}}}}}}}}}",
                           target="_blank", className="me-2"),
                    html.A("🔍 L6 Q20",
                           href=f"https://www.pathofexile.com/trade/search/{calculator.api.league}?q={{%22query%22:{{%22status%22:{{%22option%22:%22online%22}},%22type%22:%22{gem_name}%22,%22filters%22:{{%22misc_filters%22:{{%22filters%22:{{%22gem_level%22:{{%22min%22:6,%22max%22:6}},%22quality%22:{{%22min%22:20,%22max%22:20}},%22corrupted%22:{{%22option%22:%22true%22}}}}}}}}}}}}",
                           target="_blank")
                ], width=6)
            ], className="mt-2")
        ])
    ], color="dark", outline=True)
    
    return trade_card

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))  # ← Get PORT from environment
    app.run_server(host='0.0.0.0', port=port, debug=False)
