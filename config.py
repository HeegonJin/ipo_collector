"""
설정. 키는 .env 에만 둔다 (깃허브·단톡방에 올리지 말 것).

  KRX_API_KEY=...   # openapi.krx.co.kr 마이페이지 인증키
  DART_API_KEY=...  # opendart.fss.or.kr 인증키
"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # python-dotenv 없으면 환경변수만 사용
    pass

KRX_API_KEY = os.getenv("KRX_API_KEY", "")
DART_API_KEY = os.getenv("DART_API_KEY", "")

ROOT = Path(__file__).parent
DATA = ROOT / "data"
RAW = DATA / "0_raw"      # API 응답 원본 (날짜별 JSON, 다시 받지 않도록 캐시)
CLEAN = DATA / "1_clean"  # 검산 통과한 표
MART = DATA / "2_mart"    # 실험·판단용 표
META = DATA / "_meta"     # 수집 로그, 빠진 값 목록

# ── 기간 (D7: 첫 실험 데이터는 2023-07 이후) ──
SAMPLE_START = "20230701"   # 이 날 이후 '처음 거래된' 종목만 신규상장으로 본다
BUFFER_START = "20230101"   # 탐지용 여유 구간. 이 기간에 이미 거래되던 종목은 신규상장이 아님

# ── 제외 규칙 (D11 + 기획 v3.1: 스팩·리츠·코넥스 이전 제외) ──
EXCLUDE_NAME_KEYWORDS = ["스팩", "SPAC", "리츠", "기업인수목적"]

# ── 비용 가정 (results/README: 반드시 명시) ──
# 출처는 config/costs_v1.yaml 하나뿐이다 (사람이 고정, 바꾸려면 새 버전 파일). 여기서는 읽어 올 뿐 따로 두지 않는다.
# 수수료는 본인 계좌 기준으로, 매도세는 적용 전 국세청·증권사 공지로 한 번 더 확인할 것.
from core import settings as _settings  # noqa: E402

_COSTS = _settings.load_costs(2023, 2026)
COMMISSION_PER_SIDE = _COSTS["commission_per_side"]
SLIPPAGE_PER_SIDE = _COSTS["slippage_per_side"]
KOSDAQ_SELL_TAX = dict(_COSTS["kosdaq_sell_tax"])
