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
        background: linear-gradient(135deg, #0f2027 0%, #203a43 50%, #2c5364 100%);
        color: white; padding: 30px; border-radius: 12px;
        text-align: center; margin-bottom: 25px; box-shadow: 0 10px 20px rgba(0,0,0,0.15);
    }
    
    .stat-box {
        background: white; padding: 20px; border-radius: 8px;
        border-left: 5px solid #203a43; box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        text-align: center;
    }
    .stat-val { font-size: 28px; font-weight: bold; color: #333; }
    .stat-lbl { font-size: 12px; color: #666; text-transform: uppercase; letter-spacing: 1px; }

</style>
""", unsafe_allow_html=True)

# --- 3. INTELLIGENT LOGIC ENGINE ---

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

def clean_menu_name(text):
    """
    Standardizes Menu names.
    1. Removes paths (Menu/Food -> Food).
    2. Maps keywords (E.g. 'Mains' -> 'Food Menu').
    """
    if pd.isna(text): return None
    text = str(text).title().strip()
    
    # 1. Flatten Paths (Take the first generic bucket or specific name)
    delimiters = ['/', '>', '-', '\\']
    for d in delimiters:
        if d in text:
            # If "Menu/Food", take "Food"
            # If "Food/Mains", take "Food"
            parts = text.split(d)
            # Heuristic: If first part is "Menu", take second. Else take first.
            if parts[0].upper() == "MENU" and len(parts) > 1:
                text = parts[1].strip()
            else:
                text = parts[0].strip()
                
    # 2. Keyword Mapping (Standardize to Yoco defaults)
    keywords = {
        "DRINK": "Beverage Menu",
        "BEVERAGE": "Beverage Menu",
        "BAR": "Beverage Menu",
        "WINE": "Beverage Menu",
        "COCKTAIL": "Beverage Menu",
        "FOOD": "Food Menu",
        "KITCHEN": "Food Menu",
        "MAIN": "Food Menu",
        "STARTER": "Food Menu",
        "DESSERT": "Food Menu",
        "RETAIL": "Retail Menu"
    }
    
    upper_text = text.upper()
    for key, val in keywords.items():
        if key in upper_text:
            return val
            
    # Default fallback: Just ensure it ends in "Menu" if it's short
    if "MENU" not in upper_text:
        return f"{text} Menu"
        
    return text

def infer_category_from_product(product_name):
    """
    BEST GUESS LOGIC: Guesses Category based on Product Name.
    """
    if pd.isna(product_name): return "Uncategorized"
    name = str(product_name).upper()
    
    # Dictionary of Categories -> Keywords
    guesses = {
        "Burgers": ["BURGER", "PATTY", "SLIDER"],
        "Pizzas": ["PIZZA", "MARGHERITA", "HAWAIIAN", "REGINA", "FOCACCIA"],
        "Salads": ["SALAD", "GREEK", "CAESAR"],
        "Sides": ["CHIPS", "FRIES", "ONION RINGS", "SIDE", "WEDGES"],
        "Coffee": ["LATTE", "CAPPUCCINO", "AMERICANO", "ESPRESSO", "CORTADO", "FLAT WHITE", "MOCHA"],
        "Tea": ["CEYLON", "ROOIBOS", "EARL GREY", "TEA"],
        "Cold Drinks": ["COKE", "COCA COLA", "SPRITE", "FANTA", "APPLETISER", "GRAPETISER", "WATER", "SODA"],
        "Beer": ["CASTLE", "LITE", "LAGER", "PILSNER", "HEINEKEN", "STELLA", "WINDHOEK", "IPA", "DRAUGHT"],
        "Wine": ["MERLOT", "SHIRAZ", "PINOTAGE", "SAUVIGNON", "CHENIN", "CHARDONNAY", "BLEND", "RED", "WHITE", "ROSE"],
        "Spirits": ["WHISKEY", "WHISKY", "GIN", "VODKA", "BRANDY", "RUM", "TEQUILA", "JAMESON"],
        "Cocktails": ["MOJITO", "DAIQUIRI", "COSMO", "MARGARITA", "LONG ISLAND"],
        "Desserts": ["CAKE", "ICE CREAM", "WAFFLE", "BROWNIE", "DOM PEDRO"]
    }
    
    for category, keywords in guesses.items():
        if any(k in name for k in keywords):
            return category
            
    return "Uncategorized"

def infer_prep_location(category, menu):
    """Guess Kitchen vs Bar"""
    text = (str(category) + " " + str(menu)).upper()
    bar_keywords = ["DRINK", "BEER", "WINE", "COCKTAIL", "COFFEE", "BEVERAGE", "SOFT", "SPIRIT", "CIDER", "JUICE", "BAR"]
    if any(k in text for k in bar_keywords): return "Bar"
    return "Kitchen"

def split_hierarchy(text):
    """Handles 'Menu/Category/Item' -> Returns (Menu, Category)"""
    if pd.isna(text): return None, None
    text = str(text)
    delimiters = ['/', '>', '-', '\\']
    for d in delimiters:
        if d in text:
            parts = text.split(d)
            # Standard logic: Menu > Category
            menu_part = parts[0].strip().title()
            cat_part = parts[-1].strip().title()
            return menu_part, cat_part
    return None, text.strip().title()

# --- 4. THE PROCESSOR ---

def process_standardization(df_raw):
    clean_rows = []
    comparison_rows = []
    error_log = []

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
        if pd.isna(raw_name) or str(raw_name).strip() == "": continue
        if str(raw_name).upper() == "EXAMPLE": continue

        # 2. Extract Raw
        raw_p = row.get(c_price)
        raw_m = row.get(c_menu)
        raw_c = row.get(c_cat)
        raw_pl = row.get(c_prep)

        # 3. Standardization
        final_name = clean_text(raw_name)
        final_price = clean_price(raw_p)
        if final_price is None: 
            final_price = 0.0
            error_log.append({"Row": excel_row, "Issue": "Missing Price", "Fix": "Set to 0.00"})

        # HIERARCHY LOGIC
        final_menu = clean_menu_name(raw_m) # Flatten menu paths
        final_cat = clean_text(raw_c)
        
        # Check Category Column for paths (Menu/Category)
        inferred_menu_from_cat, split_cat = split_hierarchy(raw_c)
        if inferred_menu_from_cat:
            final_cat = split_cat
            # Only use inferred menu if original was empty
            if not final_menu: 
                final_menu = clean_menu_name(inferred_menu_from_cat)

        # CATEGORY GUESSING (The "Best Guess" Engine)
        if not final_cat or final_cat == "Uncategorized":
            # Try to guess from Product Name
            guessed_cat = infer_category_from_product(final_name)
            if guessed_cat != "Uncategorized":
                final_cat = guessed_cat
                error_log.append({"Row": excel_row, "Issue": "Missing Category", "Fix": f"Guessed '{final_cat}' from Name"})
            else:
                final_cat = "Uncategorized"
                error_log.append({"Row": excel_row, "Issue": "Missing Category", "Fix": "Could not guess. Set to Uncategorized"})

        # MENU INFERENCE
        if not final_menu:
            final_menu = "Beverage Menu" if infer_prep_location(final_cat, "") == "Bar" else "Food Menu"
            error_log.append({"Row": excel_row, "Issue": "Missing Menu", "Fix": f"Inferred '{final_menu}'"})

        # PREP LOCATION
        final_prep = clean_text(raw_pl)
        if not final_prep:
            final_prep = infer_prep_location(final_cat, final_menu)
            error_log.append({"Row": excel_row, "Issue": "Missing Prep", "Fix": f"Inferred '{final_prep}'"})

        # 4. Build Rows
        std_row = {
            "Product Name": final_name,
            "Selling Price (incl vat)": final_price,
            "Menu": final_menu,
            "Menu Category": final_cat,
            "Preparation Locations": final_prep
        }
        clean_rows.append(std_row)

        comp_row = {
            "Row": excel_row,
            "Product": final_name,
            "Raw Menu": str(raw_m) if pd.notna(raw_m) else "-",
            "Std Menu": final_menu,
            "Raw Cat": str(raw_c) if pd.notna(raw_c) else "-",
            "Std Cat": final_cat,
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
            df = df[df[target_col].notna()]
            df = df[df[target_col].astype(str).str.upper() != "EXAMPLE"]
        
        df['Row #'] = df.index + header_row_idx + 2
        return df
    except: return None

# --- 5. MAIN APP ---
st.markdown("""
<div class="header-box">
    <h1>🏭 Yoco Standardization Factory</h1>
    <p>Upload a messy file. We will Force-Standardize Menus, Guess Categories, and Fix Hierarchies.</p>
</div>
""", unsafe_allow_html=True)

uploaded_file = st.file_uploader("", type=["xlsx"])

if uploaded_file:
    try:
        wb = openpyxl.load_workbook(uploaded_file, read_only=True)
        visible_sheets = [s.title for s in wb.worksheets if s.sheet_state == 'visible']
    except: visible_sheets = []

    if "Products(Finished Goods)" in visible_sheets:
        
        df_raw = get_clean_data(uploaded_file, "Products(Finished Goods)", "Product Name")
        
        if df_raw is not None and not df_raw.empty:
            
            with st.spinner("🤖 Running Logic Engine: Cleaning Menus, Guessing Categories..."):
                df_std, df_comp, errors = process_standardization(df_raw)

            # METRICS
            c1, c2, c3 = st.columns(3)
            with c1:
                st.markdown(f'<div class="stat-box"><div class="stat-val">{len(df_std)}</div><div class="stat-lbl">Products</div></div>', unsafe_allow_html=True)
            with c2:
                st.markdown(f'<div class="stat-box"><div class="stat-val">{len(errors)}</div><div class="stat-lbl">Interventions</div></div>', unsafe_allow_html=True)
            with c3:
                st.markdown(f'<div class="stat-box"><div class="stat-val">100%</div><div class="stat-lbl">Completeness</div></div>', unsafe_allow_html=True)
            
            st.markdown("<br>", unsafe_allow_html=True)

            # TABS
            tab1, tab2, tab3 = st.tabs(["🔎 Compare Changes", "📥 Download Standardized File", "📜 Logic Log"])

            with tab1:
                st.subheader("Comparison: Original vs Standard")
                st.dataframe(
                    df_comp,
                    column_config={
                        "Raw Menu": st.column_config.TextColumn("Raw Menu", width="medium"),
                        "Std Menu": st.column_config.TextColumn("✅ Standard", width="medium"),
                        "Raw Cat": st.column_config.TextColumn("Raw Category", width="medium"),
                        "Std Cat": st.column_config.TextColumn("✅ Standard", width="medium"),
                    },
                    use_container_width=True,
                    hide_index=True
                )

            with tab2:
                st.success("Your file is ready. All missing fields have been inferred or defaulted.")
                
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_std.to_excel(writer, index=False, sheet_name='Products_Cleaned')
                output.seek(0)
                
                st.download_button(
                    label="📥 Download Standardized Excel",
                    data=output,
                    file_name="Yoco_Standardized_Menu.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary"
                )

            with tab3:
                st.subheader("Intervention Log")
                if errors:
                    st.dataframe(pd.DataFrame(errors), use_container_width=True)
                else:
                    st.info("No major changes needed.")

        else:
            st.error("Could not read 'Products(Finished Goods)' sheet.")
    else:
        st.error("Please upload a file with the 'Products(Finished Goods)' sheet.")