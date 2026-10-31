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
python build_demand_mart.py 20230101 20261029    # 3') 수요 지표 마트 (data/2_mart/dart_demand.csv): 수요예측 경쟁률·확약·유통가능·락업 일정·일반청약 경쟁률
python -m evaluate.real_a0 20261026              # 4) 실데이터 A0 결과 (results/*_A0_real_v1.md)
python -m evaluate.real_a0 20261029 --split train   # 구간 지정 (train/valid/forward/all). valid 는 열 때마다 data/_meta/validation_runs.csv 에 기록, 2번째부터 경고
python -m evaluate.basic_stats 20261029          # 기초 통계 (학습 구간): 경쟁률·공모 규모·첫날 유형별 수익률 분포 → results/*_기초통계_train_v1.md (비용 전 총수익률, valid 는 열지 않음)
python -m ops.paper_ledger settle 20261029       # 모의 장부(data/ledger/paper_a0.jsonl)의 청산일이 지난 매수 판단을 정산
python -m evaluate.swing B_v1 20261029          # 전략 B (config/strategy_B_v1.yaml) 학습 구간 백테스트 (C_v1 도 동일, valid 는 열지 않음)
python -m ops.schedule add 20261116 회사이름 0158S0 [공모가]   # 상장 일정 수기 입력 (data/_meta/listing_schedule.csv) / list / check YYYYMMDD
python -m ops.daily_job swing 20261116          # 매일 08:30~08:35: 전략 B·C 판단 (전 거래일 KRX 수집 선행) → 장부 기록
python -m ops.daily_job a0 20261116             # 상장일 15:20~15:25: 수기 일정의 오늘 상장 종목 A0 판단
python -m ops.daily_job settle 20261116         # 저녁: 청산일이 지난 판단 정산 (A0·B·C 한 장부)
python -m lab.server 20261029                    # 전략 실험 앱 API (127.0.0.1:8765). 화면: cd lab/web && npm install && npm run build 후 같은 주소, 개발은 npm run dev (5173)
python -m pytest -q                              # 테스트 (키 없이). tests/fixtures_real 은 로컬 전용이라 없으면 건너뛴다
```
기존 흐름(`build_sample.py` → `dart_api.py` → `report.py`)도 그대로 동작한다.

## 전략 실험 앱 (`lab/`)
조건(수요예측·청약 경쟁률, 확약률, 유통가능 비율, 공모 규모 — 상장 전 공시 값 / 상장일 값: 시초가·종가의 공모가 대비, 고점 대비 종가, 코스닥 등락률)·진입 시점(D0 종가/D1 시가)·보유(D+1/3/5)를 사람이 바꿔 보며 학습 구간(train)에서 비용 차감 후 수익률을 본다. 과적합 장치 4가지(`config/lab_v1.yaml`, 사람이 고정):
최소 표본 수(미만이면 숫자 숨김) · 시도 횟수 카운터(`data/_meta/lab_trials.csv`, 우연 기대 최고 평균 표시) · 이웃 구간 견고성 · 검증 구간 잠금(확인 문구 + 학습에서 실행한 조건만, `validation_runs.csv` 기록).
상장일 마감 후 값 + D0 종가 진입은 look-ahead 라 '상한 추정'으로, 설계도에 없는 조건은 '설계도 외 탐색'으로 화면에 표시한다. 조건 없음 + D0 종가 + D+1 = A0 기준선과 같아야 한다(train n=136, 평균 −0.11%).
서버는 127.0.0.1 전용(Host/Origin 검사)이고 데이터를 밖으로 내보내지 않는다 (KRX 약관 Art.11(2)).

## 수요 지표 수집 (`dart_demand.py`, `build_demand_mart.py`)
설계도 M1(IPO 구조·수요)의 변수를 DART 원문 표에서 뽑는다 (전략 B·C 입력). 모두 상장 전에 공시되므로 `*_available_dt`(공시 접수일) 이후에는 look-ahead 없이 쓸 수 있다.
- 발행조건확정(정정) 공시: 기관 수요예측 경쟁률·참여 건수, 확약 신청 수량(6개월·3개월·1개월·15일)과 확약률, 상장 직후 유통가능 물량, 락업 일정(상장 후 N개월에 풀리는 주식 수).
- 증권발행실적보고서: 일반청약 경쟁률(청약 수량 ÷ 배정 수량), 기관 배정분의 확약기간별 최종 비중.
- 묶음(수요예측·확약·유통가능/락업)마다 값이 있는 가장 늦은 상장 전 공시에서 가져오고 그 공시 번호(`*_rcept`)를 남긴다. 확약·유통가능 표가 최종 정정에는 없고 최초 신고서에만 있는 경우가 있다.
- 교차 검증을 통과해야 `*_status`=확인 (표 열 개수, 수량÷경쟁률 ≤ 공모 주식, 확약+미확약=합계, 유통가능÷상장주식=문장 비율, 확약 비중 합=100%). 못 읽거나 불일치면 값은 남기되 `미확인`, 없으면 빈 칸 (0 으로 채우지 않는다).
- 락업 일정은 문장에서 읽은 부분 합이라 (2026-10-30 기준 213종목 중 19종목만 읽혔고 2종목이 제한 총량과 거의 일치 — 사실상 미수집, 표 형태는 값이 일관되지 않아 쓰지 않았다) `lockup_coverage`(= 읽은 합 ÷ 제한 총량)를 함께 둔다. 1.0 이면 `확인`. 예탁원(SEIBRO) 해제 일정은 쓰지 않았다 — 설계도가 대안으로 적은 '투자설명서·실적보고서 의무보유 표'로 대체. **실제 해제 후 매도 확인(투자자별 매매)은 수집하지 않는다.**

## 알아둘 사실 (실측)
- KRX 일별 응답의 `ISU_CD` 는 6자리 단축코드(영문 섞임, 예 `0158S0`)이고 `ISU_SRT_CD` 필드는 없다. 휴장일도 `{"OutBlock_1": []}` 로 온다.
- KRX 일별 자료는 당일 저녁에는 아직 비어 있다 → 최근 4일의 빈 응답은 캐시하지 않는다. 공개 시각은 다음 거래일 08:00 로 가정(미실측).
- DART `list.json` 은 `pblntf_detail_ty` 를 무시한다. `estkRs.json` 은 회사당 최신 정정본 한 건만, 확정 전 값으로 준다 → 확정 공모가는 발행조건확정 원문 + 증권발행실적보고서로 구한다.
- 상장일 기준가(`종가 − 전일대비`)는 공모가와 다를 수 있다 (진코스텍 23,850 vs 23,500). 공모가의 주 출처는 DART.
- 상장 뒤의 발행조건확정 공시는 유상증자 등 다른 공모다 → IPO 확정가 후보에서 뺀다.

## 데이터 이용 조건
- 이 프로젝트의 결과물은 **KRX statistical information**(한국거래소 통계정보)과 DART 공시를 이용해 만들었다.
- KRX OPEN API 약관(영문): 비상업적 목적으로만 사용(Art.6(2)), KRX 데이터를 제3자에게 제공 금지(Art.11(2)), 결과 페이지에 "KRX statistical information" 명시(Art.10(3)), 키당 하루 10,000회(Art.8(4)).
  그래서 KRX 원본 응답(`data/`)과 응답 발췌(`tests/fixtures_real/`)는 저장소에 올리지 않고, 저장소에는 가공한 결과 문서만 둔다.

## 아직 안 하는 것
수요예측·확약·유통가능 물량(DART 원문 표 파싱), SEIBRO 보호예수 해제, 투자자별 매매, 키움 분봉·15:20 스냅샷, 기술특례 구분, 매크로 국면, 전략 A·B·C 와 M1/M3 모듈.
