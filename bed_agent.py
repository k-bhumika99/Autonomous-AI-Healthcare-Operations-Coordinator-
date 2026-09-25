import json
import logging
from datetime import datetime
from sqlalchemy import func
from services.database import db, Bed, Patient, DischargeRecord, ActivityLog
from services.event_manager import event_manager
from services.gemini_service import gemini_service

logger = logging.getLogger(__name__)

DEFAULT_INSTRUCTION = "Analyze current bed occupancy, available beds by ward, ICU capacity and discharge potential for patient surge requirement."

class BedAgent:
    def __init__(self):
        self.name = "Bed Management"
        self.default_instruction = DEFAULT_INSTRUCTION

    def execute(self, scenario_id, user_id, user_instruction=None):
        instruction = user_instruction or DEFAULT_INSTRUCTION
        logger.info(f"Running BedAgent for scenario {scenario_id}, user {user_id} with instruction: {instruction}")
        
        total_beds = Bed.query.filter_by(user_id=user_id).count()
        occupied_beds = Bed.query.filter_by(user_id=user_id, status='Occupied').count()
        available_beds = Bed.query.filter_by(user_id=user_id, status='Available').count()

        ready_discharge = DischargeRecord.query.filter_by(user_id=user_id, discharge_ready=True).count()
        icu_free = Bed.query.filter_by(user_id=user_id, ward='ICU', status='Available').count()
        er_free = Bed.query.filter_by(user_id=user_id, ward='Emergency', status='Available').count()

        occupancy_pct = round((occupied_beds / max(1, total_beds)) * 100, 1)

        # Ward Breakdown
        wards_query = db.session.query(Bed.ward, Bed.status, func.count(Bed.id)).filter_by(user_id=user_id).group_by(Bed.ward, Bed.status).all()
        ward_data = {}
        for ward, status, count in wards_query:
            w = ward or "General Ward"
            if w not in ward_data:
                ward_data[w] = {"Occupied": 0, "Available": 0, "Maintenance": 0}
            ward_data[w][status] = count

        all_wards = sorted(list(ward_data.keys()))
        if not all_wards:
            all_wards = ["ICU", "Emergency", "General Ward", "Pediatrics", "Surgical"]

        beds_query = Bed.query.filter_by(user_id=user_id)
        if "icu" in instruction.lower():
            beds_query = beds_query.filter(Bed.ward.ilike("%ICU%"))
        elif "emergency" in instruction.lower():
            beds_query = beds_query.filter(Bed.ward.ilike("%Emergency%"))

        beds_list = beds_query.limit(50).all()
        bed_records = []
        for b in beds_list:
            p = Patient.query.filter_by(user_id=user_id, patient_id=b.patient_id).first() if b.patient_id else None
            bed_records.append({
                "bed_id": b.bed_id,
                "ward": b.ward or "General",
                "type": b.type or "Standard",
                "status": b.status,
                "patient_name": p.name if p else ("Unassigned" if b.status == "Available" else "Patient Occupied")
            })

        db_updated = False
        action_msg = "No database records were changed."
        if ("reallocate" in instruction.lower() or "reserve" in instruction.lower()):
            for b in Bed.query.filter_by(user_id=user_id, status='Available').limit(10).all():
                b.status = 'Reserved'
            db.session.commit()
            db_updated = True
            action_msg = "10 available beds were reserved for emergency surge."

        # 2D Bar Chart Data
        chart2d_data = {
            "title": "Available Beds by Ward",
            "x_axis": "Ward",
            "y_axis": "Available Beds",
            "categories": all_wards,
            "values": [ward_data.get(w, {}).get("Available", 0) for w in all_wards]
        }

        import re
        match = re.search(r'(\d+)', instruction)
        incoming_patients = int(match.group(1)) if match else max(1, available_beds + 2)
        beds_required = incoming_patients

        capacity_gap = max(0, beds_required - available_beds)
        potential_capacity = available_beds + ready_discharge
        remaining_gap_after_discharge = max(0, beds_required - potential_capacity)

        key_findings = {
            "incoming_patients": incoming_patients,
            "beds_required": beds_required,
            "total_beds": total_beds,
            "occupied": occupied_beds,
            "available": available_beds,
            "capacity_gap": capacity_gap,
            "occupancy_pct": occupancy_pct,
            "potential_release": ready_discharge,
            "remaining_gap_after_discharge": remaining_gap_after_discharge
        }

        execution_log_lines = [
            "> Loading active dataset",
            "> Reading scenario situation",
            f"> Emergency demand detected: {incoming_patients} patients requiring {beds_required} beds",
            "> Coordinator Agent started",
            "> Bed Management Agent started",
            f"> Checking available beds by ward across {total_beds} bed records",
            f"> Available Beds: {available_beds} free beds identified ({er_free} Emergency, {icu_free} ICU)",
            "> Generating AI operational recommendations",
            "> Bed Management Agent completed"
        ]

        # Formulate Numbered Sections
        findings_items = []
        item_idx = 1
        for w in all_wards:
            w_avail = ward_data.get(w, {}).get("Available", 0)
            findings_items.append(f"{item_idx}. {w} — {w_avail} beds available.")
            item_idx += 1

        capacity_status_str = "SUFFICIENT" if available_beds >= beds_required else ("SUFFICIENT (WITH DISCHARGE RECOVERY)" if potential_capacity >= beds_required else "INSUFFICIENT")

        req_items = [
            f"{item_idx}. Emergency patients arriving — {incoming_patients}.",
            f"{item_idx+1}. Beds required — {beds_required}.",
            f"{item_idx+2}. Total currently available beds — {available_beds}.",
            f"{item_idx+3}. Capacity gap — {capacity_gap}.",
            f"{item_idx+4}. Capacity status — {capacity_status_str}."
        ]
        item_idx += 5

        # Available Bed IDs from dataset
        avail_beds_list = Bed.query.filter_by(user_id=user_id, status='Available').limit(15).all()
        bed_id_items = []
        if avail_beds_list:
            for b in avail_beds_list:
                bed_id_items.append(f"{item_idx}. Bed ID: {b.bed_id} — Ward: {b.ward or 'General'}")
                item_idx += 1
        else:
            bed_id_items.append(f"{item_idx}. No individual available bed IDs found in current active dataset.")
            item_idx += 1

        rec_items = [
            f"{item_idx}. Allocate available Emergency Ward beds first.",
            f"{item_idx+1}. If Emergency Ward capacity is insufficient, use suitable General Ward capacity according to hospital policy.",
            f"{item_idx+2}. Expedite discharge-ready patients ({ready_discharge} eligible) to release additional capacity."
        ]

        structured_sections = [
            {"title": "BED MANAGEMENT — OPERATIONAL FINDINGS BY WARD", "items": findings_items},
            {"title": "SURGE BED REQUIREMENT", "items": req_items},
            {"title": "AVAILABLE BED RECORDS (DATASET-DERIVED)", "items": bed_id_items},
            {"title": "AI RECOMMENDATION", "items": rec_items}
        ]

        narrative = gemini_service.generate_agent_narrative("Bed Management Agent", key_findings, instruction)

        human_key_finding = f"BED MANAGEMENT - CAPACITY STATUS: {capacity_status_str}\nTotal Available Beds: {available_beds} | Required Beds: {beds_required} | Gap: {capacity_gap}"

        result_payload = {
            "agent_name": self.name,
            "status": "Completed",
            "user_instruction": instruction,
            "records_analyzed": total_beds,
            "actions_taken": 10 if db_updated else 0,
            "db_action_tag": "DATABASE UPDATED" if db_updated else "ANALYSIS ONLY",
            "db_action_details": action_msg,
            "key_findings": key_findings,
            "structured_sections": structured_sections,
            "recommended_plan": [r.split('. ', 1)[-1] for r in rec_items],
            "operational_records": bed_records,
            "chart2d_data": chart2d_data,
            "chart3d_data": None,
            "execution_log_lines": execution_log_lines,
            "key_finding_text": human_key_finding,
            "ai_narrative": narrative,
            "executed_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        }

        act = ActivityLog(user_id=user_id, agent_name="Bed Management Agent", action=f"Analyzed {total_beds} beds: {available_beds} available ({occupancy_pct}% occupancy).", details=action_msg, category="info")
        db.session.add(act)
        db.session.commit()
        return result_payload

bed_agent = BedAgent()
