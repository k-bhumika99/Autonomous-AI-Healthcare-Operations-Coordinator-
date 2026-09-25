import os
import json
import logging
from datetime import datetime
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, Response
from dotenv import load_dotenv

load_dotenv()

from services.database import (db, init_db, User, Dataset, Scenario, ScenarioAgentRun, ScenarioAgentEvent,
                                Patient, Appointment, Notification, Bed, LabTest, PharmacyItem,
                                StaffMember, DischargeRecord, ActivityLog, SimulationRun, WhatsAppContact)
from services.dataset_manager import dataset_manager
from services.scenario_manager import scenario_manager
from services.gemini_service import gemini_service
from services.twilio_service import twilio_service
from services.event_manager import event_manager
from services.appointment_workflow import appointment_workflow_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'caresync-secret-key-2026')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///caresync.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
app.config['JSON_AS_ASCII'] = False

@app.after_request
def set_utf8_charset(response):
    if response.mimetype == 'application/json':
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
    elif response.mimetype == 'text/html':
        response.headers['Content-Type'] = 'text/html; charset=utf-8'
    return response

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
init_db(app)

def _start_whatsapp_inbound_sync_worker():
    import threading
    import time
    def _poll():
        # Small startup grace period
        time.sleep(2)
        while True:
            try:
                with app.app_context():
                    appointment_workflow_service.sync_inbound_sandbox_joins(limit=5)
            except Exception as e:
                logger.debug(f"Inbound sync background poll exception: {e}")
            time.sleep(3)

    t = threading.Thread(target=_poll, daemon=True, name="TwilioWhatsAppInboundSync")
    t.start()
    logger.info("Twilio WhatsApp inbound auto-sync daemon started.")

_start_whatsapp_inbound_sync_worker()

@app.template_filter('from_json')
def from_json_filter(val):
    if not val:
        return {}
    try:
        return json.loads(val)
    except Exception:
        return {}

AGENT_SLUG_MAP = {
    'coordinator': 'Coordinator',
    'bed-management': 'Bed Management',
    'bed': 'Bed Management',
    'appointments': 'Appointment',
    'appointment': 'Appointment',
    'labs': 'Lab',
    'lab': 'Lab',
    'pharmacy': 'Pharmacy',
    'staffing': 'Staffing',
    'discharge': 'Discharge'
}


AGENT_NAME_TO_SLUG = {v: k for k, v in AGENT_SLUG_MAP.items()}

# Helper: Current User Context
def get_current_user():
    user_id = session.get('user_id')
    if user_id:
        return db.session.get(User, user_id)
    return None

def login_required(f):
    def decorated_function(*args, **kwargs):
        if not session.get('user_id') or not get_current_user():
            session.clear()
            return redirect(url_for('signin_page'))
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

# ----------------------------------------------------
# PAGE ROUTES
# ----------------------------------------------------
@app.route('/')
def homepage():
    return render_template('index.html')

@app.route('/signin')
def signin_page():
    return render_template('signin.html')

@app.route('/signup')
def signup_page():
    return render_template('signup.html')

@app.route('/dashboard')
@login_required
def dashboard_page():
    user = get_current_user()
    data = dataset_manager.get_user_dashboard_data(user.id)
    active_sc = Scenario.query.filter_by(user_id=user.id).order_by(Scenario.id.desc()).first()
    return render_template(
        'dashboard.html',
        current_user=user,
        data=data,
        active_scenario=active_sc,
        gemini_status=gemini_service.get_status(),
        twilio_status=twilio_service.get_status()
    )

# ----------------------------------------------------
# SCENARIO-FIRST PAGE ROUTES
# ----------------------------------------------------
@app.route('/scenarios/create')
@login_required
def create_scenario_page():
    user = get_current_user()
    active_ds = Dataset.query.filter_by(user_id=user.id, status='LIVE').first()
    active_sc = Scenario.query.filter_by(user_id=user.id).order_by(Scenario.id.desc()).first()
    return render_template('create_scenario.html', current_user=user, active_dataset=active_ds, active_scenario=active_sc)

@app.route('/scenarios')
@login_required
def scenario_history_page():
    user = get_current_user()
    scenarios = Scenario.query.filter_by(user_id=user.id).order_by(Scenario.id.desc()).all()
    active_sc = scenarios[0] if scenarios else None
    return render_template('scenario_history.html', current_user=user, scenarios=scenarios, active_scenario=active_sc)

