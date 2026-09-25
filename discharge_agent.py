import json
import logging
from datetime import datetime
from sqlalchemy import func
from services.database import db, DischargeRecord, Patient, ActivityLog
from services.event_manager import event_manager
from services.gemini_service import gemini_service

logger = logging.getLogger(__name__)

DEFAULT_INSTRUCTION = "Identify discharge-ready patients, group them by department, and determine how many beds could potentially be released to increase hospital capacity."

class DischargeAgent:
    def __init__(self):
        self.name = "Discharge"
        self.default_instruction = DEFAULT_INSTRUCTION

    def execute(self, scenario_id, user_id, user_instruction=None):
        instruction = user_instruction or DEFAULT_INSTRUCTION
        logger.info(f"Running DischargeAgent for scenario {scenario_id}, user {user_id} with instruction: {instruction}")

        total_records = DischargeRecord.query.filter_by(user_id=user_id).count()
        ready = DischargeRecord.query.filter_by(user_id=user_id, discharge_ready=True).count()
        not_ready = total_records - ready
        potential_beds = ready

        # Department breakdown
        dept_query = db.session.query(DischargeRecord.department, DischargeRecord.discharge_ready, func.count(DischargeRecord.id)).filter_by(user_id=user_id).group_by(DischargeRecord.department, DischargeRecord.discharge_ready).all()
        dept_data = {}
        for dept, is_ready, count in dept_query:
            d = dept or "General Medicine"
            if d not in dept_data:
                dept_data[d] = {"Ready": 0, "Not Ready": 0}
            status_key = "Ready" if is_ready else "Not Ready"
            dept_data[d][status_key] = count

        all_depts = sorted(list(dept_data.keys()))[:6]
        if not all_depts:
            all_depts = ["Cardiology", "Emergency", "General Medicine", "Neurology", "Orthopedics", "Pediatrics"]

        discharges_list = DischargeRecord.query.filter_by(user_id=user_id).limit(50).all()
        discharge_records = []
        for dr in discharges_list:
            p = Patient.query.filter_by(user_id=user_id, patient_id=dr.patient_id).first() if dr.patient_id else None
            discharge_records.append({
                "patient_name": p.name if p else f"Patient #{dr.patient_id}",
                "department": dr.department or "General Medicine",
                "discharge_status": "Ready for Discharge" if dr.discharge_ready else "In Treatment",
                "bed_id": dr.bed_id or "Unassigned"
            })

        db_updated = False
        action_msg = "No database records were changed."

        # 2D Bar Chart Data
        chart2d_data = {
            "title": "Discharge-Ready Patients by Department",
            "x_axis": "Department",
            "y_axis": "Patient Count",
            "categories": all_depts,
            "values": [dept_data.get(d, {}).get("Ready", 0) for d in all_depts]
        }

        import re
        match = re.search(r'(\d+)', instruction)
        incoming_patients = int(match.group(1)) if match else 20

        highest_ready_dept = max(all_depts, key=lambda x: dept_data.get(x, {}).get("Ready", 0)) if all_depts else "General Medicine"

        # Formulate Numbered Sections
        findings_items = [
            f"1. Discharge-ready patients — {ready:,}.",
            f"2. Potential beds released — {potential_beds:,}.",
            f"3. Pending in-treatment cases — {not_ready:,}.",
            f"4. Highest discharge-ready department — {highest_ready_dept}."
        ]

        ward_discharge_items = []
        w_idx = 1
        for d in all_depts:
            d_ready = dept_data.get(d, {}).get("Ready", 0)
            ward_discharge_items.append(f"{w_idx}. {d} — {d_ready} discharge-ready cases.")
            w_idx += 1

        rec_items = [
            "1. Expedite discharge paperwork for all evaluated discharge-ready patients.",
            "2. Coordinate with ward nursing staff to clean and sanitize released beds.",
            "3. Notify Bed Management Agent immediately upon bed release confirmation."
        ]

        structured_sections = [
            {"title": "DISCHARGE — OPERATIONAL FINDINGS (DATASET-DERIVED)", "items": findings_items},
            {"title": "WARD-WISE DISCHARGE OPPORTUNITIES", "items": ward_discharge_items},
            {"title": "AI RECOMMENDATION", "items": rec_items}
        ]

        execution_log_lines = [
            "> Loading active dataset",
            "> Discharge Agent started",
            f"> Checking discharge-ready patients across {total_records} records",
            f"> Identified {ready} patients ready for discharge ({potential_beds} potential beds releasable)",
            "> Generating AI operational recommendations",
            "> Discharge Agent completed"
        ]

        key_findings = {
            "total_records": total_records,
            "ready": ready,
            "not_ready": not_ready,
            "potential_beds": potential_beds,
            "departments": len(all_depts)
        }

        human_key_finding = f"DISCHARGE - WORKLOAD SUMMARY: Total Patients Tracked: {total_records} | Discharge-Ready: {ready} | Potential Beds Released: {potential_beds}"
        narrative = gemini_service.generate_agent_narrative("Discharge Agent", key_findings, instruction)

        result_payload = {
            "agent_name": self.name,
            "status": "Completed",
            "user_instruction": instruction,
            "records_analyzed": total_records,
            "actions_taken": 0,
            "db_action_tag": "ANALYSIS ONLY",
            "db_action_details": action_msg,
            "key_findings": key_findings,
            "structured_sections": structured_sections,
            "recommended_plan": [r.split('. ', 1)[-1] for r in rec_items],
            "operational_records": discharge_records,
            "chart2d_data": chart2d_data,
            "chart3d_data": None,
            "execution_log_lines": execution_log_lines,
            "key_finding_text": human_key_finding,
            "ai_narrative": narrative,
            "executed_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        }

        act = ActivityLog(user_id=user_id, agent_name="Discharge Agent", action=f"Analyzed {total_records} discharge records: {ready} ready for discharge.", details=action_msg, category="info")
        db.session.add(act)
        db.session.commit()
        return result_payload

discharge_agent = DischargeAgent()
