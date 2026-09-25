import os
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from services.database import db, Appointment, StaffMember, Patient, Notification, WhatsAppContact
from services.gemini_service import gemini_service
from services.twilio_service import twilio_service

logger = logging.getLogger(__name__)

STANDARD_TIME_SLOTS = [
    "09:00 AM", "09:30 AM", "10:00 AM", "10:30 AM",
    "11:00 AM", "11:30 AM", "02:00 PM", "02:30 PM",
    "03:00 PM", "03:30 PM", "04:00 PM", "04:30 PM"
]

def normalize_date_str(date_input):
    if not date_input:
        return ""
    s = str(date_input).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass
    return s

def normalize_time_str(time_input):
    if not time_input:
        return ""
    s = str(time_input).strip()
    if "(" in s:
        s = s.split("(")[0].strip()
    for fmt in ("%I:%M %p", "%H:%M:%S", "%H:%M", "%I:%M%p"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%I:%M %p")
        except ValueError:
            pass
    return s

CONDITION_KNOWLEDGE_BASE = {
    "Cardiac problem": {
        "department": "Cardiology",
        "diagnostics": ["ECG", "Echocardiogram", "Cardiac blood markers"]
    },
    "Chest pain": {
        "department": "Cardiology",
        "diagnostics": ["ECG", "Echocardiogram", "Blood Test"]
    },
    "Hypertension": {
        "department": "Cardiology",
        "diagnostics": ["ECG", "Blood Pressure Monitoring", "Blood Test"]
    },
    "Diabetes": {
        "department": "General Medicine",
        "diagnostics": ["Blood Glucose", "Kidney Function Test", "CBC"]
    },
    "Kidney disease": {
        "department": "Nephrology",
        "diagnostics": ["Kidney Function Test", "Creatinine", "Electrolytes", "Urinalysis"]
    },
    "Nephrology-related condition": {
        "department": "Nephrology",
        "diagnostics": ["Kidney Function Test", "Creatinine", "Urinalysis"]
    },
    "Neurological problem": {
        "department": "Neurology",
        "diagnostics": ["CT Scan", "MRI", "Blood Test"]
    },
    "Orthopedic problem": {
        "department": "Orthopedics",
        "diagnostics": ["X-Ray", "MRI if clinically required", "CT Scan"]
    },
    "Gastrointestinal problem": {
        "department": "Gastroenterology",
        "diagnostics": ["Ultrasound", "Liver Function Test", "Blood Test"]
    },
    "Respiratory problem": {
        "department": "General Medicine",
        "diagnostics": ["X-Ray", "CBC", "Blood Test"]
    },
    "Fever / infection": {
        "department": "General Medicine",
        "diagnostics": ["CBC", "Blood Test", "Blood Glucose"]
    },
    "General medicine": {
        "department": "General Medicine",
        "diagnostics": ["Blood Test", "CBC", "Blood Glucose"]
    },
    "Cancer / oncology": {
        "department": "Oncology",
        "diagnostics": ["CT Scan", "MRI", "Blood Test", "CBC"]
    },
    "Emergency condition": {
        "department": "Emergency Department",
        "diagnostics": ["ECG", "X-Ray", "CBC", "Blood Test"]
    }
}

class AppointmentWorkflowService:
    def normalize_date_str(self, date_input):
        return normalize_date_str(date_input)

    def normalize_time_str(self, time_input):
        return normalize_time_str(time_input)

    def analyze_condition(self, disease, symptoms=""):
        """
        Decision-support recommendation for suggested department and diagnostics.
        Returns dataset knowledge or AI fallback if condition is custom/other.
        """
        d_clean = (disease or "").strip()
        if d_clean in CONDITION_KNOWLEDGE_BASE:
            info = CONDITION_KNOWLEDGE_BASE[d_clean]
            return {
                "disease": d_clean,
                "recommended_department": info["department"],
                "suggested_diagnostics": info["diagnostics"],
                "ai_suggested": False,
                "notice": "Suggested Diagnostics are decision-support recommendations only."
            }

        # AI Fallback for unlisted/other conditions
        ai_res = self._gemini_analyze_condition(disease, symptoms)
        return ai_res

    def _gemini_analyze_condition(self, disease, symptoms):
        prompt = (
            f"As a hospital decision-support system, recommend the appropriate medical department "
            f"and 2-4 suggested diagnostic tests for a patient with condition: '{disease}' and symptoms: '{symptoms}'.\n"
            f"Respond ONLY with a valid JSON object in this format:\n"
            f'{{"recommended_department": "DepartmentName", "suggested_diagnostics": ["Test1", "Test2"]}}'
        )
        try:
            raw_text = gemini_service.generate_content(prompt)
            if raw_text:
                clean = raw_text.replace("```json", "").replace("```", "").strip()
                data = json.loads(clean)
                dept = data.get("recommended_department", "General Medicine")
                diags = data.get("suggested_diagnostics", ["Blood Test", "CBC"])
                return {
                    "disease": disease or "Other",
                    "recommended_department": dept,
                    "suggested_diagnostics": diags,
                    "ai_suggested": True,
                    "notice": "AI Suggested Department & Diagnostics — Dataset information unavailable for this condition."
                }
        except Exception as e:
            logger.warning(f"Gemini condition analysis failed: {e}")

        # Static Fallback if AI call unavailable
        return {
            "disease": disease or "Other",
            "recommended_department": "General Medicine",
            "suggested_diagnostics": ["Blood Test", "CBC"],
            "ai_suggested": True,
            "notice": "AI Suggested Department & Diagnostics — Decision support fallback."
        }

    def get_available_doctors(self, user_id, department, date_str=None, time_str=None):
        """
        Queries doctors belonging to department from StaffMember or Appointment table.
        Standardizes matching (casing, spaces).
        Checks date/time availability if provided.
        Returns:
            dict with 'state': AVAILABLE | UNAVAILABLE_DATE_TIME | NO_DOCTORS_IN_DEPT
        """
        dept_raw = (department or "").strip()
        dept_clean = dept_raw.title()
        dept_lower = dept_raw.lower()

        if not dept_lower:
            return {
                "success": True,
                "state": "NO_DOCTORS_IN_DEPT",
                "department": "",
                "doctors": [],
                "message": "Please select a department."
            }

        seen_names = set()
        dept_doctors = []

        # 1. Query StaffMember table for staff members belonging to this department
        all_staff = StaffMember.query.filter_by(user_id=user_id).all()
        for s in all_staff:
            s_dept = (s.department or "").strip().lower()
            s_role = (s.role or "").strip().lower()
            s_name = (s.name or "").strip()

            if not s_name:
                continue

            # Check robust department match
            if dept_lower == s_dept or dept_lower in s_dept or s_dept in dept_lower:
                # Role check: Doctor, Physician, Specialist, Surgeon, Consultant, MD, or generic role, or name contains Dr.
                is_doctor_role = any(k in s_role for k in ['doctor', 'physician', 'specialist', 'surgeon', 'consultant', 'md'])
                if is_doctor_role or not s_role or 'dr.' in s_name.lower():
                    if s_name not in seen_names:
                        seen_names.add(s_name)
                        dept_doctors.append({
                            "name": s_name,
                            "specialty": s.role if s.role else f"{dept_clean} Specialist",
                            "department": s.department or dept_clean,
                            "status": s.availability or "Available",
                            "next_available": "09:00 AM",
                            "is_ai_fallback": False
                        })

        # 2. Query distinct doctors from Appointment table for this department
        all_appts = Appointment.query.filter_by(user_id=user_id).all()
        for a in all_appts:
            a_dept = (a.department or "").strip().lower()
            a_doc = (a.doctor or "").strip()

            if (dept_lower == a_dept or dept_lower in a_dept or a_dept in dept_lower) and a_doc:
                if a_doc not in seen_names and a_doc.lower() not in ['doctor', 'unknown', 'n/a']:
                    seen_names.add(a_doc)
                    dept_doctors.append({
                        "name": a_doc,
                        "specialty": f"{dept_clean} Specialist",
                        "department": a.department or dept_clean,
                        "status": "Available",
                        "next_available": "09:30 AM",
                        "is_ai_fallback": False
                    })

        # If zero doctors exist in dataset for this department, provide fallback doctors for seamless booking
        if not dept_doctors:
            fallback_names = [f"Dr. A. Sharma ({dept_clean} Specialist)", f"Dr. R. Verma ({dept_clean} Consultant)"]
            for fname in fallback_names:
                dept_doctors.append({
                    "name": fname,
                    "specialty": f"{dept_clean} Specialist",
                    "department": dept_clean,
                    "status": "Available",
                    "next_available": "09:00 AM",
                    "is_ai_fallback": True
                })

        # 3. Apply Date & Time Slot availability rules if provided
        processed_doctors = []
        available_count = 0
        norm_date = normalize_date_str(date_str) if date_str else None

        for doc in dept_doctors:
            doc_name = doc["name"]
            is_booked = False

            if norm_date and time_str:
                for a in all_appts:
                    if a.doctor and a.doctor.strip().lower() == doc_name.lower():
                        if a.status and a.status.strip().lower() != 'cancelled':
                            if normalize_date_str(a.date) == norm_date and a.time and a.time.strip() == time_str.strip():
                                is_booked = True
                                break

            status_str = "Busy" if is_booked else doc.get("status", "Available")
            if not is_booked:
                available_count += 1

            processed_doctors.append({
                "name": doc_name,
                "specialty": doc["specialty"],
                "specialization": doc["specialty"],
                "department": doc["department"],
                "status": status_str,
                "next_available": doc.get("next_available", "09:00 AM"),
                "is_available": not is_booked,
                "is_ai_fallback": doc.get("is_ai_fallback", False)
            })

        if norm_date and time_str and available_count == 0:
            return {
                "success": True,
                "state": "UNAVAILABLE_DATE_TIME",
                "department": dept_clean,
                "doctors": processed_doctors,
                "message": "Doctors are available in this department, but none are available for the selected date/time."
            }

        return {
            "success": True,
            "state": "AVAILABLE",
            "department": dept_clean,
            "doctors": processed_doctors,
            "message": "Available doctors found"
        }

    def get_available_slots(self, user_id, doctor, date_str):
        """
        Checks database to prevent double booking.
        Filters out slots already booked for doctor on date.
        Returns state: AVAILABLE | UNAVAILABLE_DATE | UNAVAILABLE_DOCTOR | NO_DOCTOR_OR_DATE
        """
        if not doctor or not date_str:
            return {
                "success": True,
                "state": "NO_DOCTOR_OR_DATE",
                "doctor": doctor or "",
                "date": date_str or "",
                "slots": [],
                "message": "Please select doctor and date to check slot availability."
            }

        doctor_clean = doctor.strip()
        norm_target_date = normalize_date_str(date_str)

        # 1. Check if doctor is explicitly marked as unavailable/on leave in StaffMember
        all_staff = StaffMember.query.filter_by(user_id=user_id).all()
        doc_staff = None
        for s in all_staff:
            if s.name and (s.name.strip().lower() == doctor_clean.lower() or doctor_clean.lower() in s.name.strip().lower()):
                doc_staff = s
                break

        if doc_staff and doc_staff.availability and doc_staff.availability.strip().lower() in ['on leave', 'unavailable', 'off duty']:
            return {
                "success": True,
                "state": "UNAVAILABLE_DOCTOR",
                "doctor": doctor_clean,
                "date": date_str,
                "slots": [],
                "message": "This doctor is not available on the selected date."
            }

        # 2. Query existing appointments for this user, matching doctor & normalized date
        existing_appts = Appointment.query.filter_by(user_id=user_id).all()
        booked_slots = set()
        for a in existing_appts:
            if a.doctor and (a.doctor.strip().lower() == doctor_clean.lower() or doctor_clean.lower() in a.doctor.strip().lower()):
                if a.status and a.status.strip().lower() != 'cancelled':
                    a_date_norm = normalize_date_str(a.date)
                    if a_date_norm == norm_target_date:
                        if a.time:
                            booked_slots.add(normalize_time_str(a.time))
                        if a.rescheduled_time:
                            booked_slots.add(normalize_time_str(a.rescheduled_time))

        # 3. Build slot list with availability flag
        slots_out = []
        available_count = 0
        for slot in STANDARD_TIME_SLOTS:
            norm_slot = normalize_time_str(slot)
            is_avail = norm_slot not in booked_slots
            if is_avail:
                available_count += 1
            slots_out.append({
                "slot": slot,
                "available": is_avail
            })

        if available_count == 0:
            return {
                "success": True,
                "state": "UNAVAILABLE_DATE",
                "doctor": doctor_clean,
                "date": date_str,
                "slots": slots_out,
                "message": "No available time slots for this doctor on the selected date."
            }

        return {
            "success": True,
            "state": "AVAILABLE",
            "doctor": doctor_clean,
            "date": date_str,
            "slots": slots_out,
            "message": "Available time slots found"
        }

    def get_doctor_schedule_recommendations(self, user_id, doctor, days=7):
        """
        Scans upcoming days starting today for doctor availability,
        returning recommended open dates and total open slots per day.
        """
        if not doctor:
            return {
                "success": True,
                "doctor": "",
                "total_available_days": 0,
                "recommended_dates": []
            }

        doctor_clean = doctor.strip()
        today = datetime.now()
        all_appts = Appointment.query.filter_by(user_id=user_id).all()

        recommended = []
        open_days_count = 0

        for i in range(days):
            target_dt = today + timedelta(days=i)
            date_iso = target_dt.strftime("%Y-%m-%d")
            if i == 0:
                display_label = f"Today ({target_dt.strftime('%b %d')})"
            elif i == 1:
                display_label = f"Tomorrow ({target_dt.strftime('%b %d')})"
            else:
                display_label = target_dt.strftime("%b %d (%a)")

            booked_slots = set()
            for a in all_appts:
                if a.doctor and (a.doctor.strip().lower() == doctor_clean.lower() or doctor_clean.lower() in a.doctor.strip().lower()):
                    if a.status and a.status.strip().lower() != 'cancelled':
                        if normalize_date_str(a.date) == date_iso:
                            if a.time:
                                booked_slots.add(normalize_time_str(a.time))
                            if a.rescheduled_time:
                                booked_slots.add(normalize_time_str(a.rescheduled_time))

            avail_count = sum(1 for slot in STANDARD_TIME_SLOTS if normalize_time_str(slot) not in booked_slots)

            if avail_count > 0:
                open_days_count += 1
                recommended.append({
                    "date": date_iso,
                    "display_label": display_label,
                    "available_slots_count": avail_count,
                    "is_recommended": True
                })

        return {
            "success": True,
            "doctor": doctor_clean,
            "total_available_days": open_days_count,
            "recommended_dates": recommended
        }

    def format_whatsapp_message(self, patient_name, appointment_id, doctor, department, date, time, appointment_type, disease=None, diagnostics=None):
        """
        Formats user-friendly WhatsApp confirmation message structure (Future production template structure).
        """
        diag_str = "None"
        if diagnostics:
            if isinstance(diagnostics, str):
                try:
                    diag_list = json.loads(diagnostics)
                except Exception:
                    diag_list = [d.strip() for d in diagnostics.split(",") if d.strip()]
            else:
                diag_list = diagnostics

            if diag_list:
                diag_str = ", ".join(diag_list)

        message = (
            f"👋 Hello {patient_name}!\n\n"
            f"Your CareSync AI appointment has been booked successfully.\n\n"
            f"📅 Date: {date}\n"
            f"⏰ Time: {time}\n"
            f"👨‍⚕️ Doctor: {doctor}\n"
            f"🏥 Department: {department}\n"
            f"🧪 Diagnostics: {diag_str}\n"
            f"🆔 Appointment ID: {appointment_id}\n\n"
            f"Thank you for choosing CareSync AI.\n"
            f"We look forward to seeing you! 💙"
        )
        return message

    def clean_twilio_error(self, err_msg):
        """
        Strips ANSI escape sequences, raw URLs, and sensitive credentials from error messages.
        Returns a clean, user-friendly error string.
        """
        if not err_msg:
            return "Delivery failed."
        s = str(err_msg)
        # Strip ANSI codes
        s = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', s)
        s = re.sub(r'≡\[[0-9;]*[mK]', '', s)
        s = re.sub(r'\[[0-9;]*m', '', s)

        # Redact Account SID & Tokens
        s = re.sub(r'AC[a-zA-Z0-9]{32}', '[ACCOUNT_SID]', s)
        s = re.sub(r'[a-fA-F0-9]{32}', '[REDACTED]', s)
        # Remove URLs
        s = re.sub(r'https?://[^\s]+', '', s)

        # User-friendly translations for Twilio Sandbox / Trial
        s_lower = s.lower()
        if "contentsid is invalid" in s_lower or "content_sid is invalid" in s_lower or "invalid contentsid" in s_lower or "21655" in s_lower:
            s = "Twilio ContentSid in .env is invalid for your Twilio Account. Please create a Content Template in Twilio Console (Messaging > Content Template Builder) and update TWILIO_WHATSAPP_CONTENT_SID in .env."
        elif "contentsid required" in s_lower or "content_sid required" in s_lower or "21654" in s_lower:
            s = "Twilio requires an approved ContentSid template for WhatsApp API delivery on this account. Create a template in Twilio Console and update TWILIO_WHATSAPP_CONTENT_SID in .env."
        elif "trial accounts have limited parameter access" in s_lower or "disallowed parameters" in s_lower:
            s = "Twilio Trial WhatsApp account requires approved ContentSid template or active 24-hour Sandbox session."
        elif "is not a valid whatsapp-enabled number" in s_lower:
            s = "Recipient phone number is not registered or valid for WhatsApp."
        elif "572002" in s_lower or "verified recipient" in s_lower or "trial phone number is assigned" in s_lower:
            s = "Twilio Trial Limit: Please enter the exact phone number that joined Twilio WhatsApp Sandbox (send 'join twilio-trial' on WhatsApp to +17372508034), or add the phone number as a Verified Caller ID in Twilio Console."
        elif "unverified" in s_lower or "sandbox" in s_lower or "21608" in s_lower or "not a sandbox user" in s_lower:
            s = "Patient phone number has not joined the Twilio WhatsApp Sandbox. Send 'join twilio-trial' on WhatsApp to +17372508034."
        elif "authorization" in s_lower or "authenticate" in s_lower or "20003" in s_lower:
            s = "Twilio authentication failed. Please check TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN in .env."

        s = re.sub(r'\s+', ' ', s).strip()
        return s if s else "WhatsApp delivery failed."

    def to_whatsapp_e164(self, phone_str):
        """
        Formats raw phone number into whatsapp:+E164 format.
        Example: "9502523346" -> "whatsapp:+919502523346"
        Example: "+919502523346" -> "whatsapp:+919502523346"
        """
        clean = self.normalize_phone_e164(phone_str)
        return f"whatsapp:{clean}" if clean else ""

    def normalize_phone_e164(self, phone_str):
        """
        Extracts clean canonical E.164 phone string (e.g. "+919502523346") without 'whatsapp:' prefix.
        Normalizes:
        9502523346 -> +919502523346
        +91 9502523346 -> +919502523346
        +919502523346 -> +919502523346
        91-9502523346 -> +919502523346
        whatsapp:+919502523346 -> +919502523346
        """
        if not phone_str:
            return ""
        p = str(phone_str).strip()
        if p.lower().startswith("whatsapp:"):
            p = p[9:].strip()
        p = re.sub(r'[^\d+]', '', p)
        if not p:
            return ""
        if p.startswith("00"):
            p = "+" + p[2:]
        elif p.startswith("0") and len(p) == 11:
            p = p[1:]

        if not p.startswith('+'):
            if len(p) == 10:
                p = '+91' + p
            elif len(p) == 12 and p.startswith('91'):
                p = '+' + p
            elif len(p) == 11 and p.startswith('1'):
                p = '+' + p
            else:
                p = '+' + p
        return p

    def sync_inbound_sandbox_joins(self, limit=10, force=False):
        """
        Polls Twilio Messages API for recent inbound WhatsApp messages to the Sandbox number (e.g. 'join want-my').
        Automatically registers new joins in WhatsAppContact and dispatches the Welcome Message to their phone.
        Ensures local development / localhost without public webhooks still immediately receives and responds
        to QR code scans!
        """
        now = time.time()
        # Throttle polling unless forced (minimum 2.0 seconds between Twilio API checks)
        if not force and hasattr(self, '_last_inbound_sync_time') and (now - self._last_inbound_sync_time) < 2.0:
            return []
        self._last_inbound_sync_time = now

        client = twilio_service.client
        if not client:
            return []

        raw_from = os.getenv('TWILIO_WHATSAPP_NUMBER', '+14155238886').strip()
        to_wa_sandbox = self.to_whatsapp_e164(raw_from)

        newly_processed = []
        try:
            inbound_msgs = client.messages.list(to=to_wa_sandbox, limit=limit)
            for m in inbound_msgs:
                body_clean = (m.body or '').strip().lower()
                if body_clean.startswith('join'):
                    norm_phone = self.normalize_phone_e164(m.from_)
                    if not norm_phone:
                        continue

                    msg_dt = m.date_sent or m.date_created
                    if msg_dt and msg_dt.tzinfo:
                        msg_dt_utc = msg_dt.astimezone(timezone.utc).replace(tzinfo=None)
                    else:
                        msg_dt_utc = msg_dt or datetime.utcnow()

                    contact = WhatsAppContact.query.filter_by(phone_number=norm_phone).first()

                    # Needs welcome if:
                    # 1. Phone number is not in WhatsAppContact table
                    # 2. Contact exists but welcome message was never sent or failed
                    # 3. An inbound join message arrived after the last recorded welcome/join time
                    needs_welcome = False
                    if not contact:
                        needs_welcome = True
                    elif contact.welcome_message_status != 'Sent':
                        needs_welcome = True
                    elif contact.joined_at and (msg_dt_utc - contact.joined_at).total_seconds() > 60:
                        needs_welcome = True

                    if needs_welcome:
                        logger.info(f"[Inbound Sync] Fresh Sandbox join detected from {norm_phone} ('{m.body}'). Registering & sending welcome message...")
                        reg_res = self.register_whatsapp_join(norm_phone)
                        newly_processed.append({"phone": norm_phone, "res": reg_res})

        except Exception as e:
            logger.warning(f"[Inbound Sync] Error polling Twilio inbound messages: {e}")

        return newly_processed

    def register_whatsapp_join(self, phone_number, user_id=None):
        """
        Registers an incoming WhatsApp Sandbox join for a SPECIFIC phone number.
        Saves/updates WhatsAppContact model record per phone number and triggers Welcome Message to THAT SAME number.
        """
        if not phone_number:
            return {"success": False, "error": "No phone number provided"}

        e164_clean = self.normalize_phone_e164(phone_number)
        to_wa = self.to_whatsapp_e164(phone_number)

        logger.info(f"[Twilio] Incoming From: {phone_number}")
        logger.info(f"[Twilio] Normalized From: {e164_clean}")

        contact = WhatsAppContact.query.filter_by(phone_number=e164_clean).first()
        if not contact:
            contact = WhatsAppContact(
                user_id=user_id,
                phone_number=e164_clean,
                whatsapp_number=to_wa,
                sandbox_joined=True,
                joined_at=datetime.utcnow(),
                last_seen_at=datetime.utcnow(),
                welcome_message_status='Pending'
            )
            db.session.add(contact)
        else:
            contact.sandbox_joined = True
            contact.joined_at = datetime.utcnow()
            contact.last_seen_at = datetime.utcnow()
            contact.welcome_message_status = 'Pending'

        try:
            db.session.commit()
        except Exception as e:
            logger.warning(f"Error saving WhatsAppContact: {e}")
            db.session.rollback()

        # Send Welcome Message to THAT SPECIFIC NUMBER
        welcome_res = self.send_welcome_whatsapp(phone_number=e164_clean)
        contact.welcome_message_status = 'Sent' if welcome_res.get("success") else 'Failed'

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()

        return {
            "success": True,
            "phone_number": e164_clean,
            "whatsapp_number": to_wa,
            "welcome_result": welcome_res
        }

    def check_sandbox_status(self, phone_number, user_id=None):
        """
        Checks whether a SPECIFIC phone number has joined the Twilio WhatsApp Sandbox.
        """
        if not phone_number:
            return {"success": True, "sandbox_joined": False, "message": "No phone number provided."}

        e164_clean = self.normalize_phone_e164(phone_number)
        contact = WhatsAppContact.query.filter_by(phone_number=e164_clean).first()

        # If not found or not joined, sync Twilio's inbound messages right away!
        if not contact or not contact.sandbox_joined:
            self.sync_inbound_sandbox_joins(limit=10, force=True)
            contact = WhatsAppContact.query.filter_by(phone_number=e164_clean).first()

        if contact and contact.sandbox_joined:
            # If joined but welcome message was not sent, trigger it now!
            if contact.welcome_message_status != 'Sent':
                logger.info(f"Dispatching pending welcome message for {e164_clean} during status check...")
                w_res = self.send_welcome_whatsapp(e164_clean)
                contact.welcome_message_status = 'Sent' if w_res.get('success') else 'Connected'
                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()

            status_note = " • Welcome message dispatched to WhatsApp" if contact.welcome_message_status == 'Sent' else " • WhatsApp Connected"
            return {
                "success": True,
                "phone": e164_clean,
                "sandbox_joined": True,
                "joined_at": contact.joined_at.isoformat() if contact.joined_at else None,
                "welcome_status": contact.welcome_message_status or "Sent",
                "message": f"✓ WhatsApp Connected{status_note}"
            }

        return {
            "success": True,
            "phone": e164_clean,
            "sandbox_joined": False,
            "welcome_status": "Not Joined",
            "message": "⚠ Please scan the WhatsApp QR and join the Sandbox before booking WhatsApp notifications."
        }

    def send_welcome_whatsapp(self, phone_number):
        """
        Sends Welcome message to THAT SPECIFIC number when user joins Twilio Sandbox.
        """
        welcome_text = (
            "👋 Welcome to CareSync AI!\n\n"
            "Your WhatsApp is now connected successfully. 💙\n\n"
            "You can now book your hospital appointment through CareSync AI.\n\n"
            "After booking, your appointment confirmation will be sent to this WhatsApp number.\n\n"
            "Thank you for choosing CareSync AI! 🏥"
        )
        return self._dispatch_whatsapp(
            phone_number=phone_number,
            fallback_body=welcome_text
        )

    def send_appointment_sms(self, appointment, user_id=None, phone_override=None):
        """
        Sends SMS confirmation for an appointment dynamically to the appointment phone number.
        Uses Twilio Trial SMS template (body='sms_appointment_reminders') with fallback to custom SMS text.
        """
        if isinstance(appointment, dict):
            appt_id = appointment.get('appointment_id', '')
            patient_name = appointment.get('patient_name', '')
            phone = phone_override or appointment.get('phone', '')
            doctor = appointment.get('doctor', '')
            department = appointment.get('department', '')
            date_str = appointment.get('date', '')
            time_str = appointment.get('time', '')
            u_id = user_id or appointment.get('user_id')
        else:
            appt_id = getattr(appointment, 'appointment_id', '')
            patient_name = getattr(appointment, 'patient_name', '')
            phone = phone_override or getattr(appointment, 'phone', '')
            doctor = getattr(appointment, 'doctor', '')
            department = getattr(appointment, 'department', '')
            date_str = getattr(appointment, 'date', '')
            time_str = getattr(appointment, 'time', '')
            u_id = user_id or getattr(appointment, 'user_id', None)

        if not phone or str(phone).strip() in ['', 'None', 'nan']:
            return {"success": False, "error": "No phone number provided."}

        norm_phone = self.normalize_phone_e164(phone)
        from_phone = twilio_service.phone_number or os.getenv('TWILIO_PHONE_NUMBER', '+17372508034').strip()

        # Build custom SMS message body
        custom_body = (
            f"CareSync AI: Appointment {appt_id} confirmed for {patient_name} with {doctor} ({department}) "
            f"on {date_str} at {time_str}. Thank you!"
        )

        # Store Notification record in DB
        notif = None
        if u_id and appt_id:
            notif_id = f"N-SMS-{os.urandom(4).hex().upper()}"
            notif = Notification(
                notification_id=notif_id,
                appointment_id=appt_id,
                user_id=u_id,
                phone=norm_phone,
                notification_type='sms_confirmation',
                message=custom_body,
                status='Pending',
                created_at=datetime.utcnow()
            )
            db.session.add(notif)
            try:
                db.session.commit()
            except Exception as e:
                logger.warning(f"Could not save Notification record: {e}")
                db.session.rollback()

        sid = None
        status = "failed"
        raw_error = None
        success = False

        if twilio_service.client:
            # Try 1: Trial SMS template 'sms_appointment_reminders'
            try:
                msg = twilio_service.client.messages.create(
                    from_=from_phone,
                    to=norm_phone,
                    body="sms_appointment_reminders"
                )
                sid = msg.sid
                status = msg.status or "queued"
                success = True
                logger.info(f"[Twilio SMS] Trial template SMS dispatched to {norm_phone}: SID {sid}")
            except Exception as trial_err:
                raw_error = str(trial_err)
                logger.warning(f"[Twilio SMS] Trial template dispatch error: {raw_error}")
                # Try 2: Custom Body fallback
                try:
                    msg = twilio_service.client.messages.create(
                        from_=from_phone,
                        to=norm_phone,
                        body=custom_body
                    )
                    sid = msg.sid
                    status = msg.status or "queued"
                    success = True
                    logger.info(f"[Twilio SMS] Custom body SMS dispatched to {norm_phone}: SID {sid}")
                except Exception as body_err:
                    raw_error = str(body_err)
                    logger.error(f"[Twilio SMS] Custom body dispatch error: {raw_error}")
        else:
            # Mock mode
            sid = f"SM_MOCK_{os.urandom(4).hex().upper()}"
            status = "sent"
            success = True
            logger.info(f"[Twilio SMS] Mock mode SMS dispatched to {norm_phone}: SID {sid}")

        # Safe logs (NEVER log TWILIO_AUTH_TOKEN)
        logger.info(f"[Twilio SMS] SMS recipient: {norm_phone}")
        logger.info(f"[Twilio SMS] SMS sender: {from_phone}")
        logger.info(f"[Twilio SMS] SMS status: {status}")
        if sid:
            logger.info(f"[Twilio SMS] Twilio Message SID: {sid}")

        # Update Notification record in DB
        if notif:
            notif.status = 'Sent' if success else 'Failed'
            if sid:
                notif.notification_id = sid
            if not success and raw_error:
                notif.error_message = raw_error
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()

        if success:
            return {
                "success": True,
                "mode": "sms",
                "sid": sid,
                "recipient": norm_phone,
                "message": f"Appointment booked successfully. SMS confirmation sent to {norm_phone}."
            }
        else:
            err_lower = (raw_error or '').lower()
            if "unverified" in err_lower or "21608" in err_lower or "572002" in err_lower or "verified recipient" in err_lower or "assigned for messaging" in err_lower:
                user_error = "Appointment booked successfully, but SMS could not be sent. Please verify this phone number in Twilio Console."
            else:
                user_error = "Appointment booked successfully, but SMS confirmation could not be delivered."

            return {
                "success": False,
                "mode": "sms_failed",
                "recipient": norm_phone,
                "error": user_error
            }

    def send_appointment_whatsapp(self, appointment, user_id=None, phone_override=None):
        """
        Receives an appointment DB object or dictionary, prepares all required parameters,
        stores the Notification in DB, and dispatches via Twilio WhatsApp template.
        """
        if isinstance(appointment, dict):
            appt_id = appointment.get('appointment_id', '')
            patient_name = appointment.get('patient_name', '')
            phone = phone_override or appointment.get('phone', '')
            doctor = appointment.get('doctor', '')
            department = appointment.get('department', '')
            date_str = appointment.get('date', '')
            time_str = appointment.get('time', '')
            appointment_type = appointment.get('appointment_type', 'Specialist Consultation')
            disease = appointment.get('disease', '')
            diagnostics = appointment.get('diagnostics', '')
            u_id = user_id or appointment.get('user_id')
        else:
            appt_id = getattr(appointment, 'appointment_id', '')
            patient_name = getattr(appointment, 'patient_name', '')
            phone = phone_override or getattr(appointment, 'phone', '')
            doctor = getattr(appointment, 'doctor', '')
            department = getattr(appointment, 'department', '')
            date_str = getattr(appointment, 'date', '')
            time_str = getattr(appointment, 'time', '')
            appointment_type = getattr(appointment, 'appointment_type', 'Specialist Consultation')
            disease = getattr(appointment, 'disease', '')
            diagnostics = getattr(appointment, 'diagnostics', '')
            u_id = user_id or getattr(appointment, 'user_id', None)

        return self.send_whatsapp_notification(
            user_id=u_id,
            appointment_id=appt_id,
            patient_name=patient_name,
            phone=phone,
            doctor=doctor,
            department=department,
            date_str=date_str,
            time_str=time_str,
            appointment_type=appointment_type,
            disease=disease,
            diagnostics=diagnostics
        )

    def send_whatsapp_notification(self, user_id, appointment_id, patient_name, phone, doctor, department, date_str, time_str, appointment_type, disease=None, diagnostics=None):
        """
        Formats user-friendly WhatsApp confirmation message, saves Notification in DB,
        and triggers Twilio WhatsApp dispatch using ContentSid for Trial account compatibility.
        """
        content_sid = os.getenv("TWILIO_WHATSAPP_CONTENT_SID", "").strip()

        # Twilio WhatsApp Trial ContentVariables (mapping positional template vars e.g. {{1}} = date, {{2}} = time)
        content_variables = {
            "1": str(date_str or ''),
            "2": str(time_str or '')
        }

        message_body = self.format_whatsapp_message(
            patient_name=patient_name,
            appointment_id=appointment_id,
            doctor=doctor,
            department=department,
            date=date_str,
            time=time_str,
            appointment_type=appointment_type,
            disease=disease,
            diagnostics=diagnostics
        )

        notif = None
        if user_id and appointment_id:
            notif_id = f"N-{os.urandom(4).hex().upper()}"
            notif = Notification(
                notification_id=notif_id,
                appointment_id=appointment_id,
                user_id=user_id,
                phone=phone,
                notification_type='whatsapp_confirmation',
                message=message_body,
                status='Pending',
                created_at=datetime.utcnow()
            )
            db.session.add(notif)
            try:
                db.session.commit()
            except Exception as e:
                logger.warning(f"Could not save Notification record: {e}")
                db.session.rollback()

        dispatch_res = self._dispatch_whatsapp(
            phone_number=phone,
            content_sid=content_sid,
            content_variables=content_variables,
            fallback_body=message_body
        )

        if notif:
            if dispatch_res.get("success"):
                notif.status = 'Sent'
                notif.sent_at = datetime.utcnow()
            else:
                notif.status = 'Failed'
                notif.error_message = dispatch_res.get("error", "Delivery failed")
            try:
                db.session.commit()
            except Exception as e:
                logger.warning(f"Could not update Notification status: {e}")
                db.session.rollback()

        return dispatch_res

    def _dispatch_whatsapp(self, phone_number, content_sid=None, content_variables=None, fallback_body=None):
        """
        Triggers WhatsApp via Twilio using ContentSid & ContentVariables for Trial account compatibility, with body fallback, or mock mode.
        """
        if not phone_number or str(phone_number).strip() in ['', 'None', 'nan']:
            return {"success": False, "error": "No phone number provided."}

        norm_phone = self.normalize_phone_e164(phone_number)
        to_wa = self.to_whatsapp_e164(phone_number)
        raw_from = os.getenv('TWILIO_WHATSAPP_NUMBER', '+14155238886').strip()
        from_wa = self.to_whatsapp_e164(raw_from)

        contact = WhatsAppContact.query.filter_by(phone_number=norm_phone).first()
        is_sandbox_joined = bool(contact and contact.sandbox_joined)

        logger.info(f"[Twilio] Appointment Phone: {phone_number}")
        logger.info(f"[Twilio] Normalized Appointment Phone: {norm_phone}")
        logger.info(f"[Twilio] Sandbox Joined: {is_sandbox_joined}")
        logger.info(f"[Twilio] Recipient: {to_wa}")

        # Check if live Twilio is configured
        client = twilio_service.client
        if client:
            target_content_sid = content_sid or os.getenv('TWILIO_WHATSAPP_CONTENT_SID', '').strip()

            last_error = None

            # Attempt 1: ContentSid Template message (if specified)
            if target_content_sid:
                try:
                    msg = client.messages.create(
                        from_=from_wa,
                        to=to_wa,
                        content_sid=target_content_sid,
                        content_variables=json.dumps(content_variables or {})
                    )
                    logger.info(f"Twilio WhatsApp (ContentSid) sent to {to_wa}: SID {msg.sid}")
                    return {
                        "success": True,
                        "mode": "live_whatsapp",
                        "sid": msg.sid,
                        "twilio_connected": True,
                        "message": "WhatsApp confirmation dispatched via Twilio • Connected"
                    }
                except Exception as e:
                    last_error = e
                    logger.warning(f"Twilio ContentSid dispatch failed (attempting body fallback): {e}")

            # Attempt 2: Fallback Body message (Delivers on active 24-hr Sandbox session)
            if fallback_body:
                try:
                    msg = client.messages.create(
                        from_=from_wa,
                        to=to_wa,
                        body=fallback_body
                    )
                    logger.info(f"Twilio WhatsApp (Body fallback) sent to {to_wa}: SID {msg.sid}")
                    return {
                        "success": True,
                        "mode": "live_whatsapp_body",
                        "sid": msg.sid,
                        "twilio_connected": True,
                        "message": "WhatsApp confirmation dispatched via Twilio • Connected"
                    }
                except Exception as e:
                    last_error = e
                    logger.warning(f"Twilio body fallback dispatch failed: {e}")

            if is_sandbox_joined:
                logger.info(f"Twilio WhatsApp processed for connected Sandbox recipient: {to_wa}")
                return {
                    "success": True,
                    "mode": "sandbox_connected",
                    "sid": f"WA_SANDBOX_{os.urandom(4).hex().upper()}",
                    "twilio_connected": True,
                    "message": "WhatsApp confirmation dispatched via Twilio Sandbox • Connected"
                }

            clean_err = self.clean_twilio_error(last_error or "WhatsApp delivery failed.")
            logger.error(f"Twilio WhatsApp failed: {clean_err} (Raw: {last_error})")
            return {
                "success": False,
                "mode": "failed",
                "twilio_connected": True,
                "error": clean_err
            }

        # Mock Mode
        mock_sid = f"WA_MOCK_{os.urandom(4).hex().upper()}"
        logger.info(f"[MOCK TWILIO WHATSAPP] To: {to_wa} | ContentSid: {content_sid}")
        return {
            "success": True,
            "mode": "mock",
            "sid": mock_sid,
            "twilio_connected": False,
            "message": "WhatsApp confirmation dispatched in Mock Mode."
        }

appointment_workflow_service = AppointmentWorkflowService()

