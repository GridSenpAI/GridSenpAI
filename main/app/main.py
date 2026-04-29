from __future__ import annotations

import sys

from app.orchestration.run_pipeline import main as cli_main


def _should_launch_ui(argv: list[str]) -> bool:
    normalized = {str(item).strip().lower() for item in argv}
    if "--cli" in normalized:
        return False
    if "--ui" in normalized:
        return True
    return len(argv) == 0


def main(argv: list[str] | None = None) -> int:
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    if _should_launch_ui(effective_argv):
        from app.ui.desktop_app import launch_desktop_app

        return launch_desktop_app()
    effective_argv = [item for item in effective_argv if str(item).strip().lower() not in {"--ui", "--cli"}]
    return cli_main(effective_argv)


if __name__ == "__main__":
    raise SystemExit(main())
