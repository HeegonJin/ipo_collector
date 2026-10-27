"""L4~L6(판단 계층)이 PitReader 밖으로 새지 않는지 소스를 읽어 검사한다.

판단 코드가 파일·네트워크·정산(evaluate)에 닿으면 as_of 이후 데이터가 새어 들어올 수 있다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.boundaries import DECISION_PACKAGES, find_violations, scan_packages  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def test_decision_layers_have_no_violations():
    assert scan_packages(ROOT) == []


def test_scanned_packages_exist_and_are_nonempty():
    for pkg in DECISION_PACKAGES:
        assert list((ROOT / pkg).glob("*.py")), f"{pkg} 가 비어 있거나 없다 (검사가 헛돌 수 있음)"


def test_detects_forbidden_imports():
    for src in ("import evaluate.outcomes", "from evaluate import outcomes", "import requests",
                "from config import MART", "import csv", "from krx_api import fetch", "import pandas as pd"):
        assert find_violations(src), src


def test_detects_file_reads_and_calls():
    assert find_violations("data = open('x.csv').read()")
    assert find_violations("p.read_text()")
    assert find_violations("pd.read_csv('a')")


def test_detects_wall_clock_reads_and_randomness():
    """판단은 as_of 만으로 결정돼야 한다. 현재 시각·난수를 읽으면 백테스트와 모의 운영 결과가 갈라진다."""
    for src in ("from datetime import datetime\nx = datetime.now()", "import datetime\nx = datetime.datetime.today()",
                "x = date.today()", "x = datetime.utcnow()", "import time", "import random", "from random import choice"):
        assert find_violations(src), src


def test_detects_dynamic_imports_processes_and_sockets():
    for src in ("import importlib", "m = __import__('os')", "import subprocess", "import socket",
                "import urllib.request", "eval('1')", "exec('x = 1')", "importlib.import_module('os')"):
        assert find_violations(src), src


def test_allows_pit_schema_and_stdlib_value_types():
    ok = ("from core.pit import PitReader\nfrom core.schema import Fact\nfrom core.tradingcal import KST\n"
          "from dataclasses import dataclass\nfrom datetime import datetime, time\n")
    assert find_violations(ok) == []
