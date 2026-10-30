"""DART 원문에서 수요예측 결과·의무보유 확약·유통가능 물량·락업 일정·청약 경쟁률을 뽑는 파서.
설계도(L1 1순위 코드 파서: 수요예측 결과, 확약 신청·배정, 유통가능주식, 청약 결과)와 검증 게이트
(배정 합계 = 공모 주식 수, 유통가능 + 제한 = 상장 주식 수)를 따른다. 실제 공시의 표 배치를 줄여 옮긴 문자열로 시험한다."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dart_demand  # noqa: E402

DEMAND = ("(12) 수요예측 결과(가) 수요예측 참여내역 구 분 국내기관투자자 해외기관투자자 합 계 운용사(집합) 투자매매,중개업자 "
          "연기금,운용사(고유),은행, 보험 기타 거래실적(유)(주1) 거래실적(무) "
          "건수 360 98 58 17 27 - 560 수량 26,372,000 5,156,000 5,050,000 3,200,000 76,000 - 39,854,000 "
          "경쟁률 20.73 4.05 3.97 2.52 0.06 - 31.33 주1) 인수인과 거래관계가 있는 외국기관투자자 (나) 수요예측 신청가격 분포 ")
COMMIT = ("(다) 의무보유 확약 기관수 및 신청수량 구 분 국내기관투자자 해외기관투자자 합 계 건수 수량 건수 수량 건수 수량 "
          "6개월 확약 - - - - - - - - - - - - - - 3개월 확약 30 171,000 - - - - - - - - - - 30 171,000 "
          "1개월 확약 - - - - - - - - - - - - - - 15일 확약 - - - - - - - - - - - - - - "
          "확약합계 30 171,000 - - - - - - - - - - 30 171,000 총 참여건수 및수량 대비 비율 (%) 8.33% 0.65% - - 5.36% 0.43% "
          "미확약 330 26,201,000 98 5,156,000 58 5,050,000 17 3,200,000 27 76,000 - - 530 39,683,000 "
          "합 계 360 26,372,000 98 5,156,000 58 5,050,000 17 3,200,000 27 76,000 - - 560 39,854,000 주1) 인수인과 ")
FLOAT_A = ("너. 상장 이후 유통물량 출회에 대한 위험 공모 주식을 포함하여 상장 후 당사 발행주식총수 (10,658,828주)의 25.73%에 해당하는 "
           "2,742,210주 는 상장 직후 유통가능물량입니다. 금번 공모 주식을 포함하여 당사의 상장예정주식수 10,658,828주 중 "
           "최대주주 유원양이 보유한 2,562,856주(공모 후 24.04% )는 상장일로부터 2년 6개월 간 의무보유하며, "
           "고수연 외 11인이 보유한 906,006주(공모 후 8.50% )는 상장일로부터 2년 간 의무보유할 예정입니다. "
           "투자기간이 2년 미만인 주식은 2,674,484주(공모 후 25.09% )입니다. 이중 1,283,293주(공모 후 12.04% )는 상장일로부터 1개월 간 "
           "의무보유할 예정이며, 884,379주(공모 후 8.30% )는 상장일로부터 1년, 253,406주(공모 후 2.38% )는 상장일로부터 3개월 "
           "의무보유할 예정입니다.")
FLOAT_B = ("총 2,900,000주 중 827,725주(공모 후 28.50%)는 상장 직후 시장에서 유통가능한 물량에 해당합니다. "
           "상장예정주식수 2,904,000주 기준입니다.")
RESULT = ("3. 청약 및 배정현황 (단위 : 원, 주, %) 구 분 최초 배정 청약 현황 최종 배정 현황 수량 비율 건수 수량 금액 비율 건수 수량 금액 비율 "
          "우리사주조합 - - - - - - - - - - 기관투자자 2,700,000 75.00 1,666 2,700,000 16,200,000,000 0.32 1,666 2,700,000 16,200,000,000 75.00 "
          "일반투자자 900,000 25.00 117,489 844,438,950 5,066,633,700,000 99.68 117,489 900,000 5,400,000,000 25.00 "
          "기타 - - - - - - - - - - 계 3,600,000 100 119,155 847,138,950 5,082,833,700,000 100 119,155 3,600,000 21,600,000,000 100 "
          "5. 기관투자자 의무보유확약기간별 배정현황 (단위 : 주, %) 확약기간 국내 기관투자자 외국 기관투자자 합계 수량 비중 수량 비중 "
          "6개월 30,913 1.67 - - - - 30,913 1.14 3개월 529,396 28.52 - - 5,214 2.99 534,610 19.80 "
          "1개월 93,593 5.04 4,387 2.51 5,045 1.43 103,025 3.82 15일 4,917 0.26 - - - - 4,917 0.18 "
          "미확약 1,197,212 64.50 14,729 100.00 164,993 94.50 2,026,535 75.06 계 1,856,031 100.00 14,729 100.00 2,700,000 100.00 "
          "Ⅲ. 유상증자 전후의 주요주주 지분변동")


# ── 수요예측 결과 ───────────────────────────────────────────────
def test_demand_row_is_read_from_the_total_column():
    d = dart_demand.parse_demand(DEMAND + COMMIT)
    assert (d["demand_n"], d["demand_qty"], d["demand_ratio"]) == (560, 39_854_000, 31.33)
    assert d["demand_status"] == "확인"


def test_demand_ratio_is_cross_checked_against_the_institutional_quantity():
    ok = dart_demand.parse_demand(DEMAND, offer_shares=1_800_000)          # 수량 / 경쟁률 = 1,272,000 ≤ 공모 주식 수
    assert ok["demand_status"] == "확인"
    bad = dart_demand.parse_demand(DEMAND, offer_shares=1_000_000)         # 기관 물량이 공모 전체보다 커질 수는 없다
    assert bad["demand_status"] == "미확인" and "공모" in bad["demand_note"]


def test_the_last_table_wins_so_the_corrected_filing_overrides_the_earlier_one():
    older = DEMAND.replace("31.33", "10.00").replace("39,854,000", "12,720,000")
    d = dart_demand.parse_demand("정정 전 " + older + " 정정 후 " + DEMAND)
    assert d["demand_ratio"] == 31.33


def test_missing_demand_table_is_unknown_not_zero():
    d = dart_demand.parse_demand("수요예측 결과가 없는 문서")
    assert d["demand_ratio"] is None and d["demand_status"] == "미확인"


def test_inconsistent_column_counts_are_not_trusted():
    bad = DEMAND.replace("경쟁률 20.73 4.05 3.97 2.52 0.06 - 31.33", "경쟁률 20.73 4.05 31.33")
    assert dart_demand.parse_demand(bad)["demand_status"] == "미확인"


# ── 의무보유 확약 (수요예측 단계) ────────────────────────────────
def test_commitment_ratio_is_committed_quantity_over_total_and_sums_are_checked():
    d = dart_demand.parse_demand(DEMAND + COMMIT)
    assert d["commit_qty"] == {"6m": 0, "3m": 171_000, "1m": 0, "15d": 0}
    assert d["commit_ratio"] == 171_000 / 39_854_000 and d["commit_status"] == "확인"


def test_commitment_with_a_sum_mismatch_is_flagged():
    d = dart_demand.parse_demand(DEMAND + COMMIT.replace("530 39,683,000", "530 39,000,000"))
    assert d["commit_status"] == "미확인" and d["commit_ratio"] is not None


def test_commitment_variants_total_row_name_period_label_and_stray_dot_cells():
    base = DEMAND + COMMIT
    assert dart_demand.parse_demand(base.replace("합 계 360", "총 합계 360"))["commit_status"] == "확인"          # '총 합계'
    assert dart_demand.parse_demand(base.replace("1개월 확약", "2주 확약").replace("15일 확약", "15일 확약"))["commit_status"] == "확인"
    assert dart_demand.parse_demand(base.replace("6개월 확약 - - -", "6개월 확약 - . -"))["commit_qty"]["6m"] == 0   # 빈 칸이 '.' 인 문서
    simple = DEMAND + "③ 의무보유 확약 신청내역 구 분 신청건수(건) 신청수량(주) 6개월 9 15,650,000 3개월 44 85,799,000 1개월 45 87,500,000 15일 5 9,750,000 합 계 103 198,699,000 "
    d = dart_demand.parse_demand(simple)
    assert d["commit_qty"]["3m"] == 85_799_000 and d["commit_status"] == "확인"
    assert d["commit_ratio"] == 198_699_000 / 39_854_000          # 간단한 표는 분모를 수요예측 참여 수량으로 한다


def test_no_commitment_table_gives_unknown():
    d = dart_demand.parse_demand(DEMAND)
    assert d["commit_ratio"] is None and d["commit_status"] == "미확인"


# ── 유통가능 물량 · 락업 일정 ────────────────────────────────────
def test_float_sentence_with_total_shares_is_checked_against_the_percentage():
    d = dart_demand.parse_demand(FLOAT_A)
    assert (d["float_shares"], d["listed_shares"], d["float_pct"]) == (2_742_210, 10_658_828, 25.73)
    assert d["float_status"] == "확인"


def test_float_percentage_that_disagrees_with_the_shares_is_unconfirmed():
    d = dart_demand.parse_demand(FLOAT_A.replace("25.73%", "35.73%"))
    assert d["float_status"] == "미확인" and d["float_shares"] == 2_742_210


def test_float_sentence_without_a_total_uses_the_listed_share_count_elsewhere():
    d = dart_demand.parse_demand(FLOAT_B)
    assert (d["float_shares"], d["listed_shares"]) == (827_725, 2_904_000)
    assert d["float_status"] == "확인"          # 827,725 / 2,904,000 = 28.50%


def test_float_without_any_total_is_unconfirmed():
    d = dart_demand.parse_demand("827,725주(공모 후 28.50%)는 상장 직후 시장에서 유통가능한 물량에 해당합니다.")
    assert d["float_shares"] == 827_725 and d["float_status"] == "미확인"


def test_lockup_schedule_groups_shares_by_months_after_listing():
    d = dart_demand.parse_demand(FLOAT_A)
    assert d["lockups"] == {30: 2_562_856, 24: 906_006, 1: 1_283_293, 12: 884_379, 3: 253_406}


def test_lockup_total_is_listed_minus_float_and_schedule_is_a_lower_bound():
    d = dart_demand.parse_demand(FLOAT_A)
    assert d["locked_total"] == 10_658_828 - 2_742_210
    assert sum(d["lockups"].values()) <= d["locked_total"]
    assert d["lockup_status"] == "미확인"       # 문장에서 읽은 일정 합이 제한 총량과 같지 않으면 일정은 참고용


def test_lockup_schedule_matching_the_locked_total_is_confirmed():
    text = ("상장 후 당사 발행주식총수 (1,000주)의 40.00%에 해당하는 400주는 상장 직후 유통가능물량입니다. "
            "300주(공모 후 30.00%)는 상장일로부터 6개월 간 의무보유하고 300주(공모 후 30.00%)는 상장일로부터 1년 간 의무보유합니다.")
    d = dart_demand.parse_demand(text)
    assert d["lockups"] == {6: 300, 12: 300} and d["lockup_status"] == "확인"


# ── 증권발행실적보고서: 청약 경쟁률, 확약 최종 배정 ──────────────
def test_retail_subscription_competition_is_subscribed_over_allocated():
    a = dart_demand.parse_allocation(RESULT)
    assert a["retail_ratio"] == 844_438_950 / 900_000 and a["retail_subscribers"] == 117_489
    assert a["alloc_status"] == "확인"


def test_final_commitment_ratio_is_one_minus_the_uncommitted_share():
    a = dart_demand.parse_allocation(RESULT)
    assert abs(a["final_commit_ratio"] - 0.2494) < 1e-9
    assert a["final_commit_pct"] == {"6m": 1.14, "3m": 19.80, "1m": 3.82, "15d": 0.18}


def test_commitment_percentages_that_do_not_sum_to_100_are_flagged():
    a = dart_demand.parse_allocation(RESULT.replace("2,026,535 75.06", "2,026,535 70.00"))
    assert a["alloc_status"] == "미확인"


def test_report_with_quantity_only_columns_derives_the_shares_from_quantities():
    head = RESULT[: RESULT.index("5. 기관투자자")]
    qty_table = ("5. 기관투자자 의무보유확약기간별 배정현황 (단위 : 주) 확약기간 국내 기관투자자 합계 건수 수량 건수 수량 "
                 "6개월 확약 7 60 10 100 3개월 확약 5 150 8 200 미확약 20 600 30 700 계 32 810 48 1,000 Ⅲ. 유상증자")
    a = dart_demand.parse_allocation(head + qty_table)
    assert abs(a["final_commit_ratio"] - 0.3) < 1e-9 and a["final_commit_pct"]["3m"] == 20.0 and a["alloc_status"] == "확인"
    bad = dart_demand.parse_allocation(head + qty_table.replace("30 700", "30 500"))
    assert bad["alloc_status"] == "미확인" and "배정 합계" in bad["alloc_note"]


def test_rounding_of_one_tenth_percent_is_tolerated_in_the_commitment_sum():
    a = dart_demand.parse_allocation(RESULT.replace("2,026,535 75.06", "2,026,535 75.16"))       # 합 100.10%
    assert a["alloc_status"] == "확인"


def test_report_without_the_tables_is_unknown():
    a = dart_demand.parse_allocation("증권발행실적보고서 해당사항 없습니다")
    assert a["retail_ratio"] is None and a["final_commit_ratio"] is None and a["alloc_status"] == "미확인"
