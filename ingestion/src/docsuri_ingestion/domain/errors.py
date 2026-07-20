from __future__ import annotations

from .enums import FailureClass, FailureReason


class IngestionError(Exception):
    """Typed fail-closed ingestion error with a generalized public reason."""

    failure_class: FailureClass
    reason: FailureReason
    stage: str

    def __init__(
        self,
        message: str,
        *,
        failure_class: FailureClass,
        reason: FailureReason,
        stage: str,
    ) -> None:
        super().__init__(message)
        self.failure_class = failure_class
        self.reason = reason
        self.stage = stage

    def public_error(self) -> str:
        return self.reason.value


class PermanentIngestionError(IngestionError):
    def __init__(self, message: str, *, reason: FailureReason, stage: str) -> None:
        super().__init__(
            message,
            failure_class=FailureClass.PERMANENT,
            reason=reason,
            stage=stage,
        )


class RetriableIngestionError(IngestionError):
    def __init__(self, message: str, *, reason: FailureReason, stage: str) -> None:
        super().__init__(
            message,
            failure_class=FailureClass.RETRIABLE,
            reason=reason,
            stage=stage,
        )


class LicenseRejectedError(PermanentIngestionError):
    def __init__(self, license_url: str | None) -> None:
        label = license_url or "missing"
        super().__init__(
            f"paper is not redistributable OA: {label}",
            reason=FailureReason.NON_OA,
            stage="validate",
        )


class ValidationViolationError(PermanentIngestionError):
    def __init__(self, message: str, *, stage: str = "validate") -> None:
        super().__init__(
            message,
            reason=FailureReason.VALIDATION_VIOLATION,
            stage=stage,
        )
