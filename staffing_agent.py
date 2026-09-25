import json
import logging
from datetime import datetime
from sqlalchemy import func
from services.database import db, StaffMember, ActivityLog
from services.event_manager import event_manager
from services.gemini_service import gemini_service

logger = logging.getLogger(__name__)

DEFAULT_INSTRUCTION = "Analyze staff availability, identify available doctors, nurses, laboratory technicians and other clinical staff, and identify departments requiring additional support."

class StaffingAgent:
    def __init__(self):
        self.name = "Staffing"
        self.default_instruction = DEFAULT_INSTRUCTION

    def execute(self, scenario_id, user_id, user_instruction=None):
        instruction = user_instruction or DEFAULT_INSTRUCTION
        logger.info(f"Running StaffingAgent for scenario {scenario_id}, user {user_id} with instruction: {instruction}")

        total_staff = StaffMember.query.filter_by(user_id=user_id).count()
        available = StaffMember.query.filter_by(user_id=user_id, availability='Available').count()
        busy = total_staff - available

        doctors_avail = StaffMember.query.filter_by(user_id=user_id, role='Doctor', availability='Available').count()
        nurses_avail = StaffMember.query.filter_by(user_id=user_id, role='Nurse', availability='Available').count()
        techs_avail = StaffMember.query.filter_by(user_id=user_id, role='Technician', availability='Available').count()
        other_avail = max(0, available - (doctors_avail + nurses_avail + techs_avail))

        # Dynamic Specialty Counts from Database
        spec_query = db.session.query(StaffMember.department, func.count(StaffMember.id)).filter_by(user_id=user_id, availability='Available').group_by(StaffMember.department).all()
        specialty_items = []
        item_idx = 1
        for dept, count in spec_query:
            dname = dept or "General Medicine"
            specialty_items.append(f"{item_idx}. {dname} staff available — {count}.")
            item_idx += 1
        if not specialty_items:
            specialty_items = [
                "1. Emergency Medicine available — 0.",
                "2. General Medicine available — 0.",
                "3. Surgery available — 0.",
                "4. Cardiology available — 0."
            ]

        staff_list = StaffMember.query.filter_by(user_id=user_id).limit(50).all()
        staff_records = []
        for s in staff_list:
            staff_records.append({
                "staff_id": s.staff_id or f"STF-{s.id}",
                "name": s.name or f"Staff Member #{s.id}",
                "role": s.role or "Clinical Staff",
                "department": s.department or "General",
                "availability": s.availability or "Available"
            })

        db_updated = False
        action_msg = "No database records were changed."

        # 2D Bar Chart Data
        chart2d_data = {
            "title": "Available Staff by Role",
            "x_axis": "Staff Role",
            "y_axis": "Available Count",
            "categories": ["Doctors", "Nurses", "Technicians", "Other Clinical"],
            "values": [doctors_avail, nurses_avail, techs_avail, other_avail]
        }

        # Formulate Numbered Sections
        findings_items = [
            f"1. Doctors available — {doctors_avail:,}.",
            f"2. Nurses available — {nurses_avail:,}.",
            f"3. Technicians available — {techs_avail:,}.",
            f"4. Pharmacists & Support staff available — {other_avail:,}.",
            f"5. Total clinical staff available — {available:,}."
        ]

        support_items = [
            "1. Doctors required for emergency trauma assessment & resuscitation.",
            "2. Nurses required for rapid triage & bedside monitoring.",
            "3. Laboratory technicians required for emergency diagnostics.",
            "4. Pharmacists required for emergency medication dispensing."
        ]

        staff_status_str = "SUFFICIENT" if available >= 20 else "UNDER PRESSURE"
        tech_status_str = "INSUFFICIENT (0 Available)" if techs_avail == 0 else f"AVAILABLE ({techs_avail})"

        status_items = [
            f"1. Overall available clinical staff status — {staff_status_str}.",
            f"2. Technician availability status — {tech_status_str}."
        ]

        structured_sections = [
            {"title": "STAFFING — OPERATIONAL FINDINGS (DATASET-DERIVED)", "items": findings_items},
            {"title": "SPECIALTY & DEPARTMENT BREAKDOWN (DYNAMICALLY GENERATED)", "items": specialty_items},
            {"title": "EMERGENCY SURGE SUPPORT DIRECTIVES", "items": support_items},
            {"title": "STAFFING STATUS SUMMARY", "items": status_items}
        ]

        execution_log_lines = [
            "> Loading active dataset",
            "> Staffing Agent started",
            f"> Checking clinical staff availability across {total_staff} records",
            f"> Identified {available} Available staff ({doctors_avail} Doctors, {nurses_avail} Nurses, {techs_avail} Technicians)",
            "> Generating AI operational recommendations",
            "> Staffing Agent completed"
        ]

        key_findings = {
            "total_staff": total_staff,
            "total_clinical_staff": total_staff,
            "available": available,
            "available_staff": available,
            "busy": busy,
            "doctors_available": doctors_avail,
            "nurses_available": nurses_avail,
            "technicians_available": techs_avail,
            "other_clinical_staff": other_avail
        }

        human_key_finding = f"STAFFING - WORKLOAD SUMMARY: Total Available Staff: {available} | Doctors: {doctors_avail} | Nurses: {nurses_avail} | Technicians: {techs_avail}"
        narrative = gemini_service.generate_agent_narrative("Staffing Agent", key_findings, instruction)

        result_payload = {
            "agent_name": self.name,
            "status": "Completed",
            "user_instruction": instruction,
            "records_analyzed": total_staff,
            "actions_taken": 0,
            "db_action_tag": "ANALYSIS ONLY",
            "db_action_details": action_msg,
            "key_findings": key_findings,
            "structured_sections": structured_sections,
            "recommended_plan": [r.split('. ', 1)[-1] for r in support_items],
            "operational_records": staff_records,
            "chart2d_data": chart2d_data,
            "chart3d_data": None,
            "execution_log_lines": execution_log_lines,
            "key_finding_text": human_key_finding,
            "ai_narrative": narrative,
            "executed_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        }

        act = ActivityLog(user_id=user_id, agent_name="Staffing Agent", action=f"Analyzed {total_staff} staff members: {available} available ({doctors_avail} doctors).", details=action_msg, category="info")
        db.session.add(act)
        db.session.commit()
        return result_payload

staffing_agent = StaffingAgent()
