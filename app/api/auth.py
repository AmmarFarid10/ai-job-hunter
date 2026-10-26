from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.api.dependencies import Session
from app.config import get_settings
from app.domain.auth import Credentials, EmailRequest, PasswordReset, Signup, TokenAction
from app.models import AccountSecurityEvent, WorkspaceAccount
from app.services.account_security import consume_action, send_action
from app.services.auth import account_view, current_session, login, signup
from app.services.google_auth import (
    GoogleComplete,
    GoogleStart,
    complete_google,
    google_available,
    start_google,
)


async def auth_budget(request: Request, session: Session) -> None:
    if get_settings().environment == "production" and request.method == "POST":
        from app.services.auth import throttle

        if not await throttle(
            session, "ip:" + request.headers.get("X-Client-IP", "unknown")[:100], limit=60
        ):
            raise HTTPException(429, "Too many authentication attempts. Try again in a minute")


router = APIRouter(
    prefix="/api/v1/auth", tags=["workspace authentication"], dependencies=[Depends(auth_budget)]
)
OwnerToken = Annotated[str | None, Header(alias="X-Owner-Session")]


@router.get("/status")
async def status(session: Session) -> dict[str, bool]:
    return {
        "signup_available": True,
        "password_recovery_available": bool(
            get_settings().smtp_host and get_settings().auth_sender_email
        ),
        "email_verification_required": get_settings().require_email_verification,
        "admin_bootstrap_available": get_settings().allow_admin_bootstrap
        and await session.scalar(
            select(WorkspaceAccount.id).where(
                WorkspaceAccount.role == "ADMIN", WorkspaceAccount.password_hash != "!bootstrap"
            )
        )
        is None,
        "google_available": google_available(),
    }


@router.post("/signup")
async def register(data: Signup, session: Session, background: BackgroundTasks) -> JSONResponse:
    code, result = await signup(session, data)
    if code == 201 and get_settings().require_email_verification:
        await send_action(session, data.email, "verify", background)
    return JSONResponse(jsonable_encoder(result), status_code=code)


@router.post("/login")
async def sign_in(data: Credentials, session: Session) -> JSONResponse:
    code, result = await login(session, data)
    return JSONResponse(jsonable_encoder(result), status_code=code)


@router.get("/me")
async def me(session: Session, token: OwnerToken = None) -> dict[str, Any]:
    row = await current_session(session, token)
    account = await session.get(WorkspaceAccount, row.account_id)
    assert account is not None
    return {"user": account_view(account), "expires_at": row.expires_at}


@router.post("/logout")
async def logout(session: Session, token: OwnerToken = None) -> dict[str, bool]:
    row = await current_session(session, token)
    row.revoked_at = datetime.now(UTC)
    session.add(AccountSecurityEvent(account_id=row.account_id, action="SESSION_REVOKED"))
    await session.flush()
    return {"authenticated": False}


@router.post("/google/start")
async def google_start(
    data: GoogleStart, session: Session, token: OwnerToken = None
) -> JSONResponse:
    code, result = await start_google(session, data, token)
    return JSONResponse(jsonable_encoder(result), status_code=code)


@router.post("/google/complete")
async def google_complete(data: GoogleComplete, session: Session) -> JSONResponse:
    code, result = await complete_google(session, data)
    return JSONResponse(jsonable_encoder(result), status_code=code)


@router.post("/request-verification", status_code=202)
async def request_verification(
    data: EmailRequest, session: Session, background: BackgroundTasks
) -> dict[str, str]:
    await send_action(session, data.email, "verify", background)
    return {"detail": "If the account needs verification, a link will be sent"}


@router.post("/request-password-reset", status_code=202)
async def request_password_reset(
    data: EmailRequest, session: Session, background: BackgroundTasks
) -> dict[str, str]:
    await send_action(session, data.email, "reset", background)
    return {"detail": "If the account exists, a reset link will be sent"}


@router.post("/verify-email")
async def verify_email(data: TokenAction, session: Session) -> dict[str, str]:
    await consume_action(session, data.token.get_secret_value(), "verify")
    return {"detail": "Email verified. Sign in to continue"}


@router.post("/reset-password")
async def reset_password(data: PasswordReset, session: Session) -> dict[str, str]:
    await consume_action(
        session, data.token.get_secret_value(), "reset", data.password.get_secret_value()
    )
    return {"detail": "Password reset. Sign in with your new password"}
