import streamlit as st
import pandas as pd
import io

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Yoco Data Verifier", page_icon="🛡️", layout="wide")

# --- CSS FOR ERROR TABLE ---
st.markdown("""
<style>
    .stDataFrame { border: 1px solid #ddd; border-radius: 5px; }
    div[data-testid="stMetricValue"] { font-size: 24px; }
</style>
""", unsafe_allow_html=True)

# --- 1. INTELLIGENT DATA LOADER ---
def get_clean_data(file, sheet_name, unique_col_name):
    """
    1. Scans the sheet to find the Header row.
    2. Scans BELOW the header to find where 'EXAMPLE' rows end.
    3. Returns only the CLIENT DATA after the examples.
    """
    try:
        # Step A: Find the Header Row
        # Read first 15 rows to find the column name
        df_scan = pd.read_excel(file, sheet_name=sheet_name, header=None, nrows=15)
        
        header_row_idx = None
        for i, row in df_scan.iterrows():
            # Look for the unique column name (case insensitive)
            if row.astype(str).str.contains(unique_col_name, case=False, na=False).any():
                header_row_idx = i
                break
        
        if header_row_idx is None:
            return None, f"Could not find header column '{unique_col_name}'"

        # Step B: Load data with correct header
        df = pd.read_excel(file, sheet_name=sheet_name, header=header_row_idx)
        
        # Step C: Find where "Client Data" starts
        # We look for the word "EXAMPLE" in the first column
        # We assume client data starts AFTER the last "EXAMPLE" row
        
        last_example_idx = -1
        
        # Check the first few rows for the word "EXAMPLE"
        for i in range(min(10, len(df))):
            first_col_val = str(df.iloc[i, 0]).upper()
            if "EXAMPLE" in first_col_val:
                last_example_idx = i
        
        # Slice the dataframe: Keep everything AFTER the last example
        # (index + 1)
        client_data = df.iloc[last_example_idx+1:].copy()
        
        # Add an "Excel Row Number" helper for the user
        # (Header Index + 1) + (Data Index within df) + (1 for 0-based) + (Rows we skipped)
        # This is an approximation to help users find the error
        offset = header_row_idx + 2 
        client_data['__excel_row__'] = client_data.index + offset
        
        return client_data, None

    except Exception as e:
        return None, str(e)

# --- 2. MAIN APP ---
st.sidebar.title("🛡️ Yoco Verifier")
st.sidebar.info("**Logic Update:** This tool ignores all rows labeled 'EXAMPLE' and only checks data entered below them.")

st.title("🛡️ Yoco Sheet Verifier & Fixer")
st.markdown("Upload your Excel sheet. The tool will generate a **Fix List** for any errors found.")

uploaded_file = st.file_uploader("", type=["xlsx"])

