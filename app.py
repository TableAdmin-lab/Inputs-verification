from flask import Flask, request, jsonify
from flask_cors import CORS
import pandas as pd
import io

app = Flask(__name__)
# CORS allows your dashboard (e.g., mysite.com) to talk to this API
CORS(app)

@app.route('/verify', methods=['POST'])
def verify_excel():
    # 1. Check if file is present
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    try:
        # 2. Read the file directly from memory (no need to save to disk)
        df = pd.read_excel(file)
        
        report = {
            "total_rows": int(df.shape[0]),
            "total_cols": int(df.shape[1]),
            "issues": []
        }

        # --- RULE 1: Missing Data ---
        if df.isnull().values.any():
            missing_count = int(df.isnull().sum().sum())
            report["issues"].append({
                "type": "missing_data",
                "message": f"Found {missing_count} empty cells.",
                "severity": "warning"
            })

        # --- RULE 2: Duplicates ---
        duplicates = int(df.duplicated().sum())
        if duplicates > 0:
            report["issues"].append({
                "type": "duplicates",
                "message": f"Found {duplicates} duplicated rows.",
                "severity": "error"
            })

        # --- RULE 3: Email Validation (Example) ---
        if 'Email' in df.columns:
            # Check for missing '@' in Email column
            invalid_emails = df[~df['Email'].astype(str).str.contains('@', na=False)]
            count = len(invalid_emails)
            if count > 0:
                report["issues"].append({
                    "type": "invalid_format",
                    "message": f"Found {count} invalid email addresses.",
                    "severity": "error"
                })

        return jsonify({"status": "success", "report": report}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)