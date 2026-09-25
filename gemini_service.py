import os
import json
import logging

logger = logging.getLogger(__name__)

class GeminiService:
    def __init__(self):
        self.api_key = os.getenv('GEMINI_API_KEY', '').strip()
        self.client = None
        if self.api_key:
            try:
                # Try google.genai SDK
                from google import genai
                self.client = genai.Client(api_key=self.api_key)
                self.sdk_type = 'genai'
            except Exception as e1:
                try:
                    # Fallback to google.generativeai SDK
                    import google.generativeai as genai_legacy
                    genai_legacy.configure(api_key=self.api_key)
                    self.client = genai_legacy.GenerativeModel('gemini-2.5-flash')
                    self.sdk_type = 'legacy'
                except Exception as e2:
                    logger.warning(f"Could not initialize Gemini SDK: {e1} / {e2}")
                    self.client = None
                    self.sdk_type = None
        else:
            self.sdk_type = None

    def get_status(self):
        if self.client and self.api_key:
            return {"connected": True, "label": "Gemini AI ● Connected"}
        return {"connected": False, "label": "Gemini AI ● Rule-Based Fallback"}

    def test_gemini_connection(self):
        """
        Safely tests Gemini API connection without exposing API keys.
        """
        if not self.api_key:
            return {"connected": False, "label": "Gemini Connection Failed", "error": "No GEMINI_API_KEY configured."}
        res = self.generate_text("Respond with OK")
        if res:
            return {"connected": True, "label": "Gemini Connected", "message": "Gemini API connection active."}
        return {"connected": False, "label": "Gemini Connection Failed", "error": "Gemini API endpoint unreachable or fallback active."}

    def generate_text(self, prompt, system_instruction="You are CareSync AI Hospital Operations Intelligence."):
        if not self.client:
            return None
        import concurrent.futures
        def _call():
            if self.sdk_type == 'genai':
                response = self.client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=prompt,
                )
                return response.text
            elif self.sdk_type == 'legacy':
                response = self.client.generate_content(prompt)
                return response.text
            return None

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_call)
                return future.result(timeout=2.5)
        except Exception as e:
            logger.warning(f"Gemini API generation fallback triggered: {e}")
            return None

    def map_dataset_columns(self, category, columns, sample_data=None):
        """
        Uses Gemini to semantically map user dataset columns to internal target schema.
        Falls back to rule-based fuzzy matching.
        """
        prompt = f"""
Given a hospital dataset category '{category}', map the following source column names to our internal standardized schema.
Source Columns: {columns}
Sample Data: {json.dumps(sample_data or {}, default=str)}

Required internal schema fields for '{category}':
- PATIENTS: patient_id, name, age, gender, department, emergency, severity, status, bed_id, phone
- APPOINTMENTS: appointment_id, patient_id, patient_name, doctor, department, date, time, priority, status, phone
- BEDS: bed_id, ward, type, status, patient_id
- LABS: test_id, patient_id, patient_name, test_name, lab, priority, status, turnaround
- PHARMACY: medicine_id, medicine_name, required_quantity, available_quantity, status
- STAFFING: staff_id, name, role, department, availability, workload
- DISCHARGE: discharge_id, patient_id, patient_name, department, discharge_ready, status, bed_id

Return ONLY a valid JSON dictionary mapping source column -> internal field name. Do not invent missing values.
Example output: {{"Pt_ID": "patient_id", "Full Name": "name"}}
"""
        raw_res = self.generate_text(prompt)
        if raw_res:
            try:
                # Extract JSON block
                clean_json = raw_res.strip()
                if "```json" in clean_json:
                    clean_json = clean_json.split("```json")[1].split("```")[0].strip()
                elif "```" in clean_json:
                    clean_json = clean_json.split("```")[1].split("```")[0].strip()
                return json.loads(clean_json)
            except Exception as e:
                logger.warning(f"Failed to parse Gemini column mapping JSON: {e}")

        # Deterministic fallback mapping
        return self._rule_based_column_mapping(category, columns)

    def _rule_based_column_mapping(self, category, columns):
        mapping = {}
        for col in columns:
            c_lower = col.lower().replace('_', ' ').replace('-', ' ').strip()
            if any(k in c_lower for k in ['patient id', 'patient_id', 'pid', 'pt_id', 'id', 'no']):
                mapping[col] = 'patient_id' if 'patient' in c_lower or 'pt' in c_lower or 'pid' in c_lower else 'id'
            elif any(k in c_lower for k in ['name', 'patient name', 'full name', 'pt name']):
                mapping[col] = 'name' if category in ['PATIENTS', 'STAFFING'] else 'patient_name'
            elif 'age' in c_lower:
                mapping[col] = 'age'
            elif 'gender' in c_lower or 'sex' in c_lower:
                mapping[col] = 'gender'
            elif 'dept' in c_lower or 'department' in c_lower:
                mapping[col] = 'department'
            elif 'emerg' in c_lower or 'er' in c_lower:
                mapping[col] = 'emergency'
            elif 'sever' in c_lower or 'urgenc' in c_lower or 'priority' in c_lower:
                mapping[col] = 'severity' if category == 'PATIENTS' else 'priority'
            elif 'bed' in c_lower or 'room' in c_lower:
                mapping[col] = 'bed_id'
            elif 'phone' in c_lower or 'mobile' in c_lower or 'contact' in c_lower:
                mapping[col] = 'phone'
            elif 'doc' in c_lower or 'physician' in c_lower:
                mapping[col] = 'doctor'
            elif 'date' in c_lower:
                mapping[col] = 'date'
            elif 'time' in c_lower:
                mapping[col] = 'time'
            elif 'ward' in c_lower:
                mapping[col] = 'ward'
            elif 'type' in c_lower:
                mapping[col] = 'type'
            elif 'status' in c_lower or 'state' in c_lower:
                mapping[col] = 'status'
            elif 'test' in c_lower or 'diagnostic' in c_lower:
                mapping[col] = 'test_name'
            elif 'lab' in c_lower:
                mapping[col] = 'lab'
            elif 'turnaround' in c_lower or 'tat' in c_lower:
                mapping[col] = 'turnaround'
            elif 'med' in c_lower or 'drug' in c_lower:
                mapping[col] = 'medicine_name'
            elif 'req' in c_lower or 'needed' in c_lower:
                mapping[col] = 'required_quantity'
            elif 'avail' in c_lower or 'stock' in c_lower:
                mapping[col] = 'available_quantity'
            elif 'role' in c_lower or 'title' in c_lower:
                mapping[col] = 'role'
            elif 'workload' in c_lower or 'load' in c_lower:
                mapping[col] = 'workload'
            elif 'discharge' in c_lower or 'ready' in c_lower:
                mapping[col] = 'discharge_ready'
        return mapping

    def analyze_operational_surge(self, db_summary):
        """
        Gemini AI reasoning over REAL uploaded data.
        Does NOT invent numbers. Uses db_summary strictly.
        """
        prompt = f"""
Analyze the following REAL hospital operational metrics from our live database:
- Total Patients: {db_summary.get('patients_count', 0)}
- Emergency Patients: {db_summary.get('emergency_count', 0)}
- Available Beds: {db_summary.get('available_beds', 0)} / Total Beds: {db_summary.get('total_beds', 0)}
- Today's Scheduled Appointments: {db_summary.get('appointments_count', 0)}
- Pending Lab Tests: {db_summary.get('pending_labs', 0)}
- Low Medicine Items: {db_summary.get('medicine_shortages', 0)}
- Available Staff: {db_summary.get('available_staff', 0)}
- Discharge Ready Patients: {db_summary.get('discharge_ready', 0)}

Provide a concise 2-sentence executive summary of operational bottlenecks and recommended multi-agent priorities. Use ONLY the figures provided above.
"""
        res = self.generate_text(prompt)
        if res:
            return res.strip()
        
        # Rule-based fallback summary
        emerg = db_summary.get('emergency_count', 0)
        beds = db_summary.get('available_beds', 0)
        appts = db_summary.get('appointments_count', 0)
        return f"Emergency load is at {emerg} patient(s) with {beds} available bed(s). Appointment Agent & Bed Agent will prioritize emergency admissions and reschedule {appts} scheduled visit(s)."

    def analyze_scenario_plan(self, scenario_dict, db_summary):
        """
        Gemini AI dynamic scenario analysis and agent sequence planning.
        Analyzes actual DB metrics and user instruction to choose required agents and execution order.
        """
        prompt = f"""
You are the Lead Hospital Operations Coordinator AI.
Analyze this scenario and determine the required specialized agents and optimal execution order.

SCENARIO CONTEXT:
- Name: {scenario_dict.get('name')}
- Description: {scenario_dict.get('description')}
- User Situation Instruction: {scenario_dict.get('user_instruction')}
- Scenario Type: {scenario_dict.get('scenario_type')}
- Priority: {scenario_dict.get('priority')}
- Target Department: {scenario_dict.get('department')}

REAL DATABASE METRICS:
- Total Patients: {db_summary.get('patients_count', 0)} (Emergency: {db_summary.get('emergency_count', 0)})
- Available Beds: {db_summary.get('available_beds', 0)} / {db_summary.get('total_beds', 0)}
- Scheduled Appointments: {db_summary.get('appointments_count', 0)}
- Pending Lab Tests: {db_summary.get('pending_labs', 0)}
- Medicine Shortages: {db_summary.get('medicine_shortages', 0)}
- Available Staff: {db_summary.get('available_staff', 0)}
- Discharge Ready Patients: {db_summary.get('discharge_ready', 0)}

Select required agents from: ["Bed Management", "Discharge", "Appointment", "Staffing", "Lab", "Pharmacy"].
Return ONLY a valid JSON dictionary in this structure:
{{
  "analysis_summary": "Executive breakdown of what is happening based ONLY on the metrics provided...",
  "recommended_agents": ["Bed Management", "Discharge", "Appointment", "Staffing", "Lab", "Pharmacy"],
  "agent_instructions": {{
    "Bed Management": "Specific instruction for bed agent...",
    "Discharge": "Specific instruction for discharge agent...",
    "Appointment": "Specific instruction for appointment agent...",
    "Staffing": "Specific instruction for staffing agent...",
    "Lab": "Specific instruction for lab agent...",
    "Pharmacy": "Specific instruction for pharmacy agent..."
  }}
}}
"""
        raw_res = self.generate_text(prompt)
        if raw_res:
            try:
                clean_json = raw_res.strip()
                if "```json" in clean_json:
                    clean_json = clean_json.split("```json")[1].split("```")[0].strip()
                elif "```" in clean_json:
                    clean_json = clean_json.split("```")[1].split("```")[0].strip()
                return json.loads(clean_json)
            except Exception as e:
                logger.warning(f"Failed to parse Gemini scenario plan JSON: {e}")

        # Deterministic Rule-Based Fallback Plan
        instruction_lower = str(scenario_dict.get('user_instruction', '')).lower()
        stype_lower = str(scenario_dict.get('scenario_type', '')).lower()

        # Dynamic ordering heuristic
        if 'bed' in instruction_lower or 'surge' in stype_lower or 'emergency' in instruction_lower:
            plan_order = ["Bed Management", "Discharge", "Appointment", "Staffing", "Lab", "Pharmacy"]
        elif 'appointment' in instruction_lower or 'schedule' in stype_lower:
            plan_order = ["Appointment", "Bed Management", "Staffing", "Discharge", "Lab", "Pharmacy"]
        elif 'lab' in instruction_lower or 'diagnostic' in stype_lower:
            plan_order = ["Lab", "Staffing", "Bed Management", "Appointment", "Discharge", "Pharmacy"]
        elif 'pharmacy' in instruction_lower or 'stock' in stype_lower:
            plan_order = ["Pharmacy", "Lab", "Staffing", "Bed Management", "Appointment", "Discharge"]
        else:
            plan_order = ["Bed Management", "Discharge", "Appointment", "Staffing", "Lab", "Pharmacy"]

        return {
            "analysis_summary": f"Hospital scenario '{scenario_dict.get('name')}' analyzed under {scenario_dict.get('priority')} priority. Emergency volume is {db_summary.get('emergency_count', 0)} case(s) with {db_summary.get('available_beds', 0)} available bed(s).",
            "recommended_agents": plan_order,
            "agent_instructions": {
                "Bed Management": "Analyze emergency capacity and ICU allocations.",
                "Discharge": "Identify discharge-ready patients and release bed allocations.",
                "Appointment": "Reschedule routine appointments to accommodate emergency surge and send SMS alerts.",
                "Staffing": "Reallocate available clinical staff to Emergency triage.",
                "Lab": "Prioritize urgent diagnostic lab tests and reroute backlogged queues.",
                "Pharmacy": "Check critical pharmaceutical inventory and flag stock shortages."
            }
        }

    def generate_agent_narrative(self, agent_name, metrics, user_instruction):
        """
        Generates an AI operational narrative for a specialized agent based on its calculated metrics.
        """
        prompt = f"""
You are the specialized {agent_name} AI Agent in CareSync AI.
Analyze the following operational metrics calculated from our live hospital database in response to user instruction: "{user_instruction}".

Metrics:
{json.dumps(metrics, indent=2, default=str)}

Provide a 2-3 sentence clear operational synthesis of your findings, key actions taken, and recommended next steps for hospital administration.
"""
        res = self.generate_text(prompt)
        if res:
            return res.strip()
        return f"{agent_name} operational analysis completed successfully based on database parameters."

    def generate_scenario_summary(self, scenario_dict, metrics):
        prompt = f"""
You are the Lead Hospital Coordinator AI for CareSync AI.
Synthesize the operational situation for scenario "{scenario_dict.get('name')}".
Use ONLY the following database-derived metrics (do NOT invent any numbers):
- Incoming Emergency Patients: {metrics.get('incoming_patients', 20)}
- Beds Required: {metrics.get('beds_required', 20)}
- Available Beds: {metrics.get('available_beds', 0)} / Total Beds: {metrics.get('total_beds', 0)}
- Initial Capacity Gap: {metrics.get('initial_capacity_gap', 0)}
- Discharge-Ready Patients (Potential Beds Released): {metrics.get('discharge_ready', 0)}
- Surge Verdict: {metrics.get('surge_verdict', 'CAPACITY UNDER PRESSURE')}
- Available Staff: {metrics.get('available_doctors', 0)} Doctors, {metrics.get('available_nurses', 0)} Nurses ({metrics.get('available_staff', 0)} Total)
- Pending Lab Tests: {metrics.get('pending_labs', 0)}
- Critical Medicines: {metrics.get('critical_meds', 0)}

Write a 2-3 sentence executive operational summary explaining hospital preparedness.
"""
        res = self.generate_text(prompt)
        if res:
            return res.strip()
        return f"{metrics.get('incoming_patients', 20)} emergency patients expected. Hospital has {metrics.get('available_beds', 0)} available beds (initial gap: {metrics.get('initial_capacity_gap', 0)}). {metrics.get('discharge_ready', 0)} discharge-ready patients may provide additional capacity."

    def generate_final_operational_summary(self, command_center):
        """
        Generates the final human-readable operational summary using strictly calculated DB metrics.
        """
        inc = command_center.get('incoming_patients', 20)
        avail = command_center.get('beds_available', 0)
        gap = command_center.get('capacity_gap', 0)
        labs = command_center.get('pending_labs', 0)
        pharm = command_center.get('critical_medicines', 0)
        staff = command_center.get('clinical_staff_available', 0)
        dis = command_center.get('discharge_ready', 0)
        verdict = command_center.get('surge_verdict', '')

        prompt = f"""
You are CareSync AI Lead Hospital Operations Assistant.
Summarize the multi-agent findings for the scenario using ONLY these exact figures:
- Incoming Emergency Patients: {inc}
- Available Beds: {avail}
- Initial Capacity Gap: {gap}
- Pending Lab Tests: {labs}
- Critical Medicines: {pharm}
- Available Clinical Staff: {staff}
- Discharge-Ready Patients: {dis}
- Hospital Capacity Verdict: {verdict}

Structure your response clearly following this pattern:
"{inc} emergency patients are expected to arrive. The hospital currently has {avail} available beds, creating a capacity gap of {gap}. There are {labs} pending lab tests and {pharm} critical medicine shortages. {staff} clinical staff are currently available, and {dis} discharge-ready patients may provide additional capacity."
Do NOT invent any other numbers.
"""
        res = self.generate_text(prompt)
        if res:
            return res.strip()
        return f"{inc} emergency patients are expected to arrive. The hospital currently has {avail} available beds, creating a capacity gap of {gap}. There are {labs} pending lab tests and {pharm} critical medicine shortages. {staff} clinical staff are currently available, and {dis} discharge-ready patients may provide additional capacity."

gemini_service = GeminiService()

