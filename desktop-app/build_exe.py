"""Build the Petabyte Desktop Agent into a single-file executable.

    python build_exe.py

On Windows this produces  dist/PetabyteAgent.exe  (double-clickable, no console).
On Linux/macOS it produces a native binary of the same name — useful for verifying
the build config; a Windows .exe must be built on Windows (PyInstaller does not
cross-compile). See BUILD.md for the GitHub Actions Windows build.
"""
import os
import sys
import PyInstaller.__main__

# Windows CI consoles default to cp1252, which can't encode characters like the
# arrow below; force UTF-8 so a print can never crash the build script.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
SEP = ";" if os.name == "nt" else ":"        # --add-data separator is OS-specific
ICON = os.path.join(HERE, "petabyte.ico")


def build_exe():
    print("Building Petabyte Desktop Agent...")
    args = [
        "petabyte_desktop.py",
        "--name=PetabyteAgent",
        "--onefile",
        "--windowed",                        # no console window
        f"--add-data=templates{SEP}templates",
        # Flask / web
        "--collect-all=flask",
        "--collect-all=httpx",
        # attestation + agent deps that PyInstaller can miss
        "--hidden-import=cryptography",
        "--collect-all=cryptography",
        "--hidden-import=dotenv",
        "--hidden-import=nbformat",
        "--hidden-import=nbclient",
        "--hidden-import=requests",
        # local modules bundled explicitly (imported lazily/by string)
        "--hidden-import=task_fetcher",
        "--hidden-import=crypto",
        "--hidden-import=vm",
        "--hidden-import=notebook",
        "--hidden-import=provision",
        "--hidden-import=updater",
        "--hidden-import=version",
        "--noconfirm",
        "--clean",
    ]
    if os.path.exists(ICON):
        args.append(f"--icon={ICON}")

    try:
        PyInstaller.__main__.run(args)
    except Exception as e:                    # noqa: BLE001
        print(f"\n[fail] Build failed: {e}")
        print("Install the build deps first:  pip install -r requirements.txt pyinstaller")
        sys.exit(1)
    exe = "dist/PetabyteAgent.exe" if os.name == "nt" else "dist/PetabyteAgent"
    print(f"\n[ok] Build complete -> {exe}")


if __name__ == "__main__":
    build_exe()
