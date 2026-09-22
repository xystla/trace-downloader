"""Require a modern renderer before loading the application's JavaScript."""
import sys


def prepare_renderer():
    if sys.platform != "win32":
        return None
    # Requesting edgechromium alone can still fall back to MSHTML in pywebview.
    from webview.guilib import initialize
    backend = initialize("edgechromium")
    if backend.renderer != "edgechromium":
        raise RuntimeError(
            "TraceDown requires Microsoft Edge WebView2 Runtime.\n\n"
            "Install the Evergreen Runtime from:\n"
            "https://developer.microsoft.com/microsoft-edge/webview2/\n\n"
            "Then reopen TraceDown. The bundled Chromium video engine does "
            "not replace WebView2."
        )
    return "edgechromium"


def show_startup_error(error):
    import ctypes
    ctypes.windll.user32.MessageBoxW(None, str(error), "TraceDown could not start", 0x10)
