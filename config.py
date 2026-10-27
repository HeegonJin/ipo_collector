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
EXCLUDE_NAME_KEYWORDS = ["스팩", "SPAC", "리츠"]

# ── 비용 가정 (results/README: 반드시 명시) ──
COMMISSION_PER_SIDE = 0.00015      # 0.015% (키움 비대면 기준, 본인 계좌 수수료로 바꿀 것)
SLIPPAGE_PER_SIDE = 0.0025         # 0.25% → 왕복 0.5%p (설계 v2 가정)
# 코스닥 증권거래세 (매도 시). 연도별로 다르다. 적용 전 국세청·증권사 공지로 한 번 더 확인.
KOSDAQ_SELL_TAX = {2023: 0.0020, 2024: 0.0018, 2025: 0.0015, 2026: 0.0020}
