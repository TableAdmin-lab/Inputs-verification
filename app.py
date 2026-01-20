import streamlit as st
import pandas as pd
import openpyxl
import re
import io
import time
from rapidfuzz import process, fuzz # Requires: pip install rapidfuzz

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(
    page_title="Yoco Repair Station Pro",
    page_icon="🛠️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- 2. CSS STYLING ---
st.markdown("""
<style>
    .stApp { background-color: #f8f9fa; }
    .hero-box {
        background: linear-gradient(90deg, #4b6cb7 0%, #182848 100%);
        padding: 30px; border-radius: 15px; color: white; text-align: center; margin-bottom: 20px;
    }
    .metric-card {
        background-color: white; padding: 20px; border-radius: 10px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05); text-align: center;
        border: 1px solid #e9ecef;
    }
    .metric-val { font-size: 32px; font-weight: bold; margin: 0; color: #2d3748; }
    
    /* Highlight Columns in Editor */
    div[data-testid="stDataFrame"] table tbody tr td:nth-child(2) {
        font-weight: bold; color: #e53e3e; background-color: #fff5f5; /* Action Required Red */
    }
    div[data-testid="stDataFrame"] table tbody tr td:nth-child(3) {
        font-weight: bold; color: #38a169; background-color: #f0fff4; /* Suggestion Green */
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
        
        # Init Tracking Columns
        df['🔴 ACTION REQUIRED'] = "" 
        df['✨ SUGGESTED FIX'] = ""
        
        return df, None
    except Exception as e: return None, str(e)

# --- 4. AUTO-FIX ENGINE ---
def generate_autofixed_file(original_file, bad_data_tables):
    """
    Opens original file and applies the '✨ SUGGESTED FIX' values to the cells.
    """
    wb = openpyxl.load_workbook(original_file)
    
    # Map Sheet Names to DataFrames
    for sheet_name, df_errors in bad_data_tables.items():
        if sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            
            # Find column headers map
            col_map = {}
            for r in range(1, 20):
                for c in range(1, ws.max_column + 1):
                    val = ws.cell(row=r, column=c).value
                    if val: col_map[str(val).strip()] = c
            
            # Iterate errors and apply fixes
            for idx, row in df_errors.iterrows():
                excel_row = row['Row #']
                suggestion = row['✨ SUGGESTED FIX']
                
                # We store the target column name in a hidden way or infer it
                # For this demo, we infer based on the error message (simple parsing)
                action = row['🔴 ACTION REQUIRED']
                
                target_col_idx = None
                
                # Logic to find which column to update based on the error
                if "Ghost Item" in action:
                    # It's an ingredient column. We assume "RAW MATERIALS..."
                    # In a full app, we'd pass the column name explicitly.
                    # Fallback search for ingredient column:
                    for k, v in col_map.items():
                        if "RAW MATERIAL" in k.upper(): target_col_idx = v; break
                elif "Price" in action:
                    for k, v in col_map.items(): 
                        if "Price" in k: target_col_idx = v; break
                elif "PIN" in action:
                    for k, v in col_map.items():
                        if "Login" in k: target_col_idx = v; break
                
                # Apply Fix if we have a target and a suggestion
                if target_col_idx and suggestion and suggestion != "":
                    try:
                        # Convert numeric strings back to numbers
                        if str(suggestion).replace('.','',1).isdigit():
                            ws.cell(row=int(excel_row), column=target_col_idx).value = float(suggestion)
                        else:
                            ws.cell(row=int(excel_row), column=target_col_idx).value = suggestion
                    except: pass

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output

# --- 5. MAIN APP ---
st.markdown("""
<div class="hero-box">
    <h1>🛠️ Yoco Data Doctor</h1>
    <p>Detects errors and offers <b>Auto-Fix Suggestions</b> for prices, spelling, and missing data.</p>
</div>
""", unsafe_allow_html=True)

uploaded_file = st.file_uploader("", type=["xlsx"])

if uploaded_file:
    # 1. VISIBLE SHEETS
    try:
        wb_temp = openpyxl.load_workbook(uploaded_file, read_only=True)
        visible_sheets = [s.title for s in wb_temp.worksheets if s.sheet_state == 'visible']
    except: visible_sheets = []

    if not visible_sheets:
        st.error("No visible sheets found.")
        st.stop()

    # INIT
    quality_score = 100
    valid_ingredients = set()
    bad_data_tables = {}
    
    with st.spinner("Diagnosing data health..."):
        
        # --- A. BUILD INGREDIENT LIST ---
        if "Stock Items(RAW MATERIALS)" in visible_sheets:
            df, _ = get_clean_data(uploaded_file, "Stock Items(RAW MATERIALS)", "RAW MATERIAL Product Name")
            if df is not None:
                for n in df["RAW MATERIAL Product Name"].dropna().astype(str): 
                    valid_ingredients.add(normalize_name(n))

        if "MANUFACTURED PRODUCTS" in visible_sheets:
            df, _ = get_clean_data(uploaded_file, "MANUFACTURED PRODUCTS", "MANUFACTURED Product Name")
            if df is not None:
                for n in df["MANUFACTURED Product Name"].dropna().astype(str): 
                    valid_ingredients.add(normalize_name(n))

        # --- B. CHECK PRODUCTS (Formatting & Pricing) ---
        if "Products(Finished Goods)" in visible_sheets:
            df_prod, _ = get_clean_data(uploaded_file, "Products(Finished Goods)", "Product Name")
            if df_prod is not None:
                for i, row in df_prod.iterrows():
                    issues = []
                    suggestion = ""
                    
                    # 1. Price Format Check
                    price = row.get("Selling Price (incl vat)")
                    if pd.notna(price):
                        # Regex to check if it has non-numeric chars
                        if re.search(r'[a-zA-Z\s]', str(price)):
                            issues.append(f"Bad Format: '{price}'")
                            # FIX: Strip everything except numbers and dots
                            suggestion = re.sub(r'[^0-9.]', '', str(price))
                    
                    # 2. Casing Check (e.g. "coke")
                    name = str(row.get("Product Name", ""))
                    if name.islower():
                        issues.append("Lowercase Name")
                        suggestion = name.title() # Auto-Fix to Title Case
                    
                    if issues:
                        df_prod.at[i, '🔴 ACTION REQUIRED'] = ", ".join(issues)
                        df_prod.at[i, '✨ SUGGESTED FIX'] = suggestion
                        quality_score -= 5
                
                bad = df_prod[df_prod['🔴 ACTION REQUIRED'] != ""]
                if not bad.empty: bad_data_tables["Products"] = bad

        # --- C. CHECK RECIPES (Ghost Items) ---
        if "Products Recipes" in visible_sheets:
            df_rec, _ = get_clean_data(uploaded_file, "Products Recipes", "RAW MATERIALS")
            if df_rec is not None:
                # Find Ingredient Column
                col_ing = next((c for c in df_rec.columns if "RAW MATERIAL" in c.upper() and "NAME" in c.upper()), None)
                
                if col_ing:
                    for i, row in df_rec.iterrows():
                        ing = normalize_name(row[col_ing])
                        if ing and ing not in valid_ingredients:
                            # FUZZY MATCH LOGIC
                            match = process.extractOne(ing, valid_ingredients, scorer=fuzz.WRatio)
                            suggestion = ""
                            issue_text = f"Ghost Item: '{row[col_ing]}'"
                            
                            # If > 85% match confidence
                            if match and match[1] > 85:
                                suggestion = match[0]
                                issue_text += " (Typo?)"
                            
                            df_rec.at[i, '🔴 ACTION REQUIRED'] = issue_text
                            df_rec.at[i, '✨ SUGGESTED FIX'] = suggestion
                            quality_score -= 10
                    
                    bad = df_rec[df_rec['🔴 ACTION REQUIRED'] != ""]
                    if not bad.empty: bad_data_tables["Recipes"] = bad

        # --- D. CHECK EMPLOYEES (PINs) ---
        if "Employee List" in visible_sheets:
            df_emp, _ = get_clean_data(uploaded_file, "Employee List", "Employee Name")
            if df_emp is not None and "Login Code" in df_emp.columns:
                for i, row in df_emp.iterrows():
                    code = str(row["Login Code"]).strip().replace('.0','')
                    if len(code) < 4 and code.isdigit():
                        df_emp.at[i, '🔴 ACTION REQUIRED'] = "PIN too short"
                        df_emp.at[i, '✨ SUGGESTED FIX'] = code.zfill(4) # Pad with zeros
                        quality_score -= 5
                
                bad = df_emp[df_emp['🔴 ACTION REQUIRED'] != ""]
                if not bad.empty: bad_data_tables["Employees"] = bad

    # --- 6. DASHBOARD ---
    
    quality_score = max(0, int(quality_score))
    
    c1, c2 = st.columns([1,3])
    with c1:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-val" style="color: {'#38a169' if quality_score > 80 else '#e53e3e'}">{quality_score}%</div>
            <div class="metric-lbl">Data Health</div>
        </div>
        """, unsafe_allow_html=True)
        
        # MAGIC BUTTON
        if quality_score < 100:
            st.markdown("<br>", unsafe_allow_html=True)
            st.info("💡 **Tip:** We can auto-correct formatting, casing, and typos for you.")
            
            # Generate Auto-Fixed File
            fixed_file = generate_autofixed_file(uploaded_file, bad_data_tables)
            st.download_button(
                "🪄 Download Auto-Corrected File",
                data=fixed_file,
                file_name="Yoco_AutoFixed.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
                use_container_width=True
            )

    with c2:
        if bad_data_tables:
            st.warning(f"Found {sum([len(df) for df in bad_data_tables.values()])} rows requiring attention.")
            
            tabs = st.tabs(list(bad_data_tables.keys()))
            for i, (sheet, df) in enumerate(bad_data_tables.items()):
                with tabs[i]:
                    # REORDER COLUMNS FOR UI
                    # Put Suggestion next to Action
                    cols = ['Row #', '🔴 ACTION REQUIRED', '✨ SUGGESTED FIX'] + [c for c in df.columns if c not in ['Row #', '🔴 ACTION REQUIRED', '✨ SUGGESTED FIX']]
                    
                    st.data_editor(
                        df[cols],
                        hide_index=True,
                        use_container_width=True,
                        disabled=cols # Read-only view
                    )
        else:
            st.success("🎉 No Errors! Your file is perfect.")
            st.balloons()