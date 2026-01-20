import streamlit as st
import pandas as pd
import openpyxl
import re

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Yoco Onboarding Verifier", page_icon="👨‍🍳", layout="wide")

# --- CSS STYLING ---
st.markdown("""
<style>
    .stDataFrame { border: 1px solid #ddd; border-radius: 5px; }
    .score-card { padding: 20px; border-radius: 10px; text-align: center; border: 2px solid #eee; }
    .good { background-color: #d4edda; color: #155724; border-color: #c3e6cb; }
    .average { background-color: #fff3cd; color: #856404; border-color: #ffeeba; }
    .bad { background-color: #f8d7da; color: #721c24; border-color: #f5c6cb; }
    .logic-box { background-color: #e2e3e5; padding: 15px; border-radius: 5px; margin-bottom: 10px; }
</style>
""", unsafe_allow_html=True)

# --- HELPER: NORMALIZE NAMES ---
def normalize_name(name):
    if pd.isna(name): return ""
    name = str(name).strip()
    name = re.sub(r'(?i)\(RAW\)', '', name)
    name = re.sub(r'(?i)\(MAN\)', '', name)
    return name.strip()

# --- HELPER: GET VISIBLE SHEETS ---
def get_visible_sheet_names(file):
    try:
        wb = openpyxl.load_workbook(file, read_only=True)
        visible_sheets = [sheet.title for sheet in wb.worksheets if sheet.sheet_state == 'visible']
        return visible_sheets
    except Exception as e:
        return []

# --- HELPER: INTELLIGENT DATA PARSER ---
def get_clean_data(file, sheet_name, unique_col_identifier):
    try:
        # Step A: Deep Scan for Header
        df_scan = pd.read_excel(file, sheet_name=sheet_name, header=None, nrows=50)
        matching_rows = []
        for i, row in df_scan.iterrows():
            row_str = row.astype(str).str.replace(r'\s+', ' ', regex=True).str.strip()
            if row_str.str.contains(unique_col_identifier, case=False, na=False).any():
                matching_rows.append(i)
        
        if not matching_rows: return None, f"Header '{unique_col_identifier}' not found"

        # LAST HEADER WINS
        header_row_idx = matching_rows[-1]
        df = pd.read_excel(file, sheet_name=sheet_name, header=header_row_idx)
        df.columns = df.columns.astype(str).str.strip()

        # Step C: Identity Check
        target_col = next((c for c in df.columns if unique_col_identifier.lower() in c.lower()), None)
        if target_col:
            df = df[df[target_col].notna()]
            df = df[df[target_col].astype(str).str.strip() != ""]
            df = df[df[target_col].astype(str).str.upper() != "EXAMPLE"]

        offset = header_row_idx + 2 
        df['__excel_row__'] = df.index + offset
        return df, None
    except Exception as e:
        return None, str(e)

