#!/usr/bin/env python3
"""Run the options scan every N minutes and exit as soon as there is a signal.

Meant to run as a background job in a Claude session: the job's exit wakes
Claude, which reports the entry/exit to the user and restarts the watch.

Exit codes / last line:
  SIGNAL <path>   - new entry or exit; details in the JSON file
  WINDOW_END      - outside market hours (or past --until); nothing pending
  TIME_LIMIT      - ran for --max-minutes without a signal; restart to continue
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
CT = ZoneInfo("America/Chicago")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--every", type=int, default=10, help="minutes between scans")
    ap.add_argument("--max-minutes", type=int, default=110)
    ap.add_argument("--start", default="08:25", help="CT time to begin scanning")
    ap.add_argument("--until", default="15:05", help="CT time to stop scanning")
    ap.add_argument("--signal-file", type=Path, default=Path("/tmp/options-signal.json"))
    args = ap.parse_args()
    started = time.monotonic()
    args.signal_file.unlink(missing_ok=True)
    while True:
        now = datetime.now(CT)
        hm = now.strftime("%H:%M")
        if now.weekday() >= 5 or hm >= args.until:
            print("WINDOW_END", now.strftime("%Y-%m-%d %H:%M CT"), flush=True)
            return 0
        if hm >= args.start:
            proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "options_scorer.py"), "run",
                                   "--signal-file", str(args.signal_file)],
                                  capture_output=True, text=True)
            status = "ok" if proc.returncode == 0 else f"error {proc.returncode}: {proc.stderr.strip()[-200:]}"
            print(f"{now:%H:%M} scan {status}", flush=True)
            if args.signal_file.exists():
                print("SIGNAL", args.signal_file, flush=True)
                return 0
        if (time.monotonic() - started) / 60 + args.every > args.max_minutes:
            print("TIME_LIMIT", flush=True)
            return 0
        time.sleep(args.every * 60)


if __name__ == "__main__":
    sys.exit(main())
