from abc import ABC, abstractmethod


class EmailProvider(ABC):
    @abstractmethod
    def send(self, to_email: str, subject: str, body: str) -> dict:
        raise NotImplementedError


class SMSProvider(ABC):
    @abstractmethod
    def send(self, to_phone: str, message: str) -> dict:
        raise NotImplementedError


class SMTPEmailProvider(EmailProvider):
    def send(self, to_email: str, subject: str, body: str) -> dict:
        return {"provider": "smtp", "status": "not_implemented", "to": to_email}


class TwilioSMSProvider(SMSProvider):
    def send(self, to_phone: str, message: str) -> dict:
        return {"provider": "twilio", "status": "not_implemented", "to": to_phone}