if uploaded_file:
    xls = pd.ExcelFile(uploaded_file)
    all_sheets = xls.sheet_names
    
    # We will collect all errors in this list to show a master table later
    # Format: {'Sheet': '', 'Row': '', 'Column': '', 'Value': '', 'Error': '', 'Suggestion': ''}
    error_log = []
    
    # Store valid data for cross-reference
    stock_items_set = set()

    # ==========================================
    # 1. PROCESS STOCK (Source of Truth)
    # ==========================================
    if "Stock Items(RAW MATERIALS)" in all_sheets:
        df_stock, err = get_clean_data(uploaded_file, "Stock Items(RAW MATERIALS)", "RAW MATERIAL Product Name")
        
        if df_stock is not None and not df_stock.empty:
            # Populate Source of Truth
            stock_items_set = set(df_stock["RAW MATERIAL Product Name"].dropna().astype(str).str.strip())
            
            # Check Cost Prices
            if "Cost Price " in df_stock.columns:
                for _, row in df_stock.iterrows():
                    cost = row["Cost Price "]
                    if pd.isna(cost) or str(cost).strip() == "":
                        error_log.append({
                            "Sheet": "Stock Items",
                            "Excel Row": row['__excel_row__'],
                            "Column": "Cost Price",
                            "Value": "Empty",
                            "Issue": "Missing Cost Price",
                            "Suggestion": "Enter a number (e.g. 10.50)"
                        })

    # ==========================================
    # 2. PROCESS EMPLOYEES
    # ==========================================
    if "Employee List" in all_sheets:
        df_emp, err = get_clean_data(uploaded_file, "Employee List", "Employee Name")
        
        if df_emp is not None:
            for _, row in df_emp.iterrows():
                # Validate Login Code
                if "Login Code" in df_emp.columns:
                    code = str(row["Login Code"]).strip()
                    # Remove decimals if they exist (e.g. 1234.0 -> 1234)
                    if code.endswith('.0'): code = code[:-2]
                    
                    if not code.isdigit():
                         error_log.append({
                            "Sheet": "Employee List",
                            "Excel Row": row['__excel_row__'],
                            "Column": "Login Code",
                            "Value": code,
                            "Issue": "Contains letters or symbols",
                            "Suggestion": "Must be numbers only"
                        })
                    elif len(code) < 4:
                        error_log.append({
                            "Sheet": "Employee List",
                            "Excel Row": row['__excel_row__'],
                            "Column": "Login Code",
                            "Value": code,
                            "Issue": "PIN is too short",
                            "Suggestion": f"Pad with zeros (e.g. change {code} to 00{code})"
                        })

    # ==========================================
    # 3. PROCESS PRODUCTS
    # ==========================================
    if "Products(Finished Goods)" in all_sheets:
        df_prod, err = get_clean_data(uploaded_file, "Products(Finished Goods)", "Product Name")
        
        if df_prod is not None:
            for _, row in df_prod.iterrows():
                # Validate Price
                if "Selling Price (incl vat)" in df_prod.columns:
                    price = row["Selling Price (incl vat)"]
                    if pd.isna(price):
                        error_log.append({
                            "Sheet": "Products",
                            "Excel Row": row['__excel_row__'],
                            "Column": "Selling Price",
                            "Value": "Empty",
                            "Issue": "Missing Price",
                            "Suggestion": "Enter a value (e.g. 25)"
                        })
                    elif isinstance(price, str) and not price.replace('.','',1).isdigit():
                        error_log.append({
                            "Sheet": "Products",
                            "Excel Row": row['__excel_row__'],
                            "Column": "Selling Price",
                            "Value": price,
                            "Issue": "Text found in price field",
                            "Suggestion": "Remove 'R' or currency symbols."
                        })

    # ==========================================
    # 4. PROCESS RECIPES (The Logic Check)
    # ==========================================
    if "Products Recipes" in all_sheets:
        df_rec, err = get_clean_data(uploaded_file, "Products Recipes", "RAW MATERIALS")
        
        if df_rec is not None and stock_items_set:
            col_ing = "RAW MATERIALS / MANUFACTURED PRODUCT NAME"
            
            for _, row in df_rec.iterrows():
                ingredient = str(row[col_ing]).strip()
                
                # Skip empty rows or NaNs
                if ingredient == "nan" or ingredient == "":
                    continue
                    
                if ingredient not in stock_items_set:
                    error_log.append({
                            "Sheet": "Recipes",
                            "Excel Row": row['__excel_row__'],
                            "Column": "Ingredient Name",
                            "Value": ingredient,
                            "Issue": "Ghost Item (Not in Stock List)",
                            "Suggestion": f"Check spelling. Does it match Stock Sheet exactly?"
                        })

    # ==========================================
    # OUTPUT DASHBOARD
    # ==========================================
    
    if not error_log:
        st.balloons()
        st.success("✅ AMAZING! No errors found. This sheet is ready for Yoco.")
    else:
        st.error(f"⚠️ Found {len(error_log)} issues that need fixing.")
        
        # Convert list of dicts to DataFrame
        df_errors = pd.DataFrame(error_log)
        
        # Display as an interactive table
        st.markdown("### 🛠️ Action Plan: Fix these items")
        
        # We use st.data_editor but disabled=True so it looks like a nice grid
        st.dataframe(
            df_errors,
            column_config={
                "Sheet": st.column_config.TextColumn("Tab Name"),
                "Excel Row": st.column_config.NumberColumn("Row #", format="%d"),
                "Value": st.column_config.TextColumn("Current Value", help="What is currently in the cell"),
                "Suggestion": st.column_config.TextColumn("✅ Suggested Fix", width="large"),
            },
            use_container_width=True,
            hide_index=True
        )
        
        st.download_button(
            "📥 Download Error Report (CSV)",
            df_errors.to_csv(index=False),
            "yoco_fix_list.csv",
            "text/csv"
        )

else:
    st.info("Waiting for file upload...")