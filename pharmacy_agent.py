import json
import logging
from datetime import datetime
from sqlalchemy import func
from services.database import db, PharmacyItem, ActivityLog
from services.event_manager import event_manager
from services.gemini_service import gemini_service

logger = logging.getLogger(__name__)

DEFAULT_INSTRUCTION = "Analyze current medicine inventory, identify critical and low-stock medicines, calculate shortages, and prioritize medicines needed for emergency and urgent patients."

class PharmacyAgent:
    def __init__(self):
        self.name = "Pharmacy"
        self.default_instruction = DEFAULT_INSTRUCTION

    def execute(self, scenario_id, user_id, user_instruction=None):
        instruction = user_instruction or DEFAULT_INSTRUCTION
        logger.info(f"Running PharmacyAgent for scenario {scenario_id}, user {user_id} with instruction: {instruction}")

        total_meds = PharmacyItem.query.filter_by(user_id=user_id).count()
        all_items = PharmacyItem.query.filter_by(user_id=user_id).all()

        critical_count = 0
        low_count = 0
        avail_count = 0
        top_shortage_item = None
        max_shortage = 0
        pharm_records = []
        categories_dict = {}

        for item in all_items:
            req = item.required_quantity or 100
            avail = item.available_quantity or 0
            shortage = max(0, req - avail)
            if shortage > max_shortage:
                max_shortage = shortage
                top_shortage_item = item.medicine_name

            if avail < req * 0.3:
                status_str = "Critical"
                critical_count += 1
            elif avail < req:
                status_str = "Low Stock"
                low_count += 1
            else:
                status_str = "Available"
                avail_count += 1

            cat = getattr(item, 'category', None) or "General Medicine"
            if cat not in categories_dict:
                categories_dict[cat] = {"Required": 0, "Available": 0, "Shortage": 0}
            categories_dict[cat]["Required"] += req
            categories_dict[cat]["Available"] += avail
            categories_dict[cat]["Shortage"] += shortage

            pharm_records.append({
                "medicine_name": item.medicine_name or f"Medicine #{item.id}",
                "required_qty": req,
                "available_qty": avail,
                "shortage": shortage,
                "stock_status": status_str
            })

        all_cats = sorted(list(categories_dict.keys()))[:6]
        if not all_cats:
            all_cats = ["Antibiotics", "Analgesics", "Emergency Meds", "Cardiovascular", "ICU Meds"]

        top_shortage_name = top_shortage_item if top_shortage_item else "None (Fully Stocked)"

        db_updated = False
        action_msg = "No database records were changed."

        # 2D Bar Chart Data
        chart2d_data = {
            "title": "Available Medicine Inventory by Category",
            "x_axis": "Category",
            "y_axis": "Available Quantity",
            "categories": all_cats,
            "values": [categories_dict.get(c, {}).get("Available", 0) for c in all_cats]
        }

        # Formulate Numbered Sections based on actual dataset availability
        if total_meds > 0:
            findings_items = [
                f"1. Total medicines tracked — {total_meds:,}.",
                f"2. Critical medicines — {critical_count:,}.",
                f"3. Low-stock medicines — {low_count:,}.",
                f"4. Medicines currently available — {avail_count:,}."
            ]

            item_idx = 5
            crit_items = []
            for pr in pharm_records[:10]:
                crit_items.append(f"{item_idx}. {pr['medicine_name']} — Required: {pr['required_qty']} — Available: {pr['available_qty']} — Status: {pr['stock_status']}")
                item_idx += 1

            emergency_categories = [
                "1. Emergency medication category: Analgesics",
                "2. Emergency medication category: IV Fluids",
                "3. Emergency medication category: Antibiotics",
                "4. Emergency medication category: Anti-emetics",
                "5. Emergency medication category: Emergency Resuscitation Medicines"
            ]

            rec_items = [
                f"{item_idx}. Prioritize critical emergency medicines (Analgesics, IV Fluids, Antibiotics).",
                f"{item_idx+1}. Expedite procurement for items in Shortage status.",
                f"{item_idx+2}. Ensure pharmacy emergency kits are fully stocked across trauma units."
            ]

            structured_sections = [
                {"title": "PHARMACY — OPERATIONAL FINDINGS (DATASET-DERIVED)", "items": findings_items},
                {"title": "EMERGENCY MEDICATION CATEGORIES", "items": emergency_categories},
                {"title": "MEDICINE STOCK STATUS (DATASET-DERIVED)", "items": crit_items},
                {"title": "AI RECOMMENDATION", "items": rec_items}
            ]
        else:
            findings_items = [
                "1. Medicine-level emergency inventory is not available in the uploaded dataset.",
                "2. Current pharmacy capacity can only be assessed at the available dataset level."
            ]
            rec_items = [
                "1. Paracetamol (Analgesic) — (AI RECOMMENDED MEDICINE — Not available in uploaded dataset)",
                "2. Ceftriaxone (Antibiotic) — (AI RECOMMENDED MEDICINE — Not available in uploaded dataset)",
                "3. Normal Saline (IV Fluid) — (AI RECOMMENDED MEDICINE — Not available in uploaded dataset)",
                "4. Ondansetron (Anti-emetic) — (AI RECOMMENDED MEDICINE — Not available in uploaded dataset)",
                "5. Epinephrine (Resuscitation) — (AI RECOMMENDED MEDICINE — Not available in uploaded dataset)"
            ]
            structured_sections = [
                {"title": "DATABASE DATA", "items": findings_items},
                {"title": "AI RECOMMENDED MEDICINES (NOT IN UPLOADED DATASET)", "items": rec_items}
            ]

        execution_log_lines = [
            "> Loading active dataset",
            "> Pharmacy Agent started",
            f"> Checking medicine inventory across {total_meds} records",
            f"> Stock evaluation: {avail_count} Available, {low_count} Low Stock, {critical_count} Critical Shortages",
            f"> Top shortage identified: {top_shortage_name} ({max_shortage} units deficit)",
            "> Generating AI operational recommendations",
            "> Pharmacy Agent completed"
        ]

        key_findings = {
            "total_medicines": total_meds,
            "critical": critical_count,
            "low_stock": low_count,
            "available": avail_count,
            "top_shortage": top_shortage_name
        }

        human_key_finding = f"PHARMACY - INVENTORY SUMMARY: Total Medicines: {total_meds} | Critical Shortages: {critical_count} | Low Stock: {low_count} | Available: {avail_count}"
        narrative = gemini_service.generate_agent_narrative("Pharmacy Agent", key_findings, instruction)

        result_payload = {
            "agent_name": self.name,
            "status": "Completed",
            "user_instruction": instruction,
            "records_analyzed": total_meds,
            "actions_taken": 0,
            "db_action_tag": "ANALYSIS ONLY",
            "db_action_details": action_msg,
            "key_findings": key_findings,
            "structured_sections": structured_sections,
            "recommended_plan": [r.split('. ', 1)[-1] for r in rec_items],
            "operational_records": pharm_records[:50],
            "chart2d_data": chart2d_data,
            "chart3d_data": None,
            "execution_log_lines": execution_log_lines,
            "key_finding_text": human_key_finding,
            "ai_narrative": narrative,
            "executed_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        }

        act = ActivityLog(user_id=user_id, agent_name="Pharmacy Agent", action=f"Analyzed {total_meds} medicines: {critical_count} critical shortages.", details=action_msg, category="info")
        db.session.add(act)
        db.session.commit()
        return result_payload

pharmacy_agent = PharmacyAgent()
