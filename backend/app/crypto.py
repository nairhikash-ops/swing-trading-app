from cryptography.fernet import Fernet, InvalidToken


class TokenCrypto:
    def __init__(self, secret_key: str) -> None:
        if not secret_key:
            raise ValueError("APP_SECRET_KEY is required before storing Dhan tokens.")
        self._fernet = Fernet(secret_key.encode("utf-8"))

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("Stored Dhan token cannot be decrypted with the current APP_SECRET_KEY.") from exc


def mask_token(token: str | None) -> str | None:
    if not token:
        return None
    if len(token) <= 12:
        return "***"
    return f"{token[:6]}...{token[-4:]}"
