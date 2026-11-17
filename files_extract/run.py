#!/usr/bin/env python3
"""
ShyamX backend-only launcher.

The website is deployed separately on Vercel. This launcher intentionally does NOT
install, build, start, or require Node.js/the web project. It only runs CodeX.py,
which contains the Discord bot and FastAPI backend.

    python run.py --init     create .env with generated secrets, then exit
    python run.py --check    validate configuration and exit
    python run.py            preflight, then run CodeX.py
"""
from __future__ import annotations

import os
import secrets
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent

PLACEHOLDERS = {"", "changeme", "change_this", "xxx", "your_discord_bot_token_here"}


# ───────────────────────── .env handling ─────────────────────────

def load_env(path: Path) -> dict[str, str]:
    """Minimal .env parser (KEY=value, optional quotes, # comments). No dependency needed."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        else:
            val = val.split(" #")[0].strip()
        values[key] = val
    return values


def is_placeholder(value: str) -> bool:
    v = value.strip().lower()
    return (
        v in PLACEHOLDERS
        or v.startswith("change_this")
        or v.startswith("your_")
        or v.startswith("xxx")
        or "example.com" in v
    )


def cmd_init() -> int:
    target = ROOT / ".env"
    if target.exists():
        print(".env already exists — leaving it untouched.")
        return 0
    template = (ROOT / ".env.example").read_text(encoding="utf-8")
    template = template.replace("__GENERATE_API_KEY__", secrets.token_hex(24))
    template = template.replace("__GENERATE_SESSION_SECRET__", secrets.token_hex(32))
    target.write_text(template, encoding="utf-8")
    try:
        target.chmod(0o600)
    except OSError:
        pass
    print("Created .env with generated DASHBOARD_API_KEY and DASHBOARD_SESSION_SECRET.")
    print("Now edit it and fill in: TOKEN, OWNER_IDS, DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, PUBLIC_URL.")
    return 0


def preflight(env: dict[str, str]) -> list[str]:
    """Return a list of blocking problems (empty = good to go)."""
    problems: list[str] = []

    def need(key: str, hint: str) -> None:
        if is_placeholder(env.get(key, "")):
            problems.append(f"{key} is not set. {hint}")

    need("TOKEN", "Discord bot token from https://discord.com/developers/applications")
    need("OWNER_IDS", "Comma-separated Discord user IDs of the bot owners (also grants /admin access).")
    need("DISCORD_CLIENT_ID", "OAuth2 application ID (same application as the bot).")
    need("DISCORD_CLIENT_SECRET", "OAuth2 client secret (Discord developer portal > OAuth2).")
    need("PUBLIC_URL", "The public address of the site, e.g. https://shyamx.example.com (used for Discord login).")

    key = env.get("DASHBOARD_API_KEY", "")
    if is_placeholder(key) or len(key) < 24:
        problems.append("DASHBOARD_API_KEY must be a random string of 24+ characters. Run: python run.py --init")
    sec = env.get("DASHBOARD_SESSION_SECRET", "")
    if is_placeholder(sec) or len(sec) < 32:
        problems.append("DASHBOARD_SESSION_SECRET must be a random string of 32+ characters. Run: python run.py --init")

    if env.get("PUBLIC_URL", "").lower().startswith("http://") and "localhost" not in env.get("PUBLIC_URL", "").lower():
        print("WARNING: PUBLIC_URL is plain http://. Logins work, but traffic (including the session cookie) is unencrypted. "
              "Use HTTPS in production (see DEPLOY.md).")
    return problems


# ───────────────────────── supervision ─────────────────────────

class Service(threading.Thread):
    def __init__(self, name: str, argv: list[str], cwd: Path, env: dict[str, str], stop: threading.Event):
        super().__init__(name=name, daemon=True)
        self.svc = name
        self.argv, self.cwd, self.env, self.stop_evt = argv, cwd, env, stop
        self.proc: subprocess.Popen | None = None

    def _pump(self, stream) -> None:
        for line in iter(stream.readline, ""):
            print(f"[{self.svc}] {line.rstrip()}", flush=True)

    def run(self) -> None:
        delay = 1.0
        while not self.stop_evt.is_set():
            started = time.time()
            print(f"[run] starting {self.svc}: {' '.join(self.argv)}", flush=True)
            try:
                self.proc = subprocess.Popen(
                    self.argv, cwd=self.cwd, env=self.env,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                )
            except OSError as exc:
                print(f"[run] could not start {self.svc}: {exc}", flush=True)
                self.stop_evt.wait(30)
                continue
            threading.Thread(target=self._pump, args=(self.proc.stdout,), daemon=True).start()
            code = self.proc.wait()
            if self.stop_evt.is_set():
                return
            ran = time.time() - started
            delay = 1.0 if ran > 60 else min(delay * 2, 60.0)
            print(f"[run] {self.svc} exited with code {code} after {ran:.0f}s; restarting in {delay:.0f}s "
                  f"(the other service keeps running)", flush=True)
            self.stop_evt.wait(delay)

    def terminate(self) -> None:
        p = self.proc
        if p and p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=15)
            except subprocess.TimeoutExpired:
                p.kill()


def main() -> int:
    args = set(sys.argv[1:])
    if "--init" in args:
        return cmd_init()

    file_env = load_env(ROOT / ".env")
    env = {**file_env, **os.environ}
    print(f"[run] TUNNEL_ENABLED from environment = {env.get('TUNNEL_ENABLED')!r}", flush=True)

    problems = preflight(env)
    if "--check" in args:
        for problem in problems:
            print("✗", problem)
        print("Configuration OK." if not problems else f"{len(problems)} problem(s) found.")
        return 1 if problems else 0

    if problems:
        print("ShyamX can't start yet:\n")
        for problem in problems:
            print("  ✗", problem)
        print("\nFix these in .env and try again.")
        return 1

    shared = {
        **env,
        "API_ENABLED": "true",
        "API_HOST": env.get("API_HOST") or "0.0.0.0",
        "API_PORT": env.get("API_PORT", "8000"),
        "ADMIN_DISCORD_IDS": env.get("ADMIN_DISCORD_IDS") or env.get("OWNER_IDS", ""),
        "PYTHONUNBUFFERED": "1",
    }

    stop = threading.Event()
    bot = Service("bot", [sys.executable, "CodeX.py"], ROOT, shared, stop)

    def shutdown(*_):
        if not stop.is_set():
            print("\n[run] shutting down…", flush=True)
            stop.set()
            bot.terminate()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print("[run] ShyamX backend starting — Discord Bot + FastAPI only", flush=True)
    print(f"[run] API: {shared['API_HOST']}:{shared['API_PORT']}", flush=True)
    print("[run] Website: NOT managed by run.py (deployed separately)", flush=True)

    bot.start()
    while not stop.is_set():
        time.sleep(0.5)
    bot.join(timeout=20)
    return 0


if __name__ == "__main__":
    sys.exit(main())
