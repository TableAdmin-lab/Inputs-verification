import streamlit as st
import pandas as pd
import openpyxl
import re
import altair as alt

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(
    page_title="Yoco Onboarding Pro",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- 2. CUSTOM PRO CSS ---
st.markdown("""
<style>
    /* Global Font & Background */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    
    .stApp {
        background-color: #f8f9fc;
    }

    /* Hero Section */
    .hero-container {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 40px;
        border-radius: 15px;
        color: white;
        text-align: center;
        margin-bottom: 20px;
        box-shadow: 0 10px 20px rgba(0,0,0,0.1);
    }
    .hero-title { font-size: 42px; font-weight: 700; margin: 0; }
    .hero-subtitle { font-size: 18px; opacity: 0.9; margin-top: 10px; }

    /* Metric Cards */
    .metric-container {
        background-color: white;
        padding: 20px;
        border-radius: 12px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        border: 1px solid #eef0f5;
        text-align: center;
        transition: transform 0.2s;
    }
    .metric-container:hover { transform: translateY(-5px); }
    .metric-val { font-size: 32px; font-weight: 700; color: #1a202c; }
    .metric-lbl { font-size: 14px; font-weight: 600; color: #718096; text-transform: uppercase; letter-spacing: 0.5px; }

    /* Custom Alert Boxes */
    .alert-box {
        padding: 15px; border-radius: 8px; margin-bottom: 10px; border-left: 5px solid;
    }
    .alert-critical { background-color: #fff5f5; border-color: #fc8181; color: #c53030; }
    .alert-suggestion { background-color: #ebf8ff; border-color: #63b3ed; color: #2c5282; }

</style>
""", unsafe_allow_html=True)

# --- 3. LOGIC FUNCTIONS (Kept same for stability) ---
def normalize_name(name):
    if pd.isna(name): return ""
    name = str(name).strip()
    name = re.sub(r'(?i)\(RAW\)', '', name)
    name = re.sub(r'(?i)\(MAN\)', '', name)
    return name.strip()

def get_visible_sheet_names(file):
    try:
        wb = openpyxl.load_workbook(file, read_only=True)
        return [sheet.title for sheet in wb.worksheets if sheet.sheet_state == 'visible']
    except: return []

def get_clean_data(file, sheet_name, unique_col_identifier):
    try:
        df_scan = pd.read_excel(file, sheet_name=sheet_name, header=None, nrows=50)
        matching_rows = []
        for i, row in df_scan.iterrows():
            row_str = row.astype(str).str.replace(r'\s+', ' ', regex=True).str.strip()
            if row_str.str.contains(unique_col_identifier, case=False, na=False).any():
                matching_rows.append(i)
        
        if not matching_rows: return None, f"Header '{unique_col_identifier}' not found"
        header_row_idx = matching_rows[-1]
        df = pd.read_excel(file, sheet_name=sheet_name, header=header_row_idx)
        df.columns = df.columns.astype(str).str.strip()
        target_col = next((c for c in df.columns if unique_col_identifier.lower() in c.lower()), None)
        if target_col:
            df = df[df[target_col].notna()]
            df = df[df[target_col].astype(str).str.strip() != ""]
            df = df[df[target_col].astype(str).str.upper() != "EXAMPLE"]
        offset = header_row_idx + 2 
        df['Row #'] = df.index + offset
        df['🔴 ACTION REQUIRED'] = "" 
        cols = ['Row #', '🔴 ACTION REQUIRED'] + [c for c in df.columns if c not in ['Row #', '🔴 ACTION REQUIRED']]
        df = df[cols]
        return df, None
    except Exception as e: return None, str(e)

def check_logic(df_prod, df_mod):
    suggestions = []
    # Variant Check
    if df_prod is not None:
        col_name = next((c for c in df_prod.columns if "Product Name" in c), None)
        if col_name:
            names = df_prod[col_name].astype(str).tolist()
            base_names = [n.split('-')[0].strip() for n in names if '-' in n]
            from collections import Counter
            counts = Counter(base_names)
            for base, count in counts.items():
                if count >= 2:
                    suggestions.append({"Type": "Structure", "Item": f"{base}...", "Msg": f"{count} items look like Variants", "Advice": "Group under one product with variants"})
    
    # Margin Check
    if df_prod is not None and "Selling Price (incl vat)" in df_prod.columns:
        col_cost = next((c for c in df_prod.columns if "Cost Price" in c), None)
        if col_cost:
            for idx, row in df_prod.iterrows():
                try:
                    s, c = float(row["Selling Price (incl vat)"]), float(row[col_cost])
                    if s > 0 and c > 0:
                        gp = ((s-c)/s)*100
                        if gp < 0: suggestions.append({"Type": "Money", "Item": row[col_name], "Msg": f"Negative Margin ({gp:.0f}%)", "Advice": "Cost > Sell Price"})
                except: pass
    return suggestions

# --- 4. HERO SECTION ---
st.markdown("""
<div class="hero-container">
    <div class="hero-title">Yoco Launchpad 🚀</div>
    <div class="hero-subtitle">The professional verification suite for restaurant onboarding.</div>
</div>
""", unsafe_allow_html=True)

# --- 5. MAIN LOGIC ---
uploaded_file = st.file_uploader("", type=["xlsx"])

if uploaded_file:
    visible_sheets = get_visible_sheet_names(uploaded_file)
    if not visible_sheets:
        st.error("No visible sheets found.")
        st.stop()

    # Processing State
    with st.spinner("🧠 Analyzing Menu Structure & Pricing..."):
        quality_score = 100
        valid_ingredients = set()
        bad_data_tables = {}
        error_counts = {"Stock": 0, "Products": 0, "Recipes": 0, "Employees": 0}
        
        # 1. STOCK
        if "Stock Items(RAW MATERIALS)" in visible_sheets:
            df_stock, _ = get_clean_data(uploaded_file, "Stock Items(RAW MATERIALS)", "RAW MATERIAL Product Name")
            if df_stock is not None:
                for n in df_stock["RAW MATERIAL Product Name"].dropna().astype(str): valid_ingredients.add(normalize_name(n))
                if "Cost Price" in df_stock.columns:
                    for i, r in df_stock.iterrows():
                        if pd.isna(r["Cost Price"]): 
                            df_stock.at[i, '🔴 ACTION REQUIRED'] = "Missing Cost"
                            quality_score -= 5
                            error_counts["Stock"] += 1
                bad = df_stock[df_stock['🔴 ACTION REQUIRED'] != ""]
                if not bad.empty: bad_data_tables["Stock Items"] = bad

        # 2. MANUFACTURED
        if "MANUFACTURED PRODUCTS" in visible_sheets:
            df_man, _ = get_clean_data(uploaded_file, "MANUFACTURED PRODUCTS", "MANUFACTURED Product Name")
            if df_man is not None:
                for n in df_man["MANUFACTURED Product Name"].dropna().astype(str): valid_ingredients.add(normalize_name(n))

        # 3. PRODUCTS
        df_prod_global = None
        if "Products(Finished Goods)" in visible_sheets:
            df_prod, _ = get_clean_data(uploaded_file, "Products(Finished Goods)", "Product Name")
            df_prod_global = df_prod
            if df_prod is not None:
                req = ["Selling Price (incl vat)", "Menu", "Menu Category", "Preparation Locations"]
                for i, r in df_prod.iterrows():
                    issues = [f"Missing {c}" for c in req if c in df_prod.columns and (pd.isna(r[c]) or str(r[c]).strip()=="")]
                    if issues:
                        df_prod.at[i, '🔴 ACTION REQUIRED'] = ", ".join(issues)
                        quality_score -= 5
                        error_counts["Products"] += 1
                bad = df_prod[df_prod['🔴 ACTION REQUIRED'] != ""]
                if not bad.empty: bad_data_tables["Products"] = bad

        # 4. RECIPES
        if "Products Recipes" in visible_sheets:
            df_rec, _ = get_clean_data(uploaded_file, "Products Recipes", "RAW MATERIALS")
            if df_rec is not None:
                col_ing = next((c for c in df_rec.columns if "RAW MATERIAL" in c.upper() and "NAME" in c.upper()), None)
                if col_ing:
                    for i, r in df_rec.iterrows():
                        ing = normalize_name(r[col_ing])
                        if ing and ing not in valid_ingredients:
                            df_rec.at[i, '🔴 ACTION REQUIRED'] = f"Ghost Item: {r[col_ing]}"
                            quality_score -= 5
                            error_counts["Recipes"] += 1
                    bad = df_rec[df_rec['🔴 ACTION REQUIRED'] != ""]
                    if not bad.empty: bad_data_tables["Recipes"] = bad

        # 5. LOGIC
        suggestions = check_logic(df_prod_global, None)

    # --- 6. DASHBOARD UI ---
    
    quality_score = max(0, int(quality_score))
    total_errors = sum(error_counts.values())

    # A. TOP METRICS
    c1, c2, c3, c4 = st.columns(4)
    
    with c1:
        st.markdown(f"""
        <div class="metric-container">
            <div class="metric-val" style="color: {'#48bb78' if quality_score > 80 else '#f56565'}">{quality_score}%</div>
            <div class="metric-lbl">Health Score</div>
        </div>
        """, unsafe_allow_html=True)
    
    with c2:
        st.markdown(f"""
        <div class="metric-container">
            <div class="metric-val">{total_errors}</div>
            <div class="metric-lbl">Critical Errors</div>
        </div>
        """, unsafe_allow_html=True)

    with c3:
        st.markdown(f"""
        <div class="metric-container">
            <div class="metric-val">{len(suggestions)}</div>
            <div class="metric-lbl">Logic Insights</div>
        </div>
        """, unsafe_allow_html=True)

    with c4:
        status_text = "Ready to Upload" if total_errors == 0 else "Needs Fixing"
        st.markdown(f"""
        <div class="metric-container">
            <div class="metric-val" style="font-size: 24px;">{status_text}</div>
            <div class="metric-lbl">Current Status</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # B. VISUAL BREAKDOWN (Chart)
    if total_errors > 0:
        st.markdown("##### 📉 Error Distribution")
        chart_data = pd.DataFrame(list(error_counts.items()), columns=["Category", "Errors"])
        # Filter out zero categories
        chart_data = chart_data[chart_data["Errors"] > 0]
        
        c = alt.Chart(chart_data).mark_bar(cornerRadiusTopLeft=5, cornerRadiusTopRight=5).encode(
            x=alt.X('Category', sort='-y', title=None),
            y=alt.Y('Errors', title=None),
            color=alt.value("#667eea"),
            tooltip=['Category', 'Errors']
        ).properties(height=200)
        
        st.altair_chart(c, use_container_width=True)

    # C. REPAIR STATION (Tabs)
    st.markdown("### 🛠️ Repair Station")
    
    if bad_data_tables:
        tabs = st.tabs([f"📍 {k}" for k in bad_data_tables.keys()] + ["💡 Logic & Suggestions"])
        
        # Dynamic Tabs for Errors
        for i, (sheet, df) in enumerate(bad_data_tables.items()):
            with tabs[i]:
                st.warning(f"Found {len(df)} rows to fix in **{sheet}**.")
                st.data_editor(
                    df,
                    hide_index=True,
                    use_container_width=True,
                    disabled=["Row #", "🔴 ACTION REQUIRED"]
                )
        
        # Last Tab for Logic
        with tabs[-1]:
            if suggestions:
                for s in suggestions:
                    st.markdown(f"""
                    <div class="alert-box alert-suggestion">
                        <strong>{s['Type']}: {s['Item']}</strong><br>
                        {s['Msg']}<br>
                        <em>Tip: {s['Advice']}</em>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.success("No logic suggestions found.")
    
    else:
        # Success State
        st.balloons()
        st.markdown("""
        <div style="text-align: center; padding: 50px;">
            <h1 style="color: #48bb78; font-size: 60px;">🎉</h1>
            <h2>Clean Data!</h2>
            <p>Your file is perfectly formatted and ready for the Yoco team.</p>
        </div>
        """, unsafe_allow_html=True)

else:
    # Empty State Hero
    st.markdown("""
    <div style="text-align: center; padding: 50px; color: #a0aec0;">
        <h2>Waiting for file...</h2>
        <p>Drag and drop your Excel file above to begin the audit.</p>
    </div>
    """, unsafe_allow_html=True)