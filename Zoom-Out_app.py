import streamlit as st
import pandas as pd
import json
import re
import yfinance as yf
import plotly.express as px
import plotly.graph_objects as go

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="AI Portfolio Manager", layout="wide")

# --- HELPER FUNCTIONS ---

def extract_json_blocks(text_content):
    """
    Scans the raw text file (which might contain 25 different AI reports)
    and extracts just the JSON blocks at the end of each report.
    """
    # Regex to find JSON blocks starting with '{' and ending with '}'
    # This is a basic extractor; it assumes the prompt output is relatively clean.
    matches = []
    
    # We look for the specific structure we defined in the prompt
    # Capturing from "meta" tag to the end of the JSON structure
    # This regex looks for outer braces containing "meta" and "ticker"
    pattern = r"(\{[\s\S]*?\"meta\"[\s\S]*?\"ticker\"[\s\S]*?\})"
    
    raw_blocks = re.findall(pattern, text_content)
    
    data = []
    for block in raw_blocks:
        try:
            # Clean up potential markdown wrappers like ```json
            clean_block = block.replace("```json", "").replace("```", "")
            parsed = json.loads(clean_block)
            data.append(parsed)
        except json.JSONDecodeError:
            continue
            
    return data

def fetch_market_data(tickers):
    """
    Fetches live price, beta, and sector data from Yahoo Finance.
    """
    if not tickers:
        return {}
    
    # Bulk download is faster
    string_tickers = " ".join(tickers)
    info_dict = {}
    
    # We use Ticker object for detailed info (beta, sector)
    # Note: For large portfolios, this might take 10-20 seconds.
    for t in tickers:
        try:
            stock = yf.Ticker(t)
            # Fast info fetch
            fi = stock.fast_info
            # Regular info fetch (slower but has Beta/Sector)
            reg_info = stock.info
            
            info_dict[t] = {
                'current_price': fi.last_price,
                'beta': reg_info.get('beta', 1.0), # Default to 1.0 if missing
                'sector': reg_info.get('sector', 'Unknown'),
                'dividend_yield': reg_info.get('dividendYield', 0)
            }
        except Exception as e:
            st.warning(f"Could not fetch market data for {t}")
            info_dict[t] = {'current_price': 0, 'beta': 1.0, 'sector': 'Unknown', 'dividend_yield': 0}
            
    return info_dict

# --- MAIN APP UI ---

st.title("🧠 AI Portfolio Manager")
st.markdown("### From Static Checklist to Active Strategy")

# 1. SIDEBAR - INPUTS
with st.sidebar:
    st.header("1. Upload Analysis")
    uploaded_file = st.file_uploader("Upload your AI Reports (.txt)", type="txt")
    
    st.header("2. Strategy Goals")
    target_return = st.slider("Target Annual Return (%)", 5, 30, 16)
    min_moat_score = st.slider("Min. Moat Score Threshold", 0, 100, 60)

