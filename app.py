import streamlit as st
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta, timezone
import warnings
warnings.filterwarnings('ignore')

# ── Page Config ──
st.set_page_config(
    page_title="NWVIN Strategy Lab Pro",
    page_icon="🛡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── Custom CSS ──
st.markdown("""
<style>
    .main { background-color: #04080f; }
    .stApp { background-color: #04080f; }
    
    /* Metric cards */
    [data-testid="metric-container"] {
        background: #0c1525;
        border: 1px solid #1a3050;
        border-radius: 10px;
        padding: 12px;
    }
    [data-testid="metric-container"] label { color: #4a6a8a !important; font-size: 11px !important; }
    [data-testid="metric-container"] [data-testid="metric-value"] { color: #00cfff !important; }
    
    /* Sidebar */
    [data-testid="stSidebar"] { background-color: #0c1525; border-right: 1px solid #1a3050; }
    [data-testid="stSidebar"] label { color: #4a6a8a !important; }
    
    /* Headers */
    h1, h2, h3 { color: #00cfff !important; font-family: 'Courier New', monospace; }
    
    /* Buttons */
    .stButton > button {
        background: linear-gradient(135deg, #00cfff, #0055ff);
        color: #000; font-weight: 700; border: none;
        border-radius: 7px; letter-spacing: 1px;
    }
    .stButton > button:hover { box-shadow: 0 0 20px rgba(0,207,255,.4); }
    
    /* Tables */
    .stDataFrame { background: #0c1525; }
    
    /* Signal boxes */
    .buy-signal {
        background: rgba(0,229,160,.1); border: 1px solid rgba(0,229,160,.3);
        border-radius: 10px; padding: 16px; text-align: center;
    }
    .sell-signal {
        background: rgba(255,61,107,.1); border: 1px solid rgba(255,61,107,.3);
        border-radius: 10px; padding: 16px; text-align: center;
    }
    .side-signal {
        background: rgba(74,106,138,.1); border: 1px solid rgba(74,106,138,.3);
        border-radius: 10px; padding: 16px; text-align: center;
    }
    .combined-strong {
        background: rgba(0,229,160,.08); border: 2px solid rgba(0,229,160,.4);
        border-radius: 12px; padding: 20px; text-align: center;
    }
    .combined-strong-sell {
        background: rgba(255,61,107,.08); border: 2px solid rgba(255,61,107,.4);
        border-radius: 12px; padding: 20px; text-align: center;
    }
    .combined-warn {
        background: rgba(255,208,0,.08); border: 2px solid rgba(255,208,0,.4);
        border-radius: 12px; padding: 20px; text-align: center;
    }
    .combined-no {
        background: rgba(74,106,138,.08); border: 2px solid rgba(74,106,138,.3);
        border-radius: 12px; padding: 20px; text-align: center;
    }
    div[data-testid="stTabs"] button {
        color: #4a6a8a; font-family: 'Courier New', monospace;
        font-size: 12px; letter-spacing: 1px;
    }
    div[data-testid="stTabs"] button[aria-selected="true"] {
        color: #00cfff; border-bottom: 2px solid #00cfff;
    }
    .footer-note {
        background: rgba(255,61,107,.08); border: 1px solid rgba(255,61,107,.2);
        border-radius: 8px; padding: 12px; font-size: 12px; color: #ff3d6b;
        font-family: 'Courier New', monospace; margin-top: 16px;
    }
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════
#  SESSION STATE
# ══════════════════════════════════════
if 'access_token' not in st.session_state:
    st.session_state.access_token = ''
if 'chain_data' not in st.session_state:
    st.session_state.chain_data = None
if 'oi_signal' not in st.session_state:
    st.session_state.oi_signal = '—'
if 'trade_log' not in st.session_state:
    st.session_state.trade_log = []
if 'ema_signal' not in st.session_state:
    st.session_state.ema_signal = '⚪ SIDEWAYS'

# ══════════════════════════════════════
#  UPSTOX API HELPERS
# ══════════════════════════════════════
INSTR = {
    'NIFTY 50':     'NSE_INDEX|Nifty 50',
    'BANKNIFTY':    'NSE_INDEX|Nifty Bank',
    'FINNIFTY':     'NSE_INDEX|Nifty Fin Service',
    'MIDCPNIFTY':   'NSE_INDEX|NIFTY MID SELECT',
    'SENSEX':       'BSE_INDEX|SENSEX',
    'BANKEX':       'BSE_INDEX|BANKEX',
}
STEP = {'NIFTY 50':50,'BANKNIFTY':100,'FINNIFTY':50,'MIDCPNIFTY':25,'SENSEX':100,'BANKEX':100}

def upstox_get(url, token):
    headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json'}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        return r.json()
    except Exception as e:
        return {'status': 'error', 'message': str(e)}

def get_expiries(symbol, token):
    key = INSTR.get(symbol, '')
    url = f'https://api.upstox.com/v2/option/contract?instrument_key={requests.utils.quote(key)}'
    r = upstox_get(url, token)
    if r.get('status') == 'success' and r.get('data'):
        return sorted(list(set(d['expiry'] for d in r['data'])))
    return []

def get_option_chain(symbol, expiry, token):
    key = INSTR.get(symbol, '')
    url = f'https://api.upstox.com/v2/option/chain?instrument_key={requests.utils.quote(key)}&expiry_date={expiry}'
    r = upstox_get(url, token)
    if r.get('status') == 'success':
        return r.get('data', [])
    return []

def get_historical_data(symbol, interval, token, days=5):
    """Fetch real OHLC from Upstox - tries intraday endpoint first, then range"""
    key = INSTR.get(symbol, '')
    # Map display names to Upstox valid intervals
    imap = {
        '5 Min':  '1minute',   # fetch 1min, resample to 5min
        '10 Min': '1minute',   # fetch 1min, resample to 10min
        '15 Min': '1minute',   # fetch 1min, resample to 15min
        '30 Min': '30minute',  # direct 30min
        '1 Hour': 'day',       # daily candles
    }
    resample_map = {
        '5 Min':'5min', '10 Min':'10min', '15 Min':'15min',
        '30 Min':None, '1 Hour':None
    }
    upstox_interval = imap.get(interval, '30minute')
    resample_to = resample_map.get(interval, None)

    ist_now   = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    to_date   = ist_now.strftime('%Y-%m-%d')
    # Map lookback string to days
    lb_map = {'1 Day':1, '5 Days':5, '1 Month':30}
    if isinstance(days, str):
        days = lb_map.get(days, 5)
    from_date = (ist_now - timedelta(days=days)).strftime('%Y-%m-%d')
    encoded   = requests.utils.quote(key, safe='')

    # Try 1: intraday (today only)
    # Intraday endpoint only supports 1minute; use range endpoint for others
    url1 = f'https://api.upstox.com/v2/historical-candle/intraday/{encoded}/1minute'
    r = upstox_get(url1, token)

    # Try 2: historical range
    if not (r.get('status') == 'success' and r.get('data', {}).get('candles')):
        url2 = f'https://api.upstox.com/v2/historical-candle/{encoded}/{upstox_interval}/{to_date}/{from_date}'
        r = upstox_get(url2, token)

    if r.get('status') == 'success' and r.get('data', {}).get('candles'):
        candles = r['data']['candles']
        df = pd.DataFrame(candles, columns=['timestamp','open','high','low','close','volume','oi'])
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.set_index('timestamp').sort_index()
        df = df.between_time('09:15','15:30')
        # Resample 1min data to desired timeframe
        if resample_to:
            df = df.resample(resample_to, closed='left', label='left').agg({
                'open':'first','high':'max','low':'min',
                'close':'last','volume':'sum','oi':'last'
            }).dropna()
        return df, None
    return pd.DataFrame(), r

def fmt_k(n):
    if n is None or n == 0: return '—'
    if n >= 1e7: return f'{n/1e7:.2f}Cr'
    if n >= 1e5: return f'{n/1e5:.2f}L'
    if n >= 1e3: return f'{n/1e3:.1f}K'
    return str(int(n))

# ══════════════════════════════════════
#  EMA + STRATEGY ENGINE
# ══════════════════════════════════════
def calc_ema(series, length):
    return series.ewm(span=length, adjust=False).mean()

def run_strategy(df, fast_len, fast_src, slow_len, slow_src, buffer, max_loss):
    src_map = {'Open':'open','High':'high','Low':'low','Close':'close'}
    f_col = src_map.get(fast_src, 'open')
    s_col = src_map.get(slow_src, 'close')
    
    df = df.copy()
    df['fast_ema'] = calc_ema(df[f_col], fast_len)
    df['slow_ema'] = calc_ema(df[s_col], slow_len)
    df['diff']     = df['fast_ema'] - df['slow_ema']
    
    def get_signal(row):
        if pd.isna(row['diff']): return '⚪ SIDEWAYS'
        if row['diff'] >  buffer: return '🟢 BUY'
        if row['diff'] < -buffer: return '🔴 SELL'
        return '⚪ SIDEWAYS'
    
    df['signal'] = df.apply(get_signal, axis=1)
    df.dropna(inplace=True)
    
    trades = []
    active, e_price, e_time = None, 0, None
    
    for idx, row in df.iterrows():
        sig   = row['signal']
        price = row['close']
        
        if active:
            pnl = (price - e_price) if active == '🟢 BUY' else (e_price - price)
            if pnl <= -max_loss or sig == '⚪ SIDEWAYS' or sig != active:
                final_pnl = max(pnl, -max_loss)
                sl_hit    = pnl <= -max_loss
                trades.append({
                    'Date':       idx.strftime('%d/%m/%Y'),
                    'Time Entry': e_time.strftime('%H:%M'),
                    'Time Exit':  idx.strftime('%H:%M'),
                    'Trend':      active + (' 🛑SL' if sl_hit else ''),
                    'Entry ₹':    round(e_price, 2),
                    'Exit ₹':     round(price, 2),
                    'Points':     round(final_pnl, 2),
                    'SL Hit':     sl_hit
                })
                active = None
        
        if not active and sig != '⚪ SIDEWAYS':
            active, e_price, e_time = sig, price, idx
    
    return trades, df

def calc_max_pain(chain):
    strikes = [d['strike_price'] for d in chain]
    best, mn = strikes[0], float('inf')
    for t in strikes:
        pain = sum(
            max(0, r['strike_price'] - t) * (r.get('call_options',{}).get('market_data',{}).get('oi',0) or 0) +
            max(0, t - r['strike_price']) * (r.get('put_options',{}).get('market_data',{}).get('oi',0) or 0)
            for r in chain
        )
        if pain < mn:
            mn, best = pain, t
    return best

# ══════════════════════════════════════
#  SIDEBAR
# ══════════════════════════════════════
with st.sidebar:
    st.markdown("## 🛡 NWVIN PRO")
    st.markdown("---")
    
    # Token
    st.markdown("### 🔑 Upstox Token")
    token_input = st.text_area("Access Token", value=st.session_state.access_token,
                                placeholder="Paste your Upstox access_token here...",
                                height=80, key='token_area')
    if st.button("✅ Connect Upstox"):
        st.session_state.access_token = token_input.strip()
        st.success("Token saved!")
    
    if st.session_state.access_token:
        st.success("🟢 Token Active")
    else:
        st.warning("⚠️ Token not set")
    
    st.markdown("---")
    
    # Symbol + Expiry
    st.markdown("### 📊 Option Chain")
    oc_symbol = st.selectbox("Index", list(INSTR.keys()), key='oc_sym')
    
    expiries = []
    if st.session_state.access_token:
        expiries = get_expiries(oc_symbol, st.session_state.access_token)
    
    oc_expiry = st.selectbox("Expiry", expiries if expiries else ['Set token first'], key='oc_exp')
    strike_range = st.selectbox("Strikes ± ATM", ['±10','±15','±20','All'], index=1)
    show_greeks  = st.checkbox("Show Greeks", value=False)
    
    if st.button("📡 Fetch Option Chain", type="primary"):
        if st.session_state.access_token and oc_expiry != 'Set token first':
            with st.spinner("Fetching live option chain..."):
                st.session_state.chain_data = get_option_chain(oc_symbol, oc_expiry, st.session_state.access_token)
            if st.session_state.chain_data:
                st.success(f"✓ {len(st.session_state.chain_data)} strikes loaded!")
            else:
                st.error("Failed to fetch. Check token.")
        else:
            st.error("Set token first!")
    
    st.markdown("---")
    
    # Strategy params
    st.markdown("### ⚡ Strategy Lab")
    strat_symbol = st.selectbox("Symbol", list(INSTR.keys()), key='strat_sym')
    tf           = st.selectbox("Timeframe", ['5 Min','10 Min','15 Min','30 Min','1 Hour'], index=2)
    lookback     = st.selectbox("Lookback", ['1 Day','5 Days','1 Month'], index=1)
    
    st.markdown("**Fast EMA**")
    fast_len = st.number_input("Fast Length", value=9, min_value=2, max_value=200, help="NWVIN default: 9")
    fast_src = st.selectbox("Fast Source", ['Open','High','Low','Close'], index=0)
    
    st.markdown("**Slow EMA**")
    slow_len = st.number_input("Slow Length", value=21, min_value=2, max_value=200, help="NWVIN default: 21")
    slow_src = st.selectbox("Slow Source", ['Open','High','Low','Close'], index=3)
    
    buffer_pts = st.number_input("Buffer Points (larger = fewer trades)", value=5.0, step=0.5, min_value=0.0)
    max_loss   = st.number_input("Max Loss SL (pts)", value=20.0, step=5.0, min_value=1.0)
    
    run_btn = st.button("🚀 Run Backtest", type="primary")
    
    st.markdown("---")
    st.markdown("""
    <div style='font-size:10px;color:#4a6a8a;font-family:monospace;'>
    ⚠️ DISCLAIMER<br>
    This is for analysis only.<br>
    No trade is executed.<br>
    Not financial advice.
    </div>
    """, unsafe_allow_html=True)

# ══════════════════════════════════════
#  MAIN HEADER
# ══════════════════════════════════════
col_h1, col_h2, col_h3 = st.columns([3,1,1])
with col_h1:
    st.markdown("# 🛡 NWVIN Strategy Lab Pro")
    st.markdown("`Upstox Live OI · EMA Signal Engine · Confluence System · Read-Only`")
with col_h2:
    now = ( datetime.now(timezone.utc) + timedelta(hours=5, minutes=30) ).strftime('%H:%M:%S')
    st.metric("🕐 Time", now)
with col_h3:
    sig = st.session_state.ema_signal
    color = "🟢" if "BUY" in sig else "🔴" if "SELL" in sig else "⚪"
    st.metric("Current Signal", f"{color} {sig.replace('🟢 ','').replace('🔴 ','').replace('⚪ ','')}")

st.markdown("---")

# ══════════════════════════════════════
#  TABS
# ══════════════════════════════════════
tab1, tab2, tab3, tab4 = st.tabs(["📊 Option Chain", "⚡ Strategy Lab", "🎯 Combined Signal", "📑 Trade Log"])

# ════════════════════════════════
#  TAB 1 — OPTION CHAIN
# ════════════════════════════════
with tab1:
    chain = st.session_state.chain_data
    
    if not chain:
        st.info("👈 Set token + select expiry → click **Fetch Option Chain** in sidebar")
    else:
        # Stats
        spot     = chain[0].get('underlying_spot_price', 0)
        call_oi  = sum(d.get('call_options',{}).get('market_data',{}).get('oi',0) or 0 for d in chain)
        put_oi   = sum(d.get('put_options',{}).get('market_data',{}).get('oi',0) or 0 for d in chain)
        pcr      = put_oi / call_oi if call_oi > 0 else 0
        max_pain = calc_max_pain(chain)
        step     = STEP.get(oc_symbol, 50)
        atm      = round(spot / step) * step
        atm_row  = next((d for d in chain if d['strike_price'] == atm), None)
        iv_skew  = 0
        if atm_row:
            piv = atm_row.get('put_options',{}).get('option_greeks',{}).get('iv',0) or 0
            civ = atm_row.get('call_options',{}).get('option_greeks',{}).get('iv',0) or 0
            iv_skew = piv - civ
        
        # PCR Signal
        oi_sig = '🟢 BULLISH' if pcr > 1.3 else '🔴 BEARISH' if pcr < 0.7 else '🟡 NEUTRAL'
        st.session_state.oi_signal = oi_sig
        
        pcr_delta = f"{'🟢 Bullish' if pcr > 1.3 else '🔴 Bearish' if pcr < 0.7 else '🟡 Neutral'}"
        mp_delta  = f"{'+' if max_pain >= spot else ''}{int(max_pain - spot)} from spot"
        
        c1,c2,c3,c4,c5,c6 = st.columns(6)
        c1.metric("SPOT PRICE",      f"{spot:,.1f}")
        c2.metric("PCR (OI)",         f"{pcr:.2f}",       delta=pcr_delta)
        c3.metric("MAX PAIN",         f"{max_pain:,.0f}", delta=mp_delta)
        c4.metric("TOTAL CALL OI",    fmt_k(call_oi))
        c5.metric("TOTAL PUT OI",     fmt_k(put_oi))
        c6.metric("IV SKEW (ATM)",    f"{iv_skew:+.2f}%")
        
        # OI Signal banner
        if pcr > 1.3:
            st.markdown('<div class="buy-signal"><h3>🟢 OI SIGNAL: BULLISH</h3><p>High PCR — Put writers defending support. Bullish bias.</p></div>', unsafe_allow_html=True)
        elif pcr < 0.7:
            st.markdown('<div class="sell-signal"><h3>🔴 OI SIGNAL: BEARISH</h3><p>Low PCR — Call writers capping upside. Bearish bias.</p></div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="side-signal"><h3>🟡 OI SIGNAL: NEUTRAL</h3><p>PCR in neutral zone. No strong directional bias.</p></div>', unsafe_allow_html=True)
        
        st.markdown("---")
        
        # Filters
        with st.expander("⚡ SMART FILTERS", expanded=False):
            fc1,fc2,fc3 = st.columns(3)
            with fc1:
                oi_chg_filter = st.slider("OI Change % min", 0, 200, 0)
                vol_filter    = st.number_input("Min Volume", 0, 10000000, 0, step=10000)
            with fc2:
                iv_min = st.number_input("IV Min %", 0.0, 200.0, 0.0)
                iv_max = st.number_input("IV Max %", 0.0, 200.0, 200.0)
            with fc3:
                sig_filters = st.multiselect("Signal Filters",
                    ['Vol Spike','OI Build','OI Unwind','High IV (>20)','Long CE','Short PE'])
        
        # Build table
        rows = sorted(chain, key=lambda x: x['strike_price'])
        
        # Strike range filter
        rng_map = {'±10':10,'±15':15,'±20':20,'All':9999}
        rng = rng_map.get(strike_range, 15)
        if rng < 9999:
            rows = [r for r in rows if abs(r['strike_price'] - atm) <= rng * step]
        
        table_rows = []
        for d in rows:
            ce = d.get('call_options',{}).get('market_data',{}) or {}
            pe = d.get('put_options',{}).get('market_data',{}) or {}
            cg = d.get('call_options',{}).get('option_greeks',{}) or {}
            pg = d.get('put_options',{}).get('option_greeks',{}) or {}
            
            ce_oi_chg = ((ce.get('oi',0) - ce.get('prev_oi',0)) / ce.get('prev_oi',1) * 100) if ce.get('prev_oi',0) > 0 else 0
            pe_oi_chg = ((pe.get('oi',0) - pe.get('prev_oi',0)) / pe.get('prev_oi',1) * 100) if pe.get('prev_oi',0) > 0 else 0
            ce_vr = ce.get('volume',0) / ce.get('oi',1) * 100 if ce.get('oi',0) > 0 else 0
            pe_vr = pe.get('volume',0) / pe.get('oi',1) * 100 if pe.get('oi',0) > 0 else 0
            
            # Apply filters
            if oi_chg_filter > 0 and abs(ce_oi_chg) < oi_chg_filter and abs(pe_oi_chg) < oi_chg_filter:
                continue
            if vol_filter > 0 and (ce.get('volume',0) or 0) < vol_filter and (pe.get('volume',0) or 0) < vol_filter:
                continue
            civ = cg.get('iv',0) or 0
            piv = pg.get('iv',0) or 0
            if iv_min > 0 or iv_max < 200:
                if (civ < iv_min or civ > iv_max) and (piv < iv_min or piv > iv_max):
                    continue
            if 'Vol Spike' in sig_filters:
                avg = ((ce.get('oi',0) or 0) + (pe.get('oi',0) or 0)) * 0.008
                if (ce.get('volume',0) or 0) < avg and (pe.get('volume',0) or 0) < avg:
                    continue
            if 'OI Build' in sig_filters:
                if ce_oi_chg <= 0 and pe_oi_chg <= 0: continue
            if 'OI Unwind' in sig_filters:
                if ce_oi_chg >= 0 and pe_oi_chg >= 0: continue
            if 'High IV (>20)' in sig_filters:
                if civ < 20 and piv < 20: continue
            
            is_atm = d['strike_price'] == atm
            strike_label = f"{'★ ' if is_atm else ''}{int(d['strike_price'])}{' ◄ATM' if is_atm else ''}"
            
            ce_oi_str  = fmt_k(ce.get('oi',0)) + (f" (+{ce_oi_chg:.0f}%)" if ce_oi_chg > 5 else f" ({ce_oi_chg:.0f}%)" if ce_oi_chg < -5 else "")
            pe_oi_str  = fmt_k(pe.get('oi',0)) + (f" (+{pe_oi_chg:.0f}%)" if pe_oi_chg > 5 else f" ({pe_oi_chg:.0f}%)" if pe_oi_chg < -5 else "")
            ce_vol_str = fmt_k(ce.get('volume',0)) + (" 🔥SPIKE" if ce_vr > 12 else "")
            pe_vol_str = fmt_k(pe.get('volume',0)) + (" 🔥SPIKE" if pe_vr > 12 else "")
            
            row = {
                'C IV%':    f"{civ:.1f}%" + (" ⚡" if civ > 25 else ""),
                'C Delta':  f"{cg.get('delta',0):.3f}" if cg.get('delta') else '—',
                'C Vol':    ce_vol_str,
                'C OI':     ce_oi_str,
                'C LTP':    f"{ce.get('ltp',0):.2f}" if ce.get('ltp') else '—',
                '── STRIKE ──': strike_label,
                'P LTP':    f"{pe.get('ltp',0):.2f}" if pe.get('ltp') else '—',
                'P OI':     pe_oi_str,
                'P Vol':    pe_vol_str,
                'P Delta':  f"{pg.get('delta',0):.3f}" if pg.get('delta') else '—',
                'P IV%':    f"{piv:.1f}%" + (" ⚡" if piv > 25 else ""),
            }
            if show_greeks:
                row['C θ']   = f"{cg.get('theta',0):.2f}" if cg.get('theta') else '—'
                row['C γ']   = f"{cg.get('gamma',0):.4f}" if cg.get('gamma') else '—'
                row['C ν']   = f"{cg.get('vega',0):.2f}" if cg.get('vega') else '—'
                row['C PoP'] = f"{cg.get('pop',0):.1f}%" if cg.get('pop') else '—'
                row['P θ']   = f"{pg.get('theta',0):.2f}" if pg.get('theta') else '—'
                row['P ν']   = f"{pg.get('vega',0):.2f}" if pg.get('vega') else '—'
                row['P PoP'] = f"{pg.get('pop',0):.1f}%" if pg.get('pop') else '—'
            
            table_rows.append(row)
        
        if table_rows:
            df_table = pd.DataFrame(table_rows)
            st.markdown(f"**{len(table_rows)} strikes shown** | ATM: {atm:,} | Spot: {spot:,.1f}")
            
            def highlight_atm(row):
                strike_col = '── STRIKE ──'
                if '◄ATM' in str(row.get(strike_col,'')):
                    return ['background-color: rgba(0,207,255,0.1); font-weight: bold'] * len(row)
                return [''] * len(row)
            
            st.dataframe(
                df_table.style.apply(highlight_atm, axis=1),
                use_container_width=True, height=500
            )
        else:
            st.warning("No strikes match current filters.")

# ════════════════════════════════
#  TAB 2 — STRATEGY LAB
# ════════════════════════════════
with tab2:
    if run_btn:
        if not st.session_state.access_token:
            st.error("⚠️ Set Upstox token first in sidebar!")
        else:
            with st.spinner(f"📡 Fetching real {tf} OHLC data from Upstox..."):
                df_raw, api_err = get_historical_data(strat_symbol, tf, st.session_state.access_token, days=lookback)
            
            if df_raw.empty:
                st.error("❌ No data returned. Check token or try different timeframe.")
                if api_err:
                    st.code(str(api_err), language='json')
                st.info("💡 Tip: Upstox free account — intraday historical data may need market hours (9:15–3:30 IST) or try 1D timeframe.")
            else:
                st.success(f"✓ {len(df_raw)} candles loaded ({df_raw.index[0].strftime('%d/%m %H:%M')} → {df_raw.index[-1].strftime('%d/%m %H:%M')})")
                
                trades, df_sig = run_strategy(df_raw, fast_len, fast_src, slow_len, slow_src, buffer_pts, max_loss)
                st.session_state.trade_log = trades
                
                last_sig = df_sig['signal'].iloc[-1] if not df_sig.empty else '⚪ SIDEWAYS'
                st.session_state.ema_signal = last_sig
                
                # Stats
                nets  = [t['Points'] for t in trades]
                net   = sum(nets)
                wins  = sum(1 for n in nets if n > 0)
                sl_h  = sum(1 for t in trades if t['SL Hit'])
                wr    = wins/len(trades)*100 if trades else 0
                avg   = net/len(trades) if trades else 0
                
                c1,c2,c3,c4,c5,c6 = st.columns(6)
                c1.metric("Current Signal",  last_sig)
                c2.metric("Total Trades",    len(trades))
                c3.metric("Net Points",      f"{net:+.1f}", delta=f"{net:+.1f} pts")
                c4.metric("Win Rate",        f"{wr:.0f}%",  delta="Good" if wr >= 50 else "Low")
                c5.metric("SL Hits 🛑",      sl_h)
                c6.metric("Avg Pts/Trade",   f"{avg:+.1f}")
                
                # Signal Banner
                cls = 'buy-signal' if 'BUY' in last_sig else 'sell-signal' if 'SELL' in last_sig else 'side-signal'
                lf  = df_sig['fast_ema'].iloc[-1]
                ls  = df_sig['slow_ema'].iloc[-1]
                lc  = df_sig['close'].iloc[-1]
                st.markdown(f"""
                <div class="{cls}">
                  <h2>{last_sig}</h2>
                  <p>Fast EMA: <b>{lf:.1f}</b> &nbsp;|&nbsp; Slow EMA: <b>{ls:.1f}</b> &nbsp;|&nbsp; Price: <b>{lc:.1f}</b></p>
                </div>""", unsafe_allow_html=True)
                
                st.markdown("---")
                
                # Charts
                import streamlit as st_chart
                ch1, ch2 = st.columns(2)
                with ch1:
                    st.markdown("#### 📈 Price + EMA Lines")
                    chart_df = pd.DataFrame({
                        'Price':    df_sig['close'],
                        'Fast EMA': df_sig['fast_ema'],
                        'Slow EMA': df_sig['slow_ema'],
                    }).tail(100)
                    st.line_chart(chart_df, use_container_width=True)
                with ch2:
                    st.markdown("#### 📊 EMA Difference (Signal Zone)")
                    diff_df = pd.DataFrame({'EMA Diff': df_sig['diff']}).tail(100)
                    st.bar_chart(diff_df, use_container_width=True)
    else:
        st.info("👈 Configure parameters in sidebar → click **🚀 Run Backtest**")
        st.markdown("""
        **Logic:**
        - `Fast EMA > Slow EMA + Buffer` → 🟢 **BUY**
        - `Slow EMA > Fast EMA + Buffer` → 🔴 **SELL**  
        - `|diff| < Buffer` → ⚪ **SIDEWAYS** (no trade)
        - Exit on: SL hit / Sideways / Trend flip
        """)

# ════════════════════════════════
#  TAB 3 — COMBINED SIGNAL
# ════════════════════════════════
with tab3:
    ema = st.session_state.ema_signal
    oi  = st.session_state.oi_signal
    
    c1, c2, c3, c4 = st.columns(4)
    ema_col = "🟢" if "BUY" in ema else "🔴" if "SELL" in ema else "⚪"
    oi_col  = "🟢" if "BULL" in oi else "🔴" if "BEAR" in oi else "🟡"
    c1.metric("EMA Signal",    f"{ema_col} {ema}")
    c2.metric("OI Signal",     f"{oi_col} {oi}")
    
    # Combined logic
    if "BUY" in ema and "BULL" in oi:
        final, conf, css = "✅ STRONG BUY CE", "HIGH 🔥", "combined-strong"
    elif "SELL" in ema and "BEAR" in oi:
        final, conf, css = "✅ STRONG BUY PE", "HIGH 🔥", "combined-strong-sell"
    elif "BUY" in ema and "BEAR" in oi:
        final, conf, css = "⚠️ CONFLICTING — Wait", "MEDIUM", "combined-warn"
    elif "SELL" in ema and "BULL" in oi:
        final, conf, css = "⚠️ CONFLICTING — Wait", "MEDIUM", "combined-warn"
    elif "SIDEWAYS" in ema:
        final, conf, css = "🚫 NO TRADE — Sideways", "LOW", "combined-no"
    else:
        final, conf, css = "🔄 Run backtest + fetch OI", "—", "combined-no"
    
    c3.metric("Combined Action", final)
    c4.metric("Confidence",      conf)
    
    st.markdown(f'<div class="{css}"><h2>{final}</h2><p>EMA: <b>{ema}</b> &nbsp;|&nbsp; OI: <b>{oi}</b></p><p>Confidence: <b>{conf}</b></p></div>', unsafe_allow_html=True)
    
    st.markdown("---")
    st.markdown("#### 📋 Signal Confluence Matrix")
    matrix = pd.DataFrame([
        {'EMA Signal':'🟢 BUY',     'OI Signal':'🟢 Bullish OI', 'Action':'✅ STRONG BUY CE',    'Confidence':'HIGH 🔥'},
        {'EMA Signal':'🔴 SELL',    'OI Signal':'🔴 Bearish OI', 'Action':'✅ STRONG BUY PE',    'Confidence':'HIGH 🔥'},
        {'EMA Signal':'🟢 BUY',     'OI Signal':'🔴 Bearish OI', 'Action':'⚠️ CONFLICTING',      'Confidence':'MEDIUM'},
        {'EMA Signal':'🔴 SELL',    'OI Signal':'🟢 Bullish OI', 'Action':'⚠️ CONFLICTING',      'Confidence':'MEDIUM'},
        {'EMA Signal':'⚪ SIDEWAYS','OI Signal':'Any',           'Action':'🚫 NO TRADE',         'Confidence':'LOW'},
    ])
    st.dataframe(matrix, use_container_width=True, hide_index=True)
    
    st.markdown("""
    <div class="footer-note">
    ⚠️ IMPORTANT: Yeh sirf analysis tool hai. Koi bhi trade automatically execute nahi hoti.
    Sab signals sirf informational hain — financial advice nahi hai.
    </div>
    """, unsafe_allow_html=True)

# ════════════════════════════════
#  TAB 4 — TRADE LOG
# ════════════════════════════════
with tab4:
    trades = st.session_state.trade_log
    
    if not trades:
        st.info("Run backtest first to see trade log.")
    else:
        df_log = pd.DataFrame(trades)
        wins   = len(df_log[df_log['Points'] > 0])
        losses = len(df_log[df_log['Points'] <= 0])
        net    = df_log['Points'].sum()
        sl_h   = len(df_log[df_log['SL Hit'] == True])
        
        c1,c2,c3,c4 = st.columns(4)
        c1.metric("✅ Wins",   wins)
        c2.metric("❌ Losses", losses)
        c3.metric("📊 Net",    f"{net:+.1f} pts", delta=f"{net:+.1f}")
        c4.metric("🛑 SL Hits", sl_h)
        
        # Color styling
        display_cols = ['Date','Time Entry','Time Exit','Trend','Entry ₹','Exit ₹','Points','SL Hit']
        df_display = df_log[display_cols].copy()

        def color_rows(row):
            if row.get('SL Hit', False):
                return ['background-color: rgba(255,208,0,.08)'] * len(row)
            elif float(row.get('Points', 0)) > 0:
                return ['background-color: rgba(0,229,160,.05)'] * len(row)
            else:
                return ['background-color: rgba(255,61,107,.05)'] * len(row)

        st.dataframe(
            df_display.style.apply(color_rows, axis=1),
            use_container_width=True, height=500
        )
        
        # Export
        csv = df_log[display_cols].to_csv(index=False)
        st.download_button("⬇️ Export CSV", csv, "NWVIN_TradeLog.csv", "text/csv")
        
        # Summary chart
        st.markdown("#### 📈 Cumulative P&L")
        df_log['Cumulative'] = df_log['Points'].cumsum()
        st.line_chart(df_log.set_index('Date')['Cumulative'], use_container_width=True)
