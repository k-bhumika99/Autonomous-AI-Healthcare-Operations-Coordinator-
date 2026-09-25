import os
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class BaseModel(db.Model):
    __abstract__ = True

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

class User(BaseModel):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(50), default='Hospital Administrator')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Dataset(BaseModel):
    __tablename__ = 'datasets'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    file_type = db.Column(db.String(50), nullable=False)
    upload_time = db.Column(db.DateTime, default=datetime.utcnow)
    row_count = db.Column(db.Integer, default=0)
    column_count = db.Column(db.Integer, default=0)
    status = db.Column(db.String(50), default='LIVE')
    categories_json = db.Column(db.Text, default='{}')

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

class Scenario(BaseModel):
    __tablename__ = 'scenarios'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    user_instruction = db.Column(db.Text, nullable=True)
    scenario_type = db.Column(db.String(100), default='Emergency Surge')
    priority = db.Column(db.String(50), default='Critical')
    department = db.Column(db.String(100), default='All Departments')
    date = db.Column(db.String(50), default='Today')
    dataset_id = db.Column(db.Integer, db.ForeignKey('datasets.id'), nullable=True)
    status = db.Column(db.String(50), default='DRAFT')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    execution_plan_json = db.Column(db.Text, default='[]')
    summary_json = db.Column(db.Text, default='{}')

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

