import sys
from types import SimpleNamespace

import pytest

from gui import runtime


@pytest.mark.parametrize("renderer", ["mshtml", "edgechromium"])
def test_windows_requires_webview2(monkeypatch, renderer):
    monkeypatch.setattr(runtime.sys, "platform", "win32")
    calls = []
    def initialize(gui):
        calls.append(gui)
        return SimpleNamespace(renderer=renderer)
    monkeypatch.setitem(sys.modules, "webview.guilib", SimpleNamespace(initialize=initialize))
    if renderer == "mshtml":
        with pytest.raises(RuntimeError, match="WebView2 Runtime"):
            runtime.prepare_renderer()
    else:
        assert runtime.prepare_renderer() == "edgechromium"
    assert calls == ["edgechromium"]


def test_mac_keeps_default_renderer(monkeypatch):
    monkeypatch.setattr(runtime.sys, "platform", "darwin")
    assert runtime.prepare_renderer() is None
