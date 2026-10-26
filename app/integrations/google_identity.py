import secrets
from typing import Any

import httpx
import jwt

from app.config import Settings


class GoogleIdentityError(ValueError):
    pass


async def exchange_identity(
    settings: Settings, code: str, verifier: str, nonce: str
) -> dict[str, Any]:
    try:
        assert settings.google_client_secret is not None
        async with httpx.AsyncClient(timeout=15, follow_redirects=False, trust_env=False) as client:
            token = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret.get_secret_value(),
                    "redirect_uri": settings.google_redirect_uri,
                    "grant_type": "authorization_code",
                    "code_verifier": verifier,
                },
            )
            if not token.is_success:
                raise GoogleIdentityError("Google authorization could not be completed")
            encoded = token.json()["id_token"]
            if not isinstance(encoded, str) or len(encoded) > 16384:
                raise ValueError("Invalid token")
            header = jwt.get_unverified_header(encoded)
            certificates = await client.get("https://www.googleapis.com/oauth2/v3/certs")
            if not certificates.is_success:
                raise ValueError("Could not verify identity")
            jwk = next(
                key for key in certificates.json()["keys"] if key.get("kid") == header.get("kid")
            )
            public_key = jwt.PyJWK.from_dict(jwk).key
            claims: dict[str, Any] = jwt.decode(
                encoded,
                public_key,
                algorithms=["RS256"],
                audience=settings.google_client_id,
                issuer=["https://accounts.google.com", "accounts.google.com"],
                leeway=30,
                options={"require": ["exp", "iat", "iss", "aud", "sub", "nonce"]},
            )
            if not secrets.compare_digest(str(claims["nonce"]), nonce):
                raise ValueError("Invalid nonce")
            if claims.get("azp", settings.google_client_id) != settings.google_client_id:
                raise ValueError("Invalid authorized party")
            if claims.get("email_verified") is not True or not isinstance(claims.get("email"), str):
                raise ValueError("Verified email required")
            if not isinstance(claims["sub"], str) or not 1 <= len(claims["sub"]) <= 255:
                raise ValueError("Invalid subject")
            return claims
    except (httpx.HTTPError, jwt.PyJWTError, ValueError, KeyError, TypeError, StopIteration) as exc:
        raise GoogleIdentityError(
            "Google identity could not be verified. Start sign-in again"
        ) from exc
