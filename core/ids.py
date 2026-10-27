"""ipo_id 와 종목코드 규칙. 종목코드는 항상 문자열 (0158S0 처럼 영문이 섞인다)."""
import re

_CORP_CODE = re.compile(r"^\d{8}$")
_RCEPT_NO = re.compile(r"^\d{14}$")


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