DEFAULT_AGENT_DESCRIPTIONS = {
    'Coordinator': "Orchestrates multi-agent workflows across all clinical modules, synthesizes operational data, and evaluates overall emergency surge capacity.",
    'Bed Management': "Monitors ward and ICU bed occupancy in real-time, optimizes bed allocation, and reserves available beds for incoming patient surges.",
    'Lab': "Tracks diagnostic testing queues, prioritizes emergency laboratory orders, and optimizes lab technician workload and turnaround times.",
    'Pharmacy': "Monitors medicine inventory levels, detects critical drug shortages, and calculates emergency pharmaceutical demand.",
    'Staffing': "Evaluates doctor and nursing shift coverage, identifies clinical staffing bottlenecks, and coordinates emergency personnel deployment.",
    'Appointment': "Schedules patient consultations, manages appointment capacity, and resolves scheduling conflicts to optimize doctor availability.",
    'Discharge': "Screens admitted patients for discharge eligibility, clears discharge paperwork, and coordinates bed turnover to release capacity."
}

@app.route('/agents')
@login_required
def agents_hub_page():
    user = get_current_user()
    active_sc = Scenario.query.filter_by(user_id=user.id).order_by(Scenario.id.desc()).first()
    dash_data = dataset_manager.get_user_dashboard_data(user.id)

    agent_summaries = {}
    for agent_name, overview in DEFAULT_AGENT_DESCRIPTIONS.items():
        agent_summaries[agent_name] = {
            'action': overview,
            'status': 'Active'
        }

    return render_template(
        'agents_hub.html',
        current_user=user,
        active_scenario=active_sc,
        kpis=dash_data['kpis'],
        agent_summaries=agent_summaries
    )

@app.route('/scenarios/<int:scenario_id>')
@login_required
def scenario_workspace_page(scenario_id):
    user = get_current_user()
    scenario = Scenario.query.filter_by(id=scenario_id, user_id=user.id).first_or_404()
    dataset = Dataset.query.get(scenario.dataset_id) if scenario.dataset_id else None

    execution_plan = json.loads(scenario.execution_plan_json or '[]')
    summary = json.loads(scenario.summary_json or '{}')

    agent_runs = ScenarioAgentRun.query.filter_by(scenario_id=scenario.id).all()
    runs_by_agent = {r.agent_name: r for r in agent_runs}

    dash_data = dataset_manager.get_user_dashboard_data(user.id)
    activities = ActivityLog.query.filter_by(user_id=user.id).order_by(ActivityLog.id.desc()).limit(10).all()

    return render_template(
        'scenario_workspace.html',
        current_user=user,
        scenario=scenario,
        dataset=dataset,
        execution_plan=execution_plan,
        summary=summary,
        runs_by_agent=runs_by_agent,
        agent_slugs=AGENT_NAME_TO_SLUG,
        kpis=dash_data['kpis'],
        activities=activities
    )

DEFAULT_AGENT_INSTRUCTIONS = {
    'Bed Management': "Analyze current bed occupancy and identify available beds, high-pressure wards, ICU capacity and beds that could become available through discharge. Prioritize beds that can support urgent and emergency patients.",
    'Appointment': "Analyze today's appointments, identify emergency and urgent appointments, detect scheduling conflicts and overloaded departments, and identify routine appointments that may require rescheduling.",
    'Lab': "Analyze laboratory workload, identify pending emergency and urgent diagnostic tests, find the most overloaded laboratory, and prioritize tests requiring immediate attention.",
    'Pharmacy': "Analyze current medicine inventory, identify critical and low-stock medicines, calculate shortages, and prioritize medicines needed for emergency and urgent patients.",
    'Staffing': "Analyze staff availability, identify available doctors, nurses, laboratory technicians and other clinical staff, and identify departments requiring additional support.",
    'Discharge': "Identify discharge-ready patients, group them by department, and determine how many beds could potentially be released to increase hospital capacity.",
    'Coordinator': "Analyze the current hospital situation and determine which departments and specialized agents require immediate attention. Prioritize emergency capacity, diagnostics, pharmacy, staffing, appointments and discharge based on actual database data."
}

@app.route('/scenarios/<int:scenario_id>/agents/<agent_slug>')
@login_required
def scenario_agent_page(scenario_id, agent_slug):
    user = get_current_user()
    scenario = Scenario.query.filter_by(id=scenario_id, user_id=user.id).first_or_404()
    agent_name = AGENT_SLUG_MAP.get(agent_slug, 'Coordinator')

    run_rec = ScenarioAgentRun.query.filter_by(scenario_id=scenario.id, agent_name=agent_name).first()
    active_ds = Dataset.query.filter_by(user_id=user.id, status='LIVE').first()

    # Load summary for coordinator instruction
    summary = json.loads(scenario.summary_json or '{}')
    agent_instructions = summary.get('agent_instructions', {})
    coordinator_instruction = agent_instructions.get(agent_name, '')
    default_instruction = DEFAULT_AGENT_INSTRUCTIONS.get(agent_name, '')

    return render_template(
        'scenario_agent.html',
        current_user=user,
        scenario=scenario,
        agent_name=agent_name,
        agent_slug=agent_slug,
        run_rec=run_rec,
        coordinator_instruction=coordinator_instruction,
        default_instruction=default_instruction,
        has_active_dataset=bool(active_ds),
        twilio_status=twilio_service.get_status()
    )


