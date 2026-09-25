import json
import logging
from datetime import datetime
from services.database import db, Scenario, ScenarioAgentRun, ScenarioAgentEvent, Dataset, Patient, Bed, Appointment, LabTest, PharmacyItem, StaffMember, DischargeRecord, ActivityLog
from services.dataset_manager import dataset_manager
from services.gemini_service import gemini_service
from services.event_manager import event_manager

from agents.coordinator import coordinator_agent
from agents.bed_agent import bed_agent
from agents.appointment_agent import appointment_agent
from agents.lab_agent import lab_agent
from agents.pharmacy_agent import pharmacy_agent
from agents.staffing_agent import staffing_agent
from agents.discharge_agent import discharge_agent

logger = logging.getLogger(__name__)

class ScenarioManager:
    def check_active_dataset(self, user_id):
        active_ds = Dataset.query.filter_by(user_id=user_id, status='LIVE').first()
        if not active_ds:
            raise ValueError("Dataset unavailable. Upload a dataset to execute this scenario.")
        return active_ds

    def create_and_analyze_scenario(self, user_id, scenario_data, filepath=None, filename=None, file_type=None):
        ds_id = None
        if filepath and filename and file_type:
            ingest_res = dataset_manager.process_and_ingest(user_id, filepath, filename, file_type)
            ds_id = ingest_res.get('dataset_id')
        else:
            active_ds = self.check_active_dataset(user_id)
            ds_id = active_ds.id

        sc_name = scenario_data.get('name', '').strip() or 'Hospital Operational Scenario'
        sc_desc = scenario_data.get('description', '').strip()
        sc_instr = scenario_data.get('user_instruction', '').strip() or sc_desc or sc_name

        scenario = Scenario(
            user_id=user_id,
            name=sc_name,
            description=sc_desc,
            user_instruction=sc_instr,
            scenario_type=scenario_data.get('scenario_type', 'Emergency Surge'),
            priority=scenario_data.get('priority', 'Critical'),
            department=scenario_data.get('department', 'All Departments'),
            date=scenario_data.get('date', 'Today'),
            dataset_id=ds_id,
            status='ANALYZING',
            created_at=datetime.utcnow()
        )
        db.session.add(scenario)
        db.session.commit()

        self.publish_scenario_event(scenario.id, user_id, 'Coordinator', 'started', {
            'status': 'Coordinator AI analyzing scenario with live database...'
        })

        scenario_dict = {
            'name': scenario.name,
            'description': scenario.description,
            'user_instruction': scenario.user_instruction,
            'scenario_type': scenario.scenario_type,
            'priority': scenario.priority,
            'department': scenario.department
        }

        # Dynamic Coordinator Analysis from Live DB
        coord_res = coordinator_agent.analyze_scenario(scenario_dict, user_id)
        recommended_agents = coord_res.get('recommended_agents', ["Bed Management", "Lab", "Pharmacy", "Staffing", "Appointment", "Discharge"])
        agent_instructions = coord_res.get('agent_instructions', {})
        surge_metrics = coord_res.get('surge_metrics', {})

        # Pass real DB metrics to Gemini for explanation
        ai_summary = gemini_service.generate_scenario_summary(scenario_dict, surge_metrics)

        scenario.status = 'PLANNING'
        scenario.execution_plan_json = json.dumps(recommended_agents)
        scenario.summary_json = json.dumps({
            'analysis_summary': ai_summary or coord_res.get('analysis_summary'),
            'agent_instructions': agent_instructions,
            'surge_metrics': surge_metrics
        })

        # Create ScenarioAgentRun for Coordinator as well so workspace is immediately populated
        coord_exec = coordinator_agent.execute(scenario.id, user_id, scenario.user_instruction)
        coord_run = ScenarioAgentRun(
            scenario_id=scenario.id,
            user_id=user_id,
            agent_name='Coordinator',
            status='Completed',
            user_instruction=scenario.user_instruction,
            results_json=json.dumps(coord_exec, default=str),
            executed_at=datetime.utcnow()
        )
        db.session.add(coord_run)

        for agent_name in recommended_agents:
            instr = agent_instructions.get(agent_name, '')
            run_rec = ScenarioAgentRun(
                scenario_id=scenario.id,
                user_id=user_id,
                agent_name=agent_name,
                status='Waiting',
                user_instruction=instr
            )
            db.session.add(run_rec)

        act = ActivityLog(
            user_id=user_id,
            agent_name='Coordinator Agent',
            action=f'Created scenario "{scenario.name}" ({scenario.priority}). Incoming Demand: {surge_metrics.get("incoming_patients", 20)} patients.',
            details=coord_res.get('analysis_summary'),
            category='info'
        )
        db.session.add(act)
        db.session.commit()

        self.publish_scenario_event(scenario.id, user_id, 'Coordinator', 'completed', {
            'status': 'Scenario Analyzed & Execution Plan Ready',
            'recommended_agents': recommended_agents
        })

        return scenario

    def run_scenario(self, scenario_id, user_id):
        self.check_active_dataset(user_id)
        scenario = Scenario.query.filter_by(id=scenario_id, user_id=user_id).first()
        if not scenario:
            raise ValueError('Scenario not found')
        if scenario.status == 'DATASET REMOVED':
            scenario.status = 'ACTIVE'

        scenario.status = 'RUNNING'
        scenario.started_at = datetime.utcnow()
        db.session.commit()

        agents_order = json.loads(scenario.execution_plan_json or '[]')
        summary_info = json.loads(scenario.summary_json or '{}')
        agent_instructions = summary_info.get('agent_instructions', {})

        results = {}
        
        # 1. Run Coordinator analysis step
        self.publish_scenario_event(scenario_id, user_id, 'Coordinator', 'running', {'status': 'Coordinator Agent initializing execution flow...'})
        coord_res = coordinator_agent.analyze_scenario({
            'name': scenario.name,
            'user_instruction': scenario.user_instruction,
            'description': scenario.description
        }, user_id)
        coord_exec_res = coordinator_agent.execute(scenario_id, user_id, scenario.user_instruction)
        results['Coordinator'] = coord_exec_res
        
        # Save Coordinator run record
        coord_run = ScenarioAgentRun.query.filter_by(scenario_id=scenario_id, agent_name='Coordinator').first()
        if not coord_run:
            coord_run = ScenarioAgentRun(scenario_id=scenario_id, user_id=user_id, agent_name='Coordinator')
            db.session.add(coord_run)
        coord_run.status = 'Completed'
        coord_run.results_json = json.dumps(coord_exec_res, default=str)
        coord_run.executed_at = datetime.utcnow()
        db.session.commit()

        self.publish_scenario_event(scenario_id, user_id, 'Coordinator', 'completed', {'status': 'Coordinator Agent Completed'})

        # 2. Automatically execute all 6 specialized agents in sequence
        for agent_name in agents_order:
            self.publish_scenario_event(scenario_id, user_id, agent_name, 'running', {
                'status': f'{agent_name} Agent starting...'
            })
            instr = agent_instructions.get(agent_name, scenario.user_instruction)
            res = self.run_agent_by_name(agent_name, scenario_id, user_id, instr)
            results[agent_name] = res
            self.publish_scenario_event(scenario_id, user_id, agent_name, 'completed', {
                'status': f'{agent_name} Agent Completed'
            })

        scenario.status = 'COMPLETED'
        scenario.completed_at = datetime.utcnow()

        # Consolidate metrics from database and agent runs
        surge_metrics = coord_res.get('surge_metrics', {})
        bed_res = results.get('Bed Management', {}).get('key_findings', {})
        lab_res = results.get('Lab', {}).get('key_findings', {})
        pharm_res = results.get('Pharmacy', {}).get('key_findings', {})
        staff_res = results.get('Staffing', {}).get('key_findings', {})
        appt_res = results.get('Appointment', {}).get('key_findings', {})
        dis_res = results.get('Discharge', {}).get('key_findings', {})

        command_center = {
            "incoming_patients": surge_metrics.get("incoming_patients", 20),
            "beds_required": surge_metrics.get("beds_required", 20),
            "beds_available": bed_res.get("available", surge_metrics.get("available_beds", 0)),
            "capacity_gap": bed_res.get("capacity_gap", surge_metrics.get("initial_capacity_gap", 0)),
            "doctors_available": staff_res.get("doctors_available", surge_metrics.get("available_doctors", 0)),
            "clinical_staff_available": staff_res.get("available", surge_metrics.get("available_staff", 0)),
            "pending_labs": lab_res.get("pending", surge_metrics.get("pending_labs", 0)),
            "critical_medicines": pharm_res.get("critical", surge_metrics.get("critical_meds", 0)),
            "today_appointments": appt_res.get("total_today", surge_metrics.get("today_appts", 0)),
            "discharge_ready": dis_res.get("ready", surge_metrics.get("discharge_ready", 0)),
            "potential_beds_released": dis_res.get("potential_beds", surge_metrics.get("discharge_ready", 0)),
            "surge_verdict": surge_metrics.get("surge_verdict", "CAPACITY UNDER PRESSURE"),
            "surge_code": surge_metrics.get("surge_code", "ORANGE"),
            "surge_msg": surge_metrics.get("surge_msg", "")
        }

        # Call Gemini for factual operational explanation
        final_summary = gemini_service.generate_final_operational_summary(command_center)

        summary_info['command_center'] = command_center
        summary_info['final_summary'] = final_summary
        summary_info['agent_results'] = {k: {'key_finding': v.get('key_finding_text', ''), 'key_findings': v.get('key_findings', {})} for k, v in results.items()}
        scenario.summary_json = json.dumps(summary_info)
        db.session.commit()

        act = ActivityLog(
            user_id=user_id,
            agent_name='Scenario Manager',
            action=f'Scenario "{scenario.name}" completed across all agents. Verdict: {command_center["surge_verdict"]}.',
            details=final_summary,
            category='success'
        )
        db.session.add(act)
        db.session.commit()

        return scenario

    def run_agent_by_name(self, agent_name, scenario_id, user_id, instruction=None):
        self.check_active_dataset(user_id)
        run_rec = ScenarioAgentRun.query.filter_by(scenario_id=scenario_id, agent_name=agent_name).first()
        if not run_rec:
            run_rec = ScenarioAgentRun(scenario_id=scenario_id, user_id=user_id, agent_name=agent_name)
            db.session.add(run_rec)

        run_rec.status = 'Running'
        if instruction:
            run_rec.user_instruction = instruction
        db.session.commit()

        sim_id = f'scenario_{scenario_id}'
        res = {}

        if agent_name == 'Bed Management':
            res = bed_agent.execute(scenario_id, user_id, instruction)
        elif agent_name == 'Appointment':
            res = appointment_agent.execute(scenario_id, user_id, instruction)
        elif agent_name == 'Lab':
            res = lab_agent.execute(scenario_id, user_id, instruction)
        elif agent_name == 'Pharmacy':
            res = pharmacy_agent.execute(scenario_id, user_id, instruction)
        elif agent_name == 'Staffing':
            res = staffing_agent.execute(scenario_id, user_id, instruction)
        elif agent_name == 'Discharge':
            res = discharge_agent.execute(scenario_id, user_id, instruction)
        elif agent_name == 'Coordinator':
            res = coordinator_agent.execute(scenario_id, user_id, instruction)


        run_rec.status = 'Completed'
        run_rec.actions_taken = res.get('actions_taken', 0)
        run_rec.records_analyzed = res.get('records_analyzed', 0)
        run_rec.results_json = json.dumps(res, default=str)
        run_rec.executed_at = datetime.utcnow()
        db.session.commit()

        return res

    def publish_scenario_event(self, scenario_id, user_id, agent_name, event_type, payload):
        evt = ScenarioAgentEvent(
            scenario_id=scenario_id,
            user_id=user_id,
            agent_name=agent_name,
            event_type=event_type,
            payload_json=json.dumps(payload),
            timestamp=datetime.utcnow()
        )
        db.session.add(evt)
        db.session.commit()
        event_manager.publish_agent_event(user_id, f'scenario_{scenario_id}', agent_name, event_type, payload)

scenario_manager = ScenarioManager()
