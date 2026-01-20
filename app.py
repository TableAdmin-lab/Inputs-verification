import streamlit as st
import pandas as pd
import openpyxl
import re
import io

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(
    page_title="Yoco Standardization Factory",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 2. CSS STYLING ---
st.markdown("""
<style>
    .stApp { background-color: #f4f6f9; }
    
    .header-box {
        background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
        color: white; padding: 25px; border-radius: 12px;
        text-align: center; margin-bottom: 25px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    
    .stat-box {
        background: white; padding: 15px; border-radius: 8px;
        border-left: 5px solid #2a5298; box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    
    /* Highlight changed cells in comparisons */
    .changed-cell { background-color: #fff3cd; font-weight: bold; }
    .good-cell { color: #28a745; }
    .bad-cell { color: #dc3545; }
</style>
""", unsafe_allow_html=True)

# --- 3. LOGIC ENGINE ---

def clean_text(text):
    """Title Case, Strip, Handle NaNs"""
    if pd.isna(text) or str(text).strip() == "": return None
    return str(text).strip().title()

def clean_price(price):
    """Remove R symbols, ensure float"""
    if pd.isna(price): return None
    clean = re.sub(r'[^0-9.]', '', str(price))
    try:
        val = float(clean)
        return val if val >= 0 else 0.0
    except:
        return None

def split_hierarchy(text):
    """
    Handles 'Menu/Category/Item' -> Returns (Menu, Category)
    """
    if pd.isna(text): return None, None
    text = str(text)
    
    delimiters = ['/', '>', '-', '\\']
    for d in delimiters:
        if d in text:
            parts = text.split(d)
            menu_part = parts[0].strip().title()
            cat_part = parts[-1].strip().title()
            
            if menu_part.lower() == "menu": menu_part = "Food Menu"
            return menu_part, cat_part
            
    return None, text.strip().title()

def infer_prep_location(category, menu):
    """Guess Kitchen vs Bar based on keywords"""
    text = (str(category) + " " + str(menu)).upper()
    bar_keywords = ["DRINK", "BEER", "WINE", "COCKTAIL", "COFFEE", "BEVERAGE", "SOFT", "SPIRIT", "CIDER", "JUICE"]
    if any(k in text for k in bar_keywords): return "Bar"
    return "Kitchen" # Default

def infer_menu(category):
    """Guess Food vs Drinks based on Category"""
    text = str(category).upper()
    bar_keywords = ["DRINK", "BEER", "WINE", "COCKTAIL", "COFFEE", "BEVERAGE", "SOFT"]
    if any(k in text for k in bar_keywords): return "Beverage Menu"
    return "Food Menu"

# --- 4. THE PROCESSOR ---

def process_standardization(df_raw):
    """
    Takes Raw DataFrame. Returns:
    1. Standardized DataFrame (Perfect for import)
    2. Comparison DataFrame (For UI visualization)
    3. Error Log (List of specific issues fixed/found)
    """
    clean_rows = []
    comparison_rows = []
    error_log = []

    # Map columns
    cols = df_raw.columns
    c_name = next((c for c in cols if "Product Name" in c), None)
    c_price = next((c for c in cols if "Selling Price" in c), None)
    c_cat = next((c for c in cols if "Category" in c), None)
    c_menu = next((c for c in cols if "Menu" in c and "Category" not in c), None)
    c_prep = next((c for c in cols if "Preparation" in c or "Prep" in c), None)

    for idx, row in df_raw.iterrows():
        excel_row = row.get('Row #', idx + 2)
        
        # 1. Identity Check
        raw_name = row.get(c_name)
        if pd.isna(raw_name) or str(raw_name).strip() == "": continue # Skip empty
        if str(raw_name).upper() == "EXAMPLE": continue

        # 2. Extract Raw Values
        raw_p = row.get(c_price)
        raw_m = row.get(c_menu)
        raw_c = row.get(c_cat)
        raw_pl = row.get(c_prep)

        # 3. Standardization Logic
        final_name = clean_text(raw_name)
        
        # Price
        final_price = clean_price(raw_p)
        if final_price is None:
            final_price = 0.0
            error_log.append({"Row": excel_row, "Issue": "Missing/Bad Price", "Action": "Set to 0.00"})

        # Hierarchy (Menu/Category)
        final_menu = clean_text(raw_m)
        final_cat = clean_text(raw_c)
        
        inferred_menu, split_cat = split_hierarchy(raw_c)
        if inferred_menu:
            final_cat = split_cat
            if not final_menu or final_menu == "Menu":
                final_menu = inferred_menu
                error_log.append({"Row": excel_row, "Issue": "Hierarchy Detected", "Action": f"Split '{raw_c}' into Menu/Cat"})

        # Gap Filling
        if not final_cat:
            final_cat = "Uncategorized"
            error_log.append({"Row": excel_row, "Issue": "Missing Category", "Action": "Set to 'Uncategorized'"})

        if not final_menu:
            final_menu = infer_menu(final_cat)
            error_log.append({"Row": excel_row, "Issue": "Missing Menu", "Action": f"Inferred '{final_menu}'"})

        # Prep Location
        final_prep = clean_text(raw_pl)
        if not final_prep:
            final_prep = infer_prep_location(final_cat, final_menu)
            error_log.append({"Row": excel_row, "Issue": "Missing Prep Location", "Action": f"Inferred '{final_prep}'"})

        # 4. Build Output Row (The "Standard")
        std_row = {
            "Product Name": final_name,
            "Selling Price (incl vat)": final_price,
            "Menu": final_menu,
            "Menu Category": final_cat,
            "Preparation Locations": final_prep
        }
        clean_rows.append(std_row)

        # 5. Build Comparison Row (For UI)
        comp_row = {
            "Row": excel_row,
            "Product Name": final_name,
            "ORIGINAL Menu": str(raw_m) if pd.notna(raw_m) else "-",
            "FINAL Menu": final_menu,
            "ORIGINAL Category": str(raw_c) if pd.notna(raw_c) else "-",
            "FINAL Category": final_cat,
            "ORIGINAL Prep": str(raw_pl) if pd.notna(raw_pl) else "-",
            "FINAL Prep": final_prep
        }
        comparison_rows.append(comp_row)

    return pd.DataFrame(clean_rows), pd.DataFrame(comparison_rows), error_log

def get_clean_data(file, sheet_name, unique_col_identifier):
    try:
        df_scan = pd.read_excel(file, sheet_name=sheet_name, header=None, nrows=50)
        matching_rows = []
        for i, row in df_scan.iterrows():
            if row.astype(str).str.contains(unique_col_identifier, case=False, na=False).any():
                matching_rows.append(i)
        
        if not matching_rows: return None
        header_row_idx = matching_rows[-1]
        df = pd.read_excel(file, sheet_name=sheet_name, header=header_row_idx)
        df.columns = df.columns.astype(str).str.strip()
        
        target_col = next((c for c in df.columns if unique_col_identifier.lower() in c.lower()), None)
        if target_col:
            df = df[df[target_col].notna()] # Drop empty rows
            df = df[df[target_col].astype(str).str.upper() != "EXAMPLE"]
        
        df['Row #'] = df.index + header_row_idx + 2
        return df
    except: return None

# --- 5. MAIN APP ---
st.markdown("""
<div class="header-box">
    <h1>🏭 Yoco Standardization Factory</h1>
    <p>Upload a messy file. Get a <b>Perfect, POS-Ready</b> file back.</p>
</div>
""", unsafe_allow_html=True)

uploaded_file = st.file_uploader("", type=["xlsx"])

if uploaded_file:
    # Load Visible Sheets
    try:
        wb = openpyxl.load_workbook(uploaded_file, read_only=True)
        visible_sheets = [s.title for s in wb.worksheets if s.sheet_state == 'visible']
    except: visible_sheets = []

    if "Products(Finished Goods)" in visible_sheets:
        
        # 1. LOAD RAW DATA
        df_raw = get_clean_data(uploaded_file, "Products(Finished Goods)", "Product Name")
        
        if df_raw is not None and not df_raw.empty:
            
            # 2. RUN FACTORY
            with st.spinner("⚙️ Standardizing Hierarchies, Filling Gaps, Fixing Prices..."):
                df_std, df_comp, errors = process_standardization(df_raw)

            # 3. METRICS
            c1, c2, c3 = st.columns(3)
            c1.metric("Products Processed", len(df_std))
            c2.metric("Issues Fixed", len(errors))
            completeness = 100 # By definition, the factory forces 100% completeness
            c3.metric("Result Completeness", "100%", delta="Guaranteed")

            st.markdown("---")

            # 4. DUAL VIEW TABS
            tab1, tab2, tab3 = st.tabs(["🔎 Compare: Original vs Standard", "📥 Download Results", "📜 Issue Log"])

            with tab1:
                st.subheader("Visual Comparison")
                st.markdown("See exactly how the logic changed your data.")
                
                # We use a custom dataframe display
                st.dataframe(
                    df_comp,
                    column_config={
                        "ORIGINAL Menu": st.column_config.TextColumn("Raw Menu", width="medium"),
                        "FINAL Menu": st.column_config.TextColumn("✅ Fixed Menu", width="medium"),
                        "ORIGINAL Category": st.column_config.TextColumn("Raw Category", width="medium"),
                        "FINAL Category": st.column_config.TextColumn("✅ Fixed Category", width="medium"),
                        "ORIGINAL Prep": st.column_config.TextColumn("Raw Prep", width="medium"),
                        "FINAL Prep": st.column_config.TextColumn("✅ Fixed Prep", width="medium"),
                    },
                    use_container_width=True,
                    hide_index=True
                )

            with tab2:
                st.subheader("Get your file")
                
                # Generate Excel
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_std.to_excel(writer, index=False, sheet_name='Products_Cleaned')
                output.seek(0)
                
                c_d1, c_d2 = st.columns([1,2])
                with c_d1:
                    st.download_button(
                        label="📥 Download Standardized Excel",
                        data=output,
                        file_name="Yoco_Standardized_Menu.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        type="primary"
                    )
                with c_d2:
                    st.info("This file contains **ONLY** the standardized columns required for import. All mess is removed.")

            with tab3:
                st.subheader("Detailed Logic Log")
                if errors:
                    st.dataframe(pd.DataFrame(errors), use_container_width=True)
                else:
                    st.success("No major transformations needed. Data was already clean!")

        else:
            st.error("Could not read data from 'Products(Finished Goods)' sheet.")
    else:
        st.error("Please upload a file containing the 'Products(Finished Goods)' sheet.")