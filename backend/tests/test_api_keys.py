import hmac

from app.auth.api_keys import generate_api_key, hash_api_key, verify_api_key


def test_api_key_generation_and_constant_time_verification(monkeypatch) -> None:
    raw, prefix = generate_api_key()
    digest = hash_api_key(raw, "test-pepper")
    called = False
    original = hmac.compare_digest

    def recording_compare(left: str, right: str) -> bool:
        nonlocal called
        called = True
        return original(left, right)

    monkeypatch.setattr(hmac, "compare_digest", recording_compare)
    assert raw.startswith("bf_live_")
    assert raw.startswith(prefix)
    assert verify_api_key(raw, digest, "test-pepper")
    assert called
    assert not verify_api_key(f"{raw}x", digest, "test-pepper")

