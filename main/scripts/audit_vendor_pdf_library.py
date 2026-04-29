from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.rebuild_pdf_library_index import refresh_index


def main() -> int:
    knowledge_root = REPO_ROOT / "knowledge"
    summary = refresh_index(knowledge_root=knowledge_root, write=False)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())