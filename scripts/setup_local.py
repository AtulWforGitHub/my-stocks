#!/usr/bin/env python3
"""ONE-COMMAND local setup (Windows, macOS or Linux).

    py -3.12 scripts\\setup_local.py

It creates the Python environment OUTSIDE this folder, installs the packages, writes two launchers
(run-mis.bat = daily update, Open-MIS.bat = open the dashboard), schedules the daily update, and runs the first full update.
Options: --no-schedule, --skip-first-run, --skip-install, --time 17:30, --venv PATH, --dry-run
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IS_WIN = platform.system() == "Windows"


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if IS_WIN else "bin/python")


def write_launchers(py: Path, port: int) -> list[Path]:
    run_bat = ROOT / "run-mis.bat"
    run_bat.write_text(f'@echo off\r\ncd /d "%~dp0"\r\nif not exist logs mkdir logs\r\n"{py}" -m mis.run --fill >> logs\\mis.log 2>&1\r\n', encoding="ascii")
    open_bat = ROOT / "Open-MIS.bat"
    open_bat.write_text(f'@echo off\r\ncd /d "%~dp0"\r\nstart "MIS server" /min "{py}" -m http.server {port} --directory docs\r\n'
                        f'timeout /t 2 >nul\r\nstart "" "http://localhost:{port}"\r\n', encoding="ascii")
    return [run_bat, open_bat]


def sh(cmd, dry, **kw):
    print("  >", " ".join(str(c) for c in cmd))
    if not dry:
        subprocess.run([str(c) for c in cmd], check=True, **kw)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--venv", default=str(Path.home() / "mis-venv"))
    ap.add_argument("--time", default="17:30", help="daily update time, 24h HH:MM (NSE closes 15:30 IST)")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-schedule", action="store_true"); ap.add_argument("--skip-first-run", action="store_true")
    ap.add_argument("--skip-install", action="store_true"); ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    venv = Path(a.venv); py = venv_python(venv)

    print("1/5 Python environment (kept outside this folder, so unzipping a new version never deletes it)")
    if not py.exists():
        sh([sys.executable, "-m", "venv", venv], a.dry_run)
    print("2/5 Installing packages")
    if not a.skip_install:
        sh([py, "-m", "pip", "install", "--quiet", "-r", ROOT / "requirements.txt"], a.dry_run)
    print("3/5 Writing launchers")
    for f in write_launchers(py, a.port):
        print("  wrote", f.name)
    print("4/5 Scheduling the daily update")
    if a.no_schedule:
        print("  skipped (--no-schedule)")
    elif IS_WIN:
        sh(["schtasks", "/Create", "/F", "/SC", "DAILY", "/ST", a.time, "/TN", "MIS daily", "/TR", f'"{ROOT / "run-mis.bat"}"'], a.dry_run)
        print("  The PC must be on and you must be signed in at that time. The tool skips weekends and NSE holidays by itself.")
    else:
        print(f'  Add this line with "crontab -e":  {a.time.split(":")[1]} {a.time.split(":")[0]} * * 1-5 cd "{ROOT}" && "{py}" -m mis.run --fill >> logs/mis.log 2>&1')
    print("5/5 First full update (about 10-25 minutes; repeats itself until every company is screened)")
    if a.skip_first_run:
        print("  skipped (--skip-first-run)")
    else:
        sh([py, "-m", "mis.run", "--fill", "--no-email", "--force"], a.dry_run, cwd=ROOT)
    print("\nDone. To open the dashboard, double-click Open-MIS.bat" if IS_WIN else "\nDone. Run: python -m http.server 8000 --directory docs  and open http://localhost:8000")
    if a.dry_run:
        print("(dry run: no environment, schedule or update was actually created)")


if __name__ == "__main__":
    main()
