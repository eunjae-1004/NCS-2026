from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.search_engine import NcsSearchEngine


def main() -> None:
    if len(sys.argv) < 2:
        print("사용법: python scripts/recommend_cli.py \"검색 문장\"")
        sys.exit(1)

    query = sys.argv[1]
    engine = NcsSearchEngine()

    bundle = engine.recommend(query)
    result_dict = engine.bundle_to_dict(bundle)

    # 사람이 읽기 쉽게 JSON 형태로 출력한다.
    print(json.dumps(result_dict, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