# ----------------------------------------------------
# MODULE OPERATIONAL PAGES
# ----------------------------------------------------
@app.route('/data')
@login_required
def upload_page():
    user = get_current_user()
    active_ds = Dataset.query.filter_by(user_id=user.id, status='LIVE').first()
    categories = json.loads(active_ds.categories_json or '[]') if active_ds else []
    table_counts = dataset_manager._get_table_counts(user.id) if active_ds else {}
    return render_template('upload.html', current_user=user, active_dataset=active_ds, categories=categories, table_counts=table_counts)

@app.route('/patients')
@login_required
def patients_page():
    user = get_current_user()
    patients = Patient.query.filter_by(user_id=user.id).all()
    return render_template('patients.html', current_user=user, patients=patients)

@app.route('/appointments')
@login_required
def appointments_page():
    user = get_current_user()
    appts = Appointment.query.filter_by(user_id=user.id).order_by(Appointment.id.desc()).all()
    # Load notifications keyed by appointment_id
    notifications = Notification.query.filter_by(user_id=user.id).all()
    notif_map = {}
    for n in notifications:
        # Keep latest notification per appointment
        if n.appointment_id not in notif_map:
            notif_map[n.appointment_id] = n
        else:
            if n.id > notif_map[n.appointment_id].id:
                notif_map[n.appointment_id] = n
    return render_template('appointments.html', current_user=user, appointments=appts, notif_map=notif_map, twilio_status=twilio_service.get_status())

@app.route('/beds')
@login_required
def beds_page():
    user = get_current_user()
    beds = Bed.query.filter_by(user_id=user.id).all()
    return render_template('beds.html', current_user=user, beds=beds)

@app.route('/labs')
@login_required
def labs_page():
    user = get_current_user()
    labs = LabTest.query.filter_by(user_id=user.id).all()
    return render_template('labs.html', current_user=user, labs=labs)

@app.route('/pharmacy')
@login_required
def pharmacy_page():
    user = get_current_user()
    pharm = PharmacyItem.query.filter_by(user_id=user.id).all()
    return render_template('pharmacy.html', current_user=user, pharmacy=pharm)

@app.route('/staffing')
@login_required
def staffing_page():
    user = get_current_user()
    staff = StaffMember.query.filter_by(user_id=user.id).all()
    return render_template('staffing.html', current_user=user, staff=staff)

@app.route('/discharge')
@login_required
def discharge_page():
    user = get_current_user()
    discharges = DischargeRecord.query.filter_by(user_id=user.id).all()
    return render_template('discharge.html', current_user=user, discharges=discharges)

@app.route('/reports')
@login_required
def reports_page():
    user = get_current_user()
    dash_data = dataset_manager.get_user_dashboard_data(user.id)
    return render_template('reports.html', current_user=user, has_data=dash_data['has_data'], kpis=dash_data['kpis'])

# ----------------------------------------------------
# AUTHENTICATION APIS
# ----------------------------------------------------
@app.route('/api/auth/signup', methods=['POST'])
def api_signup():
    data = request.json or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '').strip()
    full_name = data.get('full_name', '').strip()

    if not email or not password or not full_name:
        return jsonify({"success": False, "message": "All fields are required."}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"success": False, "message": "An account with this email already exists."}), 400

    new_user = User(email=email, full_name=full_name)
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()

    session['user_id'] = new_user.id
    return jsonify({"success": True, "message": "Account created successfully."})

@app.route('/api/auth/signin', methods=['POST'])
def api_signin():
    data = request.json or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '').strip()

    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        return jsonify({"success": False, "message": "Invalid email or password."}), 401

    session['user_id'] = user.id
    return jsonify({"success": True, "message": "Signed in successfully."})

@app.route('/api/auth/logout')
def api_logout():
    session.clear()
    return redirect(url_for('signin_page'))

# ----------------------------------------------------
# APPOINTMENT APIS
# ----------------------------------------------------
@app.route('/api/appointments/analyze-condition', methods=['POST'])
@login_required
def api_appointments_analyze_condition():
    """
    Analyzes disease/medical condition and optional symptoms to suggest
    recommended department and diagnostic requirements.
    """
    try:
        data = request.json or {}
        disease = data.get('disease', '').strip()
        symptoms = data.get('symptoms', '').strip()
        logger.info(f"[Appointment Workflow] analyze-condition | Disease: '{disease}' | Symptoms: '{symptoms}'")

        analysis = appointment_workflow_service.analyze_condition(disease, symptoms)
        return jsonify({
            "success": True,
            "analysis": analysis
        })
    except Exception as e:
        logger.exception("[Appointment Workflow] Error in analyze-condition:")
        return jsonify({
            "success": False,
            "message": "AI recommendation service is temporarily unavailable."
        }), 500

