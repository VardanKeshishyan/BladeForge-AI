import hashlib
import hmac
import secrets


def generate_api_key() -> tuple[str, str]:
    raw = f"bf_live_{secrets.token_urlsafe(32)}"
    return raw, raw[:16]


def hash_api_key(raw_key: str, pepper: str) -> str:
    return hmac.new(pepper.encode(), raw_key.encode(), hashlib.sha256).hexdigest()


def verify_api_key(raw_key: str, expected_hash: str, pepper: str) -> bool:
    candidate = hash_api_key(raw_key, pepper)
    return hmac.compare_digest(candidate, expected_hash)

