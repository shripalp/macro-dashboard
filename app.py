import streamlit as st
from fredapi import Fred
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
import os

st.set_page_config(page_title="Everyday Macro Copilot", layout="wide", initial_sidebar_state="expanded")

# 1. API Initialization
FRED_API_KEY = st.secrets.get("FRED_API_KEY", os.environ.get("FRED_API_KEY", "YOUR_FRED_API_KEY"))
fred = Fred(api_key=FRED_API_KEY)

@st.cache_data(ttl=21600)  # Caches for 6 hours
def load_market_data():
    start_date = (datetime.now() - timedelta(days=730)).strftime('%Y-%m-%d')
    
    # FRED Macro Series
    walcl = fred.get_series('WALCL')       # Fed Total Assets
    tga = fred.get_series('WTREGEN')       # Treasury General Account
    rrp = fred.get_series('RRPONTSYD')     # Reverse Repo Facility
    real_rate = fred.get_series('DFII10')  # 10Y Real TIPS Yield
    yield_curve = fred.get_series('T10Y2Y')# Yield Curve 10Y-2Y
    
    df_macro = pd.DataFrame({
        'Fed_Assets': walcl,
        'TGA': tga,
        'RRP': rrp,
        'Real_Rate': real_rate,
        'Yield_Curve': yield_curve
    }).dropna()
    
    # Net Liquidity in Trillions
    df_macro['Net_Liquidity'] = (df_macro['Fed_Assets'] - (df_macro['TGA'] + df_macro['RRP'])) / 1_000_000
    
    # Asset Prices (Daily)
    tickers = ['BTC-USD', 'GLD', 'USO', 'SPY', 'BIL']
    prices = yf.download(tickers, start=start_date)['Close']
    
    merged = pd.concat([df_macro, prices], axis=1).ffill().dropna()
    return merged

@st.cache_data(ttl=60)
def load_live_prices():
    """Fetch near-real-time prices and the previous close for dashboard cards."""
    symbols = {
        'Gold': 'GC=F',
        'Oil': 'CL=F',
        'Bitcoin': 'BTC-USD',
        'QQQ': 'QQQ',
        'SPY': 'SPY',
    }
    quotes = {}

    for name, symbol in symbols.items():
        ticker = yf.Ticker(symbol)
        intraday = ticker.history(period='1d', interval='1m', auto_adjust=False)
        daily = ticker.history(period='5d', interval='1d', auto_adjust=False)

        if intraday.empty or daily.empty:
            raise ValueError(f"No current price available for {name} ({symbol})")

        current_price = float(intraday['Close'].dropna().iloc[-1])
        daily_closes = daily['Close'].dropna()
        previous_close = float(daily_closes.iloc[-2] if len(daily_closes) > 1 else daily_closes.iloc[-1])
        change_pct = ((current_price - previous_close) / previous_close) * 100
        quotes[name] = {'price': current_price, 'change_pct': change_pct}

    return quotes