# --- NEW: RESTAURANT LOGIC CHECKER ---
def check_restaurant_logic(df_prod, df_mod):
    logic_issues = []
    
    # 1. COSTING LOGIC (GP Check)
    if df_prod is not None and "Selling Price (incl vat)" in df_prod.columns:
        # Try to find cost price column (Yoco sheets vary slightly)
        cost_col = next((c for c in df_prod.columns if "Cost Price" in c), None)
        
        if cost_col:
            for _, row in df_prod.iterrows():
                try:
                    sell = float(row["Selling Price (incl vat)"])
                    cost = float(row[cost_col]) if pd.notna(row[cost_col]) else 0.0
                    
                    if sell > 0 and cost > 0:
                        gp = ((sell - cost) / sell) * 100
                        
                        # LOGIC: Negative Margin (Cost > Sell)
                        if gp < 0:
                            logic_issues.append({
                                "Category": "💰 Profitability",
                                "Item": row.iloc[0], # Assumes Name is col 0
                                "Issue": f"Negative Margin ({gp:.1f}%)",
                                "Advice": f"Cost (R{cost}) is higher than Selling Price (R{sell}). Check data entry."
                            })
                        # LOGIC: Suspiciously Low Margin (Typo in cost?)
                        elif gp < 15:
                            logic_issues.append({
                                "Category": "💰 Profitability",
                                "Item": row.iloc[0],
                                "Issue": f"Low Margin ({gp:.1f}%)",
                                "Advice": "Margin is below 15%. Did you enter a 'Case Cost' instead of 'Unit Cost'?"
                            })
                except:
                    pass # Skip non-numeric

    # 2. MODIFIER VS VARIANT LOGIC
    if df_mod is not None and not df_mod.empty:
        # Check Identifier column
        mod_col = next((c for c in df_mod.columns if "Modifier Group Name" in c), None)
        opt_col = next((c for c in df_mod.columns if "Options" in c), None)
        
        if mod_col:
            for _, row in df_mod.iterrows():
                group_name = str(row[mod_col]).upper()
                option_name = str(row[opt_col]).upper() if opt_col else ""
                
                # LOGIC: Sizes as Modifiers
                suspicious_keywords = ["SIZE", "VOLUME", "WEIGHT"]
                suspicious_options = ["SMALL", "MEDIUM", "LARGE", "ML", "KG"]
                
                if any(k in group_name for k in suspicious_keywords) or \
                   any(k in option_name for k in suspicious_options):
                    
                    logic_issues.append({
                        "Category": "⚠️ Structural Logic",
                        "Item": row[mod_col],
                        "Issue": "Sizes used as Modifiers",
                        "Advice": "Best Practice: Use VARIANTS for sizes (Small/Med/Large) to track stock correctly. Use Modifiers for instructions (No Ice/Rare)."
                    })
                    break # Only flag once per group

    return logic_issues

# --- MAIN APP ---
st.title("👨‍🍳 Yoco Restaurant Logic Verifier")
st.markdown("Verifies data syntax AND applies **Common Restaurant Logic** (Margins, Menu Structure, etc).")

uploaded_file = st.file_uploader("", type=["xlsx"])