@app.route('/api/appointments/available-doctors', methods=['GET'])
@login_required
def api_appointments_available_doctors():
    """
    Queries doctors belonging to the selected department from the hospital dataset/DB.
    Evaluates date/time availability if provided.
    """
    try:
        user = get_current_user()
        department = request.args.get('department', '').strip()
        date_str = request.args.get('date', '').strip()
        time_str = request.args.get('time', '').strip()
        logger.info(f"[Appointment Workflow] available-doctors | Dept: '{department}' | Date: '{date_str}' | Time: '{time_str}'")

        result = appointment_workflow_service.get_available_doctors(
            user_id=user.id,
            department=department,
            date_str=date_str,
            time_str=time_str
        )
        return jsonify(result)
    except Exception as e:
        logger.exception("[Appointment Workflow] Error in available-doctors:")
        return jsonify({
            "success": False,
            "message": "Hospital database could not be accessed."
        }), 500

@app.route('/api/appointments/available-slots', methods=['GET'])
@login_required
def api_appointments_available_slots():
    """
    Returns available time slots for a specific doctor on a given date,
    preventing double booking by checking existing appointments.
    """
    try:
        user = get_current_user()
        doctor = request.args.get('doctor', '').strip()
        date_str = request.args.get('date', '').strip()
        logger.info(f"[Appointment Workflow] available-slots | Doctor: '{doctor}' | Date: '{date_str}'")
        slots = appointment_workflow_service.get_available_slots(user.id, doctor, date_str)
        return jsonify(slots)
    except Exception as e:
        logger.exception("[Appointment Workflow] Error in available-slots:")
        return jsonify({
            "success": False,
            "message": "Hospital database could not be accessed."
        }), 500

@app.route('/api/appointments/doctor-schedule', methods=['GET'])
@login_required
def api_appointments_doctor_schedule():
    """
    Returns upcoming 7-day recommended availability schedule for a doctor.
    """
    try:
        user = get_current_user()
        doctor = request.args.get('doctor', '').strip()
        logger.info(f"[Appointment Workflow] doctor-schedule | Doctor: '{doctor}'")
        result = appointment_workflow_service.get_doctor_schedule_recommendations(user.id, doctor)
        return jsonify(result)
    except Exception as e:
        logger.exception("[Appointment Workflow] Error in doctor-schedule:")
        return jsonify({
            "success": False,
            "message": "Hospital database could not be accessed."
        }), 500

