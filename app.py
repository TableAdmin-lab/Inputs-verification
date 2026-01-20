import streamlit as st
import pandas as pd
import openpyxl
import re
import time

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(
    page_title="Yoco Onboarding Repair Station",
    page_icon="🛠️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- 2. CSS FOR EDITOR ---
st.markdown("""
<style>
    .stApp { background-color: #f4f6f9; }
    .metric-card {
        background-color: white; padding: 15px; border-radius: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05); text-align: center;
    }
    .metric-value { font-size: 28px; font-weight: bold; margin: 0; }
    .metric-label { font-size: 12px; color: #888; text-transform: uppercase; }
    
    /* Highlight the Action Column */
    div[data-testid="stDataFrame"] table tbody tr td:first-child {
        font-weight: bold;
        color: #d63384;
        background-color: #fff0f6;
    }
</style>
""", unsafe_allow_html=True)

# --- 3. LOGIC & HELPERS ---

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

        # Identity Check & Setup Validation Column
        target_col = next((c for c in df.columns if unique_col_identifier.lower() in c.lower()), None)
        if target_col:
            df = df[df[target_col].notna()]
            df = df[df[target_col].astype(str).str.strip() != ""]
            df = df[df[target_col].astype(str).str.upper() != "EXAMPLE"]

        offset = header_row_idx + 2 
        df['Row #'] = df.index + offset
        
        # Init Error Column
        df['🔴 ACTION REQUIRED'] = "" 
        
        # Move Key Columns to Front
        cols = ['Row #', '🔴 ACTION REQUIRED'] + [c for c in df.columns if c not in ['Row #', '🔴 ACTION REQUIRED']]
        df = df[cols]
        
        return df, None
    except Exception as e:
        return None, str(e)

# --- 4. MAIN APP ---
st.title("🛠️ Yoco Data Repair Station")
st.markdown("Upload your file. This tool will extract **only the rows that need fixing** so you can see the full context.")

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
    
    # Store "Bad DataFrames" to display editors later
    bad_data_tables = {} 

    # --- PHASE 1: STOCK (Source of Truth) ---
    if "Stock Items(RAW MATERIALS)" in visible_sheets:
        df_stock, err = get_clean_data(uploaded_file, "Stock Items(RAW MATERIALS)", "RAW MATERIAL Product Name")
        if df_stock is not None:
            # Build Source of Truth
            for name in df_stock["RAW MATERIAL Product Name"].dropna().astype(str):
                valid_ingredients_set.add(normalize_name(name))
            
            # Validate Rows
            if "Cost Price" in df_stock.columns:
                for idx, row in df_stock.iterrows():
                    issues = []
                    if pd.isna(row["Cost Price"]): issues.append("Missing Cost Price")
                    
                    if issues:
                        df_stock.at[idx, '🔴 ACTION REQUIRED'] = " & ".join(issues)
                        quality_score -= PENALTY_CRITICAL
                        total_errors += 1
            
            # Filter Bad Rows
            bad_rows = df_stock[df_stock['🔴 ACTION REQUIRED'] != ""]
            if not bad_rows.empty:
                bad_data_tables["Stock Items"] = bad_rows

    # --- PHASE 2: MANUFACTURED ---
    if "MANUFACTURED PRODUCTS" in visible_sheets:
        df_man, err = get_clean_data(uploaded_file, "MANUFACTURED PRODUCTS", "MANUFACTURED Product Name")
        if df_man is not None:
            for name in df_man["MANUFACTURED Product Name"].dropna().astype(str):
                valid_ingredients_set.add(normalize_name(name))

    # --- PHASE 3: PRODUCTS (Finished Goods) ---
    if "Products(Finished Goods)" in visible_sheets:
        df_prod, err = get_clean_data(uploaded_file, "Products(Finished Goods)", "Product Name")
        if df_prod is not None:
            required = ["Selling Price (incl vat)", "Menu", "Menu Category", "Preparation Locations"]
            
            for idx, row in df_prod.iterrows():
                issues = []
                # Check Missing Fields
                for col in required:
                    if col in df_prod.columns:
                        if pd.isna(row[col]) or str(row[col]).strip() == "":
                            issues.append(f"Missing {col}")
                
                # Check Logic (Negative Margin)
                if "Selling Price (incl vat)" in df_prod.columns and "Cost Price" in df_prod.columns:
                    try:
                        sell = float(row["Selling Price (incl vat)"])
                        cost = float(row["Cost Price"]) if pd.notna(row["Cost Price"]) else 0
                        if sell > 0 and cost > sell:
                            issues.append(f"Negative Margin (Cost R{cost} > Sell R{sell})")
                    except: pass

                if issues:
                    df_prod.at[idx, '🔴 ACTION REQUIRED'] = " & ".join(issues)
                    quality_score -= PENALTY_CRITICAL
                    total_errors += 1
            
            bad_rows = df_prod[df_prod['🔴 ACTION REQUIRED'] != ""]
            if not bad_rows.empty:
                bad_data_tables["Products"] = bad_rows

    # --- PHASE 4: RECIPES ---
    if "Products Recipes" in visible_sheets:
        df_rec, err = get_clean_data(uploaded_file, "Products Recipes", "RAW MATERIALS")
        col_ing = "RAW MATERIALS / MANUFACTURED PRODUCT NAME"
        
        if df_rec is not None:
            if col_ing not in df_rec.columns:
                # Try finding fuzzy match
                match = [c for c in df_rec.columns if "RAW MATERIAL" in c.upper() and "NAME" in c.upper()]
                if match: col_ing = match[0]

            if col_ing in df_rec.columns:
                for idx, row in df_rec.iterrows():
                    issues = []
                    ing = normalize_name(row[col_ing])
                    if ing and ing not in valid_ingredients_set:
                        issues.append(f"Ghost Item: '{row[col_ing]}' (Not in Stock)")
                    
                    if issues:
                        df_rec.at[idx, '🔴 ACTION REQUIRED'] = " & ".join(issues)
                        quality_score -= PENALTY_CRITICAL
                        total_errors += 1
            
                bad_rows = df_rec[df_rec['🔴 ACTION REQUIRED'] != ""]
                if not bad_rows.empty:
                    bad_data_tables["Recipes"] = bad_rows

    # --- PHASE 5: EMPLOYEES ---
    if "Employee List" in visible_sheets:
        df_emp, err = get_clean_data(uploaded_file, "Employee List", "Employee Name")
        if df_emp is not None and "Login Code" in df_emp.columns:
            for idx, row in df_emp.iterrows():
                issues = []
                code = str(row["Login Code"]).strip().replace('.0','')
                if not code.isdigit() or len(code) < 4:
                    issues.append(f"Invalid PIN '{code}'")
                
                if issues:
                    df_emp.at[idx, '🔴 ACTION REQUIRED'] = " & ".join(issues)
                    quality_score -= PENALTY_CRITICAL
                    total_errors += 1
            
            bad_rows = df_emp[df_emp['🔴 ACTION REQUIRED'] != ""]
            if not bad_rows.empty:
                bad_data_tables["Employees"] = bad_rows

    # ================= UI DISPLAY =================
    
    # 1. METRICS
    quality_score = max(0, int(quality_score))
    c1, c2, c3 = st.columns(3)
    c1.metric("Data Quality", f"{quality_score}%", delta="Perfect" if quality_score==100 else "-Issues")
    c2.metric("Rows to Fix", total_errors, delta_color="inverse")
    c3.metric("Clean Rows", "Hidden")

    st.divider()

    # 2. INTERACTIVE EDITORS
    if bad_data_tables:
        st.warning("### 📝 Interactive Repair Station")
        st.markdown("Below are **ONLY** the rows that have errors. Use this view to find the row in your Excel file, or verify the Headers.")
        
        # Create tabs for each sheet that has errors
        sheet_tabs = st.tabs(list(bad_data_tables.keys()))
        
        for i, sheet_name in enumerate(bad_data_tables.keys()):
            with sheet_tabs[i]:
                df_show = bad_data_tables[sheet_name]
                
                st.caption(f"Found {len(df_show)} rows needing attention in '{sheet_name}'.")
                
                # THE EDITOR
                # We disable 'Row #' and 'ACTION' from editing so user focuses on data
                edited_df = st.data_editor(
                    df_show,
                    use_container_width=True,
                    num_rows="fixed",
                    disabled=["Row #", "🔴 ACTION REQUIRED"],
                    hide_index=True
                )
                
                # Download Button for this specific filtered list
                csv = df_show.to_csv(index=False).encode('utf-8')
                st.download_button(
                    f"📥 Download '{sheet_name}' Fix List",
                    csv,
                    f"fix_list_{sheet_name}.csv",
                    "text/csv"
                )

    else:
        st.balloons()
        st.success("## 🎉 Amazing! No errors found.")
        st.markdown("Your file passed all validation checks. You are ready to upload to Yoco.")

else:
    st.info("Waiting for file...")