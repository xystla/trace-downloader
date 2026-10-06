"""The menu-bar (macOS) / system-tray (Windows) icon TraceDown lives behind while
automatic downloads are on and its window is closed."""
import sys


def _image():
    """The green play triangle, drawn here so no image file is needed."""
    from PIL import Image, ImageDraw
    size = 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(image).polygon([(14, 8), (14, 56), (56, 32)], fill=(61, 220, 132, 255))
    return image


class Tray:
    """Create with start(); None is returned where no tray is available."""

    def __init__(self, icon):
        self._icon = icon

    @classmethod
    def start(cls, on_open, on_check, on_quit, visible: bool):
        """Must be called on the main thread before the window loop starts (macOS)."""
        try:
            import pystray
            icon = pystray.Icon(
                "TraceDown", _image(), "TraceDown",
                pystray.Menu(pystray.MenuItem("Open TraceDown", lambda: on_open(), default=True),
                             pystray.MenuItem("Check for new games now", lambda: on_check()),
                             pystray.Menu.SEPARATOR,
                             pystray.MenuItem("Quit TraceDown", lambda: on_quit())))
            icon.run_detached(setup=lambda i: setattr(i, "visible", visible))
            return cls(icon)
        except Exception:
            return None

    def set_visible(self, visible: bool) -> None:
        def apply():
            try:
                self._icon.visible = visible
            except Exception:
                pass
        if sys.platform == "darwin":
            # Menu-bar items may only be touched from the main thread.
            try:
                from PyObjCTools import AppHelper
                AppHelper.callAfter(apply)
                return
            except Exception:
                pass
        apply()

    def stop(self) -> None:
        try:
            self._icon.stop()
        except Exception:
            pass