try:
    data = load_market_data()
    latest = data.iloc[-1]
    prev_30d = data.iloc[-30]
    
    # Rate of Change / Metrics
    liq_change_30d = ((latest['Net_Liquidity'] - prev_30d['Net_Liquidity']) / prev_30d['Net_Liquidity']) * 100
    real_rate_change = latest['Real_Rate'] - prev_30d['Real_Rate']
    current_yc = latest['Yield_Curve']
    
    st.title("Shripal's Macro Copilot: Everyday Market Regime")
    st.caption("A layman-friendly engine translating Federal Reserve and Treasury data into clear allocation decisions.")
    
    # Dynamic Regime Logic
    st.markdown("---")
    st.subheader("Today's Weather Report for Your Capital")
    
    if current_yc < -0.1:
        regime_title = "Defensive / Recession Warning"
        regime_desc = "The bond yield curve is inverted. Lending is tight, and economic risk is elevated."
        best_asset = "Safe Haven Cash & Short-Term Bills (BIL / Ultra-Short Treasuries)"
        badge_color = "🔴 High Caution"
    elif liq_change_30d > 0.5:
        regime_title = "Liquidity Tide Rising (Risk-On)"
        regime_desc = "The U.S. financial system is expanding cash reserves. Money is actively flowing outward seeking returns."
        best_asset = "High-Growth & Risk Assets: Bitcoin (BTC) & Equities (SPY / QQQ)"
        badge_color = "🟢 Full Green Light"
    elif latest['Real_Rate'] < 1.6 and real_rate_change < 0:
        regime_title = "Monetary Debasement / Real Yield Erosion"
        regime_desc = "Holding pure cash in real terms is losing value. Capital is protecting purchasing power."
        best_asset = "Store of Value: Gold (GLD) & Hard Assets"
        badge_color = "🟡 Inflation Hedge"
    else:
        regime_title = "Neutral / Transition Phase"
        regime_desc = "Liquidity is flat. Markets are driven by specific sector fundamentals rather than a broad monetary tide."
        best_asset = "Balanced Stance: Energy (USO), High Dividend Stocks, Balanced Index"
        badge_color = "⚪ Neutral"

    col_a, col_b, col_c = st.columns([1, 1.5, 1])
    col_a.metric("Current Regime", badge_color, regime_title)
    col_b.metric("Favored Asset Class", best_asset)
    col_c.metric("30-Day Liquidity Shift", f"{liq_change_30d:+.2f}%", delta_color="normal")
    
    st.info(f"**Actionable Takeaway:** {regime_desc}")

    # Near-real-time market prices
    st.markdown("---")
    st.subheader("Live Market Prices")
    live_prices = load_live_prices()
    price_columns = st.columns(5)
    price_formats = {
        'Gold': '${:,.2f}',
        'Oil': '${:,.2f}',
        'Bitcoin': '${:,.0f}',
        'QQQ': '${:,.2f}',
        'SPY': '${:,.2f}',
    }

    for column, name in zip(price_columns, price_formats):
        quote = live_prices[name]
        column.metric(
            label=name,
            value=price_formats[name].format(quote['price']),
            delta=f"{quote['change_pct']:+.2f}% vs previous close",
        )

    st.caption("Near-real-time Yahoo Finance quotes; exchange delays may apply. Gold and oil use front-month futures.")
    
    # 4 Dial Summary Cards
    st.markdown("---")
    st.subheader("The 4 Core Gauges")
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        label="Net US Liquidity", 
        value=f"${latest['Net_Liquidity']:.2f} T", 
        delta=f"{liq_change_30d:+.2f}% (30d)",
        help="Fed Assets minus Treasury Cash & Reverse Repo. Rising = Fuel for Crypto & Stocks."
    )
    c2.metric(
        label="10Y Real TIPS Rate", 
        value=f"{latest['Real_Rate']:.2f}%", 
        delta=f"{real_rate_change:+.2f}% (30d)",
        delta_color="inverse",
        help="Real return above inflation. Dropping real rates trigger Gold rallies."
    )
    c3.metric(
        label="Yield Curve (10Y - 2Y)", 
        value=f"{latest['Yield_Curve']:.2f}%", 
        delta="Inverted" if current_yc < 0 else "Normal",
        delta_color="normal" if current_yc >= 0 else "inverse",
        help="Negative indicates recession risks within 6-18 months."
    )
    c4.metric(
        label="Bitcoin Price (USD)", 
        value=f"${latest['BTC-USD']:,.0f}", 
        delta=f"{((latest['BTC-USD'] - prev_30d['BTC-USD']) / prev_30d['BTC-USD']) * 100:+.2f}% (30d)"
    )

    # Interactive Chart
    st.markdown("---")
    st.subheader("Historical Context: Liquidity vs. Bitcoin & Gold")
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=data.index, y=data['Net_Liquidity'], name="Net US Liquidity ($T)", line=dict(color="#00FFA3", width=2)))
    fig.add_trace(go.Scatter(x=data.index, y=data['BTC-USD'], name="Bitcoin Price ($)", line=dict(color="#F7931A", width=2), yaxis="y2"))
    fig.add_trace(go.Scatter(x=data.index, y=data['GLD'], name="Gold ETF ($)", line=dict(color="#FFD700", width=1.5, dash='dot'), yaxis="y3"))
    
    fig.update_layout(
        template="plotly_dark",
        height=500,
        hovermode="x unified",
        yaxis=dict(title="Net Liquidity ($T)", side="left"),
        yaxis2=dict(title="Bitcoin ($)", overlaying="y", side="right", type="log"),
        yaxis3=dict(title="Gold ETF ($)", overlaying="y", side="right", showgrid=False, anchor="free", position=0.98),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    st.plotly_chart(fig, use_container_width=True)

except Exception as e:
    st.error(f"Error fetching live indicators: {e}")
