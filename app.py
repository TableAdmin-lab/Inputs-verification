import streamlit as st
import pandas as pd
import openpyxl
import re
import time

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(
    page_title="Yoco Onboarding Assistant",
    page_icon="✨",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 2. CUSTOM CSS (THE VISUAL MAGIC) ---
st.markdown("""
<style>
    /* Main Background */
    .stApp {
        background-color: #F8F9FA;
    }
    
    /* Score Cards */
    .metric-card {
        background-color: white;
        padding: 20px;
        border-radius: 15px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        text-align: center;
        border: 1px solid #E9ECEF;
    }
    .metric-value {
        font-size: 36px;
        font-weight: bold;
        margin: 0;
    }
    .metric-label {
        font-size: 14px;
        color: #6C757D;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    
    /* Severity Colors */
    .score-good { color: #28a745; border-top: 5px solid #28a745; }
    .score-avg { color: #ffc107; border-top: 5px solid #ffc107; }
    .score-bad { color: #dc3545; border-top: 5px solid #dc3545; }

    /* Logic Box */
    .logic-box {
        background-color: #fff;
        border-left: 4px solid #6610f2;
        padding: 15px;
        margin-bottom: 10px;
        border-radius: 4px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
</style>
""", unsafe_allow_html=True)

# --- 3. LOGIC FUNCTIONS (SAME ROBUST LOGIC AS BEFORE) ---

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
    except:
        return []

def get_clean_data(file, sheet_name, unique_col_identifier):
    try:
        # Deep Scan for Header
        df_scan = pd.read_excel(file, sheet_name=sheet_name, header=None, nrows=50)
        matching_rows = []
        for i, row in df_scan.iterrows():
            row_str = row.astype(str).str.replace(r'\s+', ' ', regex=True).str.strip()
            if row_str.str.contains(unique_col_identifier, case=False, na=False).any():
                matching_rows.append(i)
        
        if not matching_rows: return None, f"Could not find header '{unique_col_identifier}'"

        # Last Header Wins
        header_row_idx = matching_rows[-1]
        df = pd.read_excel(file, sheet_name=sheet_name, header=header_row_idx)
        df.columns = df.columns.astype(str).str.strip()

        # Identity Check
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

def check_restaurant_logic(df_prod, df_mod):
    logic_issues = []
    
    # Costing Logic
    if df_prod is not None and "Selling Price (incl vat)" in df_prod.columns:
        cost_col = next((c for c in df_prod.columns if "Cost Price" in c), None)
        if cost_col:
            for _, row in df_prod.iterrows():
                try:
                    sell = float(row["Selling Price (incl vat)"])
                    cost = float(row[cost_col]) if pd.notna(row[cost_col]) else 0.0
                    
                    if sell > 0 and cost > 0:
                        gp = ((sell - cost) / sell) * 100
                        if gp < 0:
                            logic_issues.append({
                                "Category": "💰 Profitability",
                                "Item": row.iloc[0], 
                                "Issue": f"Negative Margin ({gp:.1f}%)",
                                "Advice": f"Cost (R{cost}) > Sell (R{sell})."
                            })
                        elif gp < 15:
                            logic_issues.append({
                                "Category": "💰 Profitability",
                                "Item": row.iloc[0],
                                "Issue": f"Low Margin ({gp:.1f}%)",
                                "Advice": "Margin below 15%. Confirm Cost Price."
                            })
                except: pass 

    # Modifier Logic
    if df_mod is not None and not df_mod.empty:
        mod_col = next((c for c in df_mod.columns if "Modifier Group Name" in c), None)
        opt_col = next((c for c in df_mod.columns if "Options" in c), None)
        
        if mod_col:
            for _, row in df_mod.iterrows():
                group_name = str(row[mod_col]).upper()
                option_name = str(row[opt_col]).upper() if opt_col else ""
                
                if any(k in group_name for k in ["SIZE", "VOLUME"]) or \
                   any(k in option_name for k in ["SMALL", "MEDIUM", "LARGE"]):
                    logic_issues.append({
                        "Category": "⚠️ Menu Structure",
                        "Item": row[mod_col],
                        "Issue": "Sizes used as Modifiers",
                        "Advice": "Use VARIANTS for sizes to track stock."
                    })
                    break 

    return logic_issues

# --- 4. SIDEBAR ---
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/c/c3/Python-logo-notext.svg/120px-Python-logo-notext.svg.png", width=60)
    st.title("Yoco Assistant")
    st.info("""
    **👋 Welcome!**
    
    This tool helps you verify your Yoco Onboarding Sheet before submission.
    
    **It automatically:**
    1. Skips Example rows
    2. Ignores Hidden sheets
    3. Checks for "Ghost" ingredients
    4. Verifies Margins & Logic
    """)
    st.markdown("---")
    st.caption("v5.0 | Enhanced UI")

# --- 5. MAIN DASHBOARD ---
st.title("✨ Yoco Sheet Verifier")
st.markdown("##### Ensure your menu is perfect before upload.")

uploaded_file = st.file_uploader("", type=["xlsx"], help="Drag and drop your Yoco Excel file here")

if uploaded_file:
    # --- UI: PROGRESS BAR ---
    progress_text = "Analyzing file structure..."
    my_bar = st.progress(0, text=progress_text)
    
    visible_sheets = get_visible_sheet_names(uploaded_file)
    if not visible_sheets:
        st.error("❌ No visible sheets found. Please unhide your data tabs.")
        st.stop()
        
    time.sleep(0.5) # Slight delay for UX feel
    my_bar.progress(30, text="Cleaning data & removing examples...")

    # --- INIT VARIABLES ---
    quality_score = 100
    error_log = []
    logic_log = []
    valid_ingredients_set = set()
    PENALTY_CRITICAL = 10
    PENALTY_MINOR = 1
    
    df_prod_global = None
    df_mod_global = None

    # --- PROCESSING ---
    
    # 1. Stock
    if "Stock Items(RAW MATERIALS)" in visible_sheets:
        df_stock, err = get_clean_data(uploaded_file, "Stock Items(RAW MATERIALS)", "RAW MATERIAL Product Name")
        if df_stock is not None:
            if df_stock.empty:
                quality_score = 0
                error_log.append({"Type": "Critical", "Sheet": "Stock", "Row": "-", "Issue": "NO STOCK FOUND", "Fix": "Sheet is empty"})
            else:
                for name in df_stock["RAW MATERIAL Product Name"].dropna().astype(str):
                    valid_ingredients_set.add(normalize_name(name))
                if "Cost Price" in df_stock.columns:
                    for _, row in df_stock.iterrows():
                        if pd.isna(row["Cost Price"]):
                            quality_score -= PENALTY_CRITICAL
                            error_log.append({"Type": "Critical", "Sheet": "Stock", "Row": row['__excel_row__'], "Issue": "Missing Cost Price", "Fix": "Enter value"})
    
    my_bar.progress(60, text="Cross-referencing Recipes...")

    # 2. Manufactured
    if "MANUFACTURED PRODUCTS" in visible_sheets:
        df_man, err = get_clean_data(uploaded_file, "MANUFACTURED PRODUCTS", "MANUFACTURED Product Name")
        if df_man is not None and not df_man.empty:
            for name in df_man["MANUFACTURED Product Name"].dropna().astype(str):
                valid_ingredients_set.add(normalize_name(name))

    # 3. Products
    if "Products(Finished Goods)" in visible_sheets:
        df_prod, err = get_clean_data(uploaded_file, "Products(Finished Goods)", "Product Name")
        df_prod_global = df_prod 
        if df_prod is not None:
            if df_prod.empty:
                quality_score = 0
                error_log.append({"Type": "Critical", "Sheet": "Products", "Row": "-", "Issue": "NO PRODUCTS", "Fix": "Sheet empty"})
            else:
                required_cols = ["Selling Price (incl vat)", "Menu", "Menu Category", "Preparation Locations"]
                for _, row in df_prod.iterrows():
                    for col in required_cols:
                        if col in df_prod.columns:
                            val = row[col]
                            if pd.isna(val) or str(val).strip() == "":
                                quality_score -= PENALTY_CRITICAL
                                error_log.append({"Type": "Critical", "Sheet": "Products", "Row": row['__excel_row__'], "Issue": f"Missing {col}", "Fix": "Required Field"})

    # 4. Recipes
    if "Products Recipes" in visible_sheets:
        df_rec, err = get_clean_data(uploaded_file, "Products Recipes", "RAW MATERIALS")
        col_ing = "RAW MATERIALS / MANUFACTURED PRODUCT NAME"
        if df_rec is not None:
            if col_ing not in df_rec.columns:
                candidates = [c for c in df_rec.columns if "RAW MATERIAL" in c.upper() and "NAME" in c.upper()]
                if candidates: col_ing = candidates[0]
            if col_ing in df_rec.columns and valid_ingredients_set:
                for _, row in df_rec.iterrows():
                    ing = normalize_name(row[col_ing])
                    if ing and ing not in valid_ingredients_set:
                        quality_score -= PENALTY_CRITICAL
                        error_log.append({"Type": "Critical", "Sheet": "Recipes", "Row": row['__excel_row__'], "Issue": f"Ghost Item: '{row[col_ing]}'", "Fix": "Not found in Stock/Manufactured"})

    # 5. Modifiers
    if "Modifers" in visible_sheets:
        df_mod_global, err = get_clean_data(uploaded_file, "Modifers", "Modifier Group Name")
    elif "Modifiers" in visible_sheets:
        df_mod_global, err = get_clean_data(uploaded_file, "Modifiers", "Modifier Group Name")

    # 6. Employees
    if "Employee List" in visible_sheets:
        df_emp, err = get_clean_data(uploaded_file, "Employee List", "Employee Name")
        if df_emp is not None and "Login Code" in df_emp.columns:
             for _, row in df_emp.iterrows():
                code = str(row["Login Code"]).strip().replace('.0','')
                if not code.isdigit() or len(code) < 4:
                    quality_score -= PENALTY_MINOR
                    error_log.append({"Type": "Warning", "Sheet": "Employees", "Row": row['__excel_row__'], "Issue": f"Invalid PIN '{code}'", "Fix": "Must be 4 digits"})

    # Logic Check
    logic_log = check_restaurant_logic(df_prod_global, df_mod_global)
    
    my_bar.progress(100, text="Analysis Complete!")
    time.sleep(0.5)
    my_bar.empty()

    # --- UI: RESULTS DISPLAY ---
    
    quality_score = max(0, int(quality_score))
    
    # Determine Status
    if quality_score == 100:
        status_color = "score-good"
        status_msg = "Excellent"
        status_icon = "🌟"
    elif quality_score > 80:
        status_color = "score-avg"
        status_msg = "Good"
        status_icon = "⚠️"
    else:
        status_color = "score-bad"
        status_msg = "Needs Work"
        status_icon = "🚨"

    st.markdown("### 📊 Analysis Report")
    
    # 3-Column Layout for Metrics
    c1, c2, c3 = st.columns(3)
    
    with c1:
        st.markdown(f"""
        <div class="metric-card {status_color}">
            <p class="metric-label">Quality Score</p>
            <p class="metric-value">{quality_score}/100</p>
            <p>{status_msg}</p>
        </div>
        """, unsafe_allow_html=True)
    
    with c2:
        count_crit = len([e for e in error_log if e['Type'] == 'Critical'])
        st.markdown(f"""
        <div class="metric-card">
            <p class="metric-label">Critical Errors</p>
            <p class="metric-value" style="color: {'#dc3545' if count_crit > 0 else '#28a745'}">{count_crit}</p>
            <p>Issues blocking upload</p>
        </div>
        """, unsafe_allow_html=True)
        
    with c3:
        count_logic = len(logic_log)
        st.markdown(f"""
        <div class="metric-card">
            <p class="metric-label">Logic Suggestions</p>
            <p class="metric-value" style="color: {'#ffc107' if count_logic > 0 else '#28a745'}">{count_logic}</p>
            <p>Business optimizations</p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # --- TABS FOR DETAILS ---
    tab1, tab2, tab3 = st.tabs(["🚨 Fix List (Mandatory)", "🧠 Logic Checks (Optional)", "📥 Download Report"])

    with tab1:
        if error_log:
            df_err = pd.DataFrame(error_log)
            # Use columns for a cleaner look than a raw table
            for index, row in df_err.iterrows():
                with st.expander(f"{row['Sheet']} (Row {row['Row']}): {row['Issue']}", expanded=False):
                    st.error(f"**Problem:** {row['Issue']}")
                    st.success(f"**✅ Fix:** {row['Fix']}")
        else:
            st.balloons()
            st.success("🎉 No syntax errors found! Your file is ready for Yoco.")

    with tab2:
        if logic_log:
            st.info("These items won't break the upload, but they might affect your reporting or operations.")
            for item in logic_log:
                st.markdown(f"""
                <div class="logic-box">
                    <strong>{item['Category']}</strong>: {item['Item']}<br>
                    <span style="color:#d63384">Observation: {item['Issue']}</span><br>
                    <em>💡 Suggestion: {item['Advice']}</em>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.success("✅ Margins and Menu Structure look logical!")

    with tab3:
        st.write("Download the full list of errors to send to your team.")
        if error_log:
            df_err = pd.DataFrame(error_log)
            csv = df_err.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download Error Report (CSV)",
                data=csv,
                file_name="yoco_fix_list.csv",
                mime="text/csv",
            )
        else:
            st.write("Nothing to download - File is perfect!")

else:
    # Empty State with visual guide
    st.info("👆 Please upload your Excel file to begin the analysis.")