from empireoe_core.auth import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
    validate_password_complexity,
)


def test_password_hash_and_verify():
    pw = "SecurePass123!"
    hashed = hash_password(pw)
    assert verify_password(pw, hashed)
    assert not verify_password("wrong", hashed)


def test_token_roundtrip():
    secret = "a" * 32
    token = create_access_token({"sub": "user@example.com", "org_id": 1}, secret)
    payload = decode_access_token(token, secret)
    assert payload["sub"] == "user@example.com"
    assert payload["org_id"] == 1


def test_password_complexity():
    assert validate_password_complexity("short") is not None
    assert validate_password_complexity("alllowercase1") is not None
    assert validate_password_complexity("ALLUPPERCASE1") is not None
    assert validate_password_complexity("NoDigitsHere") is not None
    assert validate_password_complexity("ValidPass1") is None