@app.route('/api/appointments/create', methods=['POST'])
@login_required
def api_appointment_create():
    """
    Creates a new hospital appointment with full clinical workflow validation.
    1. Validates required fields (Patient Name, Phone, Age, Gender, Disease, Department, Doctor, Date, Time, Type).
    2. Prevents double-booking.
    3. Saves record into DB with status='Confirmed', source='USER BOOKED'.
    4. Triggers Twilio WhatsApp confirmation AFTER DB commit.
    """
    try:
        user = get_current_user()
        data = request.json or {}

        patient_name = data.get('patient_name', '').strip()
        phone = data.get('phone', '').strip()
        age = data.get('age', '')
        gender = data.get('gender', '').strip()
        disease = data.get('disease', '').strip()
        symptoms = data.get('symptoms', '').strip()
        severity = data.get('severity', 'Routine').strip()
        diagnostics = data.get('diagnostics', [])
        if isinstance(diagnostics, list):
            diagnostics_str = ", ".join([str(d).strip() for d in diagnostics if d])
        else:
            diagnostics_str = str(diagnostics).strip()

        department = data.get('department', '').strip()
        doctor = data.get('doctor', '').strip()
        date_str = data.get('date', '').strip()
        time_str = data.get('time', '').strip()
        appointment_type = data.get('appointment_type', 'New Consultation').strip()
        medical_history = data.get('medical_history', '').strip()
        medications = data.get('medications', '').strip()
        allergies = data.get('allergies', '').strip()
        notes = data.get('notes', '').strip()

        logger.info(f"[Appointment Workflow] create | Patient: '{patient_name}' | Doctor: '{doctor}' | Dept: '{department}' | Date: '{date_str} {time_str}'")

        # Required fields validation
        if not patient_name:
            return jsonify({"success": False, "message": "Patient Full Name is required."}), 400
        if not phone:
            return jsonify({"success": False, "message": "Phone Number is required for WhatsApp confirmation."}), 400
        if not age:
            return jsonify({"success": False, "message": "Age is required."}), 400
        if not gender:
            return jsonify({"success": False, "message": "Gender is required."}), 400
        if not disease:
            return jsonify({"success": False, "message": "Disease / Medical Condition is required."}), 400
        if not department:
            return jsonify({"success": False, "message": "Department is required."}), 400
        if not doctor:
            return jsonify({"success": False, "message": "Doctor selection is required."}), 400
        if not date_str or not time_str:
            return jsonify({"success": False, "message": "Appointment Date and Time are required."}), 400
        if not appointment_type:
            return jsonify({"success": False, "message": "Appointment Type is required."}), 400

        # Step 1: Prevent double-booking (Same doctor, same date, same time slot)
        norm_target_date = appointment_workflow_service.normalize_date_str(date_str)
        all_appts = Appointment.query.filter_by(user_id=user.id).all()
        existing_conflict = None
        for a in all_appts:
            if a.doctor and a.doctor.strip().lower() == doctor.strip().lower():
                if a.status and a.status.strip().lower() != 'cancelled':
                    if appointment_workflow_service.normalize_date_str(a.date) == norm_target_date:
                        if (a.time and a.time.strip() == time_str.strip()) or (a.rescheduled_time and a.rescheduled_time.strip() == time_str.strip()):
                            existing_conflict = a
                            break

        if existing_conflict:
            return jsonify({
                "success": False,
                "message": "This time slot was just booked. Please select another available time."
            }), 400

        # Step 2: Find or create patient record
        existing_patient = Patient.query.filter_by(user_id=user.id, name=patient_name).first()
        if existing_patient:
            patient_id = existing_patient.patient_id
            if phone:
                existing_patient.phone = phone
        else:
            patient_id = dataset_manager.generate_next_patient_id(user.id)
            try:
                age_int = int(age)
            except (ValueError, TypeError):
                age_int = None

            new_patient = Patient(
                user_id=user.id,
                patient_id=patient_id,
                name=patient_name,
                age=age_int,
                gender=gender,
                department=department,
                emergency=(severity == 'Emergency'),
                severity=severity,
                status='Outpatient',
                phone=phone,
                source='user_created',
                created_at=datetime.utcnow()
            )
            db.session.add(new_patient)
            db.session.flush()

        # Step 3: Generate unique Appointment ID
        appointment_id = dataset_manager.generate_next_appointment_id(user.id)

        # Step 4: Save Appointment into DB with status='Confirmed', source='USER BOOKED'
        new_appt = Appointment(
            user_id=user.id,
            appointment_id=appointment_id,
            patient_id=patient_id,
            patient_name=patient_name,
            doctor=doctor,
            department=department,
            date=date_str,
            time=time_str,
            original_time=time_str,
            priority=severity if severity else 'Routine',
            status='Confirmed',
            phone=phone,
            source='USER BOOKED',
            age=int(age) if str(age).isdigit() else None,
            gender=gender,
            disease=disease,
            symptoms=symptoms,
            severity=severity,
            diagnostics=diagnostics_str,
            appointment_type=appointment_type,
            medical_history=medical_history,
            medications=medications,
            allergies=allergies,
            notes=notes,
            created_at=datetime.utcnow()
        )
        db.session.add(new_appt)

        # Log action in ActivityLog before WhatsApp commit
        act = ActivityLog(
            user_id=user.id,
            agent_name="Appointment Agent",
            action=f"Appointment {appointment_id} booked for {patient_name} with {doctor} ({department}).",
            details=f"Condition: {disease} | Date: {date_str} {time_str} | Source: USER BOOKED",
            category="success"
        )
        db.session.add(act)

        # Commit appointment booking FIRST
        db.session.commit()

        # Step 5: Trigger Twilio WhatsApp & SMS notifications AFTER database commit (guaranteed no rollback)
        whatsapp_result = {"success": False, "error": "WhatsApp notification failed."}
        try:
            whatsapp_result = appointment_workflow_service.send_appointment_whatsapp(
                appointment=new_appt,
                user_id=user.id
            )
        except Exception as wa_err:
            clean_err = appointment_workflow_service.clean_twilio_error(wa_err)
            logger.error(f"[Appointment Workflow] WhatsApp dispatch error: {clean_err}")
            whatsapp_result = {
                "success": False,
                "mode": "failed",
                "error": clean_err
            }

        return jsonify({
            "success": True,
            "appointment_id": appointment_id,
            "patient_id": patient_id,
            "status": "Confirmed",
            "appointment": {
                "appointment_id": appointment_id,
                "patient_name": patient_name,
                "doctor": doctor,
                "department": department,
                "date": date_str,
                "time": time_str,
                "priority": severity,
                "status": "Confirmed",
                "source": "USER BOOKED",
                "phone": phone,
                "disease": disease,
                "appointment_type": appointment_type,
                "diagnostics": diagnostics_str
            },
            "whatsapp": whatsapp_result,
            "twilio_status": twilio_service.get_status(),
            "message": f"Appointment {appointment_id} booked successfully."
        })
    except Exception as e:
        logger.exception("[Appointment Workflow] Error in api_appointment_create:")
        db.session.rollback()
        return jsonify({
            "success": False,
            "message": "Hospital appointment service encountered an internal error."
        }), 500

