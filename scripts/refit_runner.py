"""Run the actual P03 browser regression on isolated loopback processes."""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def ready(url):
    for _ in range(100):
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:
            pass
        time.sleep(0.1)
    raise RuntimeError(f"browser prerequisite unavailable: {url}")


def main():
    with tempfile.TemporaryDirectory(prefix="p03-refit-") as temporary:
        temporary = Path(temporary)
        db = temporary / "demo.sqlite3"
        old_db = ROOT / "data" / "rfq.sqlite3"
        if old_db.exists():
            shutil.copy2(old_db, db)
        server = subprocess.Popen(
            [sys.executable, "-m", "rfq_review.server", "--port", "19103", "--db", str(db)],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        chrome = subprocess.Popen(
            ["/usr/bin/google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu",
             "--disable-dev-shm-usage", "--remote-debugging-address=127.0.0.1",
             "--remote-debugging-port=19113", f"--user-data-dir={temporary / 'chrome'}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            ready("http://127.0.0.1:19103/")
            ready("http://127.0.0.1:19113/json/version")
            env = dict(os.environ, RFQ_BROWSER_APP="http://127.0.0.1:19103",
                       RFQ_BROWSER_OUTPUT=str(ROOT / "docs" / "demo" / "refit"))
            subprocess.run([sys.executable, str(ROOT / "scripts" / "browser_check.py"),
                            "--cdp", "http://127.0.0.1:19113"],
                           cwd=ROOT, env=env, timeout=240, check=True)
        finally:
            for process in (chrome, server):
                process.terminate()
            for process in (chrome, server):
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()


if __name__ == "__main__":
    main()
