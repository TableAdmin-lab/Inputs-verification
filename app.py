import streamlit as st
import pandas as pd
import openpyxl
import re
import io

# --- 1. CONFIGURATION ---
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
        background: linear-gradient(135deg, #2c3e50 0%, #4ca1af 100%);
        color: white; padding: 30px; border-radius: 12px;
        text-align: center; margin-bottom: 25px; box-shadow: 0 4px 15px rgba(0,0,0,0.1);
    }
    
    .metric-card {
        background: white; padding: 15px; border-radius: 10px; 
        border: 1px solid #eee; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    .metric-val { font-size: 24px; font-weight: 800; color: #2c3e50; }
    .metric-lbl { font-size: 11px; color: #7f8c8d; text-transform: uppercase; letter-spacing: 1px; }

</style>
""", unsafe_allow_html=True)

# --- 3. INTELLIGENT LOGIC ENGINE ---

def clean_text(text):
    if pd.isna(text) or str(text).strip() == "": return None
    text = str(text).strip()
    # Remove emoji/non-ascii
    text = re.sub(r'[^\x00-\x7F]+', '', text) 
    return text.title()

def clean_price(price):
    if pd.isna(price): return None
    clean = re.sub(r'[^0-9.]', '', str(price))
    try:
        val = float(clean)
        return val if val >= 0 else 0.0
    except: return None

def infer_prep_location(category, menu):
    text = (str(category) + " " + str(menu)).upper()
    bar_keywords = ["DRINK", "BEER", "WINE", "COCKTAIL", "COFFEE", "BEVERAGE", "SOFT", "SPIRIT", "CIDER", "JUICE", "BAR"]
    if any(k in text for k in bar_keywords): return "Bar"
    return "Kitchen"

def split_hierarchy(text):
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

def get_valid_modifiers(file):
    try:
        wb = openpyxl.load_workbook(file, read_only=True)
        sheet_name = next((s for s in wb.sheetnames if "MODIF" in s.upper()), None)
        if not sheet_name: return set()
        df = pd.read_excel(file, sheet_name=sheet_name)
        col = next((c for c in df.columns if "GROUP" in c.upper()), None)
        if col: return set(df[col].dropna().str.strip().str.title().unique())
        return set()
    except: return set()

# --- 4. THE PROCESSOR (WITH UI LOGIC) ---

def process_standardization(df_raw, valid_modifiers):
    clean_rows = []
    ui_rows = [] # Rows optimized for the UI table
    error_log = []
    seen_products = set()

    cols = df_raw.columns
    c_name = next((c for c in cols if "Product Name" in c), None)
    c_price = next((c for c in cols if "Selling Price" in c), None)
    c_cat = next((c for c in cols if "Category" in c), None)
    c_menu = next((c for c in cols if "Menu" in c and "Category" not in c), None)
    c_prep = next((c for c in cols if "Preparation" in c or "Prep" in c), None)
    c_mod = next((c for c in cols if "Assigned" in c or "Modifer" in c), None)

    for idx, row in df_raw.iterrows():
        excel_row = row.get('Row #', idx + 2)
        changes = [] # Track what we did to this specific row

        # 1. Identity
        raw_name = row.get(c_name)
        if pd.isna(raw_name) or str(raw_name).strip() == "": continue
        if str(raw_name).upper() == "EXAMPLE": continue

        # 2. Duplicate Check
        final_name = clean_text(raw_name)
        if final_name.upper() in seen_products:
            error_log.append({"Row": excel_row, "Issue": "Duplicate Product", "Action": "Deleted"})
            continue
        seen_products.add(final_name.upper())

        # 3. Standardization
        raw_p = row.get(c_price)
        final_price = clean_price(raw_p)
        if final_price is None: 
            final_price = 0.0
            changes.append("💲 Price Fixed")
            error_log.append({"Row": excel_row, "Issue": "Missing Price", "Action": "Set to 0.00"})

        # HIERARCHY
        raw_c = row.get(c_cat)
        raw_m = row.get(c_menu)
        
        inferred_menu, split_cat = split_hierarchy(raw_c)
        final_cat = split_cat if inferred_menu else clean_text(raw_c)
        final_menu = inferred_menu if inferred_menu else clean_text(raw_m)

        if inferred_menu: changes.append("✂️ Hierarchy Split")

        # GAP FILLING
        if not final_cat:
            final_cat = "Uncategorized"
            changes.append("⚠️ Cat. Missing")
        
        if not final_menu:
            final_menu = "Beverage Menu" if infer_prep_location(final_cat, "") == "Bar" else "Food Menu"
            changes.append("🧠 Menu Inferred")

        # PREP
        raw_pl = row.get(c_prep)
        final_prep = clean_text(raw_pl)
        if not final_prep:
            final_prep = infer_prep_location(final_cat, final_menu)
            changes.append("🍳 Prep Inferred")

        # MODIFIERS
        raw_mod = row.get(c_mod)
        final_mod = clean_text(raw_mod)
        if final_mod and valid_modifiers and final_mod not in valid_modifiers:
            changes.append("🔗 Mod Link Broken")

        # 4. Clean Data for Export
        std_row = {
            "Product Name": final_name,
            "Assigned Modifer": final_mod,
            "Selling Price (incl vat)": final_price,
            "Menu": final_menu,
            "Menu Category": final_cat,
            "Preparation Locations": final_prep
        }
        clean_rows.append(std_row)

        # 5. UI Data (The Friendly View)
        # Create "Transformation Strings" -> "Old ➝ New"
        
        # Category Display
        cat_display = final_cat
        if raw_c and str(raw_c).strip() != final_cat:
            cat_display = f"{raw_c} ➝ {final_cat}"
        
        # Menu Display
        menu_display = final_menu
        if raw_m and str(raw_m).strip() != final_menu:
             menu_display = f"{raw_m} ➝ {final_menu}"
        elif not raw_m:
             menu_display = f"missing ➝ {final_menu}"

        ui_row = {
            "Status": "✨ Clean" if not changes else "🛠️ Fixed",
            "Product": final_name,
            "Category Transformation": cat_display,
            "Menu Transformation": menu_display,
            "Fixes Applied": changes
        }
        ui_rows.append(ui_row)

    return pd.DataFrame(clean_rows), pd.DataFrame(ui_rows), error_log

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
            df = df[df[target_col].notna()]
            df = df[df[target_col].astype(str).str.upper() != "EXAMPLE"]
        
        df['Row #'] = df.index + header_row_idx + 2
        return df
    except: return None

# --- 5. MAIN APP ---
st.markdown("""
<div class="header-box">
    <h1>🏭 Yoco Standardization Factory</h1>
    <p>Automated Menu Logic & Hierarchy Engine</p>
</div>
""", unsafe_allow_html=True)

uploaded_file = st.file_uploader("", type=["xlsx"])

if uploaded_file:
    try:
        wb = openpyxl.load_workbook(uploaded_file, read_only=True)
        visible_sheets = [s.title for s in wb.worksheets if s.sheet_state == 'visible']
    except: visible_sheets = []

    if "Products(Finished Goods)" in visible_sheets:
        
        valid_mods = get_valid_modifiers(uploaded_file)
        df_raw = get_clean_data(uploaded_file, "Products(Finished Goods)", "Product Name")
        
        if df_raw is not None and not df_raw.empty:
            
            with st.spinner("⚙️ Applying Standards..."):
                df_std, df_ui, errors = process_standardization(df_raw, valid_mods)

            # METRICS ROW
            c1, c2, c3, c4 = st.columns(4)
            c1.markdown(f'<div class="metric-card"><div class="metric-val">{len(df_std)}</div><div class="metric-lbl">Total Products</div></div>', unsafe_allow_html=True)
            
            fixed_count = len([r for _, r in df_ui.iterrows() if r['Status'] == "🛠️ Fixed"])
            c2.markdown(f'<div class="metric-card"><div class="metric-val" style="color:#d35400">{fixed_count}</div><div class="metric-lbl">Rows Fixed</div></div>', unsafe_allow_html=True)
            
            clean_count = len(df_std) - fixed_count
            c3.markdown(f'<div class="metric-card"><div class="metric-val" style="color:#27ae60">{clean_count}</div><div class="metric-lbl">Clean Rows</div></div>', unsafe_allow_html=True)
            
            inferred_prep = sum(1 for e in errors if "Inferred" in str(e))
            c4.markdown(f'<div class="metric-card"><div class="metric-val" style="color:#2980b9">{inferred_prep}</div><div class="metric-lbl">Logic Inferences</div></div>', unsafe_allow_html=True)

            st.markdown("---")

            # TABS
            tab1, tab2, tab3 = st.tabs(["🔎 Review Changes", "📥 Download Final File", "📜 Logic Log"])

            with tab1:
                col_a, col_b = st.columns([3, 1])
                with col_a:
                    st.subheader("Data Transformation Review")
                with col_b:
                    # Filter Toggle
                    show_all = st.checkbox("Show Clean Rows", value=False)
                
                # Filter Dataframe for UI
                if not show_all:
                    display_df = df_ui[df_ui['Status'] == "🛠️ Fixed"]
                    if display_df.empty:
                        st.info("🎉 No major changes! Your data was already perfect.")
                else:
                    display_df = df_ui

                # PRETTY TABLE
                st.dataframe(
                    display_df,
                    column_config={
                        "Status": st.column_config.TextColumn("State", width="small"),
                        "Product": st.column_config.TextColumn("Product Name", width="medium"),
                        "Category Transformation": st.column_config.TextColumn("Category Logic", width="large"),
                        "Menu Transformation": st.column_config.TextColumn("Menu Logic", width="large"),
                        "Fixes Applied": st.column_config.ListColumn("Interventions Applied"),
                    },
                    use_container_width=True,
                    hide_index=True
                )

            with tab2:
                st.success("✅ File is standardized and ready for import.")
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_std.to_excel(writer, index=False, sheet_name='Products_Cleaned')
                output.seek(0)
                st.download_button(
                    label="📥 Download Standardized Excel",
                    data=output,
                    file_name="Yoco_Standardized.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary"
                )

            with tab3:
                st.subheader("Deep Logic Log")
                if errors:
                    st.dataframe(pd.DataFrame(errors), use_container_width=True)
                else:
                    st.info("Log is empty.")

        else:
            st.error("Empty Data Found.")
    else:
        st.error("Please upload a file with 'Products(Finished Goods)'.")