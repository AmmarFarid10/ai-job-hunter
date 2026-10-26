import hashlib
import secrets

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=320, pattern=r"^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$")
    password: SecretStr = Field(min_length=12, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.casefold()


class Signup(Credentials):
    name: str = Field(min_length=1, max_length=200)
    setup_key: SecretStr | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Name cannot be blank")
        return value.strip()


def password_hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    value = hashlib.scrypt(
        password.encode(), salt=salt, n=32768, r=8, p=1, maxmem=64 * 1024 * 1024, dklen=32
    )
    return f"scrypt-v1${salt.hex()}${value.hex()}"


def password_valid(password: str, encoded: str) -> bool:
    try:
        kind, salt, _ = encoded.split("$")
        if kind != "scrypt-v1" or len(salt) != 32:
            return False
        return secrets.compare_digest(password_hash(password, bytes.fromhex(salt)), encoded)
    except (ValueError, TypeError):
        return False


def session_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class EmailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    email: str = Field(max_length=320, pattern=r"^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$")

    @field_validator("email")
    @classmethod
    def normalized(cls, value: str) -> str:
        return value.strip().casefold()


class TokenAction(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    token: SecretStr = Field(min_length=32, max_length=200)


class PasswordReset(TokenAction):
    password: SecretStr = Field(min_length=12, max_length=128)
