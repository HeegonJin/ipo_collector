"""ipo_id 와 종목코드 규칙. 종목코드는 항상 문자열 (0158S0 처럼 영문이 섞인다)."""
import re

_CORP_CODE = re.compile(r"^\d{8}$")
_RCEPT_NO = re.compile(r"^\d{14}$")


def _ascii_digits(value: str, n: int, label: str) -> str:
    """str.isdigit() 는 전각 숫자도 통과시키므로 ASCII 만 허용하고 길이를 고정한다 (경로에 쓰기 전 검증)."""
    if not (isinstance(value, str) and len(value) == n and value.isascii() and value.isdigit()):
        raise ValueError(f"{label} 는 ASCII 숫자 {n}자리여야 함: {value!r}")
    return value


def safe_rcept_no(value: str) -> str:
    return _ascii_digits(value, 14, "rcept_no")


def safe_corp_code(value: str) -> str:
    return _ascii_digits(value, 8, "corp_code")


def safe_date(value: str) -> str:
    """YYYYMMDD. 실제 달력에 있는 날짜만 허용한다."""
    from datetime import datetime
    _ascii_digits(value, 8, "날짜")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError:
        raise ValueError(f"날짜 형식(YYYYMMDD)이 아님: {value!r}") from None
    return value


def short_code(code: str) -> str:
    """6자리 단축코드 또는 12자 ISIN(KR7......) 입력을 6자리 단축코드로."""
    code = (code or "").strip()
    if len(code) == 12 and code.startswith("KR"):
        return code[3:9]
    return code


def make_ipo_id(corp_code: str, first_reg_rcept_no: str) -> str:
    """{corp_code}_{최초 증권신고서 rcept_no}. 상장일이 바뀌어도 키가 변하지 않는다."""
    if not _CORP_CODE.match(corp_code):
        raise ValueError(f"corp_code 는 8자리 숫자: {corp_code!r}")
    if not _RCEPT_NO.match(first_reg_rcept_no):
        raise ValueError(f"rcept_no 는 14자리 숫자: {first_reg_rcept_no!r}")
    return f"{corp_code}_{first_reg_rcept_no}"


def make_temp_ipo_id(code: str, listing_date: str) -> str:
    """DART 와 아직 연결되지 않은 KRX 탐지 종목의 임시 id. 건강판에서 연결 안 된 건수로 센다."""
    return f"K:{short_code(code)}_{listing_date}"


def is_temp_ipo_id(ipo_id: str) -> bool:
    return ipo_id.startswith("K:")