class ScenarioAgentRun(BaseModel):
    __tablename__ = 'scenario_agent_runs'
    id = db.Column(db.Integer, primary_key=True)
    scenario_id = db.Column(db.Integer, db.ForeignKey('scenarios.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    agent_name = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(50), default='Waiting')
    user_instruction = db.Column(db.Text, nullable=True)
    records_analyzed = db.Column(db.Integer, default=0)
    actions_taken = db.Column(db.Integer, default=0)
    results_json = db.Column(db.Text, default='{}')
    executed_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

class ScenarioAgentEvent(BaseModel):
    __tablename__ = 'scenario_agent_events'
    id = db.Column(db.Integer, primary_key=True)
    scenario_id = db.Column(db.Integer, db.ForeignKey('scenarios.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    agent_name = db.Column(db.String(100), nullable=False)
    event_type = db.Column(db.String(100), nullable=False)
    payload_json = db.Column(db.Text, default='{}')
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

class Patient(BaseModel):
    __tablename__ = 'patients'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    patient_id = db.Column(db.String(100), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    age = db.Column(db.Integer, nullable=True)
    gender = db.Column(db.String(20), nullable=True)
    department = db.Column(db.String(100), nullable=True)
    emergency = db.Column(db.Boolean, default=False)
    severity = db.Column(db.String(50), default='Routine')
    status = db.Column(db.String(50), default='Admitted')
    bed_id = db.Column(db.String(100), nullable=True)
    phone = db.Column(db.String(50), nullable=True)
    source = db.Column(db.String(50), default='dataset')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

class Appointment(BaseModel):
    __tablename__ = 'appointments'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    appointment_id = db.Column(db.String(100), nullable=False)
    patient_id = db.Column(db.String(100), nullable=True)
    patient_name = db.Column(db.String(150), nullable=True)
    doctor = db.Column(db.String(100), nullable=True)
    department = db.Column(db.String(100), nullable=True)
    date = db.Column(db.String(50), nullable=True)
    time = db.Column(db.String(50), nullable=True)
    original_time = db.Column(db.String(50), nullable=True)
    rescheduled_time = db.Column(db.String(50), nullable=True)
    priority = db.Column(db.String(50), default='Routine')
    status = db.Column(db.String(50), default='Scheduled')
    phone = db.Column(db.String(50), nullable=True)
    source = db.Column(db.String(50), default='dataset')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Extended Realistic Appointment Fields
    age = db.Column(db.Integer, nullable=True)
    gender = db.Column(db.String(20), nullable=True)
    disease = db.Column(db.String(150), nullable=True)
    symptoms = db.Column(db.Text, nullable=True)
    severity = db.Column(db.String(50), default='Routine')
    diagnostics = db.Column(db.Text, nullable=True)
    appointment_type = db.Column(db.String(100), default='Specialist Consultation')
    medical_history = db.Column(db.Text, nullable=True)
    medications = db.Column(db.Text, nullable=True)
    allergies = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

class Notification(BaseModel):
    __tablename__ = 'notifications'
    id = db.Column(db.Integer, primary_key=True)
    notification_id = db.Column(db.String(100), nullable=False)
    appointment_id = db.Column(db.String(100), nullable=False)
    patient_id = db.Column(db.String(100), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    phone = db.Column(db.String(50), nullable=True)
    notification_type = db.Column(db.String(100), default='appointment_confirmation')
    message = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(50), default='Pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    sent_at = db.Column(db.DateTime, nullable=True)
    error_message = db.Column(db.Text, nullable=True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

class Bed(BaseModel):
    __tablename__ = 'beds'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    bed_id = db.Column(db.String(100), nullable=False)
    ward = db.Column(db.String(100), nullable=True)
    type = db.Column(db.String(50), default='General')
    status = db.Column(db.String(50), default='Available')
    patient_id = db.Column(db.String(100), nullable=True)
    source = db.Column(db.String(50), default='dataset')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

class LabTest(BaseModel):
    __tablename__ = 'lab_tests'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    test_id = db.Column(db.String(100), nullable=False)
    patient_id = db.Column(db.String(100), nullable=True)
    patient_name = db.Column(db.String(150), nullable=True)
    test_name = db.Column(db.String(150), nullable=True)
    lab = db.Column(db.String(100), nullable=True)
    priority = db.Column(db.String(50), default='Normal')
    status = db.Column(db.String(50), default='Pending')
    turnaround = db.Column(db.String(50), nullable=True)
    source = db.Column(db.String(50), default='dataset')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

class PharmacyItem(BaseModel):
    __tablename__ = 'pharmacy_inventory'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    medicine_id = db.Column(db.String(100), nullable=False)
    medicine_name = db.Column(db.String(150), nullable=False)
    required_quantity = db.Column(db.Integer, default=0)
    available_quantity = db.Column(db.Integer, default=0)
    status = db.Column(db.String(50), default='In Stock')
    source = db.Column(db.String(50), default='dataset')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

class StaffMember(BaseModel):
    __tablename__ = 'staff'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    staff_id = db.Column(db.String(100), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    role = db.Column(db.String(100), nullable=True)
    department = db.Column(db.String(100), nullable=True)
    availability = db.Column(db.String(50), default='Available')
    workload = db.Column(db.String(50), default='Normal')
    source = db.Column(db.String(50), default='dataset')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

class DischargeRecord(BaseModel):
    __tablename__ = 'discharges'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    discharge_id = db.Column(db.String(100), nullable=False)
    patient_id = db.Column(db.String(100), nullable=False)
    patient_name = db.Column(db.String(150), nullable=True)
    department = db.Column(db.String(100), nullable=True)
    discharge_ready = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(50), default='Pending Clearance')
    bed_id = db.Column(db.String(100), nullable=True)
    source = db.Column(db.String(50), default='dataset')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

class ActivityLog(BaseModel):
    __tablename__ = 'activities'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    timestamp = db.Column(db.String(50), default=lambda: datetime.utcnow().strftime('%I:%M %p'))
    agent_name = db.Column(db.String(100), nullable=False)
    action = db.Column(db.String(255), nullable=False)
    details = db.Column(db.Text, nullable=True)
    category = db.Column(db.String(50), default='info')

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

class AgentEvent(BaseModel):
    __tablename__ = 'agent_events'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    simulation_id = db.Column(db.String(100), nullable=True)
    agent_name = db.Column(db.String(100), nullable=False)
    event_type = db.Column(db.String(100), nullable=False)
    payload_json = db.Column(db.Text, default='{}')
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

class SimulationRun(BaseModel):
    __tablename__ = 'simulation_runs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(50), default='Running')
    summary_json = db.Column(db.Text, default='{}')

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

class WhatsAppContact(BaseModel):
    __tablename__ = 'whatsapp_contacts'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    phone_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    whatsapp_number = db.Column(db.String(50), nullable=False)
    sandbox_joined = db.Column(db.Boolean, default=True)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen_at = db.Column(db.DateTime, default=datetime.utcnow)
    welcome_message_status = db.Column(db.String(50), default='Pending')

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

def init_db(app):
    db.init_app(app)
    with app.app_context():
        db.create_all()
        # Safe migration check for new SQLite columns
        try:
            from sqlalchemy import inspect, text
            inspector = inspect(db.engine)
            if 'appointments' in inspector.get_table_names():
                existing_cols = [c['name'] for c in inspector.get_columns('appointments')]
                new_cols = [
                    ('age', 'INTEGER'),
                    ('gender', 'VARCHAR(20)'),
                    ('disease', 'VARCHAR(150)'),
                    ('symptoms', 'TEXT'),
                    ('severity', 'VARCHAR(50)'),
                    ('diagnostics', 'TEXT'),
                    ('appointment_type', 'VARCHAR(100)'),
                    ('medical_history', 'TEXT'),
                    ('medications', 'TEXT'),
                    ('allergies', 'TEXT'),
                    ('notes', 'TEXT')
                ]
                for col_name, col_type in new_cols:
                    if col_name not in existing_cols:
                        db.session.execute(text(f"ALTER TABLE appointments ADD COLUMN {col_name} {col_type}"))
                db.session.commit()
        except Exception as e:
            db.session.rollback()
