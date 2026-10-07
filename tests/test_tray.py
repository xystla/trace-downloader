import sys
from types import SimpleNamespace


def _fake_pystray(monkeypatch):
    """pystray with a menu that just keeps its items, and an icon that never shows."""
    made = {}
    class MenuItem:
        def __init__(self, text, action, default=False, enabled=True, visible=True):
            self.text, self.action, self.default, self.enabled, self.visible = text, action, default, enabled, visible
    class Menu:
        SEPARATOR = "---"
        def __init__(self, *items):
            self.items = items
    class Icon:
        def __init__(self, name, image, title, menu):
            made["menu"], made["icon"] = menu, self
            self.updates = 0
        def run_detached(self, setup=None):
            pass
        def update_menu(self):
            self.updates += 1
    monkeypatch.setitem(sys.modules, "pystray", SimpleNamespace(Icon=Icon, Menu=Menu, MenuItem=MenuItem))
    return made


def _value(thing):
    return thing(None) if callable(thing) else thing


def test_the_tray_menu_leads_with_what_the_app_is_doing(monkeypatch):
    from gui import tray
    monkeypatch.setattr(tray, "_image", lambda: None)
    made = _fake_pystray(monkeypatch)
    said = {"status": "", "expired": False}
    opened = []
    icon = tray.Tray.start(lambda: opened.append("open"), lambda: None, lambda: None, visible=True,
                           status=lambda: said["status"], expired=lambda: said["expired"])
    status, reconnect = made["menu"].items[0], made["menu"].items[1]
    assert _value(status.visible) is False and _value(reconnect.visible) is False       # nothing to say yet
    said.update(status="Downloading vs Rovers · 42%", expired=True)
    assert _value(status.text) == "Downloading vs Rovers · 42%" and _value(status.visible) is True
    assert status.enabled is False                                                    # a line to read, not to click
    assert reconnect.text == "Reconnect to Trace…" and _value(reconnect.visible) is True
    reconnect.action()
    assert opened == ["open"]
    assert [i.text for i in made["menu"].items if not callable(getattr(i, "text", None)) and i != "---"][1:] == [
        "Open TraceDown", "Check for new games now", "Quit TraceDown"]
    monkeypatch.setattr(tray.sys, "platform", "win32")
    icon.refresh()
    assert made["icon"].updates == 1


def test_the_tray_still_starts_without_a_status(monkeypatch):
    from gui import tray
    monkeypatch.setattr(tray, "_image", lambda: None)
    made = _fake_pystray(monkeypatch)
    assert tray.Tray.start(lambda: None, lambda: None, lambda: None, visible=False) is not None
    assert _value(made["menu"].items[0].visible) is False
