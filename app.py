import streamlit as st
import pandas as pd
import openpyxl
import re
import io

# --- 1. CONFIGURATION ---
st.set_page_config(page_title="Yoco Standardization Factory", page_icon="🏭", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #f0f2f6; }
    .header-box {
        background: #101820; color: #FEE715; 
        padding: 30px; border-radius: 10px; text-align: center; margin-bottom: 20px;
    }
    .standard-card {
        background: white; padding: 20px; border-radius: 8px; 
        border-left: 5px solid #101820; box-shadow: 0 2px 5px rgba(0,0,0,0.1);
    }
    .success-text { color: #2e7d32; font-weight: bold; }
    .fail-text { color: #c62828; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# --- 2. THE STANDARDIZATION LOGIC ENGINE ---

def clean_text(text):
    """Enforce Title Case and remove extra spaces."""
    if pd.isna(text): return ""
    return str(text).strip().title()

def clean_price(price):
    """Enforce float format (no R symbols)."""
    if pd.isna(price): return None
    clean = re.sub(r'[^0-9.]', '', str(price))
    try:
        return float(clean)
    except:
        return None

def split_hierarchy(text):
    """
    Standard: 'Menu/Category/Item' -> Returns (Menu, Category)
    """
    if pd.isna(text): return None, None
    text = str(text)
    
    delimiters = ['/', '>', '-', '\\']
    for d in delimiters:
        if d in text:
            parts = text.split(d)
            # Logic: First part is usually Menu/Department, Last part is Category
            menu_part = parts[0].strip().title()
            cat_part = parts[-1].strip().title()
            
            # Correction: If menu_part is just "Menu", genericize it
            if menu_part.lower() == "menu": 
                menu_part = "Food Menu" # Assumption, but better than "Menu"
                
            return menu_part, cat_part
            
    return None, text.strip().title() # Return None for menu, Text for category

def infer_prep_location(category, menu):
    """
    Logic: Guess Kitchen vs Bar based on keywords.
    """
    text = (str(category) + " " + str(menu)).upper()
    
    bar_keywords = ["DRINK", "BEER", "WINE", "COCKTAIL", "COFFEE", "BEVERAGE", "SOFT", "SPIRIT", "CIDER"]
    kitchen_keywords = ["FOOD", "MAIN", "STARTER", "DESSERT", "PIZZA", "BURGER", "SALAD", "SIDE", "MEAT"]
    
    if any(k in text for k in bar_keywords): return "Bar"
    if any(k in text for k in kitchen_keywords): return "Kitchen"
    return "Kitchen" # Default fallback

def infer_menu(category):
    """
    Logic: Guess Food vs Drinks based on Category.
    """
    text = str(category).upper()
    bar_keywords = ["DRINK", "BEER", "WINE", "COCKTAIL", "COFFEE", "BEVERAGE"]
    
    if any(k in text for k in bar_keywords): return "Beverage Menu"
    return "Food Menu"

# --- 3. THE PROCESSOR ---

def run_standardization_factory(df_prod):
    """
    Takes a raw Products DataFrame and forces it into the Standard.
    Returns: A new, clean DataFrame and a log of changes.
    """
    clean_rows = []
    logs = []

    # Map columns flexibly
    cols = df_prod.columns
    c_name = next((c for c in cols if "Product Name" in c), None)
    c_price = next((c for c in cols if "Selling Price" in c), None)
    c_cat = next((c for c in cols if "Category" in c), None)
    c_menu = next((c for c in cols if "Menu" in c and "Category" not in c), None)
    c_prep = next((c for c in cols if "Preparation" in c or "Prep" in c), None)
    
    for idx, row in df_prod.iterrows():
        # 1. Identity Check (Skip empty rows)
        raw_name = row.get(c_name)
        if pd.isna(raw_name) or str(raw_name).strip() == "": continue
        if str(raw_name).upper() == "EXAMPLE": continue

        # 2. Extract & Clean Basic Data
        final_name = clean_text(raw_name)
        final_price = clean_price(row.get(c_price))
        
        # 3. Handle Hierarchy (Menu/Category)
        raw_cat = row.get(c_cat)
        raw_menu = row.get(c_menu)
        
        final_menu = clean_text(raw_menu)
        final_cat = clean_text(raw_cat)
        
        # LOGIC: Check if Category contains a path (e.g. Menu/Sushi)
        inferred_menu, split_cat = split_hierarchy(raw_cat)
        
        if inferred_menu:
            final_cat = split_cat
            # Only override menu if it was empty or generic
            if not final_menu or final_menu == "Menu":
                final_menu = inferred_menu
        
        # LOGIC: If Menu is still missing, infer from Category
        if not final_menu:
            final_menu = infer_menu(final_cat)
            
        # 4. Handle Prep Location
        final_prep = clean_text(row.get(c_prep))
        if not final_prep:
            final_prep = infer_prep_location(final_cat, final_menu)

        # 5. Build Standardized Row
        new_row = {
            "Product Name": final_name,
            "Selling Price": final_price if final_price is not None else 0,
            "Menu": final_menu,
            "Category": final_cat,
            "Prep Location": final_prep,
            "Status": "✅ Standardized"
        }
        
        # Log Logic Changes
        if final_menu != clean_text(raw_menu): logs.append(f"Row {idx+2}: Inferred Menu '{final_menu}'")
        if final_prep != clean_text(row.get(c_prep)): logs.append(f"Row {idx+2}: Inferred Prep '{final_prep}'")
        if "/" in str(raw_cat): logs.append(f"Row {idx+2}: Split Hierarchy '{raw_cat}'")

        clean_rows.append(new_row)

    return pd.DataFrame(clean_rows), logs

# --- 4. APP UI ---
st.markdown("""
<div class="header-box">
    <h1>🏭 Yoco Standardization Factory</h1>
    <p>Upload any messy Excel sheet. We will force it into the <b>Menu > Category > Product</b> standard.</p>
</div>
""", unsafe_allow_html=True)

uploaded_file = st.file_uploader("", type=["xlsx"])

if uploaded_file:
    try:
        # Load File
        wb = openpyxl.load_workbook(uploaded_file, read_only=True)
        visible_sheets = [s.title for s in wb.worksheets if s.sheet_state == 'visible']
        
        if "Products(Finished Goods)" in visible_sheets:
            # Load Data (Using the Last Header Logic from before)
            df_scan = pd.read_excel(uploaded_file, sheet_name="Products(Finished Goods)", header=None, nrows=50)
            header_row = 0
            for i, r in df_scan.iterrows():
                if r.astype(str).str.contains("Product Name", case=False).any(): header_row = i
            
            df_raw = pd.read_excel(uploaded_file, sheet_name="Products(Finished Goods)", header=header_row)
            
            # --- RUN FACTORY ---
            st.write("⚙️ **Running Logic Engine...**")
            df_standard, logs = run_standardization_factory(df_raw)
            
            # --- RESULTS ---
            c1, c2 = st.columns([2, 1])
            
            with c1:
                st.subheader("✅ The Standardized Output")
                st.markdown("This data is now strict, clean, and ready for import.")
                st.dataframe(df_standard, use_container_width=True)
                
                # Download Button
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_standard.to_excel(writer, index=False, sheet_name='Cleaned_Products')
                output.seek(0)
                
                st.download_button(
                    "📥 Download Standardized Excel",
                    data=output,
                    file_name="Yoco_Standardized_Menu.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary"
                )

            with c2:
                st.subheader("🤖 Logic Applied")
                st.markdown(f"**Total Items Processed:** {len(df_standard)}")
                st.markdown(f"**Automated Fixes:** {len(logs)}")
                
                with st.expander("View Logic Logs", expanded=True):
                    for log in logs:
                        st.caption(log)
                        
                st.info("""
                **Standards Enforced:**
                1. **Hierarchy:** `Menu/Sushi` → Menu: Food, Cat: Sushi.
                2. **Prep:** `Beer` → Bar. `Burger` → Kitchen.
                3. **Casing:** All text converted to Title Case.
                4. **Prices:** Currency symbols removed.
                """)
        else:
            st.error("Could not find 'Products(Finished Goods)' tab.")
            
    except Exception as e:
        st.error(f"Error: {str(e)}")