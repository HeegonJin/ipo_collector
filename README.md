# IPO 수집기 (G1 데이터 · 첫 실험)

담당 진 · 근거 D5·D7·D11·D12·D15, 기획 v3.1(S1~S8) · 상태: 초안 (가짜 데이터로 로직 검증 완료, 실데이터 미실행)

## 무엇을 하나
1. **KRX Open API**에서 2023-01 이후 날짜별 코스닥·코넥스 전 종목 시세와 코스닥 지수를 받는다 (`krx_api.py`)
2. 코스닥에 **처음 나타난 날**을 상장일로 보고 신규상장을 자동으로 찾는다. 스팩·리츠, 코넥스 이전상장을 제외한다. 공모가는 상장일 `종가 − 전일대비`(기준가)로 역산한다 (`build_sample.py`)
3. **OpenDART**에서 상장 전 12개월 발행공시를 찾아 공모 상장인지 확인하고, 증권신고서·발행조건확정·투자설명서·증권발행실적보고서 원문 링크를 붙인다. 공모 공시가 없으면(재상장·분할 등) 제외한다 (`dart_api.py`)
4. 첫 실험(상장일 종가 매수 → 다음 날 시가 매도)을 비용 반영해서 계산하고, results/README 형식의 결과 문서를 만든다 (`report.py`)

## 준비 (한 번만)
1. **KRX Open API 키** (승인 약 1일, 가장 먼저 신청)
   openapi.krx.co.kr 회원가입 → 마이페이지 → 인증키 신청 → 승인 후 서비스 이용신청:
   주식 `코스닥 일별매매정보` · `코넥스 일별매매정보` · `코스닥 종목기본정보`, 지수 `KOSDAQ 시리즈 일별시세정보`
2. **OpenDART 키**: opendart.fss.or.kr → 인증키 신청 (즉시 발급)
3. 이 폴더에 `.env` 파일:
   ```
   KRX_API_KEY=발급키
   DART_API_KEY=발급키
   ```
4. `pip install requests python-dotenv`

## 실행 순서
```bash
python krx_api.py 20261023                    # 1) 2023-01-01 ~ 10/23 수집 (처음엔 수십 분, 이후엔 캐시)
python build_sample.py 20261023 20260723      # 2) G1 샘플: 최근 3개월 (11/1 마감)
python build_sample.py 20261023 20230701      #    G1+ 전수: 2023-07 이후 (11/8 마감)
python dart_api.py data/2_mart/ipo_sample_20230701_20261023.csv   # 3) DART 보강
python report.py data/2_mart/ipo_sample_20230701_20261023_dart.csv # 4) 첫 실험 결과 (G2)
python tests/test_logic.py                    # 로직 테스트 (키 없이 실행)
```

## 산출물
| 파일 | 관문 |
|---|---|
| `data/2_mart/ipo_sample_*.csv` | G1 샘플 / G1+ 전수 데이터 |
| `data/_meta/missing_*.md` | G1 "빠진 값 목록 공개" |
| `data/_meta/collect_log.csv` | 수집 기록 |
| `results/YYYY-MM-DD_first-experiment_v1.md` | G2 첫 실험 결과 |

## 첫 실행 때 확인할 것 (VERIFY)
- KRX 엔드포인트 경로와 응답 필드명 (`TDD_CLSPRC`, `CMPPREVDD_PRC`, `TDD_OPNPRC` 등). 한 날짜만 받아 `data/0_raw/krx/ksq_daily/날짜.json`을 열어 보면 된다
- 일별매매정보의 `ISU_CD`가 6자리 단축코드인지 ISIN인지 (DART 매칭에 필요)
- 역산 공모가가 실제 공모가와 맞는지: 엘리스(0158S0, 2026-10-20) 공모가 90,500원으로 대조
- 코넥스 이전상장 종목이 같은 종목코드를 유지하는지 (이름으로도 한 번 더 거름)
- 코스닥 거래세율 (2023 0.20 / 2024 0.18 / 2025 0.15 / 2026 0.20%), 본인 계좌 수수료

## 아직 안 하는 것 (빠진 값 목록에 자동 표시)
수요예측·확약·유통가능 물량(DART 원문 표 파싱), SEIBRO 보호예수 해제, 투자자별 매매, 키움 분봉, 기술특례 구분, 매크로 국면. G1+ 이후 순서대로 붙인다.