if uploaded_file:
    visible_sheets = get_visible_sheet_names(uploaded_file)
    if not visible_sheets:
        st.error("No visible sheets found.")
        st.stop()

    quality_score = 100
    error_log = []
    logic_log = [] # New log for restaurant logic
    
    valid_ingredients_set = set()
    
    PENALTY_CRITICAL = 10
    PENALTY_MINOR = 1

    # LOAD DATASETS FOR LOGIC CHECKS
    df_prod_global = None
    df_mod_global = None

    # --- CHECK 1: STOCK ---
    if "Stock Items(RAW MATERIALS)" in visible_sheets:
        df_stock, err = get_clean_data(uploaded_file, "Stock Items(RAW MATERIALS)", "RAW MATERIAL Product Name")
        if df_stock is not None and not df_stock.empty:
            for name in df_stock["RAW MATERIAL Product Name"].dropna().astype(str):
                valid_ingredients_set.add(normalize_name(name))
            
            # Check Costs
            if "Cost Price" in df_stock.columns: # Cleaned name
                for _, row in df_stock.iterrows():
                    if pd.isna(row["Cost Price"]):
                        quality_score -= PENALTY_CRITICAL
                        error_log.append({"Type": "Critical", "Sheet": "Stock", "Row": row['__excel_row__'], "Issue": "Missing Cost", "Fix": "Enter value"})

    # --- CHECK 2: MANUFACTURED ---
    if "MANUFACTURED PRODUCTS" in visible_sheets:
        df_man, err = get_clean_data(uploaded_file, "MANUFACTURED PRODUCTS", "MANUFACTURED Product Name")
        if df_man is not None and not df_man.empty:
            for name in df_man["MANUFACTURED Product Name"].dropna().astype(str):
                valid_ingredients_set.add(normalize_name(name))

    # --- CHECK 3: PRODUCTS ---
    if "Products(Finished Goods)" in visible_sheets:
        df_prod, err = get_clean_data(uploaded_file, "Products(Finished Goods)", "Product Name")
        df_prod_global = df_prod # Save for logic check
        
        if df_prod is not None:
            if df_prod.empty:
                quality_score = 0
                error_log.append({"Type": "Critical", "Sheet": "Products", "Row": "-", "Issue": "NO PRODUCTS", "Fix": "Sheet empty"})
            elif "Selling Price (incl vat)" in df_prod.columns:
                for _, row in df_prod.iterrows():
                    price = row["Selling Price (incl vat)"]
                    if pd.isna(price):
                         quality_score -= PENALTY_CRITICAL
                         error_log.append({"Type": "Critical", "Sheet": "Products", "Row": row['__excel_row__'], "Issue": "Missing Price", "Fix": "Enter value"})

    # --- CHECK 4: RECIPES ---
    if "Products Recipes" in visible_sheets:
        df_rec, err = get_clean_data(uploaded_file, "Products Recipes", "RAW MATERIALS")
        col_ing = "RAW MATERIALS / MANUFACTURED PRODUCT NAME"
        
        if df_rec is not None:
             # Find column if name varies
            if col_ing not in df_rec.columns:
                candidates = [c for c in df_rec.columns if "RAW MATERIAL" in c.upper() and "NAME" in c.upper()]
                if candidates: col_ing = candidates[0]

            if col_ing in df_rec.columns and valid_ingredients_set:
                for _, row in df_rec.iterrows():
                    ing = normalize_name(row[col_ing])
                    if ing and ing not in valid_ingredients_set:
                        quality_score -= PENALTY_CRITICAL
                        error_log.append({"Type": "Critical", "Sheet": "Recipes", "Row": row['__excel_row__'], "Issue": f"Ghost Item: {row[col_ing]}", "Fix": "Check Stock/Manufactured Sheet"})

    # --- CHECK 5: MODIFIERS (For Logic Check) ---
    if "Modifers" in visible_sheets: # Note typo in Yoco sheet name usually "Modifers"
        df_mod_global, err = get_clean_data(uploaded_file, "Modifers", "Modifier Group Name")
    elif "Modifiers" in visible_sheets:
        df_mod_global, err = get_clean_data(uploaded_file, "Modifiers", "Modifier Group Name")

    # --- RUN RESTAURANT LOGIC CHECKS ---
    logic_log = check_restaurant_logic(df_prod_global, df_mod_global)


    # ================= DISPLAY =================
    quality_score = max(0, int(quality_score))
    
    col1, col2 = st.columns([1, 3])
    with col1:
        color = "good" if quality_score > 80 else "average" if quality_score > 50 else "bad"
        st.markdown(f'<div class="score-card {color}"><h3>Data Health</h3><h1 style="margin:0;">{quality_score}</h1></div>', unsafe_allow_html=True)
    
    with col2:
        if quality_score < 100: st.error("Errors found in data formatting.")
        else: st.success("Data syntax looks good!")

    st.divider()

    # TABS
    tab1, tab2 = st.tabs(["🚨 Data Errors (Must Fix)", "🧠 Restaurant Logic (Double Check)"])

    with tab1:
        if error_log:
            st.dataframe(pd.DataFrame(error_log), use_container_width=True, hide_index=True)
        else:
            st.info("No Syntax Errors found.")

    with tab2:
        st.markdown("#### Does this make business sense?")
        if logic_log:
            for item in logic_log:
                st.markdown(f"""
                <div class="logic-box">
                    <strong>{item['Category']}</strong>: {item['Item']}<br>
                    <span style="color:red">Issue: {item['Issue']}</span><br>
                    <em>💡 Suggestion: {item['Advice']}</em>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.success("✅ Pricing and Menu Structure look logical!")