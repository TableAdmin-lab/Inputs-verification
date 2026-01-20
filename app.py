import streamlit as st
import pandas as pd
import openpyxl
import re
import time

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(
    page_title="Yoco Repair & Logic Tool",
    page_icon="🛠️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- 2. CUSTOM CSS ---
st.markdown("""
<style>
    .stApp { background-color: #f8f9fa; }
    
    /* Metrics */
    .metric-card {
        background-color: white; padding: 15px; border-radius: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05); text-align: center;
        border: 1px solid #e9ecef;
    }
    .metric-val { font-size: 24px; font-weight: bold; margin: 0; }
    .metric-lbl { font-size: 12px; color: #6c757d; text-transform: uppercase; }

    /* Logic/Suggestion Box */
    .suggestion-box {
        background-color: #eef2ff; 
        border-left: 5px solid #4f46e5;
        padding: 15px;
        margin-bottom: 10px;
        border-radius: 4px;
    }
    
    /* Highlight Action Column in Editor */
    div[data-testid="stDataFrame"] table tbody tr td:first-child {
        font-weight: bold; color: #d63384; background-color: #fff0f6;
    }
</style>
""", unsafe_allow_html=True)

# --- 3. HELPER FUNCTIONS ---

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
        # Deep Scan for Header
        df_scan = pd.read_excel(file, sheet_name=sheet_name, header=None, nrows=50)
        matching_rows = []
        for i, row in df_scan.iterrows():
            row_str = row.astype(str).str.replace(r'\s+', ' ', regex=True).str.strip()
            if row_str.str.contains(unique_col_identifier, case=False, na=False).any():
                matching_rows.append(i)
        
        if not matching_rows: return None, f"Header '{unique_col_identifier}' not found"

        # Last Header Wins
        header_row_idx = matching_rows[-1]
        df = pd.read_excel(file, sheet_name=sheet_name, header=header_row_idx)
        df.columns = df.columns.astype(str).str.strip()

        # Identity Check & Setup
        target_col = next((c for c in df.columns if unique_col_identifier.lower() in c.lower()), None)
        if target_col:
            df = df[df[target_col].notna()]
            df = df[df[target_col].astype(str).str.strip() != ""]
            df = df[df[target_col].astype(str).str.upper() != "EXAMPLE"]

        offset = header_row_idx + 2 
        df['Row #'] = df.index + offset
        
        # Init Error Column (Empty by default)
        df['🔴 ACTION REQUIRED'] = "" 
        
        # Reorder columns
        cols = ['Row #', '🔴 ACTION REQUIRED'] + [c for c in df.columns if c not in ['Row #', '🔴 ACTION REQUIRED']]
        df = df[cols]
        
        return df, None
    except Exception as e:
        return None, str(e)

# --- 4. NEW: LOGIC ADVISORY ENGINE ---
def generate_suggestions(df_prod, df_mod):
    suggestions = []
    
    # --- A. VARIANT DETECTOR ---
    # Looks for items like "Latte - Small", "Latte - Large"
    if df_prod is not None and not df_prod.empty:
        # Extract Product Names
        col_name = next((c for c in df_prod.columns if "Product Name" in c), None)
        if col_name:
            names = df_prod[col_name].astype(str).tolist()
            # Find base names before a hyphen (e.g., "Latte" from "Latte - Small")
            base_names = [n.split('-')[0].strip() for n in names if '-' in n]
            
            # Count occurrences
            from collections import Counter
            counts = Counter(base_names)
            
            # If "Latte" appears 3+ times with hyphens, suggest variants
            for base, count in counts.items():
                if count >= 2:
                    suggestions.append({
                        "Type": "Structure",
                        "Title": "Possible Variant Group",
                        "Message": f"You have {count} items starting with **'{base}'** (e.g., {base} - Small).",
                        "Advice": "Consider grouping these as a single Product with **Variants** (Small, Medium, Large) to clean up your menu."
                    })

    # --- B. MODIFIER LOGIC ---
    if df_mod is not None and not df_mod.empty:
        col_grp = next((c for c in df_mod.columns if "Modifier Group Name" in c), None)
        col_opt = next((c for c in df_mod.columns if "Options" in c), None)
        
        if col_grp:
            # Check for "Size" in modifiers
            size_keywords = ["SIZE", "VOLUME", "WEIGHT"]
            option_keywords = ["SMALL", "MEDIUM", "LARGE", "ML", "KG"]
            
            for index, row in df_mod.iterrows():
                grp = str(row[col_grp]).upper()
                opt = str(row[col_opt]).upper() if col_opt else ""
                
                if any(k in grp for k in size_keywords) or any(k in opt for k in option_keywords):
                    suggestions.append({
                        "Type": "Logic",
                        "Title": "Sizes as Modifiers",
                        "Message": f"Modifier Group **'{row[col_grp]}'** looks like it controls sizing.",
                        "Advice": "Yoco Best Practice: Use **Variants** for sizes (so they track stock differently). Use Modifiers for instructions (e.g. No Onion)."
                    })
                    break # Only report once per group

    # --- C. CASING CHECK ---
    if df_prod is not None:
        col_name = next((c for c in df_prod.columns if "Product Name" in c), None)
        if col_name:
            lowercase_count = df_prod[col_name].astype(str).str.islower().sum()
            if lowercase_count > 3:
                 suggestions.append({
                        "Type": "Formatting",
                        "Title": "Lowercase Names Detected",
                        "Message": f"Found {lowercase_count} products using all lowercase letters (e.g. 'burger').",
                        "Advice": "Use **Title Case** (e.g. 'Burger') for better receipts."
                    })

    # --- D. PROFITABILITY (Negative Margins) ---
    if df_prod is not None and "Selling Price (incl vat)" in df_prod.columns:
        col_cost = next((c for c in df_prod.columns if "Cost Price" in c), None)
        col_sell = "Selling Price (incl vat)"
        if col_cost:
            neg_margins = 0
            for index, row in df_prod.iterrows():
                try:
                    s = float(row[col_sell])
                    c = float(row[col_cost])
                    if c > s: neg_margins += 1
                except: pass
            
            if neg_margins > 0:
                 suggestions.append({
                        "Type": "Profit",
                        "Title": "Negative Margins",
                        "Message": f"Found {neg_margins} items where Cost Price > Selling Price.",
                        "Advice": "Check your Cost Price column. You might be losing money on every sale."
                    })

    return suggestions

# --- 5. MAIN APP ---
st.title("🛠️ Yoco Data Repair & Advisory")
st.markdown("Automated cleaning, error detection, and restaurant logic suggestions.")

uploaded_file = st.file_uploader("", type=["xlsx"])

if uploaded_file:
    visible_sheets = get_visible_sheet_names(uploaded_file)
    if not visible_sheets:
        st.error("No visible sheets found.")
        st.stop()

    # INIT
    quality_score = 100
    total_errors = 0
    valid_ingredients_set = set()
    PENALTY_CRITICAL = 10
    
    # Store DataFrames
    bad_data_tables = {} 
    df_prod_global = None
    df_mod_global = None

    # --- PHASE 1: STOCK ---
    if "Stock Items(RAW MATERIALS)" in visible_sheets:
        df_stock, err = get_clean_data(uploaded_file, "Stock Items(RAW MATERIALS)", "RAW MATERIAL Product Name")
        if df_stock is not None:
            for name in df_stock["RAW MATERIAL Product Name"].dropna().astype(str):
                valid_ingredients_set.add(normalize_name(name))
            
            if "Cost Price" in df_stock.columns:
                for idx, row in df_stock.iterrows():
                    if pd.isna(row["Cost Price"]):
                        df_stock.at[idx, '🔴 ACTION REQUIRED'] = "Missing Cost Price"
                        quality_score -= PENALTY_CRITICAL
                        total_errors += 1
            
            bad = df_stock[df_stock['🔴 ACTION REQUIRED'] != ""]
            if not bad.empty: bad_data_tables["Stock"] = bad

    # --- PHASE 2: MANUFACTURED ---
    if "MANUFACTURED PRODUCTS" in visible_sheets:
        df_man, err = get_clean_data(uploaded_file, "MANUFACTURED PRODUCTS", "MANUFACTURED Product Name")
        if df_man is not None:
            for name in df_man["MANUFACTURED Product Name"].dropna().astype(str):
                valid_ingredients_set.add(normalize_name(name))

    # --- PHASE 3: PRODUCTS ---
    if "Products(Finished Goods)" in visible_sheets:
        df_prod, err = get_clean_data(uploaded_file, "Products(Finished Goods)", "Product Name")
        df_prod_global = df_prod # SAVE FOR LOGIC CHECK
        
        if df_prod is not None:
            required = ["Selling Price (incl vat)", "Menu", "Menu Category", "Preparation Locations"]
            for idx, row in df_prod.iterrows():
                issues = []
                for col in required:
                    if col in df_prod.columns:
                        if pd.isna(row[col]) or str(row[col]).strip() == "":
                            issues.append(f"Missing {col}")
                if issues:
                    df_prod.at[idx, '🔴 ACTION REQUIRED'] = " & ".join(issues)
                    quality_score -= PENALTY_CRITICAL
                    total_errors += 1
            
            bad = df_prod[df_prod['🔴 ACTION REQUIRED'] != ""]
            if not bad.empty: bad_data_tables["Products"] = bad

    # --- PHASE 4: RECIPES ---
    if "Products Recipes" in visible_sheets:
        df_rec, err = get_clean_data(uploaded_file, "Products Recipes", "RAW MATERIALS")
        col_ing = "RAW MATERIALS / MANUFACTURED PRODUCT NAME"
        if df_rec is not None:
            if col_ing not in df_rec.columns:
                match = [c for c in df_rec.columns if "RAW MATERIAL" in c.upper() and "NAME" in c.upper()]
                if match: col_ing = match[0]

            if col_ing in df_rec.columns:
                for idx, row in df_rec.iterrows():
                    ing = normalize_name(row[col_ing])
                    if ing and ing not in valid_ingredients_set:
                         df_rec.at[idx, '🔴 ACTION REQUIRED'] = f"Ghost Item: '{row[col_ing]}'"
                         quality_score -= PENALTY_CRITICAL
                         total_errors += 1
            
            bad = df_rec[df_rec['🔴 ACTION REQUIRED'] != ""]
            if not bad.empty: bad_data_tables["Recipes"] = bad

    # --- PHASE 5: MODIFIERS (For Logic) ---
    if "Modifers" in visible_sheets:
        df_mod_global, err = get_clean_data(uploaded_file, "Modifers", "Modifier Group Name")
    elif "Modifiers" in visible_sheets:
        df_mod_global, err = get_clean_data(uploaded_file, "Modifiers", "Modifier Group Name")

    # ================= LOGIC ENGINE =================
    suggestions = generate_suggestions(df_prod_global, df_mod_global)

    # ================= UI DISPLAY =================
    quality_score = max(0, int(quality_score))
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Data Quality", f"{quality_score}%")
    c2.metric("Critical Errors", total_errors, delta_color="inverse")
    c3.metric("Suggestions", len(suggestions), delta_color="off")

    st.markdown("<br>", unsafe_allow_html=True)
    
    # TABS
    tab1, tab2 = st.tabs(["🔴 Critical Repair Station", "💡 Advisory & Suggestions"])

    # TAB 1: INTERACTIVE REPAIR
    with tab1:
        if bad_data_tables:
            st.warning("The following rows prevent a successful upload. Use the 'Row #' to find and fix them in Excel.")
            
            for sheet, df_bad in bad_data_tables.items():
                with st.expander(f"📍 {sheet} ({len(df_bad)} errors)", expanded=True):
                    st.data_editor(
                        df_bad,
                        hide_index=True,
                        disabled=["Row #", "🔴 ACTION REQUIRED"],
                        use_container_width=True
                    )
        else:
            st.success("🎉 No Critical Errors! Your data is valid.")

    # TAB 2: ADVISORY (THE MISSING PIECE)
    with tab2:
        if suggestions:
            st.markdown("These suggestions help improve your restaurant's operations and reporting.")
            for s in suggestions:
                st.markdown(f"""
                <div class="suggestion-box">
                    <strong>{s['Type']}</strong>: {s['Title']}<br>
                    {s['Message']}<br>
                    <em>👉 {s['Advice']}</em>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("✅ No suggestions. Your menu structure and pricing look clean.")

else:
    st.info("Waiting for file...")