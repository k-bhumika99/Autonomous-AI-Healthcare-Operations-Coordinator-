import os
import logging

logger = logging.getLogger(__name__)

class TwilioService:
    def __init__(self):
        self.account_sid = os.getenv('TWILIO_ACCOUNT_SID', '').strip()
        self.auth_token = os.getenv('TWILIO_AUTH_TOKEN', '').strip()
        self.phone_number = os.getenv('TWILIO_PHONE_NUMBER', '').strip()
        self.content_sid = os.getenv('TWILIO_WHATSAPP_CONTENT_SID', '').strip()
        self._client = None
        self._init_client()

    def _init_client(self):
        self.account_sid = os.getenv('TWILIO_ACCOUNT_SID', '').strip()
        self.auth_token = os.getenv('TWILIO_AUTH_TOKEN', '').strip()
        self.phone_number = os.getenv('TWILIO_PHONE_NUMBER', '').strip()
        self.content_sid = os.getenv('TWILIO_WHATSAPP_CONTENT_SID', '').strip()

        if self.account_sid and self.auth_token and self.phone_number:
            try:
                from twilio.rest import Client
                self._client = Client(self.account_sid, self.auth_token)
                logger.info("Twilio client initialized successfully.")
                return self._client
            except Exception as e:
                logger.warning(f"Could not initialize Twilio client: {e}")
                self._client = None
        return None

    @property
    def client(self):
        if self._client is None:
            self._init_client()
        return self._client

    @client.setter
    def client(self, value):
        self._client = value

    def get_client(self):
        return self.client

    def get_status(self):
        if self.client:
            return {"connected": True, "label": "Twilio: CONNECTED", "mock": False, "content_sid": self.content_sid}
        return {"connected": False, "label": "Twilio: MOCK MODE", "mock": True, "content_sid": self.content_sid}

    def _send_sms(self, to_phone, body):
        """
        Internal SMS send. Returns result dict with success, mode, sid, status.
        If no phone provided, returns failure — caller must handle.
        """
        if not to_phone or to_phone.strip() in ['', 'None', 'nan']:
            return {
                "success": False,
                "mode": "no_phone",
                "sid": None,
                "status": "No Phone",
                "recipient": None,
                "body": body
            }

        if self.client:
            try:
                message = self.client.messages.create(
                    body=body,
                    from_=self.phone_number,
                    to=to_phone
                )
                logger.info(f"Twilio SMS sent to {to_phone}: SID {message.sid}")
                return {
                    "success": True,
                    "mode": "live",
                    "sid": message.sid,
                    "status": "Sent",
                    "recipient": to_phone,
                    "body": body
                }
            except Exception as e:
                logger.error(f"Twilio SMS failed: {e}")
                return {
                    "success": False,
                    "mode": "live_failed",
                    "sid": None,
                    "status": "Failed",
                    "recipient": to_phone,
                    "body": body,
                    "error": str(e)
                }

        # Mock mode
        mock_sid = f"SM_MOCK_{os.urandom(4).hex().upper()}"
        logger.info(f"[MOCK TWILIO SMS] To: {to_phone} | Body: {body}")
        return {
            "success": True,
            "mode": "mock",
            "sid": mock_sid,
            "status": "Sent",
            "recipient": to_phone,
            "body": body
        }

    def send_appointment_confirmation_sms(self, patient_name, phone_number, doctor, department, date, time):
        """
        Sends confirmation SMS for a NEWLY created appointment.
        This is the ONLY time a fresh 'Pending' notification becomes 'Sent'.
        """
        message_body = (
            f"Your CareSync AI hospital appointment has been successfully scheduled.\n\n"
            f"Doctor: {doctor}\n"
            f"Department: {department}\n"
            f"Date: {date}\n"
            f"Time: {time}\n\n"
            f"Please contact the hospital if you need assistance."
        )
        return self._send_sms(phone_number, message_body)

    def send_appointment_reschedule_sms(self, patient_name, phone_number, department, original_time, new_time):
        """
        Sends an SMS notification when an appointment is rescheduled by an agent.
        Only called when a real phone number is available.
        """
        message_body = (
            f"CareSync AI Hospital Alert:\n"
            f"Dear {patient_name}, your appointment in {department} originally scheduled at {original_time} "
            f"has been rescheduled to {new_time} due to emergency hospital situation.\n"
            f"Thank you for your understanding."
        )
        return self._send_sms(phone_number, message_body)

    def send_sms(self, to_phone, body):
        return self._send_sms(to_phone, body)

twilio_service = TwilioService()
