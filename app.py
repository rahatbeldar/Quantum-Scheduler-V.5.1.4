# AI-Based Timetable Generation System - Web App - Version 3.3 (Intelligent Log Handling)
# Author: Rahat Beldar

from flask import Flask, request, jsonify, render_template, send_from_directory
import subprocess
import os
import sqlite3
import pandas as pd
import sys # Error logging ke liye joda gaya
import click # 'init-db' command ke liye joda gaya

app = Flask(__name__)

# --- Configuration ---
DB_PATH = 'timetable.db'
OUTPUT_FILENAME = "timetable_output.xlsx"
SAMPLES_DIR = os.path.join('data', 'samples')


# --- Database Initialization Command ---
@app.cli.command('init-db')
def init_db_command():
    """Purana data saaf karke database file ko dobara banata hai."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.close()
    click.echo('Database safaltapoorvak initialize ho gaya hai. Saara purana data clear kar diya gaya hai.')


# --- Page Rendering Route ---
@app.route('/')
def index():
    """index.html page ko render karta hai."""
    return render_template('index.html')


# --- API Routes for Data Handling ---
@app.route('/api/data/<table_name>', methods=['GET'])
def get_data(table_name):
    """Database se data fetch karke JSON format mein bhejta hai."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        if not table_name.isalnum():
            return jsonify({"error": "Invalid table name"}), 400
        
        df = pd.read_sql_query(f"SELECT * FROM {table_name}", conn)
        df = df.astype(object).where(pd.notnull(df), None) # NaN ko None se badlein
        
        return jsonify(df.to_dict(orient='records'))
    except Exception as e:
        error_message = f"Server error fetching data for '{table_name}': {type(e).__name__} - {e}"
        print(error_message, file=sys.stderr)
        return jsonify({
            "error": error_message, 
            "message": "Server par data fetch karte samay error aayi. Ho sakta hai database table मौजूद na ho. 'init-db' command chalakar dobara koshish karein."
        }), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/upload/<table_name>', methods=['POST'])
def upload_csv(table_name):
    """User se CSV file upload karvata hai aur database mein save karta hai."""
    if 'file' not in request.files:
        return jsonify({"success": False, "message": "Koi file nahi chuni gayi"})
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"success": False, "message": "Koi file nahi chuni gayi"})

    try:
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_csv(file.stream)
        
        if not table_name.isalnum():
            return jsonify({"success": False, "message": "Invalid table name"}), 400
            
        df.to_sql(table_name, conn, if_exists='replace', index=False)
        conn.close()
        return jsonify({"success": True, "message": f"'{file.filename}' ka data '{table_name}' mein safaltapoorvak upload ho gaya hai."})
    except Exception as e:
        return jsonify({"success": False, "message": f"Upload fail ho gaya: {str(e)}"})


# --- Timetable Generation Route (UPGRADED) ---
@app.route('/generate', methods=['POST'])
def generate_timetable():
    """Timetable generation script ko trigger karta hai aur result ko aache se handle karta hai."""
    try:
        output_filepath = os.path.join(os.path.dirname(__file__), OUTPUT_FILENAME)
        if os.path.exists(output_filepath):
            os.remove(output_filepath)
            
        script_path = os.path.join(os.path.dirname(__file__), 'timetable_generator_db.py')
        
        # 'check=True' ko hatayein taaki hum result ko manually handle kar sakein
        result = subprocess.run(
            ['python', script_path],
            capture_output=True, text=True
        )

        # Naya, behtar logic: Script ke result ko jaanchein
        # Agar return code 0 nahi hai, ya output file nahi bani, to ise failure maanein
        if result.returncode != 0 or not os.path.exists(output_filepath):
            # stderr mein conflict report ya error hota hai
            error_logs = result.stderr if result.stderr else "Generator script fail ho gaya lekin koi error message nahi diya."
            return jsonify({
                "success": False, 
                "message": "Timetable generate nahi ho saka. Kripya neeche diye gaye logs check karein.",
                "logs": error_logs
            })
        
        # Agar sab kuch theek hai, to success message bhejein
        return jsonify({
            "success": True, 
            "message": "Naya Timetable safaltapoorvak generate ho gaya hai.",
            "logs": result.stdout if result.stdout else "Generation safal raha.",
            "output_file": OUTPUT_FILENAME
        })
        
    except Exception as e:
        # Catch any other unexpected errors
        return jsonify({"success": False, "message": f"Ek anokha server error aaya: {str(e)}", "logs": ""})


# --- Download Route ---
@app.route('/download/<path:filename>')
def download(filename):
    """Generated files ya sample CSVs ko download karata hai."""
    if filename.startswith('sample_'):
        try:
            actual_filename = filename.replace('sample_', '')
            return send_from_directory(SAMPLES_DIR, actual_filename, as_attachment=True)
        except FileNotFoundError:
             from flask import abort
             abort(404, description="Sample file not found")
    elif filename == OUTPUT_FILENAME:
        try:
            return send_from_directory('.', filename, as_attachment=True)
        except FileNotFoundError:
            from flask import abort
            abort(404, description="Timetable file not found. Please generate it first.")
    else:
        from flask import abort
        abort(404)
        
# local host keliye hai
# if __name__ == '__main__':
#     app.run(debug=True)


#deploy ke lye hai railway

import os
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))



# if __name__ == '__main__':
#     port = int(os.environ.get("PORT", 8080))  # Railway ka PORT le, warna default 8080
#     app.run(host="0.0.0.0", port=port, debug=False)






# ### Ab Kya Karna Hai (Samasya ka Pakka Ilaaj)

# 1.  Apne server ko band karein (Ctrl+C).
# 2.  Upar diye gaye naye code se apni `app.py` file ko replace karein.
# 3.  Terminal mein, apne project folder ke andar, yeh command chalayein. **Yeh aapke purane, kharab database ko delete karke ek naya, saaf database bana dega.**
#     ```bash
#     flask init-db
#     ```
# 4.  Ab apna server dobara chalu karein:
#     ```bash
#     flask run

