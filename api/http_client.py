"""공통 HTTP 호출. 예외를 한국어 ApiError 로 변환하고, URL(인증키 포함)을 로그/메시지에 남기지 않는다."""
from __future__ import annotations

import logging
from typing import Any

import requests

from api.errors import ApiError, ErrorKind
from config.settings import HTTP_TIMEOUT

log = logging.getLogger(__name__)
_HEADERS = {"User-Agent": "gohome/1.0", "Accept": "application/json"}


def get(url: str, params: dict[str, Any] | None = None, *, label: str) -> requests.Response:
    try:
        resp = requests.get(url, params=params, timeout=HTTP_TIMEOUT, headers=_HEADERS)
    except requests.exceptions.ConnectTimeout:
        log.warning("%s: connect timeout", label)
        raise ApiError(ErrorKind.TIMEOUT, "서버 연결 시간이 초과되었습니다. 잠시 후 다시 조회해 주세요.") from None
    except requests.exceptions.ReadTimeout:
        log.warning("%s: read timeout", label)
        raise ApiError(ErrorKind.TIMEOUT, "서버 응답이 지연되고 있습니다. 잠시 후 다시 조회해 주세요.") from None
    except requests.exceptions.ConnectionError:
        log.warning("%s: connection error", label)
        raise ApiError(ErrorKind.NETWORK, "서버에 연결할 수 없습니다. 인터넷 연결을 확인해 주세요.") from None
    except requests.exceptions.RequestException as e:
        log.warning("%s: request error %s", label, type(e).__name__)
        raise ApiError(ErrorKind.NETWORK, "요청 중 오류가 발생했습니다. 인터넷 연결을 확인해 주세요.") from None

    code = resp.status_code
    if code != 200:
        log.warning("%s: HTTP %s", label, code)
    if code in (401, 403):
        raise ApiError(ErrorKind.AUTH, "API 인증에 실패했습니다. API KEY가 올바른지, 해당 서비스 활용신청이 승인되었는지 확인해 주세요.")
    if code == 429:
        raise ApiError(ErrorKind.LIMIT, "API 호출 한도를 초과했습니다. 잠시 후(또는 내일) 다시 조회해 주세요.")
    if code >= 500:
        raise ApiError(ErrorKind.SERVER, f"API 서버 오류가 발생했습니다(HTTP {code}). 잠시 후 다시 조회해 주세요.")
    if code != 200:
        raise ApiError(ErrorKind.UNKNOWN, f"API 요청이 실패했습니다(HTTP {code}).")
    return resp


def parse_json(resp: requests.Response, *, label: str) -> Any:
    try:
        return resp.json()
    except ValueError:
        log.warning("%s: JSON parse failed (first bytes: %r)", label, resp.text[:80])
        raise ApiError(ErrorKind.PARSE, "API 응답을 해석할 수 없습니다(형식 오류).") from None
