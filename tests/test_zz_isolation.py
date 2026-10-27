"""다른 테스트가 config 전역값(경로·기간)을 임시 값으로 바꿔 둔 채 끝나지 않았는지 마지막에 확인한다.
파일 이름을 zz 로 시작해 전체 실행에서 마지막에 돌게 했다."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402


def test_config_globals_are_not_leaked_by_other_tests():
    root = Path(config.__file__).resolve().parent
    assert config.ROOT == root
    assert config.RAW == root / "data" / "0_raw"
    assert config.MART == root / "data" / "2_mart"
    assert config.META == root / "data" / "_meta"
    assert (config.BUFFER_START, config.SAMPLE_START) == ("20230101", "20230701")
