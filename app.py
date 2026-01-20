import pandas as pd
from flask import Flask, request, jsonify
from flask_cors import CORS
import io

app = Flask(__name__)
CORS(app)

def validate_yoco_sheet(file_stream):
    report = {"status": "success", "issues": []}
    
    # Load the Excel file (all sheets)
    try:
        xls = pd.ExcelFile(file_stream)
    except Exception as e:
        return {"status": "error", "message": f"Could not read Excel file: {str(e)}"}

    # --- TAB 1: Site Data Information ---
    if "Site Data Information" in xls.sheet_names:
        df = pd.read_excel(xls, "Site Data Information", header=0)
        # Remove example row if it exists
        df = df[df["Site Name"] != "EXAMPLE"]
        
        required_cols = ["Site Name", "Owner Email Address", "Owner Telephone Number"]
        for col in required_cols:
            if col in df.columns and df[col].isnull().any():
                report["issues"].append(f"⚠️ 'Site Data Information': Missing values in '{col}'.")

    # --- TAB 2: Employee List ---
    if "Employee List" in xls.sheet_names:
        df = pd.read_excel(xls, "Employee List", header=0)
        df = df[df["Employee Name"] != "EXAMPLE"] # Filter example
        
        if "Login Code" in df.columns:
            # Check for non-numeric PINs
            non_numeric = df[pd.to_numeric(df["Login Code"], errors='coerce').isna()]
            if not non_numeric.empty:
                 report["issues"].append(f"❌ 'Employee List': Found {len(non_numeric)} Login Codes that are not numbers.")
            
            # Check length (should be 4 digits usually, strictly speaking)
            # This converts to string and checks length
            short_pins = df[df["Login Code"].astype(str).apply(lambda x: len(x.split('.')[0])) < 4]
            if not short_pins.empty:
                report["issues"].append(f"⚠️ 'Employee List': Some Login Codes might be too short (less than 4 digits).")

    # --- TAB 3: Products (Finished Goods) ---
    if "Products(Finished Goods)" in xls.sheet_names:
        df = pd.read_excel(xls, "Products(Finished Goods)", header=0)
        df = df[df["Product Name & Variant"] != "EXAMPLE"]
        
        # Check Selling Price
        if "Selling Price (incl vat)" in df.columns:
            invalid_prices = df[pd.to_numeric(df["Selling Price (incl vat)"], errors='coerce').isna()]
            if not invalid_prices.empty:
                report["issues"].append(f"❌ 'Products': Found {len(invalid_prices)} products with invalid selling prices.")

    # --- TAB 4: Stock Items (RAW MATERIALS) ---
    # This sheet often has a header instruction on the first row
    if "Stock Items(RAW MATERIALS)" in xls.sheet_names:
        # We try to find the real header. Usually it's row 1 (index 1) if row 0 is instructions
        df = pd.read_excel(xls, "Stock Items(RAW MATERIALS)")
        
        # Determine actual header row by searching for specific column name
        if "RAW MATERIAL Product Name" not in df.columns:
            df = pd.read_excel(xls, "Stock Items(RAW MATERIALS)", header=1)
        
        df = df[df["RAW MATERIAL Product Name"] != "EXAMPLES"]
        
        # Check for Cost Price
        if "Cost Price " in df.columns:
            missing_cost = df[df["Cost Price "].isnull()]
            if not missing_cost.empty:
                report["issues"].append(f"⚠️ 'Stock Items': Found {len(missing_cost)} items with missing Cost Price.")

    # --- CROSS REFERENCE: Recipes (Advanced) ---
    # Check if ingredients in recipes actually exist in the Stock Items tab
    if "Products Recipes" in xls.sheet_names and "Stock Items(RAW MATERIALS)" in xls.sheet_names:
        recipes = pd.read_excel(xls, "Products Recipes", header=4) # Headers often lower down on recipe sheets
        stock = pd.read_excel(xls, "Stock Items(RAW MATERIALS)", header=1)
        
        # Clean data
        stock_list = stock["RAW MATERIAL Product Name"].dropna().astype(str).str.strip().unique()
        
        if "RAW MATERIALS / MANUFACTURED PRODUCT NAME" in recipes.columns:
            recipe_ingredients = recipes["RAW MATERIALS / MANUFACTURED PRODUCT NAME"].dropna().astype(str).str.strip().unique()
            
            # Find missing
            missing = [item for item in recipe_ingredients if item not in stock_list and item != "EXAMPLE"]
            if missing:
                # Limit list to first 5 to save space
                report["issues"].append(f"❌ 'Products Recipes': These ingredients are used but not found in Stock Items list: {', '.join(missing[:5])}...")

    if not report["issues"]:
        report["message"] = "✅ No critical data issues found. File looks good!"
    else:
        report["message"] = "⚠️ Found data issues. See list below."

    return report

@app.route('/verify', methods=['POST'])
def verify_excel():
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    
    file = request.files['file']
    result = validate_yoco_sheet(file)
    return jsonify(result)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)