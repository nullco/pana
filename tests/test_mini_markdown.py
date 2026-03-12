from rich.console import Console

from app.tui import mini


def _render_to_ansi(text: str) -> str:
    console = Console(force_terminal=True, color_system="truecolor", width=80)
    with console.capture() as capture:
        console.print(mini._render_markdown(text))
    return capture.get()


def test_render_markdown_highlights_code_block() -> None:
    rendered = _render_to_ansi("```python\nprint('hi')\n```")

    assert "print('hi')" in rendered
    assert "```" not in rendered
    assert "\x1b[" in rendered


def test_render_markdown_handles_plain_text() -> None:
    rendered = _render_to_ansi("Hello world")

    assert "Hello world" in rendered


def test_install_resize_handler_triggers_refresh(monkeypatch) -> None:
    if not hasattr(mini.signal, "SIGWINCH"):
        return

    calls: list[tuple[int, object]] = []
    handler = object()

    def fake_getsignal(signum):
        return handler

    def fake_signal(signum, new_handler):
        calls.append((signum, new_handler))
        return None

    class DummyLive:
        def __init__(self):
            self.refreshed = False

        def refresh(self):
            self.refreshed = True

    monkeypatch.setattr(mini.signal, "getsignal", fake_getsignal)
    monkeypatch.setattr(mini.signal, "signal", fake_signal)

    live = DummyLive()
    restore = mini._install_resize_handler(live)

    assert calls
    _, installed_handler = calls[-1]
    installed_handler(mini.signal.SIGWINCH, None)
    assert live.refreshed

    restore()
    assert calls[-1][1] is handler