@app.route('/api/appointments/resend-sms/<appointment_id>', methods=['POST'])
@app.route('/api/appointments/resend-whatsapp/<appointment_id>', methods=['POST'])
@login_required
def api_appointments_resend_sms(appointment_id):
    """
    Resends SMS notification for an existing confirmed appointment.
    Retries ONLY the SMS notification for existing appointment ID.
    Never creates another appointment in DB.
    """
    try:
        user = get_current_user()
        appt = Appointment.query.filter_by(user_id=user.id, appointment_id=appointment_id).first()
        if not appt:
            return jsonify({"success": False, "message": "Appointment not found."}), 404

        phone = request.json.get('phone', '').strip() if request.json else ''
        if not phone:
            phone = appt.phone or ''

        if not phone:
            return jsonify({"success": False, "message": "Phone number is required to send SMS notification."}), 400

        logger.info(f"[Appointment Workflow] resend-sms | ApptID: {appointment_id} | Phone: {phone}")

        is_whatsapp = 'whatsapp' in request.path
        try:
            if is_whatsapp:
                dispatch_result = appointment_workflow_service.send_appointment_whatsapp(
                    appointment=appt,
                    user_id=user.id,
                    phone_override=phone
                )
            else:
                dispatch_result = appointment_workflow_service.send_appointment_sms(
                    appointment=appt,
                    user_id=user.id,
                    phone_override=phone
                )
        except Exception as dispatch_err:
            logger.error(f"[Appointment Workflow] Resend dispatch error: {dispatch_err}")
            dispatch_result = {
                "success": False,
                "mode": "failed",
                "error": "Notification could not be delivered."
            }

        return jsonify({
            "success": dispatch_result.get("success", False),
            "appointment_id": appointment_id,
            "sms": dispatch_result,
            "whatsapp": dispatch_result,
            "twilio_status": twilio_service.get_status(),
            "message": dispatch_result.get("message") or dispatch_result.get("error", "Dispatch attempted.")
        })
    except Exception as e:
        logger.exception(f"[Appointment Workflow] Error resending SMS for {appointment_id}:")
        return jsonify({"success": False, "message": "Failed to resend SMS notification."}), 500

@app.route('/api/appointments/graph-data', methods=['GET'])
@login_required
def api_appointment_graph_data():
    """Returns live DB appointment status counts for graph rendering."""
    user = get_current_user()
    from sqlalchemy import func
    results = db.session.query(
        Appointment.status, func.count(Appointment.id)
    ).filter_by(user_id=user.id).group_by(Appointment.status).all()

    status_counts = {row[0]: row[1] for row in results}
    labels = list(status_counts.keys())
    values = list(status_counts.values())
    total = Appointment.query.filter_by(user_id=user.id).count()

    return jsonify({
        "success": True,
        "labels": labels,
        "values": values,
        "total": total
    })

@app.route('/api/notifications/<appointment_id>', methods=['GET'])
@login_required
def api_get_notification(appointment_id):
    """Get notification status for an appointment."""
    user = get_current_user()
    notif = Notification.query.filter_by(
        user_id=user.id,
        appointment_id=appointment_id
    ).order_by(Notification.id.desc()).first()
    if notif:
        return jsonify({
            "success": True,
            "status": notif.status,
            "notification_id": notif.notification_id,
            "sent_at": notif.sent_at.isoformat() if notif.sent_at else None
        })
@app.route('/api/twilio/whatsapp/incoming', methods=['GET', 'POST'])
@app.route('/api/whatsapp/webhook', methods=['GET', 'POST'])
@app.route('/whatsapp/webhook', methods=['GET', 'POST'])
def api_whatsapp_webhook():
    """
    Twilio WhatsApp Incoming Webhook endpoint.
    Triggered when patient scans QR code and sends 'join ...' to Twilio Sandbox.
    Registers the specific joining WhatsApp number and replies with the Welcome message.
    """
    from_number = request.form.get('From') or request.values.get('From', '')
    body = request.form.get('Body') or request.values.get('Body', '')
    profile_name = request.values.get('ProfileName', '')

    norm_from = appointment_workflow_service.normalize_phone_e164(from_number)

    logger.info(f"[Twilio] Incoming From: {from_number}")
    logger.info(f"[Twilio] Incoming Body: {body}")
    logger.info(f"[Twilio] Normalized From: {norm_from}")

    if from_number:
        # Register per-phone Sandbox join and trigger welcome dispatch for THAT SPECIFIC NUMBER
        reg_res = appointment_workflow_service.register_whatsapp_join(from_number)
        logger.info(f"[WhatsApp Webhook] Registered Sandbox join for {from_number}: {reg_res}")

    welcome_text = (
        "👋 Welcome to CareSync AI!\n\n"
        "Your WhatsApp is now connected successfully. 💙\n\n"
        "You can now book your hospital appointment through CareSync AI.\n\n"
        "After booking, your appointment confirmation will be sent to this WhatsApp number.\n\n"
        "Thank you for choosing CareSync AI! 🏥"
    )

    twiml_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>{welcome_text}</Message>
