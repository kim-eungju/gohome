from __future__ import annotations

from enum import Enum


class ErrorKind(Enum):
    NO_KEY = "no_key"
    NETWORK = "network"
    TIMEOUT = "timeout"
    AUTH = "auth"
    LIMIT = "limit"
    SERVER = "server"
    PARSE = "parse"
    NO_DATA = "no_data"
    UNKNOWN = "unknown"


class ApiError(Exception):
    """사용자에게 그대로 보여줄 수 있는 한국어 메시지를 가진 예외.

    메시지에는 URL이나 인증키를 절대 포함하지 않는다.
    """

    def __init__(self, kind: ErrorKind, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message
