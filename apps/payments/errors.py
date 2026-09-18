"""Exceptions shared by every gateway client.

Callers that only need "online payment didn't work, fall back" catch
`PaymentGatewayError`; each client raises its own subclass so logs still
say which gateway failed.
"""


class PaymentGatewayError(Exception):
    """Any non-2xx from a gateway, a transport failure, or a request we
    refuse to send. Carries the gateway's own error code when present."""

    def __init__(
        self, message: str, *, status: int | None = None,
        body: str = "", error_code: str = "",
    ):
        super().__init__(message)
        self.status = status
        self.body = body
        self.error_code = error_code
