import streamlit as st
from fredapi import Fred
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
import os

st.set_page_config(page_title="Everyday Macro Copilot", layout="wide", initial_sidebar_state="expanded")

# 1. API Initialization
FRED_API_KEY = os.environ.get("FRED_API_KEY")
if not FRED_API_KEY:
    try:
        FRED_API_KEY = st.secrets["FRED_API_KEY"]
    except (KeyError, FileNotFoundError):
        FRED_API_KEY = None

if not FRED_API_KEY:
    st.error("FRED_API_KEY is not configured. Add it to your environment or .streamlit/secrets.toml.")
    st.stop()

fred = Fred(api_key=FRED_API_KEY)

@st.cache_data(ttl=21600)  # Caches for 6 hours
def load_market_data():
    start_date = (datetime.now() - timedelta(days=730)).strftime('%Y-%m-%d')
    
    # FRED Macro Series
    walcl = fred.get_series('WALCL', observation_start=start_date)        # Fed Total Assets, $ millions
    tga = fred.get_series('WTREGEN', observation_start=start_date)        # Treasury General Account, $ millions
    rrp = fred.get_series('RRPONTSYD', observation_start=start_date)      # Reverse Repo Facility, $ billions
    real_rate = fred.get_series('DFII10', observation_start=start_date)   # 10Y Real TIPS Yield
    yield_curve = fred.get_series('T10Y2Y', observation_start=start_date) # Yield Curve 10Y-2Y
    dollar = fred.get_series('DTWEXBGS', observation_start=start_date)     # Broad US Dollar Index
    nfci = fred.get_series('NFCI', observation_start=start_date)           # Financial Conditions Index
    ecb_assets = fred.get_series('ECBASSETSW', observation_start=start_date) # ECB assets, EUR millions
    boj_assets = fred.get_series('JPNASSETS', observation_start=start_date)  # BOJ assets, 100 million yen
    eur_usd = fred.get_series('DEXUSEU', observation_start=start_date)       # US dollars per euro
    yen_usd = fred.get_series('DEXJPUS', observation_start=start_date)       # Yen per US dollar
    
    df_macro = pd.DataFrame({
        'Fed_Assets': walcl,
        'TGA': tga,
        'RRP': rrp,
        'Real_Rate': real_rate,
        'Yield_Curve': yield_curve,
        'Dollar_Index': dollar,
        'NFCI': nfci,
        'ECB_Assets': ecb_assets,
        'BOJ_Assets': boj_assets,
        'EUR_USD': eur_usd,
        'YEN_USD': yen_usd,
    }).sort_index().ffill().dropna()
    
    # Convert RRP from billions to millions before calculating liquidity in trillions.
    df_macro['Net_Liquidity'] = (
        df_macro['Fed_Assets'] - df_macro['TGA'] - (df_macro['RRP'] * 1_000)
    ) / 1_000_000

    # Fed + ECB + BOJ balance sheets converted to trillions of US dollars.
    df_macro['Global_Liquidity'] = (
        (df_macro['Fed_Assets'] / 1_000_000)
        + (df_macro['ECB_Assets'] * df_macro['EUR_USD'] / 1_000_000)
        + (df_macro['BOJ_Assets'] / (10_000 * df_macro['YEN_USD']))
    )
    
    # Asset Prices (Daily)
    tickers = ['BTC-USD', 'GLD', 'USO', 'SPY', 'QQQ', 'BIL']
    prices = yf.download(tickers, start=start_date, auto_adjust=False)['Close']
    
    merged = pd.concat([df_macro, prices], axis=1, sort=False).sort_index().ffill().dropna()
    return merged