</Response>"""

    return Response(twiml_xml, mimetype='application/xml')

@app.route('/api/whatsapp/latest-joined', methods=['GET'])
def api_whatsapp_latest_joined():
    """
    Returns the most recently joined WhatsApp Contact from the database.
    Used by frontend to auto-populate phone input when patient scans QR code.
    Automatically syncs recent inbound WhatsApp messages from Twilio so localhost gets new joins instantly!
    """
    try:
        force_sync = request.args.get('force', 'false').lower() == 'true'
        appointment_workflow_service.sync_inbound_sandbox_joins(limit=5, force=force_sync)
    except Exception as e:
        logger.warning(f"Error during inbound sandbox sync: {e}")

    latest_contact = WhatsAppContact.query.filter_by(sandbox_joined=True).order_by(WhatsAppContact.joined_at.desc()).first()
    if latest_contact:
        return jsonify({
            "success": True,
            "has_joined": True,
            "phone_number": latest_contact.phone_number,
            "whatsapp_number": latest_contact.whatsapp_number,
            "welcome_status": latest_contact.welcome_message_status or "Sent",
            "joined_at": latest_contact.joined_at.isoformat() if latest_contact.joined_at else None
        })
    return jsonify({
        "success": True,
        "has_joined": False,
        "phone_number": None
    })

@app.route('/api/whatsapp/check-status', methods=['GET'])
@app.route('/api/twilio/whatsapp/check-status', methods=['GET'])
def api_whatsapp_check_status():
    """
    Returns WhatsApp Sandbox connection status for a specific phone number.
    """
    phone = request.args.get('phone', '').strip()
    status_res = appointment_workflow_service.check_sandbox_status(phone)
    return jsonify(status_res)

@app.route('/api/whatsapp/register-join', methods=['GET', 'POST'])
@app.route('/api/twilio/whatsapp/register-join', methods=['GET', 'POST'])
def api_whatsapp_register_join():
    """
    Registers a phone number as joined to Twilio Sandbox and dispatches Welcome Message to THAT SPECIFIC NUMBER.
    Accepts phone parameter via JSON or query string.
    """
    if request.is_json:
        phone = (request.json or {}).get('phone', '').strip()
    else:
        phone = request.values.get('phone', '').strip()

    if not phone:
        return jsonify({"success": False, "message": "Please enter a valid WhatsApp phone number."}), 400

    user = get_current_user()
    user_id = user.id if user else None

    reg_res = appointment_workflow_service.register_whatsapp_join(phone, user_id=user_id)
    return jsonify(reg_res)

# ----------------------------------------------------
# SCENARIO APIS
# ----------------------------------------------------
@app.route('/api/scenarios/create', methods=['POST'])
@login_required
def api_scenario_create():
    user = get_current_user()

    if request.is_json:
        scenario_data = request.json or {}
        file_obj = None
    else:
        scenario_data = request.form.to_dict()
        file_obj = request.files.get('file')

    filepath, filename, file_type = None, None, None
    if file_obj and file_obj.filename != '':
        filename = file_obj.filename
        file_type = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], f"user_{user.id}_{filename}")
        file_obj.save(filepath)

    try:
        scenario = scenario_manager.create_and_analyze_scenario(user.id, scenario_data, filepath, filename, file_type)
        if request.is_json:
            return jsonify({"success": True, "scenario_id": scenario.id})
        return redirect(url_for('scenario_workspace_page', scenario_id=scenario.id))
    except Exception as e:
        logger.error(f"Scenario creation error: {e}")
        if request.is_json:
            return jsonify({"success": False, "message": str(e)}), 400
        active_ds = Dataset.query.filter_by(user_id=user.id, status='LIVE').first()
        active_sc = Scenario.query.filter_by(user_id=user.id).order_by(Scenario.id.desc()).first()
        return render_template('create_scenario.html', current_user=user, active_dataset=active_ds, active_scenario=active_sc, error_message=str(e)), 400

@app.route('/api/scenarios/<int:scenario_id>/run', methods=['POST'])
@login_required
def api_scenario_run(scenario_id):
    user = get_current_user()
    try:
        scenario = scenario_manager.run_scenario(scenario_id, user.id)
        return jsonify({"success": True, "scenario_id": scenario.id, "status": scenario.status})
    except Exception as e:
        logger.error(f"Scenario run error: {e}")
        return jsonify({"success": False, "message": str(e)}), 400

@app.route('/api/scenarios/<int:scenario_id>', methods=['DELETE'])
@login_required
def api_scenario_delete(scenario_id):
    user = get_current_user()
    scenario = Scenario.query.filter_by(id=scenario_id, user_id=user.id).first()
    if not scenario:
        return jsonify({"success": False, "message": "Scenario not found."}), 404
    try:
        ScenarioAgentRun.query.filter_by(scenario_id=scenario.id).delete()
        ScenarioAgentEvent.query.filter_by(scenario_id=scenario.id).delete()
        db.session.delete(scenario)
        db.session.commit()
        return jsonify({"success": True, "message": f"Scenario '{scenario.name}' deleted successfully."})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting scenario {scenario_id}: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/scenarios/<int:scenario_id>/agents/<agent_slug>/run', methods=['POST'])
@login_required
def api_scenario_single_agent_run(scenario_id, agent_slug):
    user = get_current_user()
    data = request.json or {}
    instruction = data.get('instruction')
    agent_name = AGENT_SLUG_MAP.get(agent_slug, 'Coordinator')

    try:
        res = scenario_manager.run_agent_by_name(agent_name, scenario_id, user.id, instruction)
        return jsonify({"success": True, "agent_name": agent_name, "results": res})
    except Exception as e:
        logger.error(f"Single agent execution error: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/scenarios/<int:scenario_id>/data', methods=['GET'])
@login_required
def api_scenario_data(scenario_id):
    user = get_current_user()
    scenario = Scenario.query.filter_by(id=scenario_id, user_id=user.id).first_or_404()
    agent_runs = ScenarioAgentRun.query.filter_by(scenario_id=scenario.id).all()
    
    runs_data = {}
    for r in agent_runs:
        runs_data[r.agent_name] = {
            "status": r.status,
            "result": json.loads(r.result_json or '{}'),
            "executed_at": r.executed_at.isoformat() if r.executed_at else None
        }
        
    db_metrics = scenario_manager.get_live_db_metrics(user.id)
    
    return jsonify({
        "success": True,
        "scenario": {
            "id": scenario.id,
            "name": scenario.name,
            "scenario_type": scenario.scenario_type,
            "priority": scenario.priority,
            "status": scenario.status,
            "user_instruction": scenario.user_instruction,
            "created_at": scenario.created_at.isoformat() if scenario.created_at else None
        },
        "summary": json.loads(scenario.summary_json or '{}'),
        "execution_plan": json.loads(scenario.execution_plan_json or '[]'),
        "agent_runs": runs_data,
        "db_metrics": db_metrics
    })

@app.route('/api/scenarios/<int:scenario_id>/agents/<agent_slug>/results', methods=['GET'])
@login_required
def api_scenario_agent_results(scenario_id, agent_slug):
    user = get_current_user()
    scenario = Scenario.query.filter_by(id=scenario_id, user_id=user.id).first_or_404()
    agent_name = AGENT_SLUG_MAP.get(agent_slug, 'Coordinator')
    
    run_rec = ScenarioAgentRun.query.filter_by(scenario_id=scenario.id, agent_name=agent_name).first()
    if not run_rec:
        return jsonify({"success": False, "message": "Agent has not been executed yet for this scenario."}), 404
        
    return jsonify({
        "success": True,
        "agent_name": agent_name,
        "status": run_rec.status,
        "executed_at": run_rec.executed_at.isoformat() if run_rec.executed_at else None,
        "result": json.loads(run_rec.results_json or '{}')
    })

# ----------------------------------------------------
# DATASET & GLOBAL SIMULATION APIS
# ----------------------------------------------------
@app.route('/api/dataset/upload', methods=['POST'])
@login_required
def api_dataset_upload():
    user = get_current_user()
    if 'file' not in request.files:
        return jsonify({"success": False, "message": "No file uploaded."}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"success": False, "message": "No selected file."}), 400

    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    save_path = os.path.join(app.config['UPLOAD_FOLDER'], f"user_{user.id}_{file.filename}")
    file.save(save_path)

    try:
        res = dataset_manager.process_and_ingest(user.id, save_path, file.filename, ext)
        return jsonify(res)
    except Exception as e:
        logger.error(f"Dataset ingestion error: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/dataset/status', methods=['GET'])
@login_required
def api_dataset_status():
    user = get_current_user()
    data = dataset_manager.get_user_dashboard_data(user.id)
    return jsonify({"success": True, "data": data})

@app.route('/api/dataset/remove', methods=['POST'])
@login_required
def api_dataset_remove():
    user = get_current_user()
    try:
        dataset_manager.remove_user_dataset(user.id)
        return jsonify({"success": True, "message": "Active dataset and operational records removed successfully."})
    except Exception as e:
        logger.error(f"Dataset removal error: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/gemini/health', methods=['GET'])
@login_required
def api_gemini_health():
    res = gemini_service.test_gemini_connection()
    return jsonify(res)

@app.route('/api/dataset/table-counts', methods=['GET'])
@login_required
def api_dataset_table_counts():
    """Returns per-table live DB counts for Dataset Management page."""
    user = get_current_user()
    counts = dataset_manager._get_table_counts(user.id)
    return jsonify({"success": True, "counts": counts})

@app.route('/api/agent-events')
@login_required
def api_agent_events():
    def event_stream():
        q = event_manager.subscribe()
        try:
            while True:
                data = q.get()
                yield f"data: {json.dumps(data)}\n\n"
        except GeneratorExit:
            event_manager.unsubscribe(q)

    return Response(event_stream(), mimetype="text/event-stream")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
