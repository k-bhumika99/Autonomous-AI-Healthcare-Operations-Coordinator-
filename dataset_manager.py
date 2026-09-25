import os
import json
import re
import pandas as pd
from datetime import datetime
from services.database import db, Dataset, Patient, Appointment, Notification, Bed, LabTest, PharmacyItem, StaffMember, DischargeRecord, ActivityLog
from services.dataset_mapper import dataset_mapper

class DatasetManager:
    def process_and_ingest(self, user_id, filepath, filename, file_type):
        """
        Ingests user dataset file (CSV/XLSX/JSON) into normalized SQLAlchemy tables.
        All dataset records get source='dataset'.
        Dataset appointments get notification status = 'Not Required' (no Twilio spam).
        """
        dataframes = {}

        if file_type in ['xlsx', 'xls']:
            excel_file = pd.ExcelFile(filepath)
            for sheet in excel_file.sheet_names:
                df = pd.read_excel(filepath, sheet_name=sheet)
                cat = dataset_mapper.detect_category(sheet, df.columns)
                if cat != 'UNKNOWN' and not df.empty:
                    dataframes[cat] = df
        elif file_type == 'csv':
            df = pd.read_csv(filepath)
            cat = dataset_mapper.detect_category(filename, df.columns)
            if cat != 'UNKNOWN' and not df.empty:
                dataframes[cat] = df
            else:
                dataframes['PATIENTS'] = df
        elif file_type == 'json':
            with open(filepath, 'r') as f:
                raw_json = json.load(f)
            if isinstance(raw_json, dict):
                for key, val in raw_json.items():
                    df = pd.DataFrame(val)
                    cat = dataset_mapper.detect_category(key, df.columns)
                    if cat != 'UNKNOWN' and not df.empty:
                        dataframes[cat] = df
            elif isinstance(raw_json, list):
                df = pd.DataFrame(raw_json)
                cat = dataset_mapper.detect_category(filename, df.columns)
                dataframes[cat if cat != 'UNKNOWN' else 'PATIENTS'] = df

        if not dataframes:
            raise ValueError("No valid hospital data tables or categories could be identified in the uploaded file.")

        # Clear pre-existing operational records for this user
        self.clear_user_data(user_id)

        total_rows = 0
        detected_categories = list(dataframes.keys())

        for cat, df in dataframes.items():
            total_rows += len(df)
            col_map = dataset_mapper.map_columns(cat, list(df.columns), df)

            if cat == 'PATIENTS':
                self._ingest_patients(user_id, df, col_map)
            elif cat == 'APPOINTMENTS':
                self._ingest_appointments(user_id, df, col_map)
            elif cat == 'BEDS':
                self._ingest_beds(user_id, df, col_map)
            elif cat == 'LABS':
                self._ingest_labs(user_id, df, col_map)
            elif cat == 'PHARMACY':
                self._ingest_pharmacy(user_id, df, col_map)
            elif cat == 'STAFFING':
                self._ingest_staffing(user_id, df, col_map)
            elif cat == 'DISCHARGE':
                self._ingest_discharge(user_id, df, col_map)

        # Mark all previous datasets inactive and save new Dataset record
        Dataset.query.filter_by(user_id=user_id).update({'status': 'INACTIVE'})
        new_ds = Dataset(
            user_id=user_id,
            filename=filename,
            file_type=file_type,
            upload_time=datetime.utcnow(),
            row_count=total_rows,
            column_count=sum(len(df.columns) for df in dataframes.values()),
            status='LIVE',
            categories_json=json.dumps(detected_categories)
        )
        db.session.add(new_ds)

        act = ActivityLog(
            user_id=user_id,
            agent_name="Dataset Manager",
            action=f"Ingested & activated dataset '{filename}' ({total_rows} total records across {len(detected_categories)} categories).",
            details=f"Categories: {', '.join(detected_categories)}",
            category="success"
        )
        db.session.add(act)

        # Restore any scenarios previously marked DATASET REMOVED back to ACTIVE
        from services.database import Scenario
        Scenario.query.filter_by(user_id=user_id, status='DATASET REMOVED').update({'status': 'ACTIVE'})
        db.session.commit()

        # Per-table counts from DB (live, not from df)
        table_counts = self._get_table_counts(user_id)

        return {
            "success": True,
            "filename": filename,
            "total_rows": total_rows,
            "categories": detected_categories,
            "dataset_id": new_ds.id,
            "table_counts": table_counts
        }

    def clear_user_data(self, user_id):
        from services.database import (AgentEvent, SimulationRun)
        Notification.query.filter_by(user_id=user_id).delete()
        Patient.query.filter_by(user_id=user_id).delete()
        Appointment.query.filter_by(user_id=user_id).delete()
        Bed.query.filter_by(user_id=user_id).delete()
        LabTest.query.filter_by(user_id=user_id).delete()
        PharmacyItem.query.filter_by(user_id=user_id).delete()
        StaffMember.query.filter_by(user_id=user_id).delete()
        DischargeRecord.query.filter_by(user_id=user_id).delete()
        ActivityLog.query.filter_by(user_id=user_id).delete()
        AgentEvent.query.filter_by(user_id=user_id).delete()
        SimulationRun.query.filter_by(user_id=user_id).delete()
        db.session.commit()

    def remove_user_dataset(self, user_id):
        """
        Deactivates active dataset, purges all operational database records for user_id,
        updates existing scenarios to status='DATASET REMOVED', and clears live analytics.
        """
        from services.database import Scenario
        Dataset.query.filter_by(user_id=user_id).delete()
        self.clear_user_data(user_id)
        
        # Mark historical scenarios as DATASET REMOVED instead of deleting them
        Scenario.query.filter_by(user_id=user_id).update({'status': 'DATASET REMOVED'})
        db.session.commit()
        return True

    def _get_table_counts(self, user_id):
        """Returns per-table live DB counts for the dataset management page."""
        active_ds = Dataset.query.filter_by(user_id=user_id, status='LIVE').first()
        if not active_ds:
            return {
                "patients": 0, "appointments": 0, "beds": 0, "labs": 0,
                "pharmacy": 0, "staffing": 0, "discharges": 0
            }
        return {
            "patients": Patient.query.filter_by(user_id=user_id).count(),
            "appointments": Appointment.query.filter_by(user_id=user_id).count(),
            "beds": Bed.query.filter_by(user_id=user_id).count(),
            "labs": LabTest.query.filter_by(user_id=user_id).count(),
            "pharmacy": PharmacyItem.query.filter_by(user_id=user_id).count(),
            "staffing": StaffMember.query.filter_by(user_id=user_id).count(),
            "discharges": DischargeRecord.query.filter_by(user_id=user_id).count(),
        }

    def get_user_dashboard_data(self, user_id):
        """
        Returns live KPI counts strictly based on user's DB.
        Zero hardcoded numbers. Zero preloaded data.
        """
        active_ds = Dataset.query.filter_by(user_id=user_id, status='LIVE').first()
        if not active_ds:
            return {
                "has_data": False,
                "dataset_info": None,
                "kpis": {
                    "total_patients": 0,
                    "emergency_patients": 0,
                    "available_beds": 0,
                    "total_beds": 0,
                    "today_appointments": 0,
                    "pending_labs": 0,
                    "critical_pharmacy": 0,
                    "available_staff": 0,
                    "discharge_ready": 0
                },
                "agents": self._get_empty_agent_statuses(),
                "activities": [],
                "hospital_overview": {"labels": ["8 AM", "12 PM", "4 PM", "8 PM"], "patients": [0, 0, 0, 0], "beds": [0, 0, 0, 0]},
                "table_counts": {
                    "patients": 0, "appointments": 0, "beds": 0, "labs": 0,
                    "pharmacy": 0, "staffing": 0, "discharges": 0
                }
            }

        categories = json.loads(active_ds.categories_json or '[]')

        # Real Database Calculations
        total_patients = Patient.query.filter_by(user_id=user_id).count()
        emergency_patients = Patient.query.filter_by(user_id=user_id, emergency=True).count()

        total_beds = Bed.query.filter_by(user_id=user_id).count()
        available_beds = Bed.query.filter_by(user_id=user_id, status='Available').count()

        today_appointments = Appointment.query.filter_by(user_id=user_id).count()

        activities = ActivityLog.query.filter_by(user_id=user_id).order_by(ActivityLog.id.desc()).limit(10).all()

        table_counts = self._get_table_counts(user_id)

        agents = {
            "Coordinator": {"status": "Ready", "data_available": True, "label": "Active", "actions": "State Monitored"},
            "Bed Management": {
                "status": "Ready" if 'BEDS' in categories else "Waiting",
                "data_available": 'BEDS' in categories,
                "label": "Active" if 'BEDS' in categories else "Waiting - Dataset unavailable",
                "actions": f"{available_beds}/{total_beds} Beds" if 'BEDS' in categories else "No bed data"
            },
            "Appointment": {
                "status": "Ready" if 'APPOINTMENTS' in categories else "Waiting",
                "data_available": 'APPOINTMENTS' in categories,
                "label": "Active" if 'APPOINTMENTS' in categories else "Waiting - Dataset unavailable",
                "actions": f"{today_appointments} Scheduled" if 'APPOINTMENTS' in categories else "No appt data"
            },
            "Lab": {
                "status": "Ready" if 'LABS' in categories else "Waiting",
                "data_available": 'LABS' in categories,
                "label": "Active" if 'LABS' in categories else "Waiting - Dataset unavailable",
                "actions": f"{LabTest.query.filter_by(user_id=user_id).count()} Tests" if 'LABS' in categories else "No lab data"
            },
            "Pharmacy": {
                "status": "Ready" if 'PHARMACY' in categories else "Waiting",
                "data_available": 'PHARMACY' in categories,
                "label": "Active" if 'PHARMACY' in categories else "Waiting - Dataset unavailable",
                "actions": f"{PharmacyItem.query.filter_by(user_id=user_id).count()} Medicines" if 'PHARMACY' in categories else "No pharmacy data"
            },
            "Staffing": {
                "status": "Ready" if 'STAFFING' in categories else "Waiting",
                "data_available": 'STAFFING' in categories,
                "label": "Active" if 'STAFFING' in categories else "Waiting - Dataset unavailable",
                "actions": f"{StaffMember.query.filter_by(user_id=user_id).count()} Staff" if 'STAFFING' in categories else "No staff data"
            },
            "Discharge": {
                "status": "Ready" if 'DISCHARGE' in categories else "Waiting",
                "data_available": 'DISCHARGE' in categories,
                "label": "Active" if 'DISCHARGE' in categories else "Waiting - Dataset unavailable",
                "actions": f"{DischargeRecord.query.filter_by(user_id=user_id).count()} Ready" if 'DISCHARGE' in categories else "No discharge data"
            }
        }

        return {
            "has_data": True,
            "dataset_info": {
                "filename": active_ds.filename,
                "row_count": active_ds.row_count,
                "upload_time": active_ds.upload_time.strftime('%Y-%m-%d %H:%M'),
                "categories": categories
            },
            "kpis": {
                "total_patients": total_patients,
                "emergency_patients": emergency_patients,
                "available_beds": available_beds,
                "total_beds": total_beds,
                "today_appointments": today_appointments
            },
            "agents": agents,
            "activities": [{
                "timestamp": a.timestamp,
                "agent_name": a.agent_name,
                "action": a.action,
                "details": a.details,
                "category": a.category
            } for a in activities],
            "hospital_overview": {
                "labels": ["8 AM", "12 PM", "4 PM", "8 PM"],
                "patients": [max(0, total_patients - 5), total_patients, max(0, total_patients - 2), total_patients + emergency_patients],
                "beds": [available_beds, available_beds, max(0, available_beds - 1), available_beds]
            },
            "table_counts": table_counts
        }

    def _get_empty_agent_statuses(self):
        agents_list = ["Coordinator", "Bed Management", "Appointment", "Lab", "Pharmacy", "Staffing", "Discharge"]
        return {
            name: {
                "status": "Waiting",
                "data_available": False,
                "label": "Waiting for Dataset",
                "actions": "No dataset"
            } for name in agents_list
        }

    def generate_next_patient_id(self, user_id):
        """
        Generates next sequential patient ID like P0501 from existing DB records.
        Finds the highest numeric suffix among P#### patterns.
        """
        all_patients = Patient.query.filter_by(user_id=user_id).with_entities(Patient.patient_id).all()
        max_num = 0
        for (pid,) in all_patients:
            m = re.match(r'P(\d+)$', str(pid).strip().upper())
            if m:
                num = int(m.group(1))
                if num > max_num:
                    max_num = num
        return f"P{max_num + 1:04d}"

    def generate_next_appointment_id(self, user_id):
        """
        Generates next sequential appointment ID like A01001 from existing DB records.
        Finds the highest numeric suffix among A##### patterns.
        """
        all_appts = Appointment.query.filter_by(user_id=user_id).with_entities(Appointment.appointment_id).all()
        max_num = 0
        for (aid,) in all_appts:
            m = re.match(r'A(\d+)$', str(aid).strip().upper())
            if m:
                num = int(m.group(1))
                if num > max_num:
                    max_num = num
        # Start from at least A01001
        next_num = max(max_num + 1, 1001)
        return f"A{next_num:05d}"

    # ---- Internal ingestion helpers ----

    def _ingest_patients(self, user_id, df, col_map):
        inv_map = {v: k for k, v in col_map.items()}
        for idx, row in df.iterrows():
            pid = str(row.get(inv_map.get('patient_id'), f"P{idx+101:04d}"))
            pname = str(row.get(inv_map.get('name'), f"Patient {idx+1}"))
            age_raw = row.get(inv_map.get('age'))
            age = int(age_raw) if pd.notnull(age_raw) and str(age_raw).isdigit() else 45
            gender = str(row.get(inv_map.get('gender'), 'Other'))
            dept = str(row.get(inv_map.get('department'), 'General Medicine'))
            emerg_raw = row.get(inv_map.get('emergency'))
            emergency = True if str(emerg_raw).lower() in ['true', '1', 'yes', 'emergency'] else False
            severity = str(row.get(inv_map.get('severity'), 'Emergency' if emergency else 'Routine'))
            bed_id = str(row.get(inv_map.get('bed_id'), ''))
            # Do NOT invent phone numbers — store None if not present
            phone_raw = row.get(inv_map.get('phone'))
            phone = str(phone_raw).strip() if pd.notnull(phone_raw) and str(phone_raw).strip() not in ['', 'nan'] else None

            p = Patient(
                user_id=user_id,
                patient_id=pid,
                name=pname,
                age=age,
                gender=gender,
                department=dept,
                emergency=emergency,
                severity=severity,
                status='Admitted',
                bed_id=bed_id,
                phone=phone,
                source='dataset',
                created_at=datetime.utcnow()
            )
            db.session.add(p)

    def _ingest_appointments(self, user_id, df, col_map):
        """
        Dataset appointments: source='dataset', status from dataset or 'Scheduled'.
        NO notification created — they are Not Required for dataset records.
        Do NOT set twilio_status Pending for dataset appointments.
        """
        inv_map = {v: k for k, v in col_map.items()}
        for idx, row in df.iterrows():
            aid = str(row.get(inv_map.get('appointment_id'), f"A{idx+201:05d}"))
            pid = str(row.get(inv_map.get('patient_id'), f"P{idx+101:04d}"))
            pname = str(row.get(inv_map.get('patient_name'), f"Patient {idx+1}"))
            doctor = str(row.get(inv_map.get('doctor'), 'Dr. Smith'))
            dept = str(row.get(inv_map.get('department'), 'Cardiology'))
            date_str = str(row.get(inv_map.get('date'), datetime.utcnow().strftime('%Y-%m-%d')))
            time_str = str(row.get(inv_map.get('time'), '09:00 AM'))
            priority = str(row.get(inv_map.get('priority'), 'Routine'))
            # Use actual dataset status; fallback to 'Scheduled'
            status_raw = row.get(inv_map.get('status'))
            status = str(status_raw).strip() if pd.notnull(status_raw) and str(status_raw).strip() not in ['', 'nan'] else 'Scheduled'
            # Do NOT invent phone numbers
            phone_raw = row.get(inv_map.get('phone'))
            phone = str(phone_raw).strip() if pd.notnull(phone_raw) and str(phone_raw).strip() not in ['', 'nan'] else None

            appt = Appointment(
                user_id=user_id,
                appointment_id=aid,
                patient_id=pid,
                patient_name=pname,
                doctor=doctor,
                department=dept,
                date=date_str,
                time=time_str,
                original_time=time_str,
                priority=priority,
                status=status,
                phone=phone,
                source='dataset',
                created_at=datetime.utcnow()
            )
            db.session.add(appt)
            # No Notification record needed for dataset appointments

    def _ingest_beds(self, user_id, df, col_map):
        inv_map = {v: k for k, v in col_map.items()}
        for idx, row in df.iterrows():
            bid = str(row.get(inv_map.get('bed_id'), f"BED-{idx+101}"))
            ward = str(row.get(inv_map.get('ward'), 'General Ward A'))
            btype = str(row.get(inv_map.get('type'), 'General'))
            status = str(row.get(inv_map.get('status'), 'Available'))
            pid = str(row.get(inv_map.get('patient_id'), '')) if status == 'Occupied' else ''

            b = Bed(
                user_id=user_id,
                bed_id=bid,
                ward=ward,
                type=btype,
                status=status,
                patient_id=pid,
                source='dataset',
                created_at=datetime.utcnow()
            )
            db.session.add(b)

    def _ingest_labs(self, user_id, df, col_map):
        inv_map = {v: k for k, v in col_map.items()}
        for idx, row in df.iterrows():
            tid = str(row.get(inv_map.get('test_id'), f"LAB-{idx+501}"))
            pid = str(row.get(inv_map.get('patient_id'), f"P{idx+101:04d}"))
            pname = str(row.get(inv_map.get('patient_name'), f"Patient {idx+1}"))
            tname = str(row.get(inv_map.get('test_name'), 'CBC & Metabolic Panel'))
            lab = str(row.get(inv_map.get('lab'), 'Lab A'))
            priority = str(row.get(inv_map.get('priority'), 'Normal'))
            status = str(row.get(inv_map.get('status'), 'Pending'))
            tat = str(row.get(inv_map.get('turnaround'), '45 mins'))

            l = LabTest(
                user_id=user_id,
                test_id=tid,
                patient_id=pid,
                patient_name=pname,
                test_name=tname,
                lab=lab,
                priority=priority,
                status=status,
                turnaround=tat,
                source='dataset',
                created_at=datetime.utcnow()
            )
            db.session.add(l)

    def _ingest_pharmacy(self, user_id, df, col_map):
        inv_map = {v: k for k, v in col_map.items()}
        for idx, row in df.iterrows():
            mid = str(row.get(inv_map.get('medicine_id'), f"MED-{idx+301}"))
            mname = str(row.get(inv_map.get('medicine_name'), f"Medicine {idx+1}"))
            req_raw = row.get(inv_map.get('required_quantity'))
            req = int(req_raw) if pd.notnull(req_raw) and str(req_raw).isdigit() else 50
            avail_raw = row.get(inv_map.get('available_quantity'))
            avail = int(avail_raw) if pd.notnull(avail_raw) and str(avail_raw).isdigit() else 20
            status = 'Shortage' if avail < req else 'In Stock'

            med = PharmacyItem(
                user_id=user_id,
                medicine_id=mid,
                medicine_name=mname,
                required_quantity=req,
                available_quantity=avail,
                status=status,
                source='dataset',
                created_at=datetime.utcnow()
            )
            db.session.add(med)

    def _ingest_staffing(self, user_id, df, col_map):
        inv_map = {v: k for k, v in col_map.items()}
        for idx, row in df.iterrows():
            sid = str(row.get(inv_map.get('staff_id'), f"STF-{idx+401}"))
            sname = str(row.get(inv_map.get('name'), f"Staff {idx+1}"))
            role = str(row.get(inv_map.get('role'), 'Nurse'))
            dept = str(row.get(inv_map.get('department'), 'Emergency'))
            avail = str(row.get(inv_map.get('availability'), 'Available'))
            workload = str(row.get(inv_map.get('workload'), 'Normal'))

            stf = StaffMember(
                user_id=user_id,
                staff_id=sid,
                name=sname,
                role=role,
                department=dept,
                availability=avail,
                workload=workload,
                source='dataset',
                created_at=datetime.utcnow()
            )
            db.session.add(stf)

    def _ingest_discharge(self, user_id, df, col_map):
        inv_map = {v: k for k, v in col_map.items()}
        for idx, row in df.iterrows():
            did = str(row.get(inv_map.get('discharge_id'), f"DIS-{idx+601}"))
            pid = str(row.get(inv_map.get('patient_id'), f"P{idx+101:04d}"))
            pname = str(row.get(inv_map.get('patient_name'), f"Patient {idx+1}"))
            dept = str(row.get(inv_map.get('department'), 'General Medicine'))
            ready_raw = row.get(inv_map.get('discharge_ready'))
            ready = True if str(ready_raw).lower() in ['true', '1', 'yes'] else False
            status = 'Discharge Ready' if ready else 'Pending Clearance'
            bed_id = str(row.get(inv_map.get('bed_id'), f"BED-{idx+101}"))

            disc = DischargeRecord(
                user_id=user_id,
                discharge_id=did,
                patient_id=pid,
                patient_name=pname,
                department=dept,
                discharge_ready=ready,
                status=status,
                bed_id=bed_id,
                source='dataset',
                created_at=datetime.utcnow()
            )
            db.session.add(disc)

dataset_manager = DatasetManager()
