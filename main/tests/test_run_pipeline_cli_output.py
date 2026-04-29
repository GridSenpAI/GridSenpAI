from __future__ import annotations

from io import BytesIO

from app.orchestration.run_pipeline import safe_print_json


class _Cp1252Stdout:
    def __init__(self) -> None:
        self.encoding = "cp1252"
        self.buffer = BytesIO()

    def write(self, text: str) -> int:
        text.encode(self.encoding)
        return len(text)

    def flush(self) -> None:
        return None


class _FailingStdout(_Cp1252Stdout):
    def write(self, text: str) -> int:
        text.encode(self.encoding)
        return super().write(text)



def test_safe_print_json_falls_back_for_non_encodable_console(monkeypatch) -> None:
    stdout = _Cp1252Stdout()
    monkeypatch.setattr("sys.stdout", stdout)

    safe_print_json({"bullet": "\u25e6 item"})

    rendered = stdout.buffer.getvalue().decode("cp1252")
    assert rendered.endswith("\n")
    assert '"bullet": "? item"' in rendered
