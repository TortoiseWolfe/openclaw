#!/usr/bin/env python3
"""One-command launcher for RPG game night.

Chains init → set-crawl → live session runner. Used by the cron job
so the Ollama agent only needs to exec a single script with no flags
to get wrong.
"""

import subprocess
import sys

ADVENTURE = "escape-from-mos-eisley"
STATE = ["python3", "/app/toolkit/cron-helpers/rpg_state.py"]
RUNNER = ["python3", "/app/toolkit/cron-helpers/rpg_session_runner.py"]

CRAWL_TEXT = (
    "The galaxy is in turmoil. The evil GALACTIC EMPIRE tightens its grip "
    "on the Outer Rim, sending patrols to every spaceport."
    "|On the dusty streets of MOS EISLEY, a ragtag group of unlikely heroes "
    "finds themselves caught in a web of Imperial intrigue."
    "|With bounty hunters on their trail and Stormtroopers at every corner, "
    "they must find a way off this desert world before it is too late..."
)


def run(cmd: list[str]) -> None:
    print(f">> {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout.rstrip())
    if result.returncode != 0:
        print(f"ERROR (exit {result.returncode}): {result.stderr.rstrip()}")
        sys.exit(result.returncode)


def main():
    # 1. Init game state
    run([*STATE, "init", "--adventure", ADVENTURE, "--auto-join-bots"])

    # 2. Set opening crawl
    run([*STATE, "set-crawl",
         "--title", "STAR WARS",
         "--episode-title", "Escape from Mos Eisley",
         "--text", CRAWL_TEXT])

    # 3. Launch live session (long-running — blocks until session ends)
    print("\n>> Starting live session...")
    proc = subprocess.run([*RUNNER, "--live", "--adventure", ADVENTURE])
    sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
