# AI-Based Timetable Generation System - Version 5.4
# Features: Added detailed faculty workload analysis on failure
# Author: Rahat Beldar & Gemini AI
# timtable clor ferturter added

import pandas as pd
import sqlite3
from ortools.sat.python import cp_model
import sys
import collections
from openpyxl.styles import PatternFill, Border, Side, Alignment, Font

# --- Database Path ---
DB_PATH = 'timetable.db'

# --- Timetable Configuration ---
TIMETABLE_CONFIG = {
    "MAX_CLASSES_PER_DAY_FACULTY": 5,
    "MAX_CLASSES_PER_WEEK_FACULTY": 25,
    "MAX_LAB_HOURS_PER_DAY_COURSE": 3,
}

def sanitize_sheet_name(name):
    """Excel sheet ke naam ke liye anuchit characters ko hatata hai."""
    invalid_chars = ['*', ':', '/', '\\', '?', '[', ']']
    clean_name = name
    for char in invalid_chars:
        clean_name = clean_name.replace(char, '')
    return clean_name[:31]

def load_data_from_db():
    """Database se data load karta hai."""
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

        if 'course_id' in rooms.columns: rooms['course_id'] = rooms['course_id'].fillna('')
        if 'is_elective' not in subjects.columns: subjects['is_elective'] = 'N'
        if 'elective_group' not in subjects.columns: subjects['elective_group'] = ''
        
        print("Database se data safaltapoorvak load aur clean ho gaya.")
        return courses, subjects, faculty, rooms, labs
    except Exception as e:
        print(f"Error: Database se data load nahi ho saka: {e}", file=sys.stderr)
        return (None,) * 5

def validate_data(courses, subjects, faculty, rooms, labs):
    """DataFrames ki jaanch karta hai."""
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

def analyze_infeasibility(courses, subjects, faculty, rooms, labs, config):
    """Solution na milne par data ka vistar se analysis karta hai."""
    report = collections.defaultdict(list)

    # --- Check 1: Har subject ke liye faculty hai ya nahi ---
    for _, subject in subjects.iterrows():
        is_faculty_assigned = faculty['subjects'].astype(str).apply(lambda s: subject['subject_id'] in [subj.strip() for subj in s.split(',')])
        if not is_faculty_assigned.any():
            report["Resource Shortage"].append(f"Subject '{subject['subject_name']}' ({subject['subject_id']}) ko padhane ke liye koi faculty assign nahi hai.")

    # --- Check 2: Har lab subject ke liye lab room hai ya nahi ---
    lab_subjects = subjects[subjects['lab_hours'] > 0]
    for _, subject in lab_subjects.iterrows():
        is_lab_assigned = labs['subject_id'].astype(str).apply(lambda s: subject['subject_id'] in [subj.strip() for subj in s.split(',')])
        if not is_lab_assigned.any():
            report["Resource Shortage"].append(f"Lab Subject '{subject['subject_name']}' ({subject['subject_id']}) ke liye koi lab room assign nahi hai.")

    # --- NAYA: WORKLOAD ANALYSIS ---
    subjects['total_hours'] = subjects['lecture_hours'] + subjects['lab_hours']
    faculty_workload = collections.defaultdict(float)
    
    # Har subject ke liye, uske hours usko padha sakne wale sabhi teachers mein anumanit roop se baant do
    for _, subject_row in subjects.iterrows():
        subject_id = subject_row['subject_id']
        hours = float(subject_row['total_hours'])
        
        possible_faculty_df = faculty[faculty['subjects'].astype(str).str.contains(f"\\b{subject_id}\\b", regex=True)]
        
        if not possible_faculty_df.empty:
            load_per_faculty = hours / len(possible_faculty_df)
            for fac_id in possible_faculty_df['faculty_id']:
                faculty_workload[fac_id] += load_per_faculty

    # Ab check karo ki kiska anumanit workload maximum limit se zyada hai
    max_weekly_hours = config.get("MAX_CLASSES_PER_WEEK_FACULTY", 25)
    for fac_id, estimated_hours in faculty_workload.items():
        if estimated_hours > max_weekly_hours:
            faculty_name = faculty.loc[faculty['faculty_id'] == fac_id, 'faculty_name'].iloc[0]
            report["Faculty Overload (Potential)"].append(f"Faculty '{faculty_name}' ({fac_id}) ka anumanit workload ({estimated_hours:.1f} hours) maximum limit ({max_weekly_hours} hours) se zyada hai.")
            
    # --- NAYA: SYSTEM-WIDE CAPACITY CHECK ---
    total_required_hours = subjects['total_hours'].sum()
    total_available_capacity = len(faculty) * max_weekly_hours
    if total_required_hours > total_available_capacity:
        report["System-Wide Overload"].append(f"Poore system mein faculty ki kami hai. Kul zaroori hours: {total_required_hours}, jabki kul uplabdh capacity: {total_available_capacity}.")

    return report


