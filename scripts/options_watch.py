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
import json
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
CT = ZoneInfo("America/Chicago")


def check_positions(path: Path, now: datetime) -> list[str]:
    """Alert once per condition on the user's real positions (stop/target/time/trend)."""
    if not path.exists():
        return []
    sys.path.insert(0, str(ROOT / "scripts"))
    import options_scorer as o  # noqa: PLC0415

    data = json.loads(path.read_text())
    latest = json.loads((ROOT / "docs" / "data" / "options" / "latest.json").read_text())
    scores = {r["symbol"]: r["score"] for r in latest["rankings"]}
    client, live = o.CboeClient(), o.NasdaqClient()
    alerts = []
    for p in data["positions"]:
        row = live.option_quote(p["contract"])  # fresher than Cboe's delayed chain
        if not row:
            try:
                row = next((x for x in client.chain(p["symbol"])["options"] if x["option"] == p["contract"]), {})
            except RuntimeError:
                continue
        mid, bid, ask, _ = o.quote_mid(row)
        if mid is None:
            continue
        pnl = (mid / p["fill"] - 1) * 100
        score = scores.get(p["symbol"])
        dte = (date.fromisoformat(p["expiration"]) - now.date()).days
        checks = {
            "target": mid >= p["target"],
            "stop": mid <= p["stop"],
            "time": now.date().isoformat() >= p["exit_by"],
            "trend": score is not None and ((p["type"] == "call" and score < 50) or (p["type"] == "put" and score > 50)),
        }
        label = {"target": "🟢 止盈到了", "stop": "🔴 止损到了", "time": "⏰ 时间退场",
                 "trend": "⚠️ 趋势反转"}
        for key, hit in checks.items():
            if hit and key not in p["alerted"]:
                p["alerted"].append(key)
                alerts.append(f"{label[key]}：{p['symbol']} {p['contract']} × {p['qty']}，"
                              f"现在 买{bid}/卖{ask}（中间价 {mid:.2f}），成本 {p['fill']}，盈亏 {pnl:+.0f}%，"
                              f"评分 {score}，剩 {dte} 天到期")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    return alerts


def sync_branch(branch: str, now: datetime) -> None:
    """Commit the scan's public data files and push them to the working branch."""
    git = ["git", "-C", str(ROOT)]
    subprocess.run(git + ["add", "docs/data/options"], capture_output=True)
    if subprocess.run(git + ["diff", "--cached", "--quiet"]).returncode == 0:
        return
    subprocess.run(git + ["commit", "-q", "-m", f"Options scan {now:%Y-%m-%d %H:%M} CT"], capture_output=True)
    push = subprocess.run(git + ["push", "-q", "origin", f"HEAD:{branch}"], capture_output=True, text=True)
    if push.returncode:
        print(f"push failed: {push.stderr.strip()[-200:]}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--every", type=int, default=5, help="minutes between scans")
    ap.add_argument("--max-minutes", type=int, default=110)
    ap.add_argument("--start", default="08:25", help="CT time to begin scanning")
    ap.add_argument("--until", default="15:05", help="CT time to stop scanning")
    ap.add_argument("--signal-file", type=Path, default=Path("/tmp/options-signal.json"))
    ap.add_argument("--push-branch", default="claude/jolly-goodall-r03ihs",
                    help="commit and push scan data to this branch after each scan ('' to disable)")
    ap.add_argument("--positions", type=Path, default=ROOT.parent / ".options-private" / "positions.json",
                    help="private file with the user's real fills (kept outside the repo)")
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
            if args.push_branch:
                sync_branch(args.push_branch, now)
            alerts = check_positions(args.positions, now)
            if alerts:
                args.signal_file.write_text(json.dumps({"title": "持仓提醒", "body": "\n".join(alerts)},
                                                       ensure_ascii=False))
            if args.signal_file.exists():
                print("SIGNAL", args.signal_file, flush=True)
                return 0
        if (time.monotonic() - started) / 60 + args.every > args.max_minutes:
            print("TIME_LIMIT", flush=True)
            return 0
        time.sleep(args.every * 60)


if __name__ == "__main__":
    sys.exit(main())
