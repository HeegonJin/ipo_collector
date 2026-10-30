# IPO 수집기 · 신호 에이전트 (G1 데이터 · A0 기준선)

담당 진 · 근거 D5·D7·D11·D12·D15, 기획 v3.1(S1~S8) · 상태: 수집·레지스트리·A0 백테스트(코스닥 기준선·D12 판정 포함) 작동

## 구조
| 층 | 파일 | 하는 일 |
|---|---|---|
| 수집 L1 | `krx_api.py`, `dart_list.py`, `dart_estk.py`, `dart_terms.py`, `dart_api.py` | KRX 일별 시세, DART 지분증권 신고서 목록·주요정보·원문(확정 공모가)·실적보고서 |
| 공통 | `core/http.py` | 요청 재시도(429·5xx·연결 오류)와 오류 메시지에서 API 키 가리기 |
| 레지스트리 | `build_dart_registry.py` | 회사당 한 줄(`ipo_id`), 확정 공모가(발행조건확정 원문 ↔ 실적보고서 대조), 매매 대상 여부 |
| 사실 L2 | `store/bars.py`, `store/facts.py` | 시세·사실에 `available_at` 부여 |
| 판단 L4~L6 | `strategies/`, `decide/` | `PitReader` 로만 읽는다 (`core/boundaries.py` 가 import·시계·파일 접근을 검사) |
| 평가 L8 | `evaluate/` | `settle`(미래 가격을 읽는 유일한 곳), A0 백테스트, 실데이터 실행기 |
| 장부 L7 | `ledger/ledger.py` | 해시 체인 추가 전용 JSONL (+ `.head`, `.lock`) |
| 설정 | `config/*.yaml` | 비용·구간·표본 (바꾸려면 새 버전 파일). `config.py` 의 비용 상수도 `costs_v1.yaml` 에서 읽는다 |

## 준비 (한 번만)
1. **KRX Open API 키** (승인 약 1일): openapi.krx.co.kr → 인증키 신청 → 서비스 이용신청 4개
   주식 `코스닥 일별매매정보`(ksq_bydd_trd) · `코넥스 일별매매정보`(knx_bydd_trd) · `코스닥 종목기본정보`(ksq_isu_base_info), 지수 `KOSDAQ 시리즈 일별시세정보`(kosdaq_dd_trd)
   (키만 있고 서비스 승인이 없으면 `401 Unauthorized API Call` 이 온다. 지수가 승인 전이면 수집을 건너뛰고 코스닥 기준선만 계산 불가가 된다. 2026-10-27 에 4개 모두 승인됨)
2. **OpenDART 키**: opendart.fss.or.kr → 인증키 신청 (즉시 발급)
3. 이 폴더에 `.env` (저장소에 올라가지 않는다):
   ```
   KRX_API_KEY=발급키
   DART_API_KEY=발급키
   ```
4. `pip install requests python-dotenv pyyaml pytest`

## 실행 순서
```bash
python krx_api.py 20261026                       # 1) KRX 일별 수집 (처음엔 수십 분, 이후엔 캐시)
python dart_list.py 20230101 20261027            # 2) DART 지분증권 신고서 목록
python build_dart_registry.py 20230101 20261027 20261026   # 3) 레지스트리 (data/2_mart/dart_ipo_registry.csv, dart_offer_terms.csv)
python -m evaluate.real_a0 20261026              # 4) 실데이터 A0 결과 (results/*_A0_real_v1.md)
python -m pytest -q                              # 테스트 (키 없이). tests/fixtures_real 은 로컬 전용이라 없으면 건너뛴다
```
기존 흐름(`build_sample.py` → `dart_api.py` → `report.py`)도 그대로 동작한다.

## 알아둘 사실 (실측)
- KRX 일별 응답의 `ISU_CD` 는 6자리 단축코드(영문 섞임, 예 `0158S0`)이고 `ISU_SRT_CD` 필드는 없다. 휴장일도 `{"OutBlock_1": []}` 로 온다.
- KRX 일별 자료는 당일 저녁에는 아직 비어 있다 → 최근 4일의 빈 응답은 캐시하지 않는다. 공개 시각은 다음 거래일 08:00 로 가정(미실측).
- DART `list.json` 은 `pblntf_detail_ty` 를 무시한다. `estkRs.json` 은 회사당 최신 정정본 한 건만, 확정 전 값으로 준다 → 확정 공모가는 발행조건확정 원문 + 증권발행실적보고서로 구한다.
- 상장일 기준가(`종가 − 전일대비`)는 공모가와 다를 수 있다 (진코스텍 23,850 vs 23,500). 공모가의 주 출처는 DART.
- 상장 뒤의 발행조건확정 공시는 유상증자 등 다른 공모다 → IPO 확정가 후보에서 뺀다.

## 아직 안 하는 것
수요예측·확약·유통가능 물량(DART 원문 표 파싱), SEIBRO 보호예수 해제, 투자자별 매매, 키움 분봉·15:20 스냅샷, 기술특례 구분, 매크로 국면, 전략 A·B·C 와 M1/M3 모듈.
