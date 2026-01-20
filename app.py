import streamlit as st
import pandas as pd
import openpyxl
import re

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Yoco Onboarding Verifier", page_icon="🛡️", layout="wide")

# --- CSS STYLING ---
st.markdown("""
<style>
    .stDataFrame { border: 1px solid #ddd; border-radius: 5px; }
    .score-card { padding: 20px; border-radius: 10px; text-align: center; border: 2px solid #eee; }
    .good { background-color: #d4edda; color: #155724; border-color: #c3e6cb; }
    .average { background-color: #fff3cd; color: #856404; border-color: #ffeeba; }
    .bad { background-color: #f8d7da; color: #721c24; border-color: #f5c6cb; }
</style>
""", unsafe_allow_html=True)

# --- HELPER: NORMALIZE NAMES (Remove Prefixes) ---
def normalize_name(name):
    """
    Removes (RAW), (MAN), and extra spaces to allow cross-matching.
    Example: "(RAW) Tomatoes" becomes "Tomatoes"
    """
    if pd.isna(name):
        return ""
    name = str(name).strip()
    # Remove (RAW) or (MAN) case insensitive
    name = re.sub(r'(?i)\(RAW\)', '', name)
    name = re.sub(r'(?i)\(MAN\)', '', name)
    # Remove double spaces created by the removal
    return name.strip()

# --- HELPER: GET VISIBLE SHEETS ---
def get_visible_sheet_names(file):
    try:
        wb = openpyxl.load_workbook(file, read_only=True)
        visible_sheets = []
        for sheet in wb.worksheets:
            if sheet.sheet_state == 'visible':
                visible_sheets.append(sheet.title)
        return visible_sheets
    except Exception as e:
        return []

# --- HELPER: INTELLIGENT DATA PARSER ---
def get_clean_data(file, sheet_name, unique_col_identifier):
    """
    1. Finds LAST header (skips examples).
    2. Strips whitespace from columns.
    3. Removes rows where the main identifier is empty.
    """
    try:
        # Step A: Deep Scan for Header
        df_scan = pd.read_excel(file, sheet_name=sheet_name, header=None, nrows=50)
        
        matching_rows = []
        for i, row in df_scan.iterrows():
            row_str = row.astype(str).str.replace(r'\s+', ' ', regex=True).str.strip()
            if row_str.str.contains(unique_col_identifier, case=False, na=False).any():
                matching_rows.append(i)
        
        if not matching_rows:
            return None, f"Could not find header '{unique_col_identifier}'"

        # LOGIC: LAST HEADER WINS
        header_row_idx = matching_rows[-1]

        # Step B: Load data
        df = pd.read_excel(file, sheet_name=sheet_name, header=header_row_idx)
        df.columns = df.columns.astype(str).str.strip()

        # Step C: Identity Check
        target_col = next((c for c in df.columns if unique_col_identifier.lower() in c.lower()), None)
        
        if target_col:
            # Drop empty rows
            df = df[df[target_col].notna()]
            df = df[df[target_col].astype(str).str.strip() != ""]
            # Drop "EXAMPLE" rows just in case
            df = df[df[target_col].astype(str).str.upper() != "EXAMPLE"]

        # Helper column
        offset = header_row_idx + 2 
        df['__excel_row__'] = df.index + offset
        
        return df, None

    except Exception as e:
        return None, str(e)

# --- MAIN APP ---
st.title("🛡️ Yoco Sheet Verifier")
st.markdown("""
**Logic:**
1. Ignores Hidden Sheets.
2. Skips Examples (Reads below 2nd header).
3. **Smart Matching:** Ignores `(RAW)` and `(MAN)` prefixes when checking recipes.
""")

uploaded_file = st.file_uploader("", type=["xlsx"])

