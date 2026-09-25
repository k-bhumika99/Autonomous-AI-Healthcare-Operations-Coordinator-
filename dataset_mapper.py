import re
import pandas as pd
from services.gemini_service import gemini_service

CATEGORY_KEYWORDS = {
    'PATIENTS': ['patient', 'pt_', 'patients', 'demographics', 'admissions', 'cases', 'people'],
    'APPOINTMENTS': ['appointment', 'appt', 'schedule', 'visit', 'booking', 'consultation', 'slots'],
    'BEDS': ['bed', 'ward', 'room', 'bed_inventory', 'capacity', 'occupancy', 'beds'],
    'LABS': ['lab', 'diagnostic', 'test', 'specimen', 'pathology', 'radiology', 'labs'],
    'PHARMACY': ['pharmacy', 'medicine', 'drug', 'stock', 'inventory', 'medication', 'pharma'],
    'STAFFING': ['staff', 'employee', 'doctor', 'nurse', 'roster', 'workforce', 'personnel'],
    'DISCHARGE': ['discharge', 'checkout', 'release', 'discharges', 'post_care']
}

class DatasetMapper:
    def detect_category(self, sheet_or_filename, columns):
        """
        Detects category based on sheet name, filename, and column names.
        """
        name_clean = sheet_or_filename.lower().replace('_', ' ').replace('-', ' ')
        
        # Check title match
        for cat, keywords in CATEGORY_KEYWORDS.items():
            if any(kw in name_clean for kw in keywords):
                return cat

        # Check column matches
        cols_lower = [str(c).lower() for c in columns]
        if any(c in cols_lower for c in ['medicine_name', 'medicine', 'drug', 'required_quantity', 'available_quantity']):
            return 'PHARMACY'
        if any(c in cols_lower for c in ['test_name', 'lab', 'turnaround', 'specimen']):
            return 'LABS'
        if any(c in cols_lower for c in ['discharge_ready', 'discharge_id', 'discharge_date']):
            return 'DISCHARGE'
        if any(c in cols_lower for c in ['bed_id', 'ward', 'bed_type']):
            return 'BEDS'
        if any(c in cols_lower for c in ['appointment_id', 'appt_id', 'doctor', 'visit_date']):
            return 'APPOINTMENTS'
        if any(c in cols_lower for c in ['staff_id', 'employee_id', 'workload', 'role']):
            return 'STAFFING'
        if any(c in cols_lower for c in ['patient_id', 'age', 'gender', 'emergency', 'severity']):
            return 'PATIENTS'

        return 'UNKNOWN'

    def map_columns(self, category, columns, sample_rows=None):
        """
        Invokes Gemini service for semantic mapping, with fallback to rule mapping.
        """
        sample_dict = {}
        if sample_rows is not None and not sample_rows.empty:
            sample_dict = sample_rows.head(3).to_dict(orient='records')

        mapped = gemini_service.map_dataset_columns(category, columns, sample_dict)
        return mapped

dataset_mapper = DatasetMapper()
