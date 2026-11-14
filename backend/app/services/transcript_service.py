"""Best-effort redaction is not a compliance or de-identification guarantee."""

import hashlib
import hmac
import re


class Redactor:
    def __init__(self, key: str, secrets=()):
        self.key = key.encode()
        self.secrets = sorted(
            (s for s in secrets if len(s) >= 4), key=len, reverse=True
        )

    def owner_key(self, namespace: str, identity: str):
        if not namespace or not identity:
            raise PermissionError("Trusted owner identity is required")
        return hmac.new(
            self.key, f"{namespace}\0{identity}".encode(), hashlib.sha256
        ).hexdigest()

    def text(self, value: str):
        for secret in self.secrets:
            value = value.replace(secret, "[REDACTED]")
        patterns = (
            r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
            r"(?i)\bBearer\s+\S+",
            r"(?i)\b(?:api[_ -]?key|password|secret|token)\s*[:=]\s*\S+",
            r"\bsk-[A-Za-z0-9_-]{8,}\b",
            r"(?<!\w)\+?\d[\d ()-]{8,}\d(?!\w)",
        )
        for pattern in patterns:
            value = re.sub(pattern, "[REDACTED]", value)
        return value[:16000]
