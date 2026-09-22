# TraceDown

A personal-use desktop app that downloads your own Trace game videos as 1080p MP4 files, directly to your Mac or Windows PC. You supply your own Trace subscription login. No third-party accounts, no cloud storage.

Trace records each game in two halves. TraceDown downloads both and **automatically stitches them into a single, continuous MP4**, losslessly, with no re-encoding or quality loss, so you get one ready-to-watch file per game instead of two clips. The result is a standard MP4 you can **upload straight to YouTube** (or Hudl, Google Drive, etc.) with no extra editing or conversion.

<p align="center">
  <img src="assets/screenshot.png" alt="TraceDown app window" width="420">
</p>

> Unofficial tool, not affiliated with or endorsed by Trace. For use with your own footage and your own Trace subscription.
> *(Screenshot uses demo data.)*

---

## Download

Go to the [**Releases**](../../releases/latest) page and download the zip for your platform:

- `TraceDown-macOS-AppleSilicon.zip` for Mac (Apple Silicon: M1/M2/M3/M4)
- `TraceDown-macOS-Intel.zip` for Mac (Intel)
- `TraceDown-Windows.zip` for Windows (x64)

---

## Install

### macOS

1. Unzip the download for your Mac (**Apple Silicon** for M1/M2/M3/M4, **Intel** otherwise; click  → *About This Mac* if unsure).
2. Drag **TraceDown** into your **Applications** folder.
3. Double-click to open. The app is signed with a Developer ID and notarized by Apple, so it opens normally, with no security workaround needed.

### Windows

Requires Windows 10/11 (x64) and the [Microsoft Edge WebView2 Evergreen Runtime](https://developer.microsoft.com/microsoft-edge/webview2/). If TraceDown reports that WebView2 is missing, install the runtime and reopen the app.

1. Extract **all files** from `TraceDown-Windows.zip` into a folder. Keep the `_internal` folder alongside the executable.
2. Double-click `TraceDown.exe`.
3. If Windows SmartScreen appears, click **More info → Run anyway** (one-time prompt for unsigned apps).

The bundled Chromium engine downloads videos; WebView2 displays the app itself. Both are needed. Older builds may display a JavaScript “Syntax error” when WebView2 is missing and Windows falls back to Internet Explorer.

---

## First Launch

On **macOS**, the first launch downloads the video engine (Chromium, ~170 MB, one time). The **Windows** build already includes it. Once ready:

1. Click **+ Add account**.
2. Log in with your Trace email address and the phone verification code.
3. Your games appear in the list.

---

## Usage

- Click a game to download it to your chosen output folder. Both halves are fetched and **automatically stitched into one continuous 1080p MP4**. The stitch is lossless (a direct stream copy, no re-encoding), and the separate half files are removed once the combined video is ready.
- Prefer the two halves as separate files? Turn off **Combine halves** in Settings.
- Turn on **Auto-download** in Settings to automatically check for and download new games every 3 hours.

---

## Maintainer / Cutting a Release

Before tagging, regenerate icons if the icon source changed:

```bash
python assets/make_icon.py
```

To publish a new release, tag and push. GitHub Actions builds both installers and attaches them to the Release automatically:

```bash
git tag v1.x
git push origin v1.x
```

The Actions workflow (`.github/workflows/build.yml`) runs a matrix build on `macos-latest` and `windows-latest`, produces `TraceDown-macOS.zip` and `TraceDown-Windows.zip`, and attaches both to the GitHub Release.
