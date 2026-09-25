import re
import json
import logging
from datetime import datetime
from services.database import db, Bed, Appointment, LabTest, PharmacyItem, StaffMember, DischargeRecord
from services.gemini_service import gemini_service

logger = logging.getLogger(__name__)

DEFAULT_INSTRUCTION = "Assess hospital operational capacity, bed availability, clinical staffing, diagnostic workload, medicine stock, appointment load, and discharge readiness to coordinate response to incoming patient surge demand."

class CoordinatorAgent:
    def __init__(self):
        self.name = "Coordinator"
        self.default_instruction = DEFAULT_INSTRUCTION

    def extract_incoming_demand(self, text):
        if not text:
            return None
        # Look for digits before "patient", "emergency", "critical", etc.
        match = re.search(r'(\d+)\s*(?:emergency|incoming|critical|icu|surge|trauma|accident|outbreak)?\s*(?:patients|admissions|cases|people|arrivals)', text, re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except Exception:
                pass
        # Fallback check for any number in instruction
        numbers = re.findall(r'\b\d+\b', text)
        if numbers:
            try:
                return int(numbers[0])
            except Exception:
                pass
        return None

    def analyze_scenario(self, scenario_data, user_id, user_instruction=None):
        instruction = user_instruction or scenario_data.get('user_instruction') or scenario_data.get('description') or self.default_instruction
        logger.info(f"Running CoordinatorAgent for user {user_id} with instruction: {instruction}")

        incoming_patients = self.extract_incoming_demand(instruction)
        beds_required = incoming_patients if incoming_patients is not None else (avail_beds + 5 if 'avail_beds' in locals() else 10)

        total_beds = Bed.query.filter_by(user_id=user_id).count()
        occupied_beds = Bed.query.filter_by(user_id=user_id, status='Occupied').count()
        avail_beds = Bed.query.filter_by(user_id=user_id, status='Available').count()

        if incoming_patients is None:
            beds_required = max(1, avail_beds + 2)

        pending_labs = LabTest.query.filter_by(user_id=user_id, status='Pending').count()
        emergency_labs = LabTest.query.filter_by(user_id=user_id, priority='Emergency').count()

        critical_meds = PharmacyItem.query.filter(
            PharmacyItem.user_id == user_id,
            PharmacyItem.available_quantity < PharmacyItem.required_quantity
        ).count()
        low_meds = PharmacyItem.query.filter(
            PharmacyItem.user_id == user_id,
            PharmacyItem.available_quantity < PharmacyItem.required_quantity * 1.5
        ).count()

        avail_staff = StaffMember.query.filter_by(user_id=user_id, availability='Available').count()
        avail_doctors = StaffMember.query.filter_by(user_id=user_id, role='Doctor', availability='Available').count()
        avail_nurses = StaffMember.query.filter_by(user_id=user_id, role='Nurse', availability='Available').count()

        today_appts = Appointment.query.filter_by(user_id=user_id).count()
        discharge_ready = DischargeRecord.query.filter_by(user_id=user_id, discharge_ready=True).count()

        initial_gap = max(0, beds_required - avail_beds)
        potential_capacity = avail_beds + discharge_ready
        final_gap = max(0, beds_required - potential_capacity)

        p_display = f"{incoming_patients}" if incoming_patients is not None else "surge"

        if avail_beds >= beds_required:
            surge_verdict = "CAPACITY AVAILABLE"
            surge_code = "GREEN"
            surge_badge_class = "bg-emerald-100 text-emerald-800 border-emerald-300"
            surge_msg = f"Current available hospital bed capacity ({avail_beds} beds) is sufficient for the {p_display} patient demand."
        elif potential_capacity >= beds_required:
            surge_verdict = "CAPACITY UNDER PRESSURE"
            surge_code = "ORANGE"
            surge_badge_class = "bg-amber-100 text-amber-800 border-amber-300"
            surge_msg = f"Current available beds ({avail_beds}) is insufficient for {p_display} patients (initial gap of {initial_gap} beds). However, releasing {discharge_ready} discharge-ready beds brings total potential capacity to {potential_capacity}, covering the surge."
        else:
            surge_verdict = "CAPACITY INSUFFICIENT"
            surge_code = "RED"
            surge_badge_class = "bg-rose-100 text-rose-800 border-rose-300"
            surge_msg = f"Hospital capacity is currently insufficient by {final_gap} beds. Available beds ({avail_beds}) + potential discharge beds ({discharge_ready}) equals {potential_capacity} total beds, leaving an unresolvable gap of {final_gap} beds for the {p_display} patients."

        summary_metrics = {
            "incoming_patients": incoming_patients if incoming_patients is not None else 0,
            "beds_required": beds_required,
            "available_beds": avail_beds,
            "occupied_beds": occupied_beds,
            "total_beds": total_beds,
            "initial_capacity_gap": initial_gap,
            "discharge_ready": discharge_ready,
            "potential_beds_released": discharge_ready,
            "potential_capacity": potential_capacity,
            "final_capacity_gap": final_gap,
            "surge_verdict": surge_verdict,
            "surge_code": surge_code,
            "surge_msg": surge_msg,
            "available_doctors": avail_doctors,
            "available_nurses": avail_nurses,
            "available_staff": avail_staff,
            "pending_labs": pending_labs,
            "critical_meds": critical_meds,
            "today_appts": today_appts
        }

        analysis_items = [
            "1. Hospital surge incident detected.",
            f"2. Incoming patient demand - {incoming_patients if incoming_patients is not None else 'Dynamic'}.",
            f"3. Bed capacity assessment ({avail_beds} available, {beds_required} required).",
            f"4. Diagnostic capacity assessment ({pending_labs} pending lab tests).",
            f"5. Medication availability assessment ({critical_meds} critical shortages).",
            f"6. Clinical staffing assessment ({avail_doctors} doctors, {avail_nurses} nurses available).",
            f"7. Appointment pressure assessment ({today_appts} scheduled today).",
            f"8. Discharge capacity assessment ({discharge_ready} discharge-ready patients).",
            "9. All specialized agents evaluated."
        ]

        decision_items = [
            "10. Bed Agent -> analyze available beds by ward.",
            "11. Lab Agent -> analyze pending and priority diagnostics.",
            "12. Pharmacy Agent -> analyze critical medicine availability.",
            "13. Staffing Agent -> analyze staff availability.",
            "14. Appointment Agent -> analyze appointment pressure.",
            "15. Discharge Agent -> identify potential capacity release."
        ]

        structured_sections = [
            {"title": "COORDINATOR - SCENARIO ANALYSIS", "items": analysis_items},
            {"title": "COORDINATOR DECISION", "items": decision_items}
        ]

        analysis_summary = f"Surge Analysis ({incoming_patients if incoming_patients is not None else 'Dynamic'} Patients): {avail_beds}/{total_beds} beds available (Gap: {initial_gap}). {discharge_ready} beds can be released via discharge. Staff ready: {avail_doctors} doctors, {avail_nurses} nurses. {pending_labs} pending labs. Verdict: {surge_verdict}."
        recommended_agents = ["Bed Management", "Lab", "Pharmacy", "Staffing", "Appointment", "Discharge"]

        return {
            "agent_name": self.name,
            "user_instruction": instruction,
            "analysis_summary": analysis_summary,
            "surge_metrics": summary_metrics,
            "recommended_agents": recommended_agents,
            "structured_sections": structured_sections,
            "agent_instructions": {
                "Bed Management": f"Assess emergency bed capacity for {incoming_patients} incoming emergency patients against {avail_beds} available beds.",
                "Lab": f"Assess diagnostic capacity and laboratory workload for {incoming_patients} incoming emergency patients.",
                "Pharmacy": f"Analyze medicine inventory and check availability of emergency critical drugs.",
                "Staffing": f"Identify available doctors ({avail_doctors}) and clinical staff ({avail_staff}) for emergency surge response.",
                "Appointment": f"Analyze appointment load ({today_appts} today) and identify routine appointments recommended for operational review.",
                "Discharge": f"Evaluate {discharge_ready} discharge-ready patients to release additional hospital bed capacity."
            }
        }

    def execute(self, scenario_id, user_id, user_instruction=None):
        instruction = user_instruction or self.default_instruction
        coord_res = self.analyze_scenario({'user_instruction': instruction}, user_id, user_instruction=instruction)
        metrics = coord_res.get('surge_metrics', {})

        incoming_patients = metrics.get('incoming_patients', 20)
        beds_required = metrics.get('beds_required', 20)
        avail_beds = metrics.get('available_beds', 0)
        occupied_beds = metrics.get('occupied_beds', 0)
        total_beds = metrics.get('total_beds', 0)
        initial_gap = metrics.get('initial_capacity_gap', 0)
        surge_verdict = metrics.get('surge_verdict', 'CAPACITY UNDER PRESSURE')

        avail_doctors = metrics.get('available_doctors', 0)
        avail_nurses = metrics.get('available_nurses', 0)
        avail_staff = metrics.get('available_staff', 0)
        pending_labs = metrics.get('pending_labs', 0)
        critical_meds = metrics.get('critical_meds', 0)
        today_appts = metrics.get('today_appts', 0)
        discharge_ready = metrics.get('discharge_ready', 0)

        key_findings = {
            "incoming_patients": incoming_patients,
            "beds_required": beds_required,
            "available_beds": avail_beds,
            "capacity_gap": initial_gap,
            "surge_verdict": surge_verdict,
            "discharge_ready": discharge_ready,
            "available_doctors": avail_doctors,
            "available_staff": avail_staff,
            "pending_labs": pending_labs,
            "critical_meds": critical_meds,
            "today_appts": today_appts
        }

        operational_records = [
            {"Domain / Module": "1. Emergency Demand", "Live Metric": f"{incoming_patients} Patients", "Resource Needed": f"{beds_required} Beds Required", "Status / Gap": f"Initial Gap: {initial_gap} Beds"},
            {"Domain / Module": "2. Bed Management", "Live Metric": f"{avail_beds} Available Beds", "Resource Needed": f"{occupied_beds} Occupied / {total_beds} Total", "Status / Gap": f"{'Capacity OK' if avail_beds >= beds_required else 'Deficit'}"},
            {"Domain / Module": "3. Staffing", "Live Metric": f"{avail_doctors} Doctors / {avail_nurses} Nurses", "Resource Needed": "Clinical Staff", "Status / Gap": f"Total Available: {avail_staff}"},
            {"Domain / Module": "4. Lab Diagnostics", "Live Metric": f"{pending_labs} Pending Labs", "Resource Needed": "Diagnostic Processing", "Status / Gap": f"{pending_labs} Tests Pending"},
            {"Domain / Module": "5. Pharmacy", "Live Metric": f"{critical_meds} Critical Shortages", "Resource Needed": "Medication Stock", "Status / Gap": f"{critical_meds} Meds Low"},
            {"Domain / Module": "6. Appointment", "Live Metric": f"{today_appts} Scheduled Today", "Resource Needed": "Outpatient Capacity", "Status / Gap": f"{today_appts} Scheduled"},
            {"Domain / Module": "7. Discharge", "Live Metric": f"{discharge_ready} Discharge-Ready", "Resource Needed": "Capacity Release", "Status / Gap": f"Potential Release: {discharge_ready} Beds"}
        ]

        chart2d_data = {
            "title": "Hospital Department Resource Overview",
            "x_axis": "Department / Operational Area",
            "y_axis": "Count",
            "categories": ["Available Beds", "Available Staff", "Pending Labs", "Critical Meds", "Today Appts", "Discharge Ready"],
            "values": [avail_beds, avail_staff, pending_labs, critical_meds, today_appts, discharge_ready]
        }

        ai_summary = gemini_service.generate_scenario_summary({'user_instruction': instruction}, metrics) or coord_res.get('analysis_summary')

        return {
            "agent_name": self.name,
            "status": "Completed",
            "key_findings": key_findings,
            "structured_sections": coord_res.get("structured_sections", []),
            "operational_records": operational_records,
            "chart2d_data": chart2d_data,
            "ai_narrative": ai_summary,
            "db_action_details": f"Coordinator Agent analyzed live SQLite database across all 6 specialized domains.",
            "db_action_tag": "ANALYSIS ONLY"
        }

coordinator_agent = CoordinatorAgent()


