import streamlit as st
import pandas as pd
import openpyxl

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Yoco Onboarding Verifier", page_icon="🛡️", layout="wide")

# --- CSS STYLING ---
st.markdown("""
<style>
    .stDataFrame { border: 1px solid #ddd; border-radius: 5px; }
    .score-card { 
        padding: 20px; 
        border-radius: 10px; 
        text-align: center; 
        border: 2px solid #eee;
    }
    .good { background-color: #d4edda; color: #155724; border-color: #c3e6cb; }
    .average { background-color: #fff3cd; color: #856404; border-color: #ffeeba; }
    .bad { background-color: #f8d7da; color: #721c24; border-color: #f5c6cb; }
</style>
""", unsafe_allow_html=True)

# --- HELPER: GET VISIBLE SHEETS ONLY ---
def get_visible_sheet_names(file):
    """
    Uses openpyxl to check which sheets are actually visible.
    Returns a list of visible sheet names.
    """
    try:
        wb = openpyxl.load_workbook(file, read_only=True)
        visible_sheets = []
        for sheet in wb.worksheets:
            if sheet.sheet_state == 'visible':
                visible_sheets.append(sheet.title)
        return visible_sheets
    except Exception as e:
        return []

# --- HELPER: CLEAN DATA LOADER ---
def get_clean_data(file, sheet_name, unique_col_identifier):
    """
    1. Finds the true header row (scans first 20 rows).
    2. Strips whitespace from column names (Fixes KeyError).
    3. Finds the last 'EXAMPLE' row and slices data below it.
    """
    try:
        # Step A: Find the Header Row
        # We read without a header first to scan the raw content
        df_scan = pd.read_excel(file, sheet_name=sheet_name, header=None, nrows=20)
        
        header_row_idx = None
        for i, row in df_scan.iterrows():
            # Check if row contains the identifier (case insensitive)
            row_str = row.astype(str).str.replace(r'\s+', ' ', regex=True).str.strip()
            if row_str.str.contains(unique_col_identifier, case=False, na=False).any():
                header_row_idx = i
                break
        
        if header_row_idx is None:
            return None, f"Could not find header containing '{unique_col_identifier}'"

        # Step B: Load data with the correct header
        df = pd.read_excel(file, sheet_name=sheet_name, header=header_row_idx)
        
        # --- CRITICAL FIX: STRIP WHITESPACE FROM COLUMNS ---
        # This fixes the error where 'Cost Price ' (with space) crashes the app
        df.columns = df.columns.astype(str).str.strip()

        # Step C: Find the last "EXAMPLE" row
        last_example_idx = -1
        # Check the first 15 rows of the loaded dataframe
        for i in range(min(15, len(df))):
            row_values = df.iloc[i].astype(str).str.upper()
            # If any cell in the row says "EXAMPLE"
            if row_values.str.contains("EXAMPLE").any():
                last_example_idx = i
        
        # Step D: Slice the data (Keep only rows AFTER the last example)
        client_data = df.iloc[last_example_idx+1:].copy()
        
        # Create a helper column for the user to find the row in Excel
        # Logic: Header Row Index + Data Index + 1 (0-based) + 1 (Excel is 1-based)
        offset = header_row_idx + 2 
        client_data['__excel_row__'] = client_data.index + offset
        
        return client_data, None

    except Exception as e:
        return None, str(e)

# --- MAIN APP ---
st.title("🛡️ Yoco Sheet Verifier")
st.markdown("Upload your Excel sheet. Hidden sheets are ignored. Examples are ignored.")

uploaded_file = st.file_uploader("", type=["xlsx"])

