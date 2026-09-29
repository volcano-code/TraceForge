import hashlib
import hmac
import re
from .domain import DomainError

def authenticate(header: str | None, developer_token: str, reviewer_token: str) -> str:
    if min(len(developer_token),len(reviewer_token))<32:
        raise DomainError("AUTH_NOT_CONFIGURED","Run bootstrap.py to configure local credentials",503)
    if hmac.compare_digest(developer_token.encode(),reviewer_token.encode()):
        raise DomainError("AUTH_NOT_CONFIGURED","Use distinct developer/reviewer tokens",503)
    if not header or not header.startswith("Bearer "):
        raise DomainError("UNAUTHORIZED","Bearer token required",401)
    token=header[7:].encode()
    if hmac.compare_digest(token,reviewer_token.encode()): return "reviewer"
    if hmac.compare_digest(token,developer_token.encode()): return "developer"
    raise DomainError("UNAUTHORIZED","Invalid token",401)

def verify_webhook(body: bytes, signature: str | None, secret: str) -> None:
    if len(secret)<32: raise DomainError("WEBHOOK_NOT_CONFIGURED","Webhook secret not configured",503)
    expected="sha256="+hmac.new(secret.encode(),body,hashlib.sha256).hexdigest()
    if not signature or not hmac.compare_digest(signature.encode(),expected.encode()):
        raise DomainError("INVALID_SIGNATURE","Invalid webhook signature",403)

def sanitize(text: str) -> str:
    # Defence in depth only: this is NOT a complete DLP system.
    text=re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]+",r"\1[REDACTED]",text)
    return re.sub(r"(?i)((?:api[_-]?key|token|password|secret)\s*[:=]\s*)[^\s,;]+",r"\1[REDACTED]",text)
