"""Manual-only public-data research CLI. NO BROKER access or trading tools."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "day_trader_skill"
ALLOWED = {
    "scanner": ("trader-scanner/scan.py", lambda symbol: ["daily", "--symbols", symbol]),
    "news": ("trader-news/news.py", lambda symbol: ["--tickers", symbol, "--hours", "24"]),
    "analyst": ("trader-analyst/facts.py", lambda symbol: [symbol]),
    "pelosi": ("trader-pelosi/ptr.py", lambda symbol: ["index", "--member", "pelosi"]),
}
TICKER = re.compile(r"[A-Z][A-Z0-9.\-]{0,9}\Z")


def command(tool, symbol):
    if tool not in ALLOWED:
        raise ValueError("Unknown or prohibited research tool")
    if not TICKER.fullmatch(symbol):
        raise ValueError("Ticker must be an uppercase symbol, not a command")
    script, args = ALLOWED[tool]
    path = VENDOR / script
    if not path.is_file():
        raise FileNotFoundError(path)
    return [sys.executable, str(path), *args(symbol)]


def main(argv=None):
    cli = argparse.ArgumentParser()
    cli.add_argument("--tool", choices=sorted(ALLOWED), required=True)
    cli.add_argument("--symbol", default="TQQQ")
    args = cli.parse_args(argv)
    # This process has no access to Webull credentials in the research workflow.
    # Upstream scripts may query public sources and write only research files.
    environment = {k: v for k, v in os.environ.items()
                   if not (k.startswith(("WEBULL_", "ALPACA_", "APCA_")) or
                           any(t in k for t in ("TOKEN", "SECRET", "API_KEY")))}
    print("RESEARCH_READ_ONLY " + args.tool + " " + args.symbol, flush=True)
    result = subprocess.run(command(args.tool, args.symbol),
                            cwd=str(ROOT), env=environment, check=False,
                            timeout=240)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