if uploaded_file:
    # 1. Identify Visible Sheets
    visible_sheets = get_visible_sheet_names(uploaded_file)
    if not visible_sheets:
        st.error("Could not read workbook. Are all sheets hidden?")
        st.stop()
        
    st.write(f"**Scanning Visible Sheets:** {', '.join(visible_sheets)}")
    
    # 2. Init Scoring & Logs
    quality_score = 100
    error_log = []
    
    # Penalties
    PENALTY_CRITICAL = 5
    PENALTY_MINOR = 1
    
    # Source of Truth Container
    stock_items_set = set()

    # ==========================================
    # CHECK 1: STOCK ITEMS (Must exist for recipes to work)
    # ==========================================
    if "Stock Items(RAW MATERIALS)" in visible_sheets:
        df_stock, err = get_clean_data(uploaded_file, "Stock Items(RAW MATERIALS)", "RAW MATERIAL Product Name")
        
        if df_stock is not None:
            # Build the master list of ingredients
            stock_items_set = set(df_stock["RAW MATERIAL Product Name"].dropna().astype(str).str.strip())
            
            if "Cost Price" in df_stock.columns:
                for _, row in df_stock.iterrows():
                    val = row["Cost Price"]
                    if pd.isna(val) or str(val).strip() == "":
                        quality_score -= PENALTY_CRITICAL
                        error_log.append({
                            "Severity": "Critical",
                            "Sheet": "Stock Items",
                            "Row": row['__excel_row__'],
                            "Column": "Cost Price",
                            "Issue": "Missing Cost Price",
                            "Fix": "Enter a value (e.g. 15.50)"
                        })

    # ==========================================
    # CHECK 2: EMPLOYEES
    # ==========================================
    if "Employee List" in visible_sheets:
        df_emp, err = get_clean_data(uploaded_file, "Employee List", "Employee Name")
        
        if df_emp is not None and "Login Code" in df_emp.columns:
            for _, row in df_emp.iterrows():
                code = str(row["Login Code"]).strip()
                if code.endswith(".0"): code = code[:-2] # Handle Excel float conversion
                
                if not code.isdigit():
                    quality_score -= PENALTY_MINOR
                    error_log.append({
                        "Severity": "Warning",
                        "Sheet": "Employee List",
                        "Row": row['__excel_row__'],
                        "Column": "Login Code",
                        "Issue": f"Invalid PIN '{code}'",
                        "Fix": "Use numbers only (4 digits)"
                    })
                elif len(code) < 4:
                    quality_score -= PENALTY_MINOR
                    error_log.append({
                        "Severity": "Warning",
                        "Sheet": "Employee List",
                        "Row": row['__excel_row__'],
                        "Column": "Login Code",
                        "Issue": f"PIN '{code}' is too short",
                        "Fix": "Pad with zeros (e.g. 0012)"
                    })

    # ==========================================
    # CHECK 3: PRODUCTS
    # ==========================================
    if "Products(Finished Goods)" in visible_sheets:
        df_prod, err = get_clean_data(uploaded_file, "Products(Finished Goods)", "Product Name")
        
        if df_prod is not None and "Selling Price (incl vat)" in df_prod.columns:
            for _, row in df_prod.iterrows():
                price = row["Selling Price (incl vat)"]
                
                if pd.isna(price):
                    quality_score -= PENALTY_CRITICAL
                    error_log.append({
                        "Severity": "Critical",
                        "Sheet": "Products",
                        "Row": row['__excel_row__'],
                        "Column": "Selling Price",
                        "Issue": "Missing Price",
                        "Fix": "Enter a numeric value"
                    })
                # Check if it contains letters (e.g. R50.00)
                elif isinstance(price, str) and not price.replace('.','',1).isdigit():
                    quality_score -= PENALTY_CRITICAL
                    error_log.append({
                        "Severity": "Critical",
                        "Sheet": "Products",
                        "Row": row['__excel_row__'],
                        "Column": "Selling Price",
                        "Issue": f"Invalid format '{price}'",
                        "Fix": "Remove 'R' or spaces. Use numbers only."
                    })

    # ==========================================
    # CHECK 4: RECIPES (Ghost Inventory)
    # ==========================================
    if "Products Recipes" in visible_sheets:
        # We search for "RAW MATERIALS" to find header
        df_rec, err = get_clean_data(uploaded_file, "Products Recipes", "RAW MATERIALS")
        
        # The specific column that failed previously
        col_ing_name = "RAW MATERIALS / MANUFACTURED PRODUCT NAME"
        
        if df_rec is not None:
            if col_ing_name not in df_rec.columns:
                # Fallback: Try to find a column that looks similar
                candidates = [c for c in df_rec.columns if "RAW MATERIAL" in c.upper()]
                if candidates:
                    col_ing_name = candidates[0]
                else:
                    st.warning(f"⚠️ Could not verify recipes. Column '{col_ing_name}' not found.")
                    col_ing_name = None

            if col_ing_name and stock_items_set:
                for _, row in df_rec.iterrows():
                    ing = str(row[col_ing_name]).strip()
                    
                    if ing == "nan" or ing == "": continue
                    
                    if ing not in stock_items_set:
                        quality_score -= PENALTY_CRITICAL
                        error_log.append({
                            "Severity": "Critical",
                            "Sheet": "Recipes",
                            "Row": row['__excel_row__'],
                            "Column": "Ingredient",
                            "Issue": f"Ghost Item: '{ing}'",
                            "Fix": "Spelling must match Stock Sheet EXACTLY"
                        })

    # ==========================================
    # DISPLAY DASHBOARD
    # ==========================================
    quality_score = max(0, int(quality_score))
    
    # 1. Score Card
    col1, col2 = st.columns([1, 3])
    with col1:
        color = "good" if quality_score > 80 else "average" if quality_score > 50 else "bad"
        st.markdown(f"""
        <div class="score-card {color}">
            <h3>Quality Score</h3>
            <h1 style="font-size: 50px; margin:0;">{quality_score}</h1>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        if quality_score == 100:
            st.success("🌟 Perfect! File is ready for upload.")
        elif quality_score > 80:
            st.warning("⚠️ Good, but check the warnings below.")
        else:
            st.error("🚨 Critical errors found. Do not upload yet.")

    st.divider()

    # 2. Fix List
    if error_log:
        st.subheader("🛠️ Action Plan: Fix these items")
        df_err = pd.DataFrame(error_log)
        
        st.dataframe(
            df_err,
            column_config={
                "Severity": st.column_config.TextColumn("Type", width="small"),
                "Row": st.column_config.NumberColumn("Excel Row", format="%d"),
                "Fix": st.column_config.TextColumn("✅ Suggested Fix", width="large"),
            },
            use_container_width=True,
            hide_index=True
        )
        
        # Download
        csv = df_err.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Download Fix List (CSV)", csv, "fix_list.csv", "text/csv")
    elif uploaded_file:
        st.balloons()