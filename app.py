# AI-Based Timetable Generation System - Web App - Version 4.5
# Author: Rahat Beldar & Gemini AI

from flask import Flask, request, jsonify, render_template, send_from_directory, abort
import subprocess
import os
import sqlite3
import pandas as pd
import sys 
import click 

app = Flask(__name__)

# --- Configuration ---
DB_PATH = 'timetable.db'
COURSE_OUTPUT = "course_timetable.xlsx"
FACULTY_OUTPUT = "faculty_timetable.xlsx"
LAB_OUTPUT = "lab_timetable.xlsx"
SAMPLES_DIR = os.path.join('data', 'samples')
ALL_OUTPUT_FILES = [COURSE_OUTPUT, FACULTY_OUTPUT, LAB_OUTPUT]

@app.cli.command('init-db')
def init_db_command():
    if os.path.exists(DB_PATH): os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.close()
    click.echo('Database safaltapoorvak initialize ho gaya hai.')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/data/<table_name>', methods=['GET'])
def get_data(table_name):
    # (Function pehle jaisa hi hai)
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        if not table_name.isalnum(): return jsonify({"error": "Invalid table name"}), 400
        df = pd.read_sql_query(f"SELECT * FROM {table_name}", conn)
        df = df.astype(object).where(pd.notnull(df), None)
        return jsonify(df.to_dict(orient='records'))
    except Exception as e:
        error_message = f"Server error fetching data for '{table_name}': {e}"
        print(error_message, file=sys.stderr)
        return jsonify({"error": error_message, "message": "Database table maujood nahi hai."}), 500
    finally:
        if conn: conn.close()


@app.route('/api/upload/<table_name>', methods=['POST'])
def upload_csv(table_name):
    # (Function pehle jaisa hi hai)
    if 'file' not in request.files: return jsonify({"success": False, "message": "Koi file nahi chuni gayi"})
    file = request.files['file']
    if file.filename == '': return jsonify({"success": False, "message": "Koi file nahi chuni gayi"})
    try:
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_csv(file.stream)
        if not table_name.isalnum(): return jsonify({"success": False, "message": "Invalid table name"}), 400
        df.to_sql(table_name, conn, if_exists='replace', index=False)
        conn.close()
        return jsonify({"success": True, "message": f"'{file.filename}' ka data '{table_name}' mein upload ho gaya hai."})
    except Exception as e:
        return jsonify({"success": False, "message": f"Upload fail ho gaya: {str(e)}"})

@app.route('/generate', methods=['POST'])
def generate_timetable():
    """Timetable generation script ko trigger karta hai."""
    try:
        # NAYA: UI se mode lena
        mode = request.json.get('mode', 'compact')
        if mode not in ['compact', 'flexible']:
            mode = 'compact' # Input ko sanitize karein

        for f in ALL_OUTPUT_FILES:
            if os.path.exists(f): os.remove(f)
            
        script_path = os.path.join(os.path.dirname(__file__), 'timetable_generator_db.py')
        
        # NAYA: Mode ko script mein pass karna
        result = subprocess.run(['python', script_path, mode], capture_output=True, text=True)

        if result.returncode != 0 or not os.path.exists(COURSE_OUTPUT):
            error_logs = result.stderr if result.stderr else "Generator script fail ho gaya."
            return jsonify({"success": False, "message": "Timetable generate nahi ho saka.", "logs": error_logs})
        
        files_to_download = {}
        if os.path.exists(COURSE_OUTPUT): files_to_download["course"] = {"name": "Course / Student Timetable", "path": COURSE_OUTPUT}
        if os.path.exists(FACULTY_OUTPUT): files_to_download["faculty"] = {"name": "Faculty Timetable", "path": FACULTY_OUTPUT}
        if os.path.exists(LAB_OUTPUT): files_to_download["lab"] = {"name": "Lab Timetable", "path": LAB_OUTPUT}

        return jsonify({
            "success": True, "message": "Naya Timetable safaltapoorvak generate ho gaya hai.",
            "logs": result.stdout or "Generation safal raha.", "files": files_to_download
        })
    except Exception as e:
        return jsonify({"success": False, "message": f"Server error: {str(e)}", "logs": ""})

@app.route('/download/<path:filename>')
def download(filename):
    """Files download karata hai."""
    # (Function pehle jaisa hi hai)
    if '..' in filename or filename.startswith('/'): abort(400)
    if filename.startswith('sample_'):
        try:
            actual_filename = filename.replace('sample_', '')
            return send_from_directory(SAMPLES_DIR, actual_filename, as_attachment=True)
        except FileNotFoundError: abort(404)
    elif filename in ALL_OUTPUT_FILES:
        try:
            return send_from_directory('.', filename, as_attachment=True)
        except FileNotFoundError: abort(404)
    else:
        abort(404)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

