import queue
import json
import time
from datetime import datetime

class EventManager:
    def __init__(self):
        self.subscribers = []

    def subscribe(self):
        q = queue.Queue()
        self.subscribers.append(q)
        return q

    def unsubscribe(self, q):
        if q in self.subscribers:
            self.subscribers.remove(q)

    def publish_agent_event(self, user_id, simulation_id, agent_name, event_type, payload):
        """
        Publishes an event to all active SSE subscribers and returns event dictionary.
        """
        event_data = {
            "user_id": user_id,
            "simulation_id": simulation_id,
            "agent_name": agent_name,
            "event_type": event_type, # 'waiting', 'started', 'running', 'completed', 'error'
            "payload": payload,
            "timestamp": datetime.utcnow().strftime('%H:%M:%S')
        }
        
        # Remove dead subscribers
        dead_subscribers = []
        for q in self.subscribers:
            try:
                q.put_nowait(event_data)
            except Exception:
                dead_subscribers.append(q)
        
        for dq in dead_subscribers:
            self.unsubscribe(dq)

        return event_data

    def publish(self, data):
        agent_name = data.get('agent_name', 'Agent')
        event_type = data.get('event_type', 'progress')
        payload = data.get('payload', {})
        return self.publish_agent_event(None, None, agent_name, event_type, payload)

event_manager = EventManager()