if uploaded_file:
    # 1. Visible Sheets
    visible_sheets = get_visible_sheet_names(uploaded_file)
    if not visible_sheets:
        st.error("No visible sheets found. Please unhide your data.")
        st.stop()

    # 2. Init Scoring
    quality_score = 100
    error_log = []
    
    # We store the "Cleaned" stock names here
    normalized_stock_set = set()
    
    PENALTY_CRITICAL = 10
    PENALTY_MINOR = 1

    # ==========================================
    # CHECK 1: STOCK ITEMS
    # ==========================================
    if "Stock Items(RAW MATERIALS)" in visible_sheets:
        df_stock, err = get_clean_data(uploaded_file, "Stock Items(RAW MATERIALS)", "RAW MATERIAL Product Name")
        
        if df_stock is not None:
            if df_stock.empty:
                quality_score = 0
                error_log.append({
                    "Severity": "Critical",
                    "Sheet": "Stock Items",
                    "Row": "-",
                    "Column": "All",
                    "Issue": "NO STOCK FOUND",
                    "Fix": "Stock sheet is empty (Examples ignored)."
                })
            else:
                # --- BUILD NORMALIZED STOCK LIST ---
                # We strip (RAW) and (MAN) from the Source of Truth
                raw_names = df_stock["RAW MATERIAL Product Name"].dropna().astype(str)
                normalized_stock_set = set([normalize_name(x) for x in raw_names])

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
                                "Fix": "Enter a value"
                            })

    # ==========================================
    # CHECK 2: EMPLOYEES
    # ==========================================
    if "Employee List" in visible_sheets:
        df_emp, err = get_clean_data(uploaded_file, "Employee List", "Employee Name")
        
        if df_emp is not None:
            if df_emp.empty:
                # Assuming employees are required
                quality_score -= 10
                error_log.append({
                    "Severity": "Warning",
                    "Sheet": "Employee List",
                    "Row": "-",
                    "Column": "All",
                    "Issue": "No Employees Found",
                    "Fix": "Please add employees."
                })
            elif "Login Code" in df_emp.columns:
                for _, row in df_emp.iterrows():
                    code = str(row["Login Code"]).strip()
                    if code.endswith(".0"): code = code[:-2]
                    
                    if not code.isdigit():
                        quality_score -= PENALTY_MINOR
                        error_log.append({
                            "Severity": "Warning",
                            "Sheet": "Employee List",
                            "Row": row['__excel_row__'],
                            "Column": "Login Code",
                            "Issue": f"Invalid PIN '{code}'",
                            "Fix": "Numbers only"
                        })

    # ==========================================
    # CHECK 3: PRODUCTS
    # ==========================================
    if "Products(Finished Goods)" in visible_sheets:
        df_prod, err = get_clean_data(uploaded_file, "Products(Finished Goods)", "Product Name")
        
        if df_prod is not None:
            if df_prod.empty:
                quality_score = 0
                error_log.append({
                    "Severity": "Critical",
                    "Sheet": "Products",
                    "Row": "-",
                    "Column": "All",
                    "Issue": "NO PRODUCTS FOUND",
                    "Fix": "Product sheet is empty."
                })
            elif "Selling Price (incl vat)" in df_prod.columns:
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
                            "Fix": "Enter value"
                        })
                    elif isinstance(price, str) and not price.replace('.','',1).isdigit():
                        quality_score -= PENALTY_CRITICAL
                        error_log.append({
                            "Severity": "Critical",
                            "Sheet": "Products",
                            "Row": row['__excel_row__'],
                            "Column": "Selling Price",
                            "Issue": f"Invalid format '{price}'",
                            "Fix": "Remove 'R' symbols"
                        })

    # ==========================================
    # CHECK 4: RECIPES (With Normalization)
    # ==========================================
    if "Products Recipes" in visible_sheets:
        df_rec, err = get_clean_data(uploaded_file, "Products Recipes", "RAW MATERIALS")
        
        col_ing_name = "RAW MATERIALS / MANUFACTURED PRODUCT NAME"
        
        if df_rec is not None:
            if df_rec.empty:
                # Only warn if stock exists but recipes don't
                if normalized_stock_set:
                     quality_score -= 5
                     error_log.append({
                        "Severity": "Info",
                        "Sheet": "Recipes",
                        "Row": "-",
                        "Column": "All",
                        "Issue": "No Recipes Found",
                        "Fix": "Optional: Add recipes to track stock."
                    })
            else:
                # Column Name Fallback
                if col_ing_name not in df_rec.columns:
                    candidates = [c for c in df_rec.columns if "RAW MATERIAL" in c.upper() and "NAME" in c.upper()]
                    if candidates: col_ing_name = candidates[0]

                if col_ing_name in df_rec.columns and normalized_stock_set:
                    for _, row in df_rec.iterrows():
                        original_ing_name = str(row[col_ing_name]).strip()
                        if original_ing_name == "nan" or original_ing_name == "": continue
                        
                        # --- NORMALIZE BEFORE CHECKING ---
                        # Clean the recipe ingredient name (remove RAW/MAN)
                        clean_ing_name = normalize_name(original_ing_name)
                        
                        if clean_ing_name not in normalized_stock_set:
                            quality_score -= PENALTY_CRITICAL
                            error_log.append({
                                "Severity": "Critical",
                                "Sheet": "Recipes",
                                "Row": row['__excel_row__'],
                                "Column": "Ingredient",
                                "Issue": f"Ghost Item: '{original_ing_name}'",
                                "Fix": "Spelling must match Stock (ignoring RAW/MAN prefixes)"
                            })

    # ==========================================
    # OUTPUT
    # ==========================================
    quality_score = max(0, int(quality_score))
    
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
        elif quality_score == 0:
            st.error("🚨 EMPTY DATA. Did you fill in the rows below the examples?")
        else:
            st.error("🚨 Critical errors found. Do not upload yet.")

    st.divider()

    if error_log:
        st.subheader("🛠️ Action Plan")
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
        
        csv = df_err.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Download Fix List (CSV)", csv, "fix_list.csv", "text/csv")