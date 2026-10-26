from enum import StrEnum


class State(StrEnum):
    DISCOVERED = "DISCOVERED"
    MATCHED = "MATCHED"
    RESUME_GENERATED = "RESUME_GENERATED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUBMITTING = "SUBMITTING"
    ACTION_REQUIRED = "ACTION_REQUIRED"
    VERIFICATION_REQUIRED = "VERIFICATION_REQUIRED"
    SUBMITTED = "SUBMITTED"
    FAILED = "FAILED"


TRANSITIONS: dict[State, set[State]] = {
    State.DISCOVERED: {State.MATCHED, State.REJECTED},
    State.MATCHED: {State.RESUME_GENERATED, State.REJECTED},
    State.RESUME_GENERATED: {State.PENDING_APPROVAL, State.REJECTED},
    State.PENDING_APPROVAL: {State.APPROVED, State.ACTION_REQUIRED, State.REJECTED},
    State.ACTION_REQUIRED: {State.PENDING_APPROVAL, State.REJECTED},
    State.APPROVED: {State.SUBMITTING, State.PENDING_APPROVAL, State.REJECTED},
    State.SUBMITTING: {
        State.SUBMITTED,
        State.FAILED,
        State.VERIFICATION_REQUIRED,
        State.ACTION_REQUIRED,
    },
    State.VERIFICATION_REQUIRED: {State.SUBMITTED, State.FAILED},
    State.FAILED: {State.PENDING_APPROVAL, State.REJECTED},
    State.SUBMITTED: set(),
    State.REJECTED: set(),
}


def validate_transition(current: State, target: State) -> None:
    if target not in TRANSITIONS[current]:
        raise ValueError(f"Invalid transition: {current} → {target}")
    if target in {State.APPROVED, State.SUBMITTING}:
        raise ValueError(
            "Use the exact-version approval workflow; submission remains unavailable until Phase 6"
        )
