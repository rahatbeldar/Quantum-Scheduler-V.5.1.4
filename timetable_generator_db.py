# AI-Based Timetable Generation System - Version 3.2 (Workload Report)
# Features: Dedicated Rooms, Exact Subject Matching, Consistent Faculty, Conflict Analysis, Workload Balancing & Reporting

import pandas as pd
import sqlite3
from ortools.sat.python import cp_model
import sys
import collections

# Database ka path
DB_PATH = 'timetable.db'

def sanitize_sheet_name(name):
    """Excel sheet ke naam ke liye anuchit characters ko hatata hai aur naam ko chhota karta hai."""
    invalid_chars = ['*', ':', '/', '\\', '?', '[', ']']
    clean_name = name
    for char in invalid_chars:
        clean_name = clean_name.replace(char, '')
    return clean_name[:31]

def load_data_from_db():
    """Database se data load karke DataFrames return karta hai."""
    try:
        conn = sqlite3.connect(DB_PATH)
        courses = pd.read_sql_query("SELECT * from courses", conn, index_col=None)
        subjects = pd.read_sql_query("SELECT * from subjects", conn, index_col=None)
        faculty = pd.read_sql_query("SELECT * from faculty", conn, index_col=None)
        rooms = pd.read_sql_query("SELECT * from rooms", conn, index_col=None)
        labs = pd.read_sql_query("SELECT * from labs", conn, index_col=None)
        conn.close()
        
        for col in ['lecture_hours', 'lab_hours']:
            if col in subjects.columns:
                subjects[col] = pd.to_numeric(subjects[col], errors='coerce').fillna(0).astype(int)

        if 'course_id' in rooms.columns:
            rooms['course_id'] = rooms['course_id'].fillna('')

        print("Database se data safaltapoorvak load aur clean ho gaya.")

        if 'is_elective' not in subjects.columns: subjects['is_elective'] = 'N'
        if 'elective_group' not in subjects.columns: subjects['elective_group'] = ''
            
        return courses, subjects, faculty, rooms, labs
    except Exception as e:
        print(f"Error: Database se data load nahi ho saka: {e}", file=sys.stderr)
        return (None,) * 5

def validate_data(courses, subjects, faculty, rooms, labs):
    """DataFrames ki jaanch karke sunishchit karta hai ki sabhi zaroori columns maujood hain."""
    required_columns = {
        'courses': ['course_id', 'course_name'],
        'subjects': ['subject_id', 'subject_name', 'course_id', 'lecture_hours', 'lab_hours'],
        'faculty': ['faculty_id', 'faculty_name', 'subjects'],
        'rooms': ['room_id', 'capacity'],
        'labs': ['lab_id', 'subject_id', 'capacity']
    }
    dataframes = {'courses': courses, 'subjects': subjects, 'faculty': faculty, 'rooms': rooms, 'labs': labs}
    for name, df in dataframes.items():
        if df is None or df.empty:
            print(f"CRITICAL ERROR: '{name}' ka data nahi mila.", file=sys.stderr)
            return False
        for col in required_columns[name]:
            if col not in df.columns:
                print(f"CRITICAL ERROR in '{name}': Column '{col}' nahi mila.", file=sys.stderr)
                return False
    print("Sabhi data files ka validation safal raha.")
    return True

def analyze_infeasibility(courses, subjects, faculty, rooms, labs):
    """Jab solver solution nahi dhoondh pata, tab yeh function data ka analysis karta hai."""
    report = collections.defaultdict(list)
    for _, subject in subjects.iterrows():
        is_faculty_assigned = faculty['subjects'].astype(str).apply(lambda s: subject['subject_id'] in [subj.strip() for subj in s.split(',')])
        if not is_faculty_assigned.any():
            report["Faculty Shortage"].append(f"Subject '{subject['subject_name']}' ({subject['subject_id']}) ko padhane ke liye koi faculty assign nahi hai.")

    lab_subjects = subjects[subjects['lab_hours'] > 0]
    for _, subject in lab_subjects.iterrows():
        is_lab_assigned = labs['subject_id'].astype(str).apply(lambda s: subject['subject_id'] in [subj.strip() for subj in s.split(',')])
        if not is_lab_assigned.any():
            report["Resource Shortage"].append(f"Lab Subject '{subject['subject_name']}' ({subject['subject_id']}) ke liye koi lab room assign nahi hai.")
            
    return report

# --- Timetable Configuration ---
DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
SLOT_TIMES = {
    0: "09:00 - 10:00", 1: "10:00 - 11:00", 2: "11:15 - 12:15", 3: "12:15 - 01:15",
    4: "02:00 - 03:00", 5: "03:00 - 04:00", 6: "04:00 - 05:00"
}
AVAILABLE_SLOTS_PER_DAY = len(SLOT_TIMES)