@st.cache_data(ttl=60)
def load_live_prices():
    """Fetch the latest available price and its change from the prior close."""
    symbols = {
        'Gold': 'GC=F',
        'Oil': 'CL=F',
        'Bitcoin': 'BTC-USD',
        'QQQ': 'QQQ',
        'SPY': 'SPY',
    }
    quotes = {}

    for name, symbol in symbols.items():
        try:
            ticker = yf.Ticker(symbol)
            intraday = ticker.history(period='5d', interval='5m', auto_adjust=False)
            daily = ticker.history(period='5d', interval='1d', auto_adjust=False)
            daily_closes = daily['Close'].dropna() if not daily.empty else pd.Series(dtype=float)
            intraday_closes = intraday['Close'].dropna() if not intraday.empty else pd.Series(dtype=float)

            if not intraday_closes.empty:
                current_price = float(intraday_closes.iloc[-1])
                previous_close = float(daily_closes.iloc[-2] if len(daily_closes) > 1 else daily_closes.iloc[-1])
                source = 'intraday'
            elif not daily_closes.empty:
                current_price = float(daily_closes.iloc[-1])
                previous_close = float(daily_closes.iloc[-2] if len(daily_closes) > 1 else current_price)
                source = 'daily close'
            else:
                quotes[name] = None
                continue

            change_pct = ((current_price - previous_close) / previous_close) * 100
            quotes[name] = {
                'price': current_price,
                'change_pct': change_pct,
                'source': source,
            }
        except Exception:
            quotes[name] = None

    return quotes

