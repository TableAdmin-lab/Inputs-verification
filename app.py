import streamlit as st
import pandas as pd
import io

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Yoco Input Verifier", page_icon="✅", layout="wide")

st.title("✅ Yoco Data Verification Tool")
st.markdown("""
This tool checks your **Yoco Input Sheet** for common errors before you submit it.
**Checks performed:**
- Missing required fields (Site Info, Owner details)
- Invalid Employee PINs (must be numbers, often 4 digits)
- Missing Cost Prices
- **Ghost Inventory:** Recipes using ingredients that don't exist in Stock Items
""")

# --- UPLOAD SECTION ---
uploaded_file = st.file_uploader("Upload your Excel file (.xlsx)", type=["xlsx"])

def clean_yoco_header(df, col_name):
    """Helper to find the real header row if it's not row 0"""
    # If the specific column isn't in the first row, look deeper
    if col_name not in df.columns:
        # Try finding the row index where the column exists
        for i, row in df.iterrows():
            if row.astype(str).str.contains(col_name).any():
                # Reload dataframe with this row as header
                new_df = pd.read_excel(uploaded_file, sheet_name=df.name, header=i+1)
                return new_df
    return df

if uploaded_file:
    xls = pd.ExcelFile(uploaded_file)
    
    # Create tabs for the report
    tab1, tab2, tab3 = st.tabs(["🔴 Critical Errors", "⚠️ Warnings", "📋 Data Summary"])
    
    critical_errors = []
    warnings = []
    summary_data = []

    # --- 1. SITE INFO CHECK ---
    if "Site Data Information" in xls.sheet_names:
        df_site = pd.read_excel(uploaded_file, "Site Data Information")
        # Filter out example row
        df_site = df_site[df_site.iloc[:, 0] != "EXAMPLE"]
        
        req_cols = ["Site Name", "Owner Email Address", "Owner Telephone Number"]
        for col in req_cols:
            if col in df_site.columns and df_site[col].isnull().any():
                critical_errors.append(f"**Site Data:** Missing required value in column `{col}`")
        
        if not df_site.empty:
            summary_data.append(f"Site Name: **{df_site.iloc[0].get('Site Name', 'Unknown')}**")

    # --- 2. EMPLOYEE CHECK ---
    if "Employee List" in xls.sheet_names:
        df_emp = pd.read_excel(uploaded_file, "Employee List")
        df_emp = df_emp[df_emp.iloc[:, 0] != "EXAMPLE"]
        
        if "Login Code" in df_emp.columns:
            # Check for non-numeric
            non_nums = df_emp[pd.to_numeric(df_emp["Login Code"], errors='coerce').isna()]
            for _, row in non_nums.iterrows():
                critical_errors.append(f"**Employee List:** Login Code for `{row['Employee Name']}` is not a number.")

            # Check for short PINs (Safety check)
            short_pins = df_emp[df_emp["Login Code"].astype(str).str.len() < 4]
            if not short_pins.empty:
                warnings.append(f"**Employee List:** {len(short_pins)} employees have PINs shorter than 4 digits.")

    # --- 3. PRODUCTS & PRICES CHECK ---
    if "Products(Finished Goods)" in xls.sheet_names:
        df_prod = pd.read_excel(uploaded_file, "Products(Finished Goods)")
        df_prod = df_prod[df_prod.iloc[:, 0] != "EXAMPLE"]
        
        if "Selling Price (incl vat)" in df_prod.columns:
            missing_price = df_prod[pd.to_numeric(df_prod["Selling Price (incl vat)"], errors='coerce').isna()]
            if not missing_price.empty:
                critical_errors.append(f"**Products:** Found {len(missing_price)} products with invalid or missing selling prices.")
        
        summary_data.append(f"Total Products to Import: **{len(df_prod)}**")

    # --- 4. RECIPE VS STOCK CHECK (The Complex One) ---
    if "Products Recipes" in xls.sheet_names and "Stock Items(RAW MATERIALS)" in xls.sheet_names:
        # Load Stock (Handling the weird header rows Yoco sometimes has)
        df_stock = pd.read_excel(uploaded_file, "Stock Items(RAW MATERIALS)", header=None)
        
        # Simple search for the row containing "RAW MATERIAL Product Name"
        header_row_idx = 0
        for i, row in df_stock.iterrows():
            if row.astype(str).str.contains("RAW MATERIAL Product Name").any():
                header_row_idx = i
                break
        
        # Reload with correct header
        df_stock = pd.read_excel(uploaded_file, "Stock Items(RAW MATERIALS)", header=header_row_idx)
        df_stock = df_stock[df_stock["RAW MATERIAL Product Name"] != "EXAMPLES"]
        stock_list = set(df_stock["RAW MATERIAL Product Name"].dropna().astype(str).str.strip())

        # Load Recipes
        df_recipes = pd.read_excel(uploaded_file, "Products Recipes", header=None)
        # Find recipe header
        rec_header_idx = 0
        for i, row in df_recipes.iterrows():
            if row.astype(str).str.contains("RAW MATERIALS / MANUFACTURED PRODUCT NAME").any():
                rec_header_idx = i
                break
        
        df_recipes = pd.read_excel(uploaded_file, "Products Recipes", header=rec_header_idx)
        df_recipes = df_recipes[df_recipes.iloc[:, 0] != "EXAMPLE"]

        if "RAW MATERIALS / MANUFACTURED PRODUCT NAME" in df_recipes.columns:
            ingredients = df_recipes["RAW MATERIALS / MANUFACTURED PRODUCT NAME"].dropna().astype(str).str.strip().unique()
            
            missing_ingredients = [ing for ing in ingredients if ing not in stock_list and ing != "EXAMPLE"]
            
            if missing_ingredients:
                critical_errors.append(f"**Recipes:** The following ingredients are used in recipes but NOT found in Stock Items list (Ghost Inventory):")
                for m in missing_ingredients:
                    critical_errors.append(f"- `{m}`")

    # --- DISPLAY RESULTS ---
    with tab1:
        if critical_errors:
            st.error(f"Found {len(critical_errors)} Critical Issues")
            for err in critical_errors:
                st.write(f"❌ {err}")
        else:
            st.success("No critical errors found!")

    with tab2:
        if warnings:
            st.warning(f"Found {len(warnings)} Warnings")
            for warn in warnings:
                st.write(f"⚠️ {warn}")
        else:
            st.info("No warnings.")

    with tab3:
        st.write("### File Summary")
        for line in summary_data:
            st.markdown(f"- {line}")
        
        if st.checkbox("Show Raw Data Preview"):
            st.dataframe(pd.read_excel(uploaded_file, sheet_name=0).head())