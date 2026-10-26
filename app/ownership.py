"""Fail-closed workspace isolation for ORM reads, bulk writes and new records."""

import hashlib

from fastapi import HTTPException
from sqlalchemy import event, false
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria

from app.models import Owned


@event.listens_for(Session, "do_orm_execute")
def scope_statement(state: ORMExecuteState) -> None:
    if state.session.info.get("system"):
        return
    owner = state.session.info.get("owner_id")
    if owner is None:
        state.statement = state.statement.options(
            with_loader_criteria(Owned, lambda model: false(), include_aliases=True)
        )
    else:
        state.statement = state.statement.options(
            with_loader_criteria(
                Owned, lambda model: model.owner_account_id == owner, include_aliases=True
            )
        )


@event.listens_for(Session, "before_flush")
def scope_records(session: Session, flush_context: object, instances: object) -> None:
    owner = session.info.get("owner_id")
    for row in session.new | session.dirty | session.deleted:
        if not isinstance(row, Owned):
            continue
        if session.info.get("system"):
            continue
        if owner is None:
            raise HTTPException(403, "Workspace context required")
        if row in session.new:
            if row.owner_account_id is not None and row.owner_account_id != owner:
                raise HTTPException(403, "Invalid workspace ownership")
            row.owner_account_id = owner
        elif row.owner_account_id != owner:
            raise HTTPException(403, "Workspace ownership cannot be changed")


def identity_key(session: Session, key: str) -> str:
    owner = session.info.get("owner_id")
    return hashlib.sha256(f"{owner}:{key}".encode()).hexdigest() if owner else key