def main():
    courses, subjects, faculty, rooms, labs = load_data_from_db()
    if not validate_data(courses, subjects, faculty, rooms, labs): return

    model = cp_model.CpModel()
    assignments = {}

    # --- Variables Definition ---
    for _, subject_row in subjects.iterrows():
        course_id, subject_id = subject_row['course_id'], subject_row['subject_id']
        faculty_series = faculty['subjects'].astype(str).apply(lambda s: subject_id in [subj.strip() for subj in s.split(',')])
        possible_faculty = faculty[faculty_series]['faculty_id'].tolist()
        for fac in possible_faculty:
            for day_idx in range(len(DAYS)):
                for slot_idx in range(AVAILABLE_SLOTS_PER_DAY):
                    if subject_row['lecture_hours'] > 0:
                        dedicated_rooms = rooms[rooms['course_id'] == course_id]['room_id'].tolist() if 'course_id' in rooms.columns and not rooms[rooms['course_id'] == course_id].empty else []
                        general_rooms = rooms[rooms['course_id'] == '']['room_id'].tolist() if 'course_id' in rooms.columns else rooms['room_id'].tolist()
                        lecture_rooms = dedicated_rooms if dedicated_rooms else general_rooms
                        for room in lecture_rooms:
                            key = (course_id, subject_id, fac, day_idx, slot_idx, room, "Lecture")
                            assignments[key] = model.NewBoolVar(''.join(map(str,key)).replace('-', '_'))
                    if subject_row['lab_hours'] > 0:
                        lab_series = labs['subject_id'].astype(str).apply(lambda s: subject_id in [subj.strip() for subj in s.split(',')])
                        possible_labs = labs[lab_series]['lab_id'].tolist()
                        for lab in possible_labs:
                            key = (course_id, subject_id, fac, day_idx, slot_idx, lab, "Lab")
                            assignments[key] = model.NewBoolVar(''.join(map(str,key)).replace('-', '_'))

    # --- Constraints ---
    core_subjects = subjects[subjects['is_elective'] == 'N']
    for _, subject_row in core_subjects.iterrows():
         course_id, subject_id = subject_row['course_id'], subject_row['subject_id']
         if subject_row['lecture_hours'] > 0:
            model.Add(sum(assignments[k] for k in assignments if k[0]==course_id and k[1]==subject_id and k[6]=="Lecture") == subject_row['lecture_hours'])
         if subject_row['lab_hours'] > 0:
            model.Add(sum(assignments[k] for k in assignments if k[0]==course_id and k[1]==subject_id and k[6]=="Lab") == subject_row['lab_hours'])

    # --- Consistent Teacher & Workload Balancing System ---
    faculty_choice_vars = {} 
    for course_id, subject_id in subjects[['course_id', 'subject_id']].drop_duplicates().itertuples(index=False):
        faculty_series = faculty['subjects'].astype(str).apply(lambda s: subject_id in [subj.strip() for subj in s.split(',')])
        possible_faculty = faculty[faculty_series]['faculty_id'].tolist()
        # Ek se zyada teacher hone par hi choice banayein
        if len(possible_faculty) > 1:
            choices = {fac: model.NewBoolVar(f'choice_{course_id}_{subject_id}_{fac}'.replace('-', '_')) for fac in possible_faculty}
            faculty_choice_vars[(course_id, subject_id)] = choices
            model.AddExactlyOne(choices.values())
            for fac, choice_var in choices.items():
                for k in assignments:
                    if k[0] == course_id and k[1] == subject_id and k[2] == fac:
                        model.AddImplication(assignments[k], choice_var)

    multi_faculty_subjects = (faculty['subjects'].str.split(',').explode().str.strip().value_counts().loc[lambda x: x > 1].index)
    for subject_id in multi_faculty_subjects:
        if subject_id not in subjects['subject_id'].values: continue
        faculty_series = faculty['subjects'].astype(str).apply(lambda s: subject_id in [subj.strip() for subj in s.split(',')])
        possible_faculty = faculty[faculty_series]['faculty_id'].tolist()
        num_faculties = len(possible_faculty)
        courses_for_this_subject = subjects[subjects['subject_id'] == subject_id]['course_id'].tolist()
        num_batches = len(courses_for_this_subject)
        if num_batches < num_faculties: continue # Agar batches kam hain, to balance karne ki zaroorat nahi
        min_batches_per_faculty = num_batches // num_faculties
        max_batches_per_faculty = (num_batches + num_faculties - 1) // num_faculties
        for fac in possible_faculty:
            choice_vars_for_fac = [faculty_choice_vars.get((c_id, subject_id), {}).get(fac) for c_id in courses_for_this_subject]
            choice_vars_for_fac = [v for v in choice_vars_for_fac if v is not None]
            if choice_vars_for_fac:
                num_batches_assigned_to_fac = sum(choice_vars_for_fac)
                model.Add(num_batches_assigned_to_fac >= min_batches_per_faculty)
                model.Add(num_batches_assigned_to_fac <= max_batches_per_faculty)

    # --- Clash constraints ---
    all_courses = courses['course_id'].tolist(); all_faculty = faculty['faculty_id'].tolist(); all_rooms = rooms['room_id'].tolist(); all_labs = labs['lab_id'].tolist()
    for day_idx in range(len(DAYS)):
        for slot_idx in range(AVAILABLE_SLOTS_PER_DAY):
            for course_id in all_courses:
                 model.AddAtMostOne(assignments[key] for key in assignments if key[0]==course_id and key[3]==day_idx and key[4]==slot_idx)
            for fac in all_faculty:
                model.AddAtMostOne(assignments[key] for key in assignments if key[2]==fac and key[3]==day_idx and key[4]==slot_idx)
            for room in all_rooms:
                model.AddAtMostOne(assignments[key] for key in assignments if key[5]==room and key[3]==day_idx and key[4]==slot_idx and key[6]=='Lecture')
            for lab in all_labs:
                model.AddAtMostOne(assignments[key] for key in assignments if key[5]==lab and key[3]==day_idx and key[4]==slot_idx and key[6]=='Lab')
                
    # --- Solver & Results ---
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 60.0
    status = solver.Solve(model)

    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        print('Ek feasible solution mil gaya!')

        # --- NAYA: Faculty Workload Calculation & Reporting ---
        faculty_workload = collections.defaultdict(int)
        for key, var in assignments.items():
            if solver.Value(var) == 1:
                # key = (course_id, subject_id, fac_id, day_idx, slot_idx, room/lab, type)
                fac_id = key[2]
                faculty_workload[fac_id] += 1
        
        print("\n--- Faculty Weekly Workload Report ---")
        # faculty DataFrame se faculty_name lene ke liye
        for fac_id, hours in sorted(faculty_workload.items()):
            fac_name = faculty.loc[faculty['faculty_id'] == fac_id, 'faculty_name'].iloc[0]
            print(f"- {fac_name} ({fac_id}): {hours} weekly/hours")
        print("-------------------------------------\n")
        # --- End of New Section ---

        with pd.ExcelWriter('timetable_output.xlsx', engine='openpyxl') as writer:
            for _, course_row in courses.iterrows():
                course_id = course_row['course_id']
                df = pd.DataFrame(index=[SLOT_TIMES[i] for i in range(AVAILABLE_SLOTS_PER_DAY)], columns=DAYS)
                for key, var in assignments.items():
                    if solver.Value(var) == 1 and key[0] == course_id:
                        day, slot = key[3], key[4]
                        sub_name = subjects.loc[subjects['subject_id'] == key[1], 'subject_name'].iloc[0]
                        fac_name = faculty.loc[faculty['faculty_id'] == key[2], 'faculty_name'].iloc[0]
                        loc, type = key[5], key[6]
                        df.loc[SLOT_TIMES[slot], DAYS[day]] = f"{sub_name}\n({fac_name})\n@{loc} [{type}]"
                sheet_name = sanitize_sheet_name(f"C_{course_id}")
                df.to_excel(writer, sheet_name=sheet_name)
            for _, fac_row in faculty.iterrows():
                fac_id, fac_name = fac_row['faculty_id'], fac_row['faculty_name']
                df = pd.DataFrame(index=[SLOT_TIMES[i] for i in range(AVAILABLE_SLOTS_PER_DAY)], columns=DAYS)
                for key, var in assignments.items():
                    if solver.Value(var) == 1 and key[2] == fac_id:
                        day, slot = key[3], key[4]
                        course_name = courses.loc[courses['course_id'] == key[0], 'course_name'].iloc[0]
                        sub_name = subjects.loc[subjects['subject_id'] == key[1], 'subject_name'].iloc[0]
                        loc, type = key[5], key[6]
                        df.loc[SLOT_TIMES[slot], DAYS[day]] = f"{sub_name}\n({course_name})\n@{loc} [{type}]"
                sheet_name = sanitize_sheet_name(f"F_{fac_name}")
                df.to_excel(writer, sheet_name=sheet_name)
        print("Timetable 'timetable_output.xlsx' file mein generate ho gaya hai.")
    else:
        print('KOI FEASIBLE SOLUTION NAHI MILA.', file=sys.stderr)
        report = analyze_infeasibility(courses, subjects, faculty, rooms, labs)
        if not report:
            print("Basic analysis mein koi saaf samasya nahi mili. Ho sakta hai ki constraints bahut zyada sakht hon.", file=sys.stderr)
        else:
            print("\n--- CONFLICT REPORT ---", file=sys.stderr)
            for category, messages in report.items():
                print(f"* {category}:", file=sys.stderr)
                for msg in messages:
                    print(f"  - {msg}", file=sys.stderr)
            print("-----------------------", file=sys.stderr)

if __name__ == '__main__':
    main()

