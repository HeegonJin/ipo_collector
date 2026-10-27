"""수집기 공통 HTTP GET: 오류 메시지에서 API 키를 가리고, 일시 오류(429·5xx·연결 오류)만 재시도한다.

DART 는 키를 쿼리 문자열(crtfc_key)로 받는데, requests 예외 메시지에는 URL 이 그대로 들어간다.
로그·트레이스백(공개 저장소의 CI 출력 포함)에 키가 남지 않도록, 원본 예외는 버리고 가린 메시지로 새로 던진다.
"""
import time

import requests

DEFAULT_ATTEMPTS = 3
DEFAULT_BACKOFF_SEC = 1.0


def scrub(text: str) -> str:
    import config  # 늦게 import: 테스트에서 키를 바꿔 끼울 수 있게
    for secret in (config.DART_API_KEY, config.KRX_API_KEY):
        if secret:
            text = text.replace(secret, "***")
    return text


def safe_get(url: str, *, params=None, headers=None, timeout: float = 30,
             attempts: int = DEFAULT_ATTEMPTS, backoff: float = DEFAULT_BACKOFF_SEC):
    err = None
    for n in range(attempts):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp
        except requests.HTTPError as e:
            r = e.response
            status = getattr(r, "status_code", 0)
            err = requests.HTTPError(scrub(f"{status} Error for url: {getattr(r, 'url', url)}"), response=r)
            retry = status == 429 or status >= 500
        except requests.RequestException as e:
            err = type(e)(scrub(str(e)))
            retry = True
        if not retry or n == attempts - 1:
            break
        time.sleep(backoff * (2 ** n))
    raise err from None