try:
    data = load_market_data()
    latest = data.iloc[-1]
    four_weeks_ago = data.loc[data.index <= data.index[-1] - timedelta(days=28)].iloc[-1]
    thirteen_weeks_ago = data.loc[data.index <= data.index[-1] - timedelta(days=91)].iloc[-1]
    
    # Rate of Change / Metrics
    liq_change_30d = ((latest['Net_Liquidity'] - four_weeks_ago['Net_Liquidity']) / four_weeks_ago['Net_Liquidity']) * 100
    global_liq_change = (
        (latest['Global_Liquidity'] - thirteen_weeks_ago['Global_Liquidity'])
        / thirteen_weeks_ago['Global_Liquidity']
    ) * 100
    real_rate_change = latest['Real_Rate'] - four_weeks_ago['Real_Rate']
    current_yc = latest['Yield_Curve']
    btc_200d_average = data['BTC-USD'].tail(200).mean()

    # US and global liquidity split one point to avoid double-counting liquidity.
    btc_signals = [
        {
            'Factor': 'US net liquidity',
            'Score': 0.5 if latest['Net_Liquidity'] > four_weeks_ago['Net_Liquidity'] else -0.5,
            'Reading': f"{liq_change_30d:+.2f}% over 4 weeks",
            'Supportive when': 'Rising',
        },
        {
            'Factor': 'Global liquidity proxy',
            'Score': 0.5 if latest['Global_Liquidity'] > thirteen_weeks_ago['Global_Liquidity'] else -0.5,
            'Reading': f"{global_liq_change:+.2f}% over 13 weeks",
            'Supportive when': 'Rising',
        },
        {
            'Factor': '10Y real yield',
            'Score': 1 if latest['Real_Rate'] < four_weeks_ago['Real_Rate'] else -1,
            'Reading': f"{real_rate_change:+.2f} pp over 4 weeks",
            'Supportive when': 'Falling',
        },
        {
            'Factor': 'US dollar',
            'Score': 1 if latest['Dollar_Index'] < four_weeks_ago['Dollar_Index'] else -1,
            'Reading': f"{latest['Dollar_Index'] - four_weeks_ago['Dollar_Index']:+.2f} over 4 weeks",
            'Supportive when': 'Falling',
        },
        {
            'Factor': 'Financial conditions',
            'Score': 1 if latest['NFCI'] < four_weeks_ago['NFCI'] else -1,
            'Reading': f"{latest['NFCI'] - four_weeks_ago['NFCI']:+.3f} over 4 weeks",
            'Supportive when': 'Loosening',
        },
        {
            'Factor': 'BTC price trend',
            'Score': 1 if latest['BTC-USD'] > btc_200d_average else -1,
            'Reading': f"${latest['BTC-USD']:,.0f} vs ${btc_200d_average:,.0f} 200D avg",
            'Supportive when': 'Above 200D avg',
        },
    ]
    btc_score = sum(signal['Score'] for signal in btc_signals)

    if btc_score >= 4:
        outlook = 'Strongly Supportive'
        badge_color = '🟢'
        regime_desc = 'Most measured liquidity, rates, currency, credit, and price-trend signals favor Bitcoin.'
    elif btc_score >= 2:
        outlook = 'Moderately Supportive'
        badge_color = '🟢'
        regime_desc = 'More indicators support Bitcoin than oppose it, but the signal is not unanimous.'
    elif btc_score >= -1:
        outlook = 'Mixed / Neutral'
        badge_color = '⚪'
        regime_desc = 'The indicators disagree, so there is no strong directional BTC signal.'
    elif btc_score >= -3:
        outlook = 'Unfavorable'
        badge_color = '🟠'
        regime_desc = 'More indicators oppose Bitcoin than support it; conditions warrant caution.'
    else:
        outlook = 'Strongly Unfavorable'
        badge_color = '🔴'
        regime_desc = 'Most measured indicators currently create a difficult backdrop for Bitcoin.'
    
    st.title("Shripal's Macro Copilot: Everyday Market Regime")
    st.caption("A layman-friendly engine translating Federal Reserve and Treasury data into clear allocation decisions.")
    
    # Transparent BTC scoring model
    st.markdown("---")
    st.subheader("Bitcoin Macro Signal")

    col_a, col_b, col_c = st.columns(3)
    col_a.metric("BTC Score", f"{btc_score:+.0f} / 5")
    col_b.metric("BTC Outlook", f"{badge_color} {outlook}")
    col_c.metric("4-Week Liquidity Shift", f"{liq_change_30d:+.2f}%", delta_color="normal")
    
    st.info(f"**What it means:** {regime_desc}")

    signal_table = pd.DataFrame(btc_signals)
    signal_table['Signal'] = signal_table['Score'].apply(
        lambda score: f"✅ Supportive (+{score:g})" if score > 0 else f"❌ Unfavorable ({score:g})"
    )
    st.dataframe(
        signal_table[['Factor', 'Signal', 'Reading', 'Supportive when']],
        width='stretch',
        hide_index=True,
    )
    st.caption("This is a market-regime indicator, not a BTC price forecast or investment recommendation.")

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
        if quote is None:
            column.metric(label=name, value="Unavailable")
        else:
            column.metric(
                label=name,
                value=price_formats[name].format(quote['price']),
                delta=f"{quote['change_pct']:+.2f}% vs previous close",
                help=f"Latest {quote['source']} price from Yahoo Finance.",
            )

    st.caption("Latest available Yahoo Finance quotes; exchange delays may apply. Daily closes are used when intraday quotes are unavailable. Gold and oil use front-month futures.")
    
    # Core macro gauges
    st.markdown("---")
    st.subheader("Core Macro Gauges")
    
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric(
        label="Net US Liquidity", 
        value=f"${latest['Net_Liquidity']:.2f} T", 
        delta=f"{liq_change_30d:+.2f}% (4 weeks)",
        help="Fed Assets minus Treasury Cash & Reverse Repo. Rising = Fuel for Crypto & Stocks."
    )
    c2.metric(
        label="Global Liquidity Proxy",
        value=f"${latest['Global_Liquidity']:.2f} T",
        delta=f"{global_liq_change:+.2f}% (13 weeks)",
        help="Fed, ECB, and BOJ balance sheets converted to USD. This is a proxy, not all global liquidity."
    )
    c3.metric(
        label="10Y Real TIPS Rate", 
        value=f"{latest['Real_Rate']:.2f}%", 
        delta=f"{real_rate_change:+.2f} pp (4 weeks)",
        delta_color="inverse",
        help="Real return above inflation. Dropping real rates trigger Gold rallies."
    )
    c4.metric(
        label="Yield Curve (10Y - 2Y)", 
        value=f"{latest['Yield_Curve']:.2f}%", 
        delta="Inverted" if current_yc < 0 else "Normal",
        delta_color="normal" if current_yc >= 0 else "inverse",
        help="Negative indicates recession risks within 6-18 months."
    )
    c5.metric(
        label="Bitcoin Price (USD)", 
        value=f"${latest['BTC-USD']:,.0f}", 
        delta=f"{((latest['BTC-USD'] - four_weeks_ago['BTC-USD']) / four_weeks_ago['BTC-USD']) * 100:+.2f}% (4 weeks)"
    )

    # Interactive Chart
    st.markdown("---")
    st.subheader("Historical Context: US & Global Liquidity vs. Bitcoin & Gold")
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=data.index, y=data['Net_Liquidity'], name="Net US Liquidity ($T)", line=dict(color="#00FFA3", width=2)))
    fig.add_trace(go.Scatter(x=data.index, y=data['Global_Liquidity'], name="Global Liquidity Proxy ($T)", line=dict(color="#00BFFF", width=2)))
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
    st.plotly_chart(fig, width='stretch')

except Exception as e:
    st.error(f"Error fetching live indicators: {e}")
