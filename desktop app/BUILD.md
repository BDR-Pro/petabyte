# Building the Petabyte Desktop Agent (.exe)

A double-clickable Windows app that runs the Petabyte node agent and a local
dashboard at http://127.0.0.1:5000. Same tested agent code as the Linux/WSL2
node — just packaged for the desktop.

## Option A — GitHub Actions (recommended, no Windows machine needed)
This repo ships `.github/workflows/build-desktop-exe.yml`. On every push (or via
"Run workflow"), a **windows-latest** runner builds the real `.exe` and uploads it
as a downloadable artifact named `PetabyteAgent-windows`. This is the easiest way
to get a genuine Windows binary from any OS.

## Option B — build locally on Windows
```powershell
cd "desktop app"
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt pyinstaller
python build_exe.py
```
Output: `dist\PetabyteAgent.exe`. No extra files needed — templates + icon are bundled.

## Run
Double-click `PetabyteAgent.exe`. The dashboard opens in your browser. Paste your
**API key** (from the `/keys` page or `POST /create_api_key`) and your **Spec ID**
(from `POST /register_specs`), click Save — the agent starts automatically.

## Honest limits
- PyInstaller does **not** cross-compile: a Windows `.exe` must be built on Windows
  (Option A or B). Building on Linux/macOS produces a native binary for that OS,
  which is only useful for verifying the build.
- **Job execution needs Docker.** The desktop app handles onboarding, attestation,
  heartbeats, status, and idle-fallback, but buyer jobs run in a Docker sandbox — so
  Docker Desktop (or the WSL2 path in `../lumaris_agent/WINDOWS.md`) must be present
  for the node to accept paid work. Without Docker the node still registers and shows
  status, it just won't be handed compute jobs.
- The `.exe` is unsigned. Windows SmartScreen may warn on first run ("More info →
  Run anyway"). Code-sign it for production distribution.
