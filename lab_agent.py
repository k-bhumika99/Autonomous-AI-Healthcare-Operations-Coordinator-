import json
import logging
from datetime import datetime
from sqlalchemy import func
from services.database import db, LabTest, Patient, ActivityLog
from services.event_manager import event_manager
from services.gemini_service import gemini_service

logger = logging.getLogger(__name__)

DEFAULT_INSTRUCTION = "Analyze laboratory workload, identify pending emergency and urgent diagnostic tests, find the most overloaded laboratory, and prioritize tests requiring immediate attention."

class LabAgent:
    def __init__(self):
        self.name = "Lab"
        self.default_instruction = DEFAULT_INSTRUCTION

    def execute(self, scenario_id, user_id, user_instruction=None):
        instruction = user_instruction or DEFAULT_INSTRUCTION
        logger.info(f"Running LabAgent for scenario {scenario_id}, user {user_id} with instruction: {instruction}")

        total_tests = LabTest.query.filter_by(user_id=user_id).count()
        pending = LabTest.query.filter_by(user_id=user_id, status='Pending').count()
        completed = LabTest.query.filter_by(user_id=user_id, status='Completed').count()
        in_progress = LabTest.query.filter_by(user_id=user_id, status='In Progress').count()

        emergency = LabTest.query.filter_by(user_id=user_id, priority='Emergency').count()
        urgent = LabTest.query.filter_by(user_id=user_id, priority='Urgent').count()

        # Lab Facility breakdown
        lab_query = db.session.query(LabTest.lab, LabTest.priority, func.count(LabTest.id)).filter_by(user_id=user_id).group_by(LabTest.lab, LabTest.priority).all()
        lab_data = {}
        for lab, priority, count in lab_query:
            l = lab or "Central Lab"
            if l not in lab_data:
                lab_data[l] = {"Emergency": 0, "Urgent": 0, "Routine": 0, "Total": 0}
            lab_data[l][priority] = count
            lab_data[l]["Total"] += count

        all_labs = sorted(list(lab_data.keys()))
        if not all_labs:
            all_labs = ["Central Lab", "Emergency Lab", "Stat Diagnostics", "Pathology Lab"]

        highest_lab = max(all_labs, key=lambda x: lab_data.get(x, {}).get("Total", 0)) if all_labs else "Central Lab"

        labs_list = LabTest.query.filter_by(user_id=user_id).limit(50).all()
        lab_records = []
        for lr in labs_list:
            p = Patient.query.filter_by(user_id=user_id, patient_id=lr.patient_id).first() if lr.patient_id else None
            lab_records.append({
                "test_id": lr.test_id or f"LAB-{lr.id}",
                "patient_name": p.name if p else f"Patient #{lr.patient_id}",
                "test_name": lr.test_name or "Diagnostic Panel",
                "laboratory": lr.lab or "Central Lab",
                "priority": lr.priority or "Routine",
                "status": lr.status or "Pending"
            })

        db_updated = False
        prioritized_count = 0
        action_msg = "No database records were changed."
        if ("expedite" in instruction.lower() or "prioritize" in instruction.lower()):
            pending_emergencies = LabTest.query.filter_by(user_id=user_id, priority='Emergency', status='Pending').limit(20).all()
            prioritized_count = len(pending_emergencies)
            for pe in pending_emergencies:
                pe.status = 'In Progress'
            db.session.commit()
            if prioritized_count > 0:
                db_updated = True
                action_msg = f"{prioritized_count} emergency lab test orders escalated to 'In Progress' for stat diagnostic processing."

        # 2D Bar Chart Data
        chart2d_data = {
            "title": "Pending Tests by Laboratory",
            "x_axis": "Laboratory",
            "y_axis": "Pending Tests",
            "categories": all_labs,
            "values": [lab_data.get(l, {}).get("Total", 0) for l in all_labs]
        }

        import re
        match = re.search(r'(\d+)', instruction)
        incoming_patients = int(match.group(1)) if match else (pending if pending > 0 else 10)

        # Formulate Numbered Sections
        routine_count = max(0, pending - (emergency + urgent))
        findings_items = [
            f"1. Total pending lab tests — {pending:,}.",
            f"2. Emergency-priority tests — {emergency:,}.",
            f"3. Urgent tests — {urgent:,}.",
            f"4. Routine pending tests — {routine_count:,}.",
            f"5. Highest workload laboratory — {highest_lab}."
        ]
        item_idx = 6
        for l in all_labs:
            l_pending = lab_data.get(l, {}).get("Total", 0)
            findings_items.append(f"{item_idx}. {l} pending workload — {l_pending:,} tests.")
            item_idx += 1

        # Trauma Emergency Diagnostics Requirements
        trauma_tests = [
            "CBC (Complete Blood Count)",
            "Blood Group & Crossmatch",
            "Electrolyte Panel",
            "Renal Function Test",
            "Liver Function Test",
            "Coagulation Profile",
            "Blood Glucose",
            "X-Ray / Trauma Series",
            "CT Scan (where clinically indicated)"
        ]

        # Check existing test names in dataset
        existing_test_names = [t.test_name for t in labs_list if t.test_name]
        diag_req_items = [
            f"{item_idx}. Trauma patients requiring emergency diagnostics — {incoming_patients}.",
            f"{item_idx+1}. Priority — Emergency Stat."
        ]
        item_idx += 2

        for tname in trauma_tests:
            is_present = any(tname.lower() in et.lower() for et in existing_test_names)
            label = "(DATASET MATCH)" if is_present else "(AI RECOMMENDATION — NOT PRESENT IN DATASET)"
            diag_req_items.append(f"{item_idx}. {tname} — {label}")
            item_idx += 1

        rec_items = [
            f"{item_idx}. Prioritize emergency diagnostic requests for arriving trauma patients.",
            f"{item_idx+1}. Route additional workload to laboratories with available processing capacity.",
            f"{item_idx+2}. Fast-track blood crossmatch and Stat imaging turnaround."
        ]

        structured_sections = [
            {"title": "LAB DIAGNOSTICS — OPERATIONAL FINDINGS (DATASET-DERIVED)", "items": findings_items},
            {"title": "EMERGENCY SURGE DIAGNOSTIC REQUIREMENTS", "items": diag_req_items},
            {"title": "AI RECOMMENDATION", "items": rec_items}
        ]

        execution_log_lines = [
            "> Loading active dataset",
            "> Lab Diagnostics Agent started",
            f"> Checking pending diagnostic workload across {total_tests} test records",
            f"> Identified {pending} pending tests ({emergency} Emergency, {urgent} Urgent)",
            f"> Highest workload laboratory: {highest_lab}",
            "> Generating AI operational recommendations",
            "> Lab Diagnostics Agent completed"
        ]

        human_key_finding = f"LAB DIAGNOSTICS - WORKLOAD SUMMARY\nTotal Pending Tests: {pending} | Emergency: {emergency} | Urgent: {urgent} | Highest Workload Lab: {highest_lab}"

        key_findings = {
            "total_tests": total_tests,
            "pending": pending,
            "emergency": emergency,
            "urgent": urgent,
            "highest_workload_lab": highest_lab
        }

        narrative = gemini_service.generate_agent_narrative("Lab Diagnostics Agent", key_findings, instruction)

        result_payload = {
            "agent_name": self.name,
            "status": "Completed",
            "user_instruction": instruction,
            "records_analyzed": total_tests,
            "actions_taken": prioritized_count,
            "db_action_tag": "DATABASE UPDATED" if db_updated else "ANALYSIS ONLY",
            "db_action_details": action_msg,
            "key_findings": key_findings,
            "structured_sections": structured_sections,
            "recommended_plan": [r.split('. ', 1)[-1] for r in rec_items],
            "operational_records": lab_records,
            "chart2d_data": chart2d_data,
            "chart3d_data": None,
            "execution_log_lines": execution_log_lines,
            "key_finding_text": human_key_finding,
            "ai_narrative": narrative,
            "executed_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        }

        act = ActivityLog(user_id=user_id, agent_name="Lab Diagnostics Agent", action=f"Analyzed {total_tests} lab tests: {pending} pending, highest workload in {highest_lab}.", details=action_msg, category="info")
        db.session.add(act)
        db.session.commit()
        return result_payload

lab_agent = LabAgent()
