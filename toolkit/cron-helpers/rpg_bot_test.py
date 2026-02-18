#!/usr/bin/env python3
"""Test the RPG bot GM capability with tool calling (one-shot).

Calls the GM bot once for the current act and exits.
All shared logic lives in rpg_bot_common.py.
"""

import sys
import time

from rpg_bot_common import (
    build_context, chat, process_response, run_rpg_cmd,
    get_act_kick, GM_SYSTEM_PROMPT,
)


def main():
    state, context = build_context()
    if state is None:
        print(f"ERROR: {context}", flush=True)
        sys.exit(1)

    print(f"Context built ({len(context)} chars). Starting bot.\n", flush=True)

    # Show thinking on overlay immediately
    map_name = state.get("map", {}).get("name", "the scene")
    run_rpg_cmd(["update-scene", "--narration",
                 f"The Game Master surveys {map_name}... (thinking)"])
    print(f"Overlay: 'GM thinking at {map_name}' — check OBS.", flush=True)

    act_num = state.get("session", {}).get("act", 1)
    user_kick = get_act_kick(act_num)

    messages = [
        {"role": "system", "content": GM_SYSTEM_PROMPT},
        {"role": "user", "content": context +
         f"\n\n{user_kick} Use ALL your tools — update_narration, move_token, log_action, roll_dice."},
    ]

    t0 = time.time()
    print(f"Sending to Ollama...", flush=True)

    response = chat(messages)
    elapsed = time.time() - t0
    msg = response.get("message", {})
    print(f"Response in {elapsed:.0f}s\n", flush=True)

    text = process_response(msg, messages)

    if text:
        print(f"\n=== TWITCH CHAT ===\n{text}\n", flush=True)
    else:
        print(f"\n(bot returned no text)\n", flush=True)

    print(f"=== FINAL STATE ===", flush=True)
    print(run_rpg_cmd(["status"]), flush=True)


if __name__ == "__main__":
    main()
