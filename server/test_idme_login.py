#!/usr/bin/env python3
"""
Standalone IDME portal automation test (login + read student list).

READ-ONLY: this script logs into the live IDME/MOEIS portal, navigates to the
attendance page, extracts cookies/CSRF, and reads the student table. It does
NOT mark anyone absent and does NOT submit anything.

Credentials are read from `.idme-test.env` (gitignored) in this directory, or
from the IDME_TEST_IC / IDME_TEST_PASSWORD environment variables.

Usage:
    cd server/
    . .venv-idme/bin/activate
    python test_idme_login.py            # visible browser (default)
    python test_idme_login.py --headless # no window
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# Make `src` importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.idme.login_engine import IDMELoginEngine, LoginEngineError
from src.idme.form_filler import IDMEFormFiller, FormFillerError


def load_env_file(path: Path) -> None:
    """Minimal .env loader (KEY=VALUE lines) into os.environ."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def get_credentials() -> tuple[str, str]:
    load_env_file(Path(__file__).resolve().parent / ".idme-test.env")
    ic = os.getenv("IDME_TEST_IC", "").strip()
    password = os.getenv("IDME_TEST_PASSWORD", "").strip()
    if not ic or not password:
        sys.exit(
            "ERROR: credentials missing.\n"
            "Create server/.idme-test.env from .idme-test.env.example, "
            "or set IDME_TEST_IC and IDME_TEST_PASSWORD."
        )
    return ic, password


async def run(headless: bool, debug: bool) -> int:
    ic, password = get_credentials()

    engine = IDMELoginEngine(
        ic_number=ic,
        password=password,
        headless=headless,
        debug=debug,
        timeout=30000,
    )

    masked_ic = ic[:4] + "*" * max(0, len(ic) - 6) + ic[-2:]
    print(f"\n=== IDME login test (IC {masked_ic}, headless={headless}) ===\n")

    try:
        session = await engine.login_and_navigate()
    except LoginEngineError as e:
        print(f"\nLOGIN FAILED: {e}")
        return 1

    print("\n--- Login result ---")
    print(f"  success     : {session['success']}")
    print(f"  duration    : {session['duration']:.1f}s")
    print(f"  cookies     : {len(session['cookies'])}")
    print(f"  csrf token  : {'present' if session['csrf_token'] else 'MISSING'}")
    print(f"  current url : {engine.page.url}")

    # READ-ONLY: read the student table (no marking, no submit)
    print("\n--- Reading student table (read-only) ---")
    rc = 0
    try:
        filler = IDMEFormFiller(engine.page, debug=debug)
        students = await filler.get_student_list()
        print(f"  students found: {len(students)}")
        for i, s in enumerate(students[:10], 1):
            print(f"    {i:>2}. {s['name']}  (id={s['id']})")
        if len(students) > 10:
            print(f"    ... and {len(students) - 10} more")
    except FormFillerError as e:
        print(f"  could not read student table: {e}")
        print("  (The attendance page may require selecting a class/date first.)")
        rc = 2

    if not headless:
        print("\nBrowser stays open 20s so you can inspect the page...")
        await engine.page.wait_for_timeout(20000)

    await engine.close()
    print("\nDone. (No data was submitted.)")
    return rc


def main() -> int:
    parser = argparse.ArgumentParser(description="IDME login + read-only student list test")
    parser.add_argument("--headless", action="store_true", help="run browser without a window")
    parser.add_argument("--debug", action="store_true", help="save screenshots on errors")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    return asyncio.run(run(headless=args.headless, debug=args.debug))


if __name__ == "__main__":
    raise SystemExit(main())
