import streamlit as st
import pandas as pd
import io

# --- 1. DASHBOARD CONFIGURATION ---
st.set_page_config(
    page_title="Yoco Onboarding Verifier",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS to make it look cleaner
st.markdown("""
    <style>
    .main {
        background-color: #f8f9fa;
    }
    .stAlert {
        padding: 1rem;
        border-radius: 8px;
    }
    div.stButton > button {
        width: 100%;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 2. SIDEBAR: INSTRUCTIONS ---
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/c/c3/Python-logo-notext.svg/1200px-Python-logo-notext.svg.png", width=50)
    st.title("Yoco Sheet Verifier")
    
    st.markdown("### 📝 How to use this tool")
    st.info("""
    1. **Upload** your completed Yoco Input Excel file.
    2. The tool will **scan** all tabs (Products, Employees, Recipes).
    3. Review the **Errors** in the main dashboard.
    4. Fix the Excel file and re-upload until all checks pass.
    """)
    
    st.markdown("---")
    st.markdown("### ⚠️ Common Mistakes")
    st.markdown("""
    * **Recipes:** Ingredient names must match *exactly* (spelling & spacing) with the "Stock Items" tab.
    * **Prices:** Must be numbers only (no 'R' symbols).
    * **Login Codes:** Must be 4 digits.
    """)
    st.markdown("---")
    st.caption("v2.0 | Dashboard Mode")

# --- 3. HELPER FUNCTIONS ---
def find_header_and_read(file, sheet_name, search_term):
    """
    Intelligently finds the header row by searching for a specific column name.
    """
    try:
        # First, just read the first few rows to scan for the header
        df_scan = pd.read_excel(file, sheet_name=sheet_name, header=None, nrows=10)
        
        header_row = 0
        for i, row in df_scan.iterrows():
            # Check if the row contains the search term (case insensitive)
            if row.astype(str).str.contains(search_term, case=False, na=False).any():
                header_row = i
                break
        
        # Now read the full file with the correct header
        df = pd.read_excel(file, sheet_name=sheet_name, header=header_row)
        
        # Clean: Remove "EXAMPLE" rows or empty instruction rows
        if not df.empty:
            df = df[df.iloc[:, 0].astype(str).str.upper() != "EXAMPLE"]
            
        return df
    except ValueError:
        return pd.DataFrame() # Sheet not found

# --- 4. MAIN APPLICATION LOGIC ---
st.title("📊 Yoco Data Verification Dashboard")
st.markdown("Upload your **Site Input Sheet** below to validate data integrity.")

uploaded_file = st.file_uploader("", type=["xlsx"], help="Drag and drop your Yoco Excel file here")

if uploaded_file:
    # -- LOAD DATA --
    xls = pd.ExcelFile(uploaded_file)
    all_sheets = xls.sheet_names
    
    # Store issues here
    critical_issues = []
    warnings = []
    
    # Data Containers for Metrics
    total_products = 0
    total_employees = 0
    site_name = "Unknown Site"

    # --- PROCESS: SITE INFO ---
    if "Site Data Information" in all_sheets:
        df_site = find_header_and_read(uploaded_file, "Site Data Information", "Site Name")
        if not df_site.empty:
            site_name = df_site.iloc[0].get("Site Name", "Unknown")
            
            # Check required fields
            req_fields = ["Owner Email Address", "Owner Telephone Number", "Company VAT Number"]
            for col in req_fields:
                if col in df_site.columns and df_site[col].isnull().any():
                    critical_issues.append(f"**Site Info:** Missing `{col}`.")

    # --- PROCESS: PRODUCTS ---
    if "Products(Finished Goods)" in all_sheets:
        df_prod = find_header_and_read(uploaded_file, "Products(Finished Goods)", "Product Name")
        total_products = len(df_prod)
        
        if "Selling Price (incl vat)" in df_prod.columns:
            # Check for non-numeric prices
            bad_prices = df_prod[pd.to_numeric(df_prod["Selling Price (incl vat)"], errors='coerce').isna()]
            if not bad_prices.empty:
                critical_issues.append(f"**Products:** {len(bad_prices)} products have invalid prices (check for currency symbols).")

    # --- PROCESS: EMPLOYEES ---
    if "Employee List" in all_sheets:
        df_emp = find_header_and_read(uploaded_file, "Employee List", "Employee Name")
        total_employees = len(df_emp)
        
        if "Login Code" in df_emp.columns:
            # Check short pins
            short_pins = df_emp[df_emp["Login Code"].astype(str).str.strip().str.len() < 4]
            if not short_pins.empty:
                warnings.append(f"**Employees:** {len(short_pins)} employees have Login Codes shorter than 4 digits.")

    # --- PROCESS: RECIPES (The big one) ---
    stock_items = set()
    if "Stock Items(RAW MATERIALS)" in all_sheets:
        df_stock = find_header_and_read(uploaded_file, "Stock Items(RAW MATERIALS)", "RAW MATERIAL Product Name")
        stock_items = set(df_stock["RAW MATERIAL Product Name"].dropna().astype(str).str.strip())
        
        # Check Cost Price in Stock
        if "Cost Price " in df_stock.columns:
             missing_cost = df_stock[df_stock["Cost Price "].isnull()]
             if not missing_cost.empty:
                 warnings.append(f"**Stock:** {len(missing_cost)} stock items are missing a Cost Price.")

    if "Products Recipes" in all_sheets and stock_items:
        df_recipes = find_header_and_read(uploaded_file, "Products Recipes", "RAW MATERIALS")
        
        if "RAW MATERIALS / MANUFACTURED PRODUCT NAME" in df_recipes.columns:
            recipe_ingredients = df_recipes["RAW MATERIALS / MANUFACTURED PRODUCT NAME"].dropna().astype(str).str.strip().unique()
            
            ghost_items = [i for i in recipe_ingredients if i not in stock_items and i != "nan"]
            
            if ghost_items:
                critical_issues.append(f"**Recipes:** Found {len(ghost_items)} ingredients used in recipes that do NOT exist in the Stock sheet.")
                # Add details to warnings so the user can see which ones
                for g in ghost_items:
                    warnings.append(f"🔴 Ghost Ingredient: `{g}` (Check spelling matches Stock Sheet exactly)")

    # --- 5. DASHBOARD LAYOUT ---
    
    st.divider()
    
    # Top Metrics Row
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Site Name", site_name)
    col2.metric("Total Products", total_products)
    col3.metric("Employees", total_employees)
    col4.metric("Issues Found", len(critical_issues) + len(warnings), delta_color="inverse")

    st.divider()

    # Tabs for detailed view
    tab_errors, tab_data = st.tabs(["🚨 Verification Report", "📂 Data Preview"])

    with tab_errors:
        if not critical_issues and not warnings:
            st.success("🎉 No issues found! The file looks ready for upload.")
            st.balloons()
        else:
            if critical_issues:
                st.error("### Critical Errors (Must Fix)")
                for err in critical_issues:
                    st.write(f"- {err}")
            
            if warnings:
                st.warning("### Warnings (Check these)")
                for warn in warnings:
                    st.write(f"- {warn}")

    with tab_data:
        st.write("### Quick Look at Uploaded Data")
        if "Products(Finished Goods)" in all_sheets:
            st.caption("First 5 rows of Products")
            st.dataframe(df_prod.head())
        
        if "Stock Items(RAW MATERIALS)" in all_sheets:
            st.caption("First 5 rows of Stock")
            st.dataframe(df_stock.head())

else:
    # Placeholder when no file is uploaded
    st.info("👈 Please upload your Excel file to begin.")