"""Starts the journal. Usage: python run.py [--demo] [--port 8765]"""
import argparse
import os
import threading
import webbrowser
from pathlib import Path

import uvicorn

from app.main import create_app

ROOT = Path(__file__).parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true", help="use sample data in a separate database")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    os.environ["JOURNAL_PORT"] = str(args.port)
    path = ROOT / "data" / ("demo.db" if args.demo else "journal.db")
    if args.demo:
        from tools.demo import seed
        seed(path)
    app = create_app(path, demo=args.demo, background=True)
    url = f"http://127.0.0.1:{args.port}"
    if not args.no_browser:
        threading.Timer(1.2, webbrowser.open, [url]).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
