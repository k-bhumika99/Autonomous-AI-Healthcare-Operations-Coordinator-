import pandas as pd

def generate_sample_excel(output_filename="sample_hospital_data.xlsx"):
    # Sheet 1: Patients (Patient_Master)
    df_patients = pd.DataFrame([
        {"patient_no": "P-101", "full_name": "Eleanor Vance", "age": 42, "gender": "Female", "dept": "Cardiology", "emergency_flag": True, "severity": "Emergency", "phone": "+15550199281"},
        {"patient_no": "P-102", "full_name": "Marcus Aurelius", "age": 58, "gender": "Male", "dept": "General Medicine", "emergency_flag": False, "severity": "Routine", "phone": "+15550199282"},
        {"patient_no": "P-103", "full_name": "Sophia Martinez", "age": 29, "gender": "Female", "dept": "Emergency", "emergency_flag": True, "severity": "Critical", "phone": "+15550199283"},
        {"patient_no": "P-104", "full_name": "Arthur Pendelton", "age": 67, "gender": "Male", "dept": "Neurology", "emergency_flag": False, "severity": "Routine", "phone": "+15550199284"},
        {"patient_no": "P-105", "full_name": "Chloe Bennett", "age": 35, "gender": "Female", "dept": "Orthopedics", "emergency_flag": True, "severity": "Emergency", "phone": "+15550199285"}
    ])

    # Sheet 2: Appointments (Visit_Schedule)
    df_appts = pd.DataFrame([
        {"appt_no": "APT-201", "pt_name": "Eleanor Vance", "doctor": "Dr. Sarah Jenkins", "dept": "Cardiology", "visit_date": "2026-09-11", "slot_time": "09:00 AM", "urgency": "Emergency", "contact": "+15550199281"},
        {"appt_no": "APT-202", "pt_name": "Marcus Aurelius", "doctor": "Dr. Alan Grant", "dept": "General Medicine", "visit_date": "2026-09-11", "slot_time": "09:30 AM", "urgency": "Routine", "contact": "+15550199282"},
        {"appt_no": "APT-203", "pt_name": "Arthur Pendelton", "doctor": "Dr. House", "dept": "Neurology", "visit_date": "2026-09-11", "slot_time": "10:00 AM", "urgency": "Routine", "contact": "+15550199284"},
        {"appt_no": "APT-204", "pt_name": "Chloe Bennett", "doctor": "Dr. Watson", "dept": "Orthopedics", "visit_date": "2026-09-11", "slot_time": "10:30 AM", "urgency": "Emergency", "contact": "+15550199285"}
    ])

    # Sheet 3: Beds (Bed_Inventory)
    df_beds = pd.DataFrame([
        {"bed_no": "BED-ICU-01", "ward_name": "ICU Ward A", "bed_type": "ICU", "state": "Available", "occupant_id": ""},
        {"bed_no": "BED-ICU-02", "ward_name": "ICU Ward A", "bed_type": "ICU", "state": "Occupied", "occupant_id": "P-101"},
        {"bed_no": "BED-GEN-01", "ward_name": "General Ward B", "bed_type": "General", "state": "Available", "occupant_id": ""},
        {"bed_no": "BED-GEN-02", "ward_name": "General Ward B", "bed_type": "General", "state": "Occupied", "occupant_id": "P-102"},
        {"bed_no": "BED-EMG-01", "ward_name": "Emergency Triage", "bed_type": "Emergency", "state": "Available", "occupant_id": ""}
    ])

    # Sheet 4: Labs (Diagnostic_Queue)
    df_labs = pd.DataFrame([
        {"test_code": "LAB-501", "pt_name": "Eleanor Vance", "diagnostic_test": "Cardiac Enzymes Panel", "assigned_lab": "Lab A", "urgency": "High", "tat": "20 mins"},
        {"test_code": "LAB-502", "pt_name": "Marcus Aurelius", "diagnostic_test": "Complete Blood Count", "assigned_lab": "Lab A", "urgency": "Normal", "tat": "45 mins"},
        {"test_code": "LAB-503", "pt_name": "Sophia Martinez", "diagnostic_test": "CT Brain Scan", "assigned_lab": "Lab B", "urgency": "High", "tat": "15 mins"}
    ])

    # Sheet 5: Pharmacy (Medicine_Stock)
    df_pharm = pd.DataFrame([
        {"med_code": "MED-301", "medicine": "Epinephrine 1mg", "required_stock": 100, "current_stock": 15},
        {"med_code": "MED-302", "medicine": "Heparin Sodium Injection", "required_stock": 50, "current_stock": 40},
        {"med_code": "MED-303", "medicine": "Paracetamol 500mg", "required_stock": 500, "current_stock": 450}
    ])

    # Sheet 6: Staff (Employees)
    df_staff = pd.DataFrame([
        {"emp_id": "STF-401", "employee_name": "Dr. Sarah Jenkins", "title": "Cardiologist", "dept": "Cardiology", "status": "Available", "workload": "Normal"},
        {"emp_id": "STF-402", "employee_name": "Nurse Brenda Vance", "title": "Senior Nurse", "dept": "General Medicine", "status": "Available", "workload": "Low"},
        {"emp_id": "STF-403", "employee_name": "Dr. Gregory House", "title": "Diagnostician", "dept": "Neurology", "status": "On Duty", "workload": "High"}
    ])

    # Sheet 7: Discharge (Discharge_List)
    df_discharge = pd.DataFrame([
        {"case_id": "DIS-601", "pt_name": "Marcus Aurelius", "dept": "General Medicine", "clearance_ready": True, "allocated_bed": "BED-GEN-02"}
    ])

    with pd.ExcelWriter(output_filename, engine='openpyxl') as writer:
        df_patients.to_excel(writer, sheet_name='Patient_Master', index=False)
        df_appts.to_excel(writer, sheet_name='Visit_Schedule', index=False)
        df_beds.to_excel(writer, sheet_name='Bed_Inventory', index=False)
        df_labs.to_excel(writer, sheet_name='Diagnostic_Queue', index=False)
        df_pharm.to_excel(writer, sheet_name='Medicine_Stock', index=False)
        df_staff.to_excel(writer, sheet_name='Employees', index=False)
        df_discharge.to_excel(writer, sheet_name='Discharge_List', index=False)

    print(f"Sample hospital dataset generated at: {output_filename}")

if __name__ == "__main__":
    generate_sample_excel()
