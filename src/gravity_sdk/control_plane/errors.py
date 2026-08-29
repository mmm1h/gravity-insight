"""Stable failures for the Stage B verification boundary."""


class ControlPlaneVerificationError(ValueError):
    """Reject an artifact or metadata set that cannot be trusted."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")
