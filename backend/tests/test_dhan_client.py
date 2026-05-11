from app.dhan_client import renewed_access_token


def test_renewed_access_token_accepts_dhan_token_field():
    assert renewed_access_token({"token": "new-token-value"}) == "new-token-value"


def test_renewed_access_token_accepts_documented_access_token_fields():
    assert renewed_access_token({"accessToken": "camel-token"}) == "camel-token"
    assert renewed_access_token({"access_token": "snake-token"}) == "snake-token"


def test_renewed_access_token_returns_empty_string_when_missing():
    assert renewed_access_token({"status": "success"}) == ""