# 2. DATA PROCESSING
if uploaded_file is not None:
    # Read file
    content = uploaded_file.read().decode("utf-8")
    
    # Parse JSONs
    json_data = extract_json_blocks(content)
    
    if not json_data:
        st.error("No valid JSON blocks found. Did you add the 'Phase 11' code to your prompt?")
    else:
        st.success(f"Successfully loaded {len(json_data)} companies.")
        
        # Flatten the JSON data for the DataFrame
        rows = []
        tickers = []
        for item in json_data:
            t = item['meta']['ticker']
            tickers.append(t)
            rows.append({
                'Ticker': t,
                'Quality Score': item['scoring']['final_total'],
                'Moat Score': item['scoring']['moat'],
                'Lifecycle': item['lifecycle']['stage'],
                'Moat Verdict': item['qualitative']['moat_verdict'],
                'Spread (ROIC-WACC)': item['valuation_metrics']['spread'],
                'Thesis': item['qualitative']['neal_g_verdict']
            })
            
        # Create base DataFrame
        df = pd.DataFrame(rows)
        
        # Fetch Live Data
        with st.spinner('Fetching live market data (Prices, Beta, Sectors)...'):
            market_data = fetch_market_data(tickers)
        
        # Merge Live Data
        df['Price'] = df['Ticker'].map(lambda x: market_data.get(x, {}).get('current_price', 0))
        df['Beta'] = df['Ticker'].map(lambda x: market_data.get(x, {}).get('beta', 1.0))
        df['Sector'] = df['Ticker'].map(lambda x: market_data.get(x, {}).get('sector', 'Unknown'))
        
        # 3. USER INPUT (The "Missing Link")
        st.subheader("3. Portfolio Composition")
        st.markdown("Enter the number of shares you own to calculate portfolio-level metrics.")
        
        # Editable Dataframe
        df['Shares'] = 0  # Default column
        edited_df = st.data_editor(
            df[['Ticker', 'Shares', 'Price', 'Quality Score', 'Moat Score', 'Lifecycle', 'Beta']],
            column_config={
                "Shares": st.column_config.NumberColumn("Your Shares", min_value=0, step=1, required=True),
                "Price": st.column_config.NumberColumn("Live Price", format="$%.2f", disabled=True),
                "Quality Score": st.column_config.ProgressColumn("AI Score", min_value=0, max_value=250, format="%d"),
            },
            disabled=["Ticker", "Price", "Quality Score", "Moat Score", "Lifecycle", "Beta"],
            hide_index=True,
            use_container_width=True
        )

        # 4. PORTFOLIO ANALYTICS (The "Brain")
        # Calculate Position Values
        edited_df['Position Value'] = edited_df['Shares'] * edited_df['Price']
        total_portfolio_value = edited_df['Position Value'].sum()

        if total_portfolio_value > 0:
            edited_df['Weight'] = edited_df['Position Value'] / total_portfolio_value
            
            # Weighted Metrics
            portfolio_score = (edited_df['Quality Score'] * edited_df['Weight']).sum()
            portfolio_beta = (edited_df['Beta'] * edited_df['Weight']).sum()
            portfolio_moat = (edited_df['Moat Score'] * edited_df['Weight']).sum()
            
            # --- DASHBOARD ROW 1: HEADLINES ---
            st.markdown("---")
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Total Value", f"${total_portfolio_value:,.2f}")
            col2.metric("Portfolio Quality Score", f"{portfolio_score:.0f}/250", delta=f"{portfolio_score - 150:.0f} vs Baseline")
            col3.metric("Portfolio Beta (Risk)", f"{portfolio_beta:.2f}", delta=f"{1.0 - portfolio_beta:.2f} vs Market", delta_color="inverse")
            col4.metric("Weighted Moat Strength", f"{portfolio_moat:.0f}/100", delta="Target > 60" if portfolio_moat > 60 else "Weak")

            # --- DASHBOARD ROW 2: VISUALS ---
            c1, c2 = st.columns(2)
            
            with c1:
                st.subheader("Allocation by Lifecycle Stage")
                # Ensure colors match the logic (Green for growth, etc.)
                fig_life = px.pie(edited_df, values='Position Value', names='Lifecycle', 
                                  title="Are you buying Growth or Decline?",
                                  hole=0.4)
                st.plotly_chart(fig_life, use_container_width=True)
                
            with c2:
                st.subheader("Risk vs. Quality Map")
                # X = Risk (Beta), Y = Quality (Score), Size = Position Size
                fig_scatter = px.scatter(edited_df, x="Beta", y="Quality Score", 
                                         size="Position Value", color="Lifecycle",
                                         hover_name="Ticker", text="Ticker",
                                         title="Find the 'Weak Links' (Low Score + High Risk)")
                # Add crosshairs for averages
                fig_scatter.add_hline(y=portfolio_score, line_dash="dot", annotation_text="Avg Quality")
                fig_scatter.add_vline(x=portfolio_beta, line_dash="dot", annotation_text="Avg Risk")
                st.plotly_chart(fig_scatter, use_container_width=True)

            # --- DASHBOARD ROW 3: TEXT WARNINGS ---
            st.subheader("⚠️ AI Detected Warnings")
            
            # Logic Checks
            warnings = []
            if portfolio_score < 150:
                warnings.append(f"❌ **Quality Alert:** Your weighted average score ({portfolio_score:.0f}) is below the investable baseline of 150.")
            if portfolio_beta > 1.3:
                warnings.append(f"🔥 **Volatility Alert:** Your portfolio is 30% more volatile than the market. Ensure this matches your risk tolerance.")
            
            # Check for "Fake Diversification" (Concentration in one lifecycle)
            lifecycle_counts = edited_df['Lifecycle'].value_counts(normalize=True)
            for stage, pct in lifecycle_counts.items():
                if pct > 0.60:
                     warnings.append(f"⚖️ **Concentration Risk:** You have {pct:.0%} of your money in '{stage}'. This lacks structural diversity.")

            if warnings:
                for w in warnings:
                    st.markdown(w)
            else:
                st.success("✅ No structural portfolio breaches detected.")

        else:
            st.info("👆 Enter your share counts above to see the Portfolio Analysis.")

else:
    st.info("Waiting for upload... (Paste your prompt output into a .txt file and drag it here)")
