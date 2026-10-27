"""판단 계층(L4~L6) 소스가 PitReader 밖으로 새지 않는지 AST 로 검사한다.

금지: 정산(evaluate)·설정/수집/저장 모듈·네트워크·파일/표 읽기 import 와 open/read_* 호출.
허용: core.pit, core.schema, core.tradingcal 과 표준 라이브러리의 값 타입(dataclasses, datetime 등).
"""
import ast
from pathlib import Path

DECISION_PACKAGES = ("decide", "strategies")  # modules/ 가 생기면 여기에 추가
FORBIDDEN_IMPORT_ROOTS = {
    "evaluate", "store", "config", "build_sample", "krx_api", "dart_api", "dart_list", "dart_estk", "dart_terms",
    "build_dart_registry", "report", "requests", "csv", "json", "pathlib", "os", "shutil", "sqlite3", "pandas", "numpy",
}
FORBIDDEN_CALLS = {"open", "read_text", "read_bytes", "read_csv", "read_json", "read_parquet"}


def find_violations(source: str) -> list[str]:
    out = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            out += [f"import {a.name}" for a in node.names if a.name.split(".")[0] in FORBIDDEN_IMPORT_ROOTS]
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] in FORBIDDEN_IMPORT_ROOTS:
            out.append(f"from {node.module} import ...")
        elif isinstance(node, ast.Call):
            f = node.func
            name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
            if name in FORBIDDEN_CALLS:
                out.append(f"call {name}()")
    return out


def scan_packages(root: Path) -> list[str]:
    found = []
    for pkg in DECISION_PACKAGES:
        for path in sorted((root / pkg).glob("*.py")):
            found += [f"{path.relative_to(root)}: {v}" for v in find_violations(path.read_text(encoding="utf-8"))]
    return found