# --- Timetable Static Configuration ---
DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
SLOT_TIMES = { 0: "09:00 - 10:00", 1: "10:00 - 11:00", 2: "11:15 - 12:15", 3: "12:15 - 01:15", 4: "02:00 - 03:00", 5: "03:00 - 04:00", 6: "04:00 - 05:00" }
AVAILABLE_SLOTS_PER_DAY = len(SLOT_TIMES)
MORNING_SLOTS_COUNT = 4 
INVALID_2H_LAB_START_SLOTS = {1, 3, 6}



## ----- COLOR STYLES FOR EXCEL FILES -----## 

def apply_excel_formatting(writer, sheet_name, df):
    """Excel sheet par custom formatting apply karta hai."""
    # --- Styles Define Karein (Image ke hisab se) ---
    header_fill = PatternFill(start_color='E800A3', end_color='E800A3', fill_type='solid') # Magenta/Pink
    break_fill = PatternFill(start_color='FFFF00', end_color='FFFF00', fill_type='solid')   # Yellow
    lecture_fill = PatternFill(start_color='BDD7EE', end_color='BDD7EE', fill_type='solid') # Light Blue
    lab_fill = PatternFill(start_color='C0C0C0', end_color='C0C0C0', fill_type='solid')       # Grey

    header_font = Font(color='FFFFFF', bold=True) # White & Bold
    
    thin_border_side = Side(style='thin')
    cell_border = Border(left=thin_border_side, right=thin_border_side, top=thin_border_side, bottom=thin_border_side)
    
    cell_alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)

    # --- Workbook aur Worksheet Access Karein ---
    workbook = writer.book
    worksheet = writer.sheets[sheet_name]

    # --- Formatting Apply Karein ---
    
    # 1. Header Row (Days)
    for cell in worksheet[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = cell_alignment
        cell.border = cell_border
        
    # 2. Baki saari cells
    for row in worksheet.iter_rows(min_row=2): # Header ke baad se start karein
        for cell in row:
            cell.border = cell_border
            cell.alignment = cell_alignment
            if cell.value:
                # String me check karke color fill karein
                if "Tea Break" in str(cell.value) or "Lunch Break" in str(cell.value):
                    cell.fill = break_fill
                elif "[Lab]" in str(cell.value):
                    cell.fill = lab_fill
                elif "[Lecture]" in str(cell.value):
                    cell.fill = lecture_fill
                # Time slots column (Column A) ke liye alag se
                if cell.column_letter == 'A':
                     cell.font = Font(bold=True)


    # 3. Column ki chaudai (width) auto-adjust karein
    for column_cells in worksheet.columns:
        # Har column ki max length nikalo
        max_length = 0
        column_letter = column_cells[0].column_letter
        for cell in column_cells:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except:
                pass
        # Thodi extra space ke saath width set karo
        adjusted_width = (max_length + 4)
        worksheet.column_dimensions[column_letter].width = adjusted_width
        
    # Row ki height set karein
    for i in range(1, worksheet.max_row + 1):
        worksheet.row_dimensions[i].height = 45

# END OF EXCEL FORMATTING FUNCTION


def main(schedule_mode='compact'):
    print(f"--- Quantum Scheduler v5.4 ---")
    print(f"Selected Mode: {schedule_mode.upper()} Schedule")
    
    courses, subjects, faculty, rooms, labs = load_data_from_db()
    if not validate_data(courses, subjects, faculty, rooms, labs): return

    model = cp_model.CpModel()
    
    lecture_assignments, lab_1h_assignments, lab_2h_assignments = {}, {}, {}

    print("Step 1: Saare possible assignments ke liye variables banaye ja rahe hain...")
    for _, subject_row in subjects.iterrows():
        course_id, subject_id = subject_row['course_id'], subject_row['subject_id']
        faculty_series = faculty['subjects'].astype(str).apply(lambda s: subject_id in [s.strip() for s in s.split(',')])
        possible_faculty = faculty[faculty_series]['faculty_id'].tolist()
        lab_hours = subject_row['lab_hours']
        num_2h_blocks, num_1h_slots = lab_hours // 2, lab_hours % 2
        
        for fac in possible_faculty:
            if subject_row['lecture_hours'] > 0:
                dedicated_rooms = rooms.loc[rooms['course_id'] == course_id, 'room_id'].tolist() if 'course_id' in rooms.columns else []
                general_rooms = rooms.loc[rooms['course_id'] == '', 'room_id'].tolist() if 'course_id' in rooms.columns else rooms['room_id'].tolist()
                lecture_rooms = dedicated_rooms if dedicated_rooms else general_rooms
                for room in lecture_rooms:
                    for day in range(len(DAYS)):
                        for slot in range(AVAILABLE_SLOTS_PER_DAY):
                            key = (course_id, subject_id, fac, day, slot, room, "Lecture")
                            lecture_assignments[key] = model.NewBoolVar(f'L_{course_id}_{subject_id}_{fac}_{day}_{slot}_{room}'.replace('-', '_'))
            if lab_hours > 0:
                lab_series = labs['subject_id'].astype(str).apply(lambda s: subject_id in [s.strip() for s in s.split(',')])
                possible_labs = labs[lab_series]['lab_id'].tolist()
                for lab in possible_labs:
                    for day in range(len(DAYS)):
                        if num_2h_blocks > 0:
                            for slot in range(AVAILABLE_SLOTS_PER_DAY - 1):
                                if slot in INVALID_2H_LAB_START_SLOTS: continue
                                key = (course_id, subject_id, fac, day, slot, lab, "Lab2H")
                                lab_2h_assignments[key] = model.NewBoolVar(f'L2H_{course_id}_{subject_id}_{fac}_{day}_{slot}_{lab}'.replace('-', '_'))
                        if num_1h_slots > 0:
                            for slot in range(AVAILABLE_SLOTS_PER_DAY):
                                key = (course_id, subject_id, fac, day, slot, lab, "Lab1H")
                                lab_1h_assignments[key] = model.NewBoolVar(f'L1H_{course_id}_{subject_id}_{fac}_{day}_{slot}_{lab}'.replace('-', '_'))
    print(f"Variables creation complete. Total possibilities: {len(lecture_assignments) + len(lab_1h_assignments) + len(lab_2h_assignments)}")

    print("Step 2: Model par saare niyam (constraints) lagaye ja rahe hain...")
    all_courses, all_faculty, all_rooms, all_labs = courses['course_id'].tolist(), faculty['faculty_id'].tolist(), rooms['room_id'].tolist(), labs['lab_id'].tolist()

    # Consistent Teacher
    for course_id, subject_id in subjects[['course_id', 'subject_id']].drop_duplicates().itertuples(index=False):
        faculty_series = faculty['subjects'].astype(str).apply(lambda s: subject_id in [s.strip() for s in s.split(',')])
        possible_faculty = faculty[faculty_series]['faculty_id'].tolist()
        if len(possible_faculty) > 1:
            choices = {fac: model.NewBoolVar(f'choice_{course_id}_{subject_id}_{fac}') for fac in possible_faculty}
            model.AddExactlyOne(choices.values())
            for fac, choice_var in choices.items():
                for k,v in {**lecture_assignments, **lab_1h_assignments, **lab_2h_assignments}.items():
                    if k[0]==course_id and k[1]==subject_id and k[2]==fac:
                        model.AddImplication(v, choice_var)

    # Subject Hours
    for _, sub in subjects.iterrows():
        model.Add(sum(v for k,v in lecture_assignments.items() if k[0]==sub.course_id and k[1]==sub.subject_id) == sub.lecture_hours)
        model.Add(sum(v for k,v in lab_2h_assignments.items() if k[0]==sub.course_id and k[1]==sub.subject_id) == sub.lab_hours // 2)
        model.Add(sum(v for k,v in lab_1h_assignments.items() if k[0]==sub.course_id and k[1]==sub.subject_id) == sub.lab_hours % 2)

    # Clash Constraints
    for day in range(len(DAYS)):
        for slot in range(AVAILABLE_SLOTS_PER_DAY):
            for res_list, res_idx in [(all_courses, 0), (all_faculty, 2)]:
                for res_id in res_list:
                    occupancy = [v for k,v in lecture_assignments.items() if k[res_idx]==res_id and k[3]==day and k[4]==slot]
                    occupancy += [v for k,v in lab_1h_assignments.items() if k[res_idx]==res_id and k[3]==day and k[4]==slot]
                    occupancy += [v for k,v in lab_2h_assignments.items() if k[res_idx]==res_id and k[3]==day and k[4]==slot]
                    if slot > 0: occupancy += [v for k,v in lab_2h_assignments.items() if k[res_idx]==res_id and k[3]==day and k[4]==slot-1]
                    model.Add(sum(occupancy) <= 1)
            for room_id in all_rooms: model.AddAtMostOne(v for k,v in lecture_assignments.items() if k[5]==room_id and k[3]==day and k[4]==slot)
            for lab_id in all_labs:
                occupancy = [v for k,v in lab_1h_assignments.items() if k[5]==lab_id and k[3]==day and k[4]==slot]
                occupancy += [v for k,v in lab_2h_assignments.items() if k[5]==lab_id and k[3]==day and k[4]==slot]
                if slot > 0: occupancy += [v for k,v in lab_2h_assignments.items() if k[5]==lab_id and k[3]==day and k[4]==slot-1]
                model.Add(sum(occupancy) <= 1)
    
    # One Lecture Per Day
    for course_id, subject_id in subjects[['course_id', 'subject_id']].drop_duplicates().itertuples(index=False):
        for day in range(len(DAYS)):
            model.Add(sum(v for k, v in lecture_assignments.items() if k[0] == course_id and k[1] == subject_id and k[3] == day) <= 1)

    # Advanced Rules
    for course in all_courses:
        for day in range(len(DAYS)):
            model.Add(sum(v for k,v in lab_1h_assignments.items() if k[0]==course and k[3]==day) + \
                      sum(v*2 for k,v in lab_2h_assignments.items() if k[0]==course and k[3]==day) <= TIMETABLE_CONFIG["MAX_LAB_HOURS_PER_DAY_COURSE"])
            for subject in subjects['subject_id'].unique():
                model.Add(sum(v for k,v in lab_1h_assignments.items() if k[0]==course and k[1]==subject and k[3]==day) + \
                          sum(v*2 for k,v in lab_2h_assignments.items() if k[0]==course and k[1]==subject and k[3]==day) <= 2)

    # Workload Rules
    for fac in all_faculty:
        model.Add(sum(v for k,v in lecture_assignments.items() if k[2]==fac) + sum(v for k,v in lab_1h_assignments.items() if k[2]==fac) + (sum(v for k,v in lab_2h_assignments.items() if k[2]==fac)*2) <= TIMETABLE_CONFIG["MAX_CLASSES_PER_WEEK_FACULTY"])
        for day in range(len(DAYS)):
             model.Add(sum(v for k,v in lecture_assignments.items() if k[2]==fac and k[3]==day) + sum(v for k,v in lab_1h_assignments.items() if k[2]==fac and k[3]==day) + (sum(v for k,v in lab_2h_assignments.items() if k[2]==fac and k[3]==day)*2) <= TIMETABLE_CONFIG["MAX_CLASSES_PER_DAY_FACULTY"])

    print(f"Step 3: '{schedule_mode.upper()}' mode ke anusaar objectives set kiye ja rahe hain...")
    gap_penalties = []
    for course_id in all_courses:
        for day in range(len(DAYS)):
            class_in_slot = [model.NewBoolVar(f'occ_{course_id}_{day}_{s}') for s in range(AVAILABLE_SLOTS_PER_DAY)]
            for s in range(AVAILABLE_SLOTS_PER_DAY):
                occupancy = [v for k,v in {**lecture_assignments, **lab_1h_assignments, **lab_2h_assignments}.items() if k[0]==course_id and k[3]==day and (k[4]==s or (k[6]=='Lab2H' and k[4]==s-1))]
                model.Add(sum(occupancy) > 0).OnlyEnforceIf(class_in_slot[s])
                model.Add(sum(occupancy) == 0).OnlyEnforceIf(class_in_slot[s].Not())

            if schedule_mode == 'compact':
                for s in range(AVAILABLE_SLOTS_PER_DAY - 1):
                    model.AddImplication(class_in_slot[s+1], class_in_slot[s])
            
            elif schedule_mode == 'flexible':
                for s in range(1, AVAILABLE_SLOTS_PER_DAY - 1):
                    is_a_gap = model.NewBoolVar(f'gap_{course_id}_{day}_{s}')
                    class_before = model.NewBoolVar(f'cb_{s}')
                    class_after = model.NewBoolVar(f'ca_{s}')
                    model.AddBoolOr([class_in_slot[i] for i in range(s)]).OnlyEnforceIf(class_before)
                    model.Add(sum([class_in_slot[i] for i in range(s)]) == 0).OnlyEnforceIf(class_before.Not())
                    model.AddBoolOr([class_in_slot[i] for i in range(s + 1, AVAILABLE_SLOTS_PER_DAY)]).OnlyEnforceIf(class_after)
                    model.Add(sum([class_in_slot[i] for i in range(s+1, AVAILABLE_SLOTS_PER_DAY)]) == 0).OnlyEnforceIf(class_after.Not())
                    model.AddBoolAnd([class_in_slot[s].Not(), class_before, class_after]).OnlyEnforceIf(is_a_gap)
                    gap_penalties.append(is_a_gap)
    
    faculty_daily_loads, student_daily_loads = [], []
    for fac in all_faculty:
        for day in range(len(DAYS)):
            load = sum(v for k,v in lecture_assignments.items() if k[2]==fac and k[3]==day) + sum(v for k,v in lab_1h_assignments.items() if k[2]==fac and k[3]==day) + (sum(v for k,v in lab_2h_assignments.items() if k[2]==fac and k[3]==day)*2)
            faculty_daily_loads.append(load)
    for course in all_courses:
        for day in range(len(DAYS)):
            load = sum(v for k,v in lecture_assignments.items() if k[0]==course and k[3]==day) + sum(v for k,v in lab_1h_assignments.items() if k[0]==course and k[3]==day) + (sum(v for k,v in lab_2h_assignments.items() if k[0]==course and k[3]==day)*2)
            student_daily_loads.append(load)
    
    max_faculty_load = model.NewIntVar(0, TIMETABLE_CONFIG["MAX_CLASSES_PER_DAY_FACULTY"], 'max_f_load')
    max_student_load = model.NewIntVar(0, AVAILABLE_SLOTS_PER_DAY, 'max_s_load')
    total_gaps = model.NewIntVar(0, len(gap_penalties) if gap_penalties else 0, 'total_gaps')
    
    for load in faculty_daily_loads: model.Add(load <= max_faculty_load)
    for load in student_daily_loads: model.Add(load <= max_student_load)
    model.Add(total_gaps == sum(gap_penalties))

    model.Minimize(max_faculty_load + max_student_load + total_gaps)

    print("Step 4: Solver ko chala kar best solution dhoondha ja raha hai...")
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 240.0
    status = solver.Solve(model)

    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        print('SUCCESS: Ek optimal/feasible solution mil gaya!')
        
        faculty_workload = collections.defaultdict(int)
        all_solved_assignments = {**lecture_assignments, **lab_1h_assignments, **lab_2h_assignments}
        for key, var in all_solved_assignments.items():
            if solver.Value(var) == 1:
                fac_id = key[2]
                duration = 2 if key[6] == "Lab2H" else 1
                faculty_workload[fac_id] += duration
        
        print("\n--- Faculty Weekly Workload Report ---")
        for fac_id, hours in sorted(faculty_workload.items()):
            fac_name = faculty.loc[faculty['faculty_id'] == fac_id, 'faculty_name'].iloc[0]
            print(f"- {fac_name} ({fac_id}): {hours} weekly hours")
        print("-------------------------------------\n")

        EXCEL_ROW_ORDER = [ "09:00 - 10:00", "10:00 - 11:00", "11:00 - 11:15", "11:15 - 12:15", "12:15 - 01:15", "01:15 - 02:00", "02:00 - 03:00", "03:00 - 04:00", "04:00 - 05:00" ]
        
        
        
        
        # with pd.ExcelWriter('course_timetable.xlsx', engine='openpyxl') as writer:
        #     for _, course_row in courses.iterrows():
        #         course_id, course_name = course_row['course_id'], course_row['course_name']
        #         df = pd.DataFrame(index=SLOT_TIMES.values(), columns=DAYS)
        #         for key, var in all_solved_assignments.items():
        #             if solver.Value(var) == 1 and key[0] == course_id:
        #                 day, slot, sub_id, fac_id, loc_id, type = key[3], key[4], key[1], key[2], key[5], key[6]
        #                 sub_name = subjects.loc[subjects['subject_id'] == sub_id, 'subject_name'].iloc[0]
        #                 fac_name = faculty.loc[faculty['faculty_id'] == fac_id, 'faculty_name'].iloc[0]
        #                 entry = f"{sub_name}\n({fac_name})\n@{loc_id} [{type.replace('Lab2H', 'Lab').replace('Lab1H', 'Lab')}]"
        #                 df.loc[SLOT_TIMES[slot], DAYS[day]] = entry
        #                 if type == "Lab2H": df.loc[SLOT_TIMES[slot+1], DAYS[day]] = entry
        #         df.loc["11:00 - 11:15"] = "Tea Break"
        #         df.loc["01:15 - 02:00"] = "Lunch Break"
        #         df = df.reindex(EXCEL_ROW_ORDER)
        #         sheet_name = sanitize_sheet_name(f"C_{course_name}")
        #         df.to_excel(writer, sheet_name=sheet_name)
        # print("Course timetable 'course_timetable.xlsx' file mein generate ho gaya hai.")

        # with pd.ExcelWriter('faculty_timetable.xlsx', engine='openpyxl') as writer:
        #     for _, fac_row in faculty.iterrows():
        #         fac_id, fac_name = fac_row['faculty_id'], fac_row['faculty_name']
        #         df = pd.DataFrame(index=SLOT_TIMES.values(), columns=DAYS)
        #         for key, var in all_solved_assignments.items():
        #             if solver.Value(var) == 1 and key[2] == fac_id:
        #                 day, slot, sub_id, course_id, loc_id, type = key[3], key[4], key[1], key[0], key[5], key[6]
        #                 sub_name = subjects.loc[subjects['subject_id'] == sub_id, 'subject_name'].iloc[0]
        #                 course_name = courses.loc[courses['course_id'] == course_id, 'course_name'].iloc[0]
        #                 entry = f"{sub_name}\n({course_name})\n@{loc_id} [{type.replace('Lab2H', 'Lab').replace('Lab1H', 'Lab')}]"
        #                 df.loc[SLOT_TIMES[slot], DAYS[day]] = entry
        #                 if type == "Lab2H": df.loc[SLOT_TIMES[slot+1], DAYS[day]] = entry
        #         df.loc["11:00 - 11:15"] = "Tea Break"
        #         df.loc["01:15 - 02:00"] = "Lunch Break"
        #         df = df.reindex(EXCEL_ROW_ORDER)
        #         sheet_name = sanitize_sheet_name(f"F_{fac_name}")
        #         df.to_excel(writer, sheet_name=sheet_name)
        # print("Faculty timetable 'faculty_timetable.xlsx' file mein generate ho gaya hai.")

        # with pd.ExcelWriter('lab_timetable.xlsx', engine='openpyxl') as writer:
        #     for _, lab_row in labs.iterrows():
        #         lab_id = lab_row['lab_id']
        #         df = pd.DataFrame(index=SLOT_TIMES.values(), columns=DAYS)
        #         for key, var in {**lab_1h_assignments, **lab_2h_assignments}.items():
        #             if solver.Value(var) == 1 and key[5] == lab_id:
        #                 day, slot, sub_id, fac_id, course_id, type = key[3], key[4], key[1], key[2], key[0], key[6]
        #                 sub_name = subjects.loc[subjects['subject_id'] == sub_id, 'subject_name'].iloc[0]
        #                 fac_name = faculty.loc[faculty['faculty_id'] == fac_id, 'faculty_name'].iloc[0]
        #                 course_name = courses.loc[courses['course_id'] == course_id, 'course_name'].iloc[0]
        #                 entry = f"{sub_name}\n({course_name})\n- {fac_name} -"
        #                 df.loc[SLOT_TIMES[slot], DAYS[day]] = entry
        #                 if type == "Lab2H": df.loc[SLOT_TIMES[slot+1], DAYS[day]] = entry
        #         df.loc["11:00 - 11:15"] = "Tea Break"
        #         df.loc["01:15 - 02:00"] = "Lunch Break"
        #         df = df.reindex(EXCEL_ROW_ORDER)
        #         sheet_name = sanitize_sheet_name(f"Lab_{lab_id}")
        #         df.to_excel(writer, sheet_name=sheet_name)
        # print("Lab timetable 'lab_timetable.xlsx' file mein generate ho gaya hai.")
        
        
# COLOR FORMATTING FUNCTION
# --- Course Timetable Generation ---
        with pd.ExcelWriter('course_timetable.xlsx', engine='openpyxl') as writer:
            for _, course_row in courses.iterrows():
                course_id, course_name = course_row['course_id'], course_row['course_name']
                df = pd.DataFrame(index=SLOT_TIMES.values(), columns=DAYS)
                for key, var in all_solved_assignments.items():
                    if solver.Value(var) == 1 and key[0] == course_id:
                        day, slot, sub_id, fac_id, loc_id, type = key[3], key[4], key[1], key[2], key[5], key[6]
                        sub_name = subjects.loc[subjects['subject_id'] == sub_id, 'subject_name'].iloc[0]
                        fac_name = faculty.loc[faculty['faculty_id'] == fac_id, 'faculty_name'].iloc[0]
                        
                        type_tag = "Lab" if "Lab" in type else "Lecture"
                        entry = f"{sub_name}\n({fac_name})\n@{loc_id} [{type_tag}]"
                        
                        df.loc[SLOT_TIMES[slot], DAYS[day]] = entry
                        if type == "Lab2H": df.loc[SLOT_TIMES[slot+1], DAYS[day]] = entry
                
                df.loc["11:00 - 11:15"] = "Tea Break"
                df.loc["01:15 - 02:00"] = "Lunch Break"
                df = df.reindex(EXCEL_ROW_ORDER)
                sheet_name = sanitize_sheet_name(f"C_{course_name}")
                
                df.to_excel(writer, sheet_name=sheet_name)
                apply_excel_formatting(writer, sheet_name, df) # Formatting function call

        print("Course timetable 'course_timetable.xlsx' file mein generate ho gaya hai.")

        # --- Faculty Timetable Generation ---
        with pd.ExcelWriter('faculty_timetable.xlsx', engine='openpyxl') as writer:
            for _, fac_row in faculty.iterrows():
                fac_id, fac_name = fac_row['faculty_id'], fac_row['faculty_name']
                df = pd.DataFrame(index=SLOT_TIMES.values(), columns=DAYS)
                for key, var in all_solved_assignments.items():
                    if solver.Value(var) == 1 and key[2] == fac_id:
                        day, slot, sub_id, course_id, loc_id, type = key[3], key[4], key[1], key[0], key[5], key[6]
                        sub_name = subjects.loc[subjects['subject_id'] == sub_id, 'subject_name'].iloc[0]
                        course_name = courses.loc[courses['course_id'] == course_id, 'course_name'].iloc[0]
                        
                        type_tag = "Lab" if "Lab" in type else "Lecture"
                        entry = f"{sub_name}\n({course_name})\n@{loc_id} [{type_tag}]"
                        
                        df.loc[SLOT_TIMES[slot], DAYS[day]] = entry
                        if type == "Lab2H": df.loc[SLOT_TIMES[slot+1], DAYS[day]] = entry

                df.loc["11:00 - 11:15"] = "Tea Break"
                df.loc["01:15 - 02:00"] = "Lunch Break"
                df = df.reindex(EXCEL_ROW_ORDER)
                sheet_name = sanitize_sheet_name(f"F_{fac_name}")

                df.to_excel(writer, sheet_name=sheet_name)
                apply_excel_formatting(writer, sheet_name, df) # Formatting function call

        print("Faculty timetable 'faculty_timetable.xlsx' file mein generate ho gaya hai.")

        # --- Lab Timetable Generation ---
        with pd.ExcelWriter('lab_timetable.xlsx', engine='openpyxl') as writer:
            for _, lab_row in labs.iterrows():
                lab_id = lab_row['lab_id']
                df = pd.DataFrame(index=SLOT_TIMES.values(), columns=DAYS)
                for key, var in {**lab_1h_assignments, **lab_2h_assignments}.items():
                    if solver.Value(var) == 1 and key[5] == lab_id:
                        day, slot, sub_id, fac_id, course_id, type = key[3], key[4], key[1], key[2], key[0], key[6]
                        sub_name = subjects.loc[subjects['subject_id'] == sub_id, 'subject_name'].iloc[0]
                        fac_name = faculty.loc[faculty['faculty_id'] == fac_id, 'faculty_name'].iloc[0]
                        course_name = courses.loc[courses['course_id'] == course_id, 'course_name'].iloc[0]
                        
                        entry = f"{sub_name}\n({course_name})\n- {fac_name} - [Lab]" # Lab file me hamesha Lab hi rahega
                        
                        df.loc[SLOT_TIMES[slot], DAYS[day]] = entry
                        if type == "Lab2H": df.loc[SLOT_TIMES[slot+1], DAYS[day]] = entry

                df.loc["11:00 - 11:15"] = "Tea Break"
                df.loc["01:15 - 02:00"] = "Lunch Break"
                df = df.reindex(EXCEL_ROW_ORDER)
                sheet_name = sanitize_sheet_name(f"Lab_{lab_id}")
                
                df.to_excel(writer, sheet_name=sheet_name)
                apply_excel_formatting(writer, sheet_name, df) # Formatting function call

        print("Lab timetable 'lab_timetable.xlsx' file mein generate ho gaya hai.")
        
    # --- END OF TIMETABLE GENERATION ---   


    else:
        print('FAILURE: KOI FEASIBLE SOLUTION NAHI MILA.', file=sys.stderr)
        print("Karan: Diye gaye niyam (constraints) itne sakht hain ki unke saath timetable banana possible nahi hai.", file=sys.stderr)
        print("\n--- SUGGESTION ---", file=sys.stderr)
        if schedule_mode == 'compact':
            print("Aap abhi 'Compact Mode' ka istemal kar rahe hain, jo bahut sakht hai.", file=sys.stderr)
            print("Salah: 'Flexible Mode' mein generate karne ki koshish karein. Isse solution milne ki sambhavna badh jayegi.", file=sys.stderr)
        else:
            print("Aap 'Flexible Mode' ka istemal kar rahe hain, fir bhi solution nahi mila.", file=sys.stderr)
            print("Salah: Faculty workload limits ko thoda badha kar dekhein, ya check karein ki sabhi subjects ke liye anivarya resources (faculty, labs) hain ya nahi.", file=sys.stderr)
        print("------------------\n", file=sys.stderr)
        
        # Yahan updated function call kiya ja raha hai
        report = analyze_infeasibility(courses, subjects, faculty, rooms, labs, TIMETABLE_CONFIG)
        if report:
            print("\n--- DETAILED CONFLICT ANALYSIS ---", file=sys.stderr)
            for category, messages in report.items():
                print(f"\n* {category}:", file=sys.stderr)
                for msg in messages: print(f"  - {msg}", file=sys.stderr)
            print("--------------------------------", file=sys.stderr)

if __name__ == '__main__':
    mode_arg = 'compact'
    if len(sys.argv) > 1 and sys.argv[1] in ['compact', 'flexible']:
        mode_arg = sys.argv[1]
    main(schedule_mode=mode_arg)
 