"""Typed errors raised at the herdr boundary."""


class HerdrError(Exception):
    """Base class for everything that goes wrong talking to herdr."""


class HerdrUnavailable(HerdrError):
    """The herdr server can't be reached, or the connection dropped."""


class HerdrProtocolError(HerdrError):
    """herdr sent something this client can't understand."""


class HerdrRequestError(HerdrError):
    """herdr understood the request and answered with an error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
