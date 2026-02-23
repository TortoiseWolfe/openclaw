#!/usr/bin/env python3
"""RPG session runner — continuous game loop with persistent transcript.

Dry-run mode: bot plays all characters, objective-based pacing across 3 acts.
Live mode: integrates with Twitch chat for real player input.

Usage:
    rpg_session_runner.py --dry-run [--adventure escape-from-mos-eisley]
    rpg_session_runner.py --live    [--adventure escape-from-mos-eisley]
"""

import argparse
import json
import logging
import os
import pathlib
import random
import re
import signal
import tempfile
import time
from datetime import datetime

logger = logging.getLogger(__name__)

from module_loader import ModuleData, find_module
# ── In-memory cache for game-state.json (invalidated after run_rpg_cmd) ──
_state_cache: dict | None = None
_STATE_PATH = "/home/node/.openclaw/rpg/state/game-state.json"
_terrain_data_cache: dict | None = None
_terrain_map_key: str = ""


def _read_game_state() -> dict:
    """Return cached game state, loading from disk only on first call or after invalidation."""
    global _state_cache
    if _state_cache is None:
        try:
            with open(_STATE_PATH) as f:
                _state_cache = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            _state_cache = {}
    return _state_cache


def _invalidate_state_cache() -> None:
    """Clear the game state and terrain caches (call after any run_rpg_cmd that mutates state)."""
    global _state_cache, _terrain_data_cache, _terrain_map_key
    _state_cache = None
    _terrain_data_cache = None
    _terrain_map_key = ""


from rpg_bot_common import (
    ACT_MAPS,
    ACT_MAP_TERRAIN,
    CHAR_MOVE,
    CHAR_STATS,
    DEFAULT_DICE,
    DEFAULT_MOVE,
    GM_SYSTEM_PROMPT,
    build_context,
    calc_move_penalty,
    chat,
    clean_narration,
    get_act_kick,
    pre_roll_combat_round,
    pre_roll_skill_check,
    process_response,
    run_rpg_cmd,
)
from rpg_transcript import TranscriptLogger

# Module data loaded at session start — None means use hardcoded fallback
_module: ModuleData | None = None


def _mod(attr: str, default=None):
    """Safe access to the loaded module data, falling back to default."""
    return getattr(_module, attr, default) if _module else default


def _log_dice_to_state(char: str, skill: str, result: dict) -> None:
    """Write dice result to game-state.json so overlay plays SFX + popup."""
    args = ["log-dice", "--character", char, "--skill", skill,
            "--total", str(result["total"]),
            "--detail", result["detail"]]
    if result.get("difficulty") is not None:
        args += ["--difficulty", str(result["difficulty"])]
    if result.get("success") is not None:
        args += ["--success", "true" if result["success"] else "false"]
    run_rpg_cmd(args)


def _get_wound_level(character_name: str) -> int:
    """Read a character's current wound level from cached game state."""
    state = _read_game_state()
    for v, p in state.get("players", {}).items():
        if p.get("character") == character_name:
            return p.get("wound_level", 0)
    slug = character_name.lower().replace(" ", "-").replace("'", "")
    npc = state.get("npcs", {}).get(slug, {})
    return npc.get("wound_level", 0)



def _apply_wound(character_name: str, levels: int = 1) -> None:
    """Escalate wound level for a character after a combat hit."""
    state = _read_game_state()
    if not state:
        return
    current = 0
    # Check players
    for v, p in state.get("players", {}).items():
        if p.get("character") == character_name:
            current = p.get("wound_level", 0)
            break
    else:
        # Check NPCs
        slug = character_name.lower().replace(" ", "-").replace("'", "")
        npc = state.get("npcs", {}).get(slug, {})
        current = npc.get("wound_level", 0)
    new_level = min(current + levels, 5)
    if new_level > current:
        run_rpg_cmd(["wound", "--character", character_name, "--level", str(new_level)])
        _invalidate_state_cache()
        logger.info(f"  [wound] {character_name}: {current} -> {new_level}")


def _heal_wound(character_name: str, levels: int = 1) -> None:
    """Reduce wound level for a character after successful First Aid."""
    current = _get_wound_level(character_name)
    new_level = max(current - levels, 0)
    if new_level < current:
        run_rpg_cmd(["wound", "--character", character_name, "--level", str(new_level)])
        _invalidate_state_cache()
        logger.info(f"  [heal] {character_name}: {current} -> {new_level}")


# Characters that have the First Aid skill (fallback when no module loaded)
_HEALERS = {"Zeph Ando"}


def _check_heal_priority(char: str) -> tuple | None:
    """If char is a healer and an ally is wounded, return a heal action tuple."""
    healers = _mod("healers", _HEALERS)
    if char not in healers:
        return None
    # Find the most wounded able ally (wound_level 1-3)
    pregens = _mod("pregens", PREGENS)
    worst_char = ""
    worst_wl = 0
    for pc in pregens:
        if pc == char:
            continue
        wl = _get_wound_level(pc)
        if 1 <= wl <= 3 and wl > worst_wl:
            worst_wl = wl
            worst_char = pc
    if not worst_char:
        return None
    return (
        "do",
        f"*kneels beside {worst_char} and applies first aid*",
        "First Aid", None, 10, None,
    )


def _check_carry_priority(char: str) -> tuple | None:
    """If an ally is incapacitated (wl >= 3) and nearby, drag them to the ship."""
    pregens = _mod("pregens", PREGENS)
    for pc in pregens:
        if pc == char:
            continue
        wl = _get_wound_level(pc)
        if wl < 3:
            continue  # not incapacitated
        char_xy = _get_token_xy(char)
        ally_xy = _get_token_xy(pc)
        if not char_xy or not ally_xy:
            continue
        dist = ((char_xy[0] - ally_xy[0])**2 + (char_xy[1] - ally_xy[1])**2) ** 0.5
        if dist < 300:  # within reach
            return (
                "do",
                f"*grabs {pc} and drags them toward the ship ramp*",
                "Lifting", None, 10, "ship-ramp",
            )
    return None


def _load_game_state() -> dict | None:
    """Load the current game-state.json, returning None on error."""
    state_path = "/home/node/.openclaw/rpg/state/game-state.json"
    try:
        with open(state_path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _get_token_xy(char: str) -> tuple[int, int] | None:
    """Look up a character's current (x,y) from game-state.json tokens."""
    state = _load_game_state()
    if not state:
        return None
    slug = char.lower().replace(" ", "-").replace("'", "")
    token = state.get("tokens", {}).get(slug)
    if token:
        return (token["x"], token["y"])
    return None


def _resolve_position_xy(position_name: str) -> tuple[int, int] | None:
    """Resolve a named position to (x,y) from the current map's terrain."""
    import os
    state_path = "/home/node/.openclaw/rpg/state/game-state.json"
    try:
        with open(state_path) as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    map_image = (state.get("map") or {}).get("image", "")
    if not map_image:
        return None
    base = map_image.rsplit(".", 1)[0] if "." in map_image else map_image
    terrain_path = os.path.join("/app/rpg/maps", f"{base}-terrain.json")
    try:
        with open(terrain_path) as f:
            terrain = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    pos = terrain.get("positions", {}).get(position_name)
    if pos:
        return (pos["x"], pos["y"])
    return None


def _compute_move_penalty(char: str, move_to: str) -> tuple[int, int]:
    """Compute movement penalty and max distance for a character moving to a position.

    Returns (penalty, max_distance_px). penalty=3 means move is too far.
    """
    from_xy = _get_token_xy(char)
    to_xy = _resolve_position_xy(move_to)
    if not from_xy or not to_xy:
        return (0, 0)  # Can't compute — allow move without penalty
    char_move = _mod("char_move", CHAR_MOVE)
    penalty = calc_move_penalty(char, from_xy, to_xy, char_move=char_move)
    move_allowance = char_move.get(char, DEFAULT_MOVE)
    # Max distance is 4× move (sprint limit)
    max_dist = move_allowance * 4
    return (penalty, max_dist)


# Movement tier labels for transcript logging
_MOVE_TIER_LABELS = {0: "walk", 1: "run", 2: "sprint"}


# ---------------------------------------------------------------------------
# Player natural-language → position resolution
# ---------------------------------------------------------------------------

_MOVEMENT_VERBS = {
    "go", "move", "walk", "run", "sprint", "head", "sneak", "hide",
    "flee", "approach", "enter", "leave", "exit", "climb", "crawl",
    "dash", "rush", "retreat", "duck", "crouch", "step", "cross",
}

_MOVE_STOP_WORDS = {"the", "and", "then"}

# Scoring weights for position matching
_POS_ID_WEIGHT = 3
_POS_DESC_WEIGHT = 2
_ZONE_NAME_WEIGHT = 2
_ZONE_DESC_WEIGHT = 1
_MIN_MOVE_SCORE = 3

_WORD_SPLIT_RE = re.compile(r'[^a-z0-9]+')


def _load_current_terrain() -> dict | None:
    """Load and cache terrain data for the current map."""
    global _terrain_data_cache, _terrain_map_key
    state = _read_game_state()
    map_image = (state.get("map") or {}).get("image", "")
    if not map_image:
        return None
    if map_image == _terrain_map_key and _terrain_data_cache is not None:
        return _terrain_data_cache
    base = map_image.rsplit(".", 1)[0] if "." in map_image else map_image
    terrain_path = os.path.join("/app/rpg/maps", f"{base}-terrain.json")
    try:
        with open(terrain_path) as f:
            _terrain_data_cache = json.load(f)
            _terrain_map_key = map_image
    except (FileNotFoundError, json.JSONDecodeError):
        _terrain_data_cache = None
    return _terrain_data_cache


def _build_zone_index(terrain: dict) -> dict[str, tuple[str, str]]:
    """Build {position_id: (zone_name, zone_desc)} from terrain zones."""
    index = {}
    for zone_name, zone_data in terrain.get("zones", {}).items():
        zone_desc = zone_data.get("desc", "")
        for pos_id in zone_data.get("positions", []):
            index[pos_id] = (zone_name, zone_desc)
    return index


def _tokenize_text(text: str, exclude: set[str] | None = None) -> set[str]:
    """Split text into lowercase word tokens, removing short words and exclusions."""
    words = set(_WORD_SPLIT_RE.split(text.lower()))
    words.discard("")
    if exclude:
        words -= exclude
    return {w for w in words if len(w) > 2}


def _score_positions(action_words: set[str], terrain: dict,
                     zone_index: dict[str, tuple[str, str]]) -> list[tuple[str, float]]:
    """Score all positions against action text words. Returns [(pos_id, score)] sorted desc."""
    positions = terrain.get("positions", {})
    scores = []
    for pos_id, pos_data in positions.items():
        score = 0.0

        # Score from position ID (split on hyphens)
        id_words = {w for w in pos_id.split("-") if len(w) > 2}
        score += len(action_words & id_words) * _POS_ID_WEIGHT

        # Score from position description
        desc_words = _tokenize_text(pos_data.get("desc", ""))
        score += len(action_words & desc_words) * _POS_DESC_WEIGHT

        # Score from zone
        if pos_id in zone_index:
            zone_name, zone_desc = zone_index[pos_id]
            zone_name_words = {w for w in zone_name.split("-") if len(w) > 2}
            score += len(action_words & zone_name_words) * _ZONE_NAME_WEIGHT
            zone_desc_words = _tokenize_text(zone_desc)
            score += len(action_words & zone_desc_words) * _ZONE_DESC_WEIGHT

        if score > 0:
            scores.append((pos_id, score))

    scores.sort(key=lambda x: -x[1])
    return scores


def _resolve_player_movement(char: str, action_text: str) -> tuple[str | None, int]:
    """Resolve natural language action text to a position ID for movement.

    Returns (position_id, move_penalty) or (None, 0) if no movement detected.
    """
    words = action_text.lower().split()

    # Step 1: Check for movement verb
    if not any(w in _MOVEMENT_VERBS for w in words):
        return (None, 0)

    # Step 2: Load terrain
    terrain = _load_current_terrain()
    if not terrain:
        return (None, 0)

    # Step 3: Tokenize action text (exclude movement verbs and stop words)
    exclude = _MOVEMENT_VERBS | _MOVE_STOP_WORDS
    action_words = _tokenize_text(action_text, exclude=exclude)
    if not action_words:
        return (None, 0)

    # Step 4: Build zone index and score all positions
    zone_index = _build_zone_index(terrain)
    scored = _score_positions(action_words, terrain, zone_index)
    if not scored or scored[0][1] < _MIN_MOVE_SCORE:
        return (None, 0)

    # Step 5: Get character position for proximity and reachability
    from_xy = _get_token_xy(char)
    positions = terrain.get("positions", {})
    char_move_map = _mod("char_move", CHAR_MOVE)
    move_allowance = char_move_map.get(char, DEFAULT_MOVE)
    max_sprint = move_allowance * 4

    # Step 6: Apply proximity bonus to break ties, skip current position
    final_scored = []
    for pos_id, text_score in scored:
        pos_data = positions.get(pos_id, {})
        prox_bonus = 0.0
        if from_xy and "x" in pos_data and "y" in pos_data:
            dx = pos_data["x"] - from_xy[0]
            dy = pos_data["y"] - from_xy[1]
            dist = (dx * dx + dy * dy) ** 0.5
            if dist < 30:
                continue  # Already at this position
            prox_bonus = max(0.0, 1.0 - (dist / max_sprint)) if max_sprint > 0 else 0.0
        final_scored.append((pos_id, text_score + prox_bonus))

    if not final_scored:
        return (None, 0)
    final_scored.sort(key=lambda x: -x[1])

    # Step 7: Filter for reachability
    best_pos_id = final_scored[0][0]
    penalty, _ = _compute_move_penalty(char, best_pos_id)

    if penalty < 3:
        logger.info(f"  [move-resolve] {char} \"{action_text[:60]}\" -> {best_pos_id} "
                    f"(score={final_scored[0][1]:.1f}, penalty={penalty})")
        return (best_pos_id, penalty)

    # Best match is unreachable — try same zone first
    best_zone = zone_index.get(best_pos_id, (None, None))[0]
    if best_zone:
        for pos_id, score in final_scored[1:]:
            if score < _MIN_MOVE_SCORE:
                break
            pos_zone = zone_index.get(pos_id, (None, None))[0]
            if pos_zone == best_zone:
                p, _ = _compute_move_penalty(char, pos_id)
                if p < 3:
                    logger.info(f"  [move-resolve] {char} \"{action_text[:60]}\" -> {pos_id} "
                                f"(fallback in zone '{best_zone}', score={score:.1f})")
                    return (pos_id, p)

    # No same-zone fallback — pick closest reachable position above threshold
    for pos_id, score in final_scored[1:]:
        if score < _MIN_MOVE_SCORE:
            break
        p, _ = _compute_move_penalty(char, pos_id)
        if p < 3:
            logger.info(f"  [move-resolve] {char} \"{action_text[:60]}\" -> {pos_id} "
                        f"(closest reachable, score={score:.1f})")
            return (pos_id, p)

    logger.info(f"  [move-resolve] {char}: best match '{best_pos_id}' unreachable, no fallback")
    return (None, 0)


# ---------------------------------------------------------------------------
# Pre-gen characters and their personality action pools
# ---------------------------------------------------------------------------

PREGENS = ["Kira Voss", "Tok-3", "Renn Darkhollow", "Zeph Ando"]

# ---------------------------------------------------------------------------
# Token auto-placement per act (real position names from terrain files)
# ---------------------------------------------------------------------------

ACT_STARTING_POSITIONS = {
    1: {  # Cantina
        "Kira Voss": "booth-1-left",
        "Tok-3": "bar-stool-r3",
        "Renn Darkhollow": "table-2",
        "Zeph Ando": "bar-stool-l2",
    },
    2: {  # Streets — just exited the cantina
        "Kira Voss": "cantina-street",
        "Tok-3": "cantina-door",
        "Renn Darkhollow": "cantina-street",
        "Zeph Ando": "cantina-street",
    },
    3: {  # Docking Bay — everyone near the ship
        # ship-stern (262px to cockpit) lets Kira sprint to pilot.
        # ship-port (395px to cockpit) would BLOCK her — just over sprint limit.
        "Kira Voss": "ship-stern",
        "Tok-3": "ship-ramp",
        "Renn Darkhollow": "ship-starboard",
        "Zeph Ando": "ship-port",
    },
}

# NPC tokens per act — tuples: (position, color, hidden)
# Red (#f54e4e) = hostile, Orange (#e8a030) = neutral, Gray (#888) = civilian
# Vehicle tokens get type "vehicle" (rectangular on overlay instead of circular)
VEHICLE_TOKENS = {"Speeder 1", "Speeder 2"}
NPC_STARTING_POSITIONS = {
    1: {  # Cantina
        "Stormtrooper 1": ("entrance", "#f54e4e", False),
        "Stormtrooper 2": ("entrance-right", "#f54e4e", False),
        "Wuher": ("behind-bar-center", "#e8a030", False),
        "Rodian Contact": ("booth-1-right", "#e8a030", False),
        "Figrin Dan": ("band-stage", "#888888", False),
        "Patron 1": ("bar-stool-l4", "#888888", False),
        "Patron 2": ("table-3", "#888888", False),
    },
    2: {  # Street 1 — Cantina District (NPCs on Streets 2/3 placed on map transition)
        "Speeder 1": ("speeder-1", "#8899aa", False),  # large speeder (seats 4)
        "Speeder 2": ("speeder-2", "#997766", False),  # small speeder (seats 2)
        "Speeder Driver": ("speeder-1", "#e8a030", False),  # driver sits on speeder 1
        "Civilian 1": ("road-center", "#888888", False),
        "Civilian 2": ("tapcaf-front", "#888888", False),
    },
    3: {  # Docking Bay
        "Lt. Hask": ("blast-door", "#f54e4e", False),
        "Stormtrooper 1": ("blast-door-left", "#f54e4e", False),
        "Stormtrooper 2": ("blast-door-right", "#f54e4e", False),
        "Stormtrooper 3": ("bay-floor-center", "#f54e4e", False),
        "Stormtrooper 4": ("bay-floor-right", "#f54e4e", False),
        "Dock Worker": ("cargo-right", "#888888", False),
    },
}

# ---------------------------------------------------------------------------
# Skill-check-aware bot actions per act
# Tuples: (action_type, text, skill, dice_override, difficulty, move_to_position)
# When skill is set, Python pre-rolls the check.
# When move_to_position is set, Python moves the character token after the action.
# ---------------------------------------------------------------------------

ACT_BOT_ACTIONS = {
    1: {  # Cantina — lockdown, data chip, escape
        # Every action moves the character. Stepping stones pull toward exits.
        # Exits (back-door, storage-door) reserved for climax only.
        "Kira Voss": [
            ("do", "palms the data chip from the Rodian", "Con", None, 15, "booth-1-center"),
            ("do", "slides out of the booth and signals the others", None, None, None, "booth-1-approach"),
            ("do", "draws her DL-44 under the table and edges toward the back", None, None, None, "near-table-1"),
            ("do", "bluffs the officer about never seeing any Rodian", "Con", None, 20, "booth-2-approach"),
            ("do", "slips past the booths toward the staff door", "Sneak", None, 12, "near-table-2"),
            ("do", "ducks behind the round tables heading east", None, None, None, "table-2-east"),
            ("do", "checks the staff door — it's unlocked", "Search", None, 10, "staff-door"),
            ("do", "pushes into the back hallway", None, None, None, "back-hallway-center"),
            ("do", "moves down the hallway toward the storage room", None, None, None, "back-hallway-south"),
        ],
        "Tok-3": [
            ("do", "*scans the Stormtroopers' comlink frequencies while rolling sideways*", "Computer Prog", None, 12, "bar-stool-r2"),
            ("do", "*whistles nervously and rolls toward the booth area*", None, None, None, "booth-3-approach"),
            ("do", "*trundles east past the tables*", None, None, None, "table-3-east"),
            ("do", "*rolls toward the center of the room, sensors sweeping*", None, None, None, "center-floor-north"),
            ("do", "*interfaces with the droid detector near the foyer*", "Computer Prog", None, 15, "droid-detector"),
            ("do", "*rolls behind the bar counter to hide*", "Sneak", None, 10, "bar-front"),
            ("do", "*trundles toward the staff doorway*", None, None, None, "staff-door"),
            ("do", "*rolls down the back hallway*", None, None, None, "back-hallway-center"),
            ("do", "*heads toward the storage room*", None, None, None, "back-hallway-south"),
        ],
        "Renn Darkhollow": [
            ("do", "*readies blaster rifle and moves to a better position*", None, None, None, "table-2-east"),
            ("do", "*scans the cantina for Imperial reinforcements*", "Search", None, 12, "booth-3-right"),
            ("do", "*slides east along the wall toward the back*", "Sneak", None, 10, "near-table-2"),
            ("do", "*takes cover behind the round table*", None, None, None, "table-3"),
            ("do", "*moves to the near table for a better firing angle*", None, None, None, "near-table-3"),
            ("do", "*covers the staff door, ready to move*", "Search", None, 10, "staff-door"),
            ("do", "*pushes into the back hallway, rifle raised*", None, None, None, "back-hallway-center"),
            ("do", "*advances toward the storage room*", "Sneak", None, 10, "back-hallway-south"),
        ],
        "Zeph Ando": [
            ("do", "*closes eyes, sensing danger through the Force*", "Sense", None, 15, "bar-stool-l3"),
            ("do", "*moves toward the center of the cantina, sensing the way*", None, None, None, "center-floor-north"),
            ("do", "*edges along the bar toward the right side*", None, None, None, "bar-stool-r5"),
            ("do", "*senses a path through the crowd toward the booths*", "Sense", None, 12, "booth-2-approach"),
            ("do", "*slips past the tables, guided by the Force*", None, None, None, "table-3-east"),
            ("do", "*moves toward the staff door — the Force says this way*", "Sense", None, 12, "staff-door"),
            ("do", "*follows the others into the back hallway*", None, None, None, "back-hallway-center"),
            ("do", "*heads toward the storage room, hand on lightsaber*", None, None, None, "back-hallway-south"),
        ],
    },
    2: {  # Streets — westward traversal toward Docking Bay 87
        # Every action moves. Stepping stones pull westward toward the bay.
        "Kira Voss": [
            ("do", "leads the group into the alleys — main road is a death trap", "Streetwise", None, 12, "side-alley"),
            ("do", "spots the bounty hunter's trap and redirects the group", "Dodge", None, 15, "dwelling-front"),
            ("do", "talks the speeder driver into giving them a ride west", "Con", None, 15, "speeder-1"),
            ("do", "asks the dockworker for directions to Bay 87", "Streetwise", None, 10, "npc-dockworker"),
            ("do", "reads the directional sign pointing toward the bays", None, None, None, "sign-docking-bays"),
            ("do", "scouts the road ahead toward the bay checkpoint", "Streetwise", None, 12, "road-west"),
            ("do", "waves the others forward and pushes west", None, None, None, "road-west"),
            ("do", "doubles back to cover the group's rear", "Blaster", None, 12, "road-center"),
        ],
        "Tok-3": [
            ("do", "*hacks the speeder's ignition lock*", "Security", None, 10, "speeder-1"),
            ("do", "*rolls west along the main road, scanning for patrols*", "Search", None, 12, "road-west"),
            ("do", "*interfaces with the directional sign's data port*", "Computer Prog", None, 10, "sign-docking-bays"),
            ("do", "*scans the road ahead for Imperial patrols*", "Search", None, 12, "npc-dockworker"),
            ("do", "*hacks into a nearby terminal for bay access codes*", "Computer Prog", None, 15, "road-west"),
            ("do", "*rolls back to guide stragglers with a projected holomap*", None, None, None, "road-center"),
            ("do", "*trundles into the alley, scanning for a shortcut*", "Search", None, 12, "side-alley"),
            ("do", "*rolls toward the dwelling to check for supplies*", None, None, None, "dwelling-front"),
        ],
        "Renn Darkhollow": [
            ("do", "*scouts the road ahead from the dwelling doorway*", "Search", None, 15, "dwelling-front"),
            ("do", "*sneaks along the building walls heading west*", "Sneak", None, 15, "road-west"),
            ("do", "*climbs to a vantage point overlooking the road*", "Sneak", None, 12, "side-alley"),
            ("do", "*scouts ahead toward the docking bay signs*", "Search", None, 15, "sign-docking-bays"),
            ("do", "*checks the alley for ambushes before waving the group forward*", "Search", None, 12, "npc-dockworker"),
            ("do", "*drops back to lay suppressing fire for the others*", "Blaster", None, 12, "road-center"),
            ("do", "*takes a defensive position at the road junction*", "Blaster", None, 12, "road-east"),
            ("do", "*covers the tapcaf entrance while the party passes*", "Search", None, 10, "tapcaf-front"),
        ],
        "Zeph Ando": [
            ("do", "*senses the safest path west through the streets*", "Sense", None, 15, "road-west"),
            ("do", "*patches up Renn's blaster wound in the alley*", "First Aid", None, 10, "side-alley"),
            ("do", "*checks the tapcaf for medical supplies*", None, None, None, "tapcaf-front"),
            ("do", "*asks the dockworker about Bay 87*", "Bargain", None, 10, "npc-dockworker"),
            ("do", "*uses the Force to scan for danger near the bay signs*", "Sense", None, 12, "sign-docking-bays"),
            ("do", "*reaches out with the Force to guide stragglers to safety*", "Sense", None, 15, "road-center"),
            ("do", "*senses an ambush near the dwelling and warns the group*", "Sense", None, 15, "dwelling-front"),
            ("do", "*drops back to heal a wounded ally*", "First Aid", None, 10, "road-east"),
        ],
    },
    3: {  # Docking Bay — ship repair, combat, escape
        # All PCs start at ship positions. Every action moves.
        "Kira Voss": [
            ("do", "sprints for the cockpit to prep for launch", "Starship Piloting", None, 12, "ship-cockpit"),
            ("do", "fires from the ship ramp at advancing Stormtroopers", "Blaster", None, 15, "ship-ramp"),
            ("do", "ducks behind the ship hull for cover", "Dodge", None, 18, "ship-port"),
            ("do", "runs to the starboard side to return fire", "Blaster", None, 15, "ship-starboard"),
        ],
        "Tok-3": [
            ("do", "*frantically repairs the Rusty Mynock's engine*", "Starship Repair", None, 12, "ship-ramp"),
            ("do", "*plots the hyperspace jump coordinates*", "Astrogation", None, 15, "ship-cockpit"),
            ("do", "*reroutes power to the dorsal turret*", "Starship Repair", None, 12, "ship-turret"),
            ("do", "*welds a hull breach while under fire*", None, None, None, "ship-port"),
        ],
        "Renn Darkhollow": [
            ("do", "*fires from the ship turret at the blast door*", "Blaster", None, 15, "ship-turret"),
            ("do", "*lays suppressing fire from the boarding ramp*", "Blaster", None, 12, "ship-ramp"),
            ("do", "*takes a defensive position at the ship's starboard side*", "Blaster", None, 15, "ship-starboard"),
            ("do", "*falls back to the port side, covering the flank*", "Blaster", None, 12, "ship-port"),
        ],
        "Zeph Ando": [
            ("do", "*ignites lightsaber to deflect incoming fire at the ramp*", "Lightsaber", None, 18, "ship-ramp"),
            ("do", "*uses the Force to hurl debris at the advancing troopers*", "Sense", None, 15, "ship-port"),
            ("do", "*applies first aid to a wounded ally at the ramp*", "First Aid", None, 10, "ship-ramp"),
            ("do", "*rushes to the turret to provide covering fire*", None, None, None, "ship-turret"),
        ],
    },
}

# NPCs that follow PCs when certain keywords appear in the action text.
# The NPC token moves to the SAME destination as the PC.
# Format: { "keyword": ["npc_name", ...] }
COMPANION_NPC_KEYWORDS = {
    "speeder": ["Speeder Driver", "Speeder 1"],
    "hotwire": ["Speeder Driver", "Speeder 1"],
    "driver": ["Speeder Driver", "Speeder 1"],
    "speeder-2": ["Speeder 2"],
    "smaller speeder": ["Speeder 2"],
    "fast speeder": ["Speeder 2"],
}

# ---------------------------------------------------------------------------
# NPC behavior — context-aware movement based on game mode
# ---------------------------------------------------------------------------

# Ambient routes: NPCs cycle through these during peaceful RP.
# When combat/cutscene starts, ambient movement stops.
NPC_AMBIENT_ROUTES = {
    2: {
        "Speeder 2": [
            "road-west", "road-center", "road-east",
            "road-center",
        ],
        "Civilian 1": [
            "road-center", "dwelling-front", "road-center",
            "road-west",
        ],
        "Civilian 2": [
            "tapcaf-front", "shop-front", "tapcaf-front",
            "road-center",
        ],
    },
}

# Hostile NPC advancement — routes hostiles follow each roam interval in combat.
# Unlike ambient routes (looping), these are one-shot: each step moves the NPC
# closer to the party.  Once the route is exhausted the NPC holds position.
NPC_HOSTILE_ADVANCE = {
    1: {
        "Stormtrooper 1": [
            "entrance", "vestibule-inner", "near-table-1", "table-2",
        ],
        "Stormtrooper 2": [
            "entrance-right", "vestibule-inner", "bar-stool-r3", "near-table-2",
        ],
    },
    3: {
        "Lt. Hask": [
            "blast-door-left", "bay-floor-center", "ship-bow", "ship-ramp",
        ],
        "Stormtrooper 1": [
            "blast-door-left", "bay-floor-left", "bay-crate-left", "ship-port",
        ],
        "Stormtrooper 2": [
            "blast-door-right", "bay-floor-right", "bay-crate-right", "ship-starboard",
        ],
        "Stormtrooper 3": [
            "blast-door-left", "bay-floor-center", "bay-floor-center", "ship-bow",
        ],
        "Stormtrooper 4": [
            "blast-door-right", "blast-door-right", "bay-floor-right", "ship-stern",
        ],
    },
}

# Reactive positions: where NPCs go when combat starts.
# "cover" = take cover, "flee" = run off-map, "engage" = join the fight.
NPC_COMBAT_REACTIONS = {
    1: {
        "Patron 1": ("cover", "bar-stool-l4"),            # ducks behind bar
        "Patron 2": ("cover", "booth-3-center"),            # dives into empty booth
        "Figrin Dan": ("cover", "band-stage"),             # stays on stage
    },
    2: {
        "Speeder 2": ("flee", "road-west"),               # speeds away toward market
        "Civilian 1": ("flee", "dwelling-front"),          # runs to dwelling
        "Civilian 2": ("cover", "shop-front"),             # hides near shop
    },
    3: {
        "Lt. Hask": ("engage", "bay-floor-center"),        # advances into the bay
        "Stormtrooper 1": ("engage", "bay-floor-left"),    # flanks left
        "Stormtrooper 2": ("engage", "bay-floor-right"),   # flanks right
        "Stormtrooper 3": ("engage", "bay-floor-center"),  # center assault
        "Stormtrooper 4": ("engage", "blast-door-right"),  # holds the exit
        "Dock Worker": ("flee", "side-entry"),             # civilian runs
    },
}

# ---------------------------------------------------------------------------
# Position-based act pacing — acts end when characters reach exits
# ---------------------------------------------------------------------------

ACT_EXIT_POSITIONS = {
    1: {"back-door", "storage-door"},
    2: {"bay-87-entrance", "checkpoint-bay"},  # docking bay area — reachable via stepping stones
    3: {"ship-cockpit", "ship-turret"},
}

# Safety-valve hard cap — acts are objective-based but we need an upper
# bound to prevent infinite loops from bad RNG.  This is NOT pacing; the
# real act-end trigger is reaching exit positions (+ Act 3 objectives).
ACT_HARD_CAP = 20

# Climax actions — dramatic finale moments that move characters to exits
ACT_CLIMAX_ACTIONS = {
    1: {
        # Climax: target real exits. Characters should be at stepping stones
        # (near-table-1, near-table-2, booth-3-right, table-3-east) by now.
        # back-door reachable from near-table-1 (166px), near-table-2 (250px).
        # storage-door reachable from booth-3-right (216px), table-3-east (253px).
        # If a character hasn't moved close enough, the move gets BLOCKED and
        # the act ends on max turns instead — acceptable fallback.
        "Kira Voss": [
            ("do", "kicks over the table and fires at the lead trooper while sprinting for the back door", "Blaster", None, 15, "back-door"),
            ("do", "grabs the data chip and bolts for the storage exit under a hail of blaster fire", "Dodge", None, 18, "storage-door"),
        ],
        "Tok-3": [
            ("do", "*overloads the cantina's power grid — lights explode, plunging the room into darkness*", "Computer Prog", None, 15, "storage-door"),
            ("do", "*triggers the fire suppression system, filling the cantina with blinding foam*", "Security", None, 12, "storage-door"),
        ],
        "Renn Darkhollow": [
            ("do", "*opens covering fire on the Stormtroopers while backing toward the exit*", "Blaster", None, 15, "back-door"),
            ("do", "*hurls a bottle of Corellian whiskey at the trooper's visor and charges for the door*", "Brawling", None, 12, "back-door"),
        ],
        "Zeph Ando": [
            ("do", "*uses the Force to slam the cantina door shut behind the fleeing party*", "Sense", None, 20, "storage-door"),
            ("do", "*deflects a blaster bolt with an instinctive Force push and dives for the exit*", "Sense", None, 18, "storage-door"),
        ],
    },
    2: {
        "Kira Voss": [
            ("do", "guns the speeder straight through the checkpoint barricade toward Bay 87", "Starship Piloting", None, 18, "bay-87-entrance"),
            ("do", "throws a smoke bomb and sprints for the Bay 87 blast door", "Dodge", None, 15, "bay-87-entrance"),
        ],
        "Tok-3": [
            ("do", "*broadcasts a fake Imperial all-clear — the checkpoint troopers stand down*", "Computer Prog", None, 20, "checkpoint-bay"),
            ("do", "*jams the checkpoint scanners and rolls for Bay 87*", "Security", None, 15, "bay-87-entrance"),
        ],
        "Renn Darkhollow": [
            ("do", "*lays covering fire at the checkpoint while the group runs for Bay 87*", "Blaster", None, 18, "checkpoint-bay"),
            ("do", "*tackles Greevak and sprints for the Bay 87 blast door*", "Brawling", None, 15, "bay-87-entrance"),
        ],
        "Zeph Ando": [
            ("do", "*senses the safest path and guides the group to Bay 87's entrance*", "Sense", None, 15, "bay-87-entrance"),
            ("do", "*uses the Force to topple a market stall into the troopers' path*", "Sense", None, 18, "checkpoint-bay"),
        ],
    },
    3: {
        "Kira Voss": [
            ("do", "slides into the cockpit and punches the engines to full thrust", "Starship Piloting", None, 18, "ship-cockpit"),
            ("do", "fires the ship's forward guns at the AT-ST as it enters the bay", "Blaster", None, 20, "ship-cockpit"),
        ],
        "Tok-3": [
            ("do", "*slams the hyperspace lever — coordinates locked, stars streak!*", "Astrogation", None, 15, "ship-cockpit"),
            ("do", "*reroutes ALL power to engines — emergency liftoff NOW!*", "Starship Repair", None, 12, "ship-cockpit"),
        ],
        "Renn Darkhollow": [
            ("do", "*lays a final barrage from the turret and seals the hatch*", "Blaster", None, 15, "ship-turret"),
            ("do", "*sprints up the ramp and slams the boarding hatch shut*", "Dodge", None, 12, "ship-ramp"),
        ],
        "Zeph Ando": [
            ("do", "*ignites lightsaber and holds the ramp while the ship powers up*", "Lightsaber", None, 20, "ship-ramp"),
            ("do", "*uses the Force to slam the ramp shut behind the crew*", "Sense", None, 18, "ship-ramp"),
        ],
    },
}


# ---------------------------------------------------------------------------
# Act pacer — position-based flexible turn pacing
# ---------------------------------------------------------------------------

SHIP_POSITIONS = {
    "ship-ramp", "ship-cockpit", "ship-top-hatch", "ship-bow",
    "ship-stern", "ship-port", "ship-starboard", "ship-turret",
}


class ActPacer:
    """Objective-based act progression — no fixed turn limits.

    Acts end when PCs complete their objectives:
      Act 1/2: any PC reaches an exit position
      Act 3:   ship repaired + all surviving PCs aboard + someone at cockpit/turret

    A hard cap (ACT_HARD_CAP) prevents infinite loops from bad RNG.
    """

    def __init__(self, act_num: int):
        self.act_num = act_num
        exit_pos = _mod("act_exit_positions", ACT_EXIT_POSITIONS)
        self.exit_positions = exit_pos.get(act_num, set())
        self.hard_cap = ACT_HARD_CAP
        self.min_turns = 4
        self.ship_positions = _mod("ship_positions", SHIP_POSITIONS)
        if _module:
            act_data = _module.get_act(act_num)
            if act_data:
                if act_data.pacer.get("hard_cap"):
                    self.hard_cap = act_data.pacer["hard_cap"]
                if act_data.pacer.get("min_turns"):
                    self.min_turns = act_data.pacer["min_turns"]
        self.turn = 0
        self.visited: set[str] = set()
        self.reached_exit = False
        # Act 3 objectives
        self.ship_repaired = False
        self.pc_positions: dict[str, str] = {}  # char -> last known position

    def record_turn(self, positions_this_turn: list[str],
                    pc_position_map: dict[str, str] | None = None):
        """Record positions PCs moved to this turn."""
        self.turn += 1
        self.visited.update(p for p in positions_this_turn if p)
        if self.visited & self.exit_positions:
            self.reached_exit = True
        if pc_position_map:
            self.pc_positions.update(pc_position_map)

    def _all_surviving_aboard(self) -> bool:
        """Check if all able PCs are in ship positions.

        PCs with wound_level >= 3 (incapacitated/mortally wounded/dead) can't
        move themselves, so they're narratively carried — don't block departure.
        """
        if not self.pc_positions:
            return False
        state_path = "/home/node/.openclaw/rpg/state/game-state.json"
        try:
            with open(state_path) as f:
                state = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return False
        for viewer, pdata in state.get("players", {}).items():
            wl = pdata.get("wound_level", 0)
            if wl >= 3:  # incapacitated — narratively carried aboard
                continue
            char = pdata.get("character", "")
            pos = self.pc_positions.get(char, "")
            if pos not in self.ship_positions:
                return False
        return True

    def should_end_act(self) -> bool:
        """Should the act end after this turn?"""
        if self.turn >= self.hard_cap:
            return True
        if self.turn < self.min_turns:
            return False
        if self.act_num == 3:
            return (self.ship_repaired and self.reached_exit
                    and self._all_surviving_aboard())
        return self.reached_exit

    def _any_pc_near_exit(self) -> bool:
        """Check if any PC is within sprint range of an exit position."""
        if not self.exit_positions:
            return False
        pregens = _mod("pregens", PREGENS)
        for char in pregens:
            if _get_wound_level(char) >= 3:
                continue  # incapacitated — can't move
            for exit_pos in self.exit_positions:
                penalty, _ = _compute_move_penalty(char, exit_pos)
                if penalty < 3:  # reachable (walk, run, or sprint)
                    return True
        return False

    @property
    def is_climax(self) -> bool:
        """Should the next turn use the climax action pool?

        Narrative-driven: climax fires when a character has naturally moved
        close enough to an exit to make a dramatic escape. No arbitrary
        position counting — the story gets there when it gets there.

        Act 3: Climax fires once the ship is repaired (escape sequence).
        Hard cap is the only safety valve.
        """
        if self.turn + 1 >= self.hard_cap:
            return True
        if self.turn < self.min_turns:
            return False
        if self.act_num == 3:
            return self.ship_repaired or self.turn >= 8
        # Acts 1-2: climax when someone is close enough to actually escape
        return self._any_pc_near_exit()

    def pacing_hint(self) -> str:
        """Generate a pacing hint for the GM prompt."""
        if self.act_num == 3:
            if not self.ship_repaired:
                return ("PACING: The ship still needs repairs! "
                        "Someone must succeed a Starship Repair check before escape.")
            if not self._all_surviving_aboard():
                return ("PACING: The ship is repaired but not everyone is aboard! "
                        "Get all surviving crew to the ship!")
            return "PACING: Ship ready, crew aboard — this is the CLIMAX! Launch NOW!"
        if self.is_climax:
            return "PACING: This is the CLIMAX! Dramatic finale — force a decisive moment."
        return "PACING: The act is in progress. Escalate tension, raise the stakes."


# ---------------------------------------------------------------------------
# Polls
# ---------------------------------------------------------------------------

BETWEEN_ACT_POLL = {
    "question": "POLL: How was the pacing? 1=too fast, 2=just right, 3=too slow",
    "options": ["1 — too fast", "2 — just right", "3 — too slow"],
}

POST_SESSION_POLL = {
    "question": "Session over! Rate 1-5 stars. What was your favorite moment?",
    "options": ["1", "2", "3", "4", "5"],
}

# ---------------------------------------------------------------------------
# Session runner
# ---------------------------------------------------------------------------

_running = True


def _signal_handler(sig, frame):
    global _running
    logger.info("\nInterrupted — ending session gracefully...")
    _running = False


def _init_session(adventure: str, transcript: TranscriptLogger):
    """Initialize game state with all pre-gen characters as bot-controlled."""
    global _module
    _module = find_module(adventure)
    if _module:
        logger.info(f"=== LOADED MODULE: {_module.name} ({_module.slug}) ===")
    else:
        logger.info("=== NO MODULE JSON FOUND — using hardcoded fallback ===")

    logger.info("=== INITIALIZING SESSION ===")
    out = run_rpg_cmd(["init", "--adventure", adventure, "--auto-join-bots"])
    logger.info(f"  init: {out}")
    # Log persistent wound state (wounds carry over from last canon session)
    pregens = _mod("pregens", PREGENS)
    for char in pregens:
        wl = _get_wound_level(char)
        if wl > 0:
            logger.info(f"  {char} starts wounded (level {wl})")
    logger.info("  PCs loaded with persistent state")
    transcript.log_session_event("init", {"adventure": adventure, "auto_join_bots": True})


def _auto_place_tokens(act_num: int):
    """Place PC and NPC tokens at their starting positions for this act."""
    # Place PCs
    positions = _mod("act_starting_positions", ACT_STARTING_POSITIONS).get(act_num, {})
    for char, pos in positions.items():
        out = run_rpg_cmd(["move-token", "--character", char, "--position", pos])
        logger.info(f"  TOKEN: {char} -> {pos} ({out})")

    # Place NPCs (and vehicles)
    npcs = _mod("npc_starting_positions", NPC_STARTING_POSITIONS).get(act_num, {})
    vehicle_tokens = _mod("vehicle_tokens", VEHICLE_TOKENS)
    for npc, (pos, color, hidden) in npcs.items():
        cmd = ["move-token", "--character", npc, "--position", pos, "--color", color]
        if npc in vehicle_tokens:
            cmd += ["--type", "vehicle"]
        if hidden:
            cmd.append("--hidden")
        out = run_rpg_cmd(cmd)
        vis = " [hidden]" if hidden else ""
        logger.info(f"  NPC: {npc} -> {pos} ({color}){vis} ({out})")


def _get_act_scene_name(act_num: int) -> str:
    """Get the scene name for an act from module data, or a sensible default."""
    if _module:
        ad = _module.get_act(act_num)
        if ad and ad.name:
            return ad.name
    return f"Act {act_num}"


def _update_scene_for_act(act_num: int):
    """Set act number and scene name in game state."""
    scene_name = _get_act_scene_name(act_num)
    run_rpg_cmd(["update-scene", "--act", str(act_num), "--scene", scene_name])


def _set_act_map(act_num: int, transcript: TranscriptLogger):
    """Set the map for the current act and auto-place tokens."""
    act_maps = _mod("act_maps", ACT_MAPS)
    act_map_terrain = _mod("act_map_terrain", ACT_MAP_TERRAIN)
    if act_num not in act_maps:
        return
    map_image, map_name = act_maps[act_num]
    cmd = ["set-map", "--image", map_image, "--name", map_name,
           "--clear-tokens"]
    terrain_file = act_map_terrain.get(act_num)
    if terrain_file:
        cmd.extend(["--terrain", terrain_file])
    out = run_rpg_cmd(cmd)
    logger.info(f"  map: {map_name} ({map_image}) -> {out}")
    transcript.log_scene_change(act_num, map_name, map_image)
    _auto_place_tokens(act_num)

    # Camera per act (zoom tuned to map size):
    #   Act 1 (cantina-expanded 1920x1080): follow-party zoom 1.5
    #   Act 2 (streets 1920x1080): zoom 2.0 — large street map, pan with party
    #   Act 3 (docking bay): zoom 1.0 overview — small map, show the whole bay
    if act_num == 1:
        # Expanded cantina (1920x1080) — follow party, moderate zoom
        run_rpg_cmd(["set-camera", "--follow-party", "--zoom", "1.5"])
        logger.info("  camera: follow-party zoom=1.5 (expanded cantina)")
    elif act_num == 3:
        run_rpg_cmd(["set-camera", "--follow-party", "--zoom", "1.0"])
        logger.info("  camera: overview zoom=1.0 (full bay visible)")
    else:
        run_rpg_cmd(["set-camera", "--follow-party", "--zoom", "2.0"])
        logger.info("  camera: follow-party zoom=2.0")


def _maybe_auto_transfer(char_name: str, position_name: str):
    """If position is a map connection exit, auto-transfer the token.

    Checks if ``position_name`` is a connection point on the current map.
    If so, transfers the token to the connected map and switches the scene
    so the overlay follows the character.
    """
    state_path = os.environ.get(
        "RPG_STATE_FILE",
        "/home/node/.openclaw/rpg/state/game-state.json",
    )
    try:
        with open(state_path) as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return
    current_map = (state.get("map") or {}).get("image", "")
    if not current_map:
        return

    # Load terrain for current map to check connections
    terrain_file = current_map.replace(".svg", "-terrain.json")
    terrain_path = pathlib.Path("/app/rpg/maps") / terrain_file
    if not terrain_path.exists():
        return
    with open(terrain_path) as f:
        terrain = json.load(f)

    connections = terrain.get("connections", {})
    if position_name not in connections:
        return

    conn = connections[position_name]
    target_map = conn["map"]
    logger.info(f"  [auto-transfer] {char_name}: {position_name} -> {target_map}")
    run_rpg_cmd(["transfer-token", "--character", char_name,
                  "--to-map", target_map])
    run_rpg_cmd(["switch-scene", "--map", target_map])


# ---------------------------------------------------------------------------
# Action classification — detect off-script exploration
# ---------------------------------------------------------------------------

def _position_name_from_token(state: dict, token: dict) -> str:
    """Reverse-lookup a named position from token (x,y) coordinates.

    Returns the position name if the token is within 30px of a named
    position, otherwise returns empty string.
    """
    map_image = (state.get("map") or {}).get("image", "")
    if not map_image:
        return ""
    import os
    base = map_image.rsplit(".", 1)[0] if "." in map_image else map_image
    terrain_path = os.path.join("/app/rpg/maps", f"{base}-terrain.json")
    try:
        with open(terrain_path) as f:
            terrain = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return ""
    tx, ty = token.get("x", 0), token.get("y", 0)
    best_name = ""
    best_dist = 30  # max snap distance
    for name, pos in terrain.get("positions", {}).items():
        dx = tx - pos["x"]
        dy = ty - pos["y"]
        dist = (dx * dx + dy * dy) ** 0.5
        if dist < best_dist:
            best_dist = dist
            best_name = name
    return best_name


_EXPLORE_KEYWORDS = {
    "shop", "inn", "dwelling", "junk", "dealer", "warehouse", "rooftop",
    "roof", "alley", "market", "speeder", "climb", "hide", "sneak",
    "back room", "upstairs", "underground", "tunnel",
}


def _classify_actions(actions: list[dict]) -> str:
    """Return 'explore' if actions mention off-script locations, else 'normal'."""
    for a in actions:
        text_lower = a.get("text", "").lower()
        if any(kw in text_lower for kw in _EXPLORE_KEYWORDS):
            return "explore"
    return "normal"


_EXPLORE_KICK = (
    "A player is exploring off the main path. Describe what they "
    "find at that location using the AVAILABLE POSITIONS details. "
    "Create a consequence — discovery, NPC encounter, or complication "
    "— then hint at the mission goal without forcing them back."
)


def _pick_reachable_action(char: str, pool: list,
                           recent_texts: set[str] | None = None) -> tuple:
    """Pick an action whose move_to is reachable and not the current position.

    Splits the pool into:
      1. Actions with reachable move_to that isn't where the char already is
      2. Stationary actions (no move_to)
      3. Unreachable actions (penalty >= 3) or already-there duplicates
    Picks from group 1 first (movement), then 2 (still useful RP), then 3 last.
    If recent_texts is provided, filters out actions the character already did
    (unless all remaining options have been done — then allow repeats).
    """
    from_xy = _get_token_xy(char)
    reachable = []
    stationary = []
    blocked = []
    for action in pool:
        move_to = action[5]  # 6th element is move_to_position
        if not move_to:
            stationary.append(action)
        else:
            # Skip if character is already at this position (within 30px)
            to_xy = _resolve_position_xy(move_to)
            if from_xy and to_xy:
                dist = ((from_xy[0] - to_xy[0])**2 + (from_xy[1] - to_xy[1])**2) ** 0.5
                if dist < 30:
                    continue  # Already there — skip entirely
            penalty, _ = _compute_move_penalty(char, move_to)
            if penalty < 3:
                reachable.append(action)
            else:
                blocked.append(action)
    # Prefer reachable moves (progresses the story), then stationary RP
    pick_from = reachable or stationary or blocked
    if not pick_from:
        pick_from = pool  # Last resort: pick anything
    # Filter out recently-done actions (avoid mindless repetition)
    if recent_texts and len(pick_from) > 1:
        fresh = [a for a in pick_from if a[1] not in recent_texts]
        if fresh:
            pick_from = fresh
    return random.choice(pick_from)


def _simulate_player_actions(act_num: int, turn_num: int,
                             transcript: TranscriptLogger,
                             is_climax: bool = False,
                             pacer: "ActPacer | None" = None):
    """Dry-run: generate 1-2 random bot PC actions with pre-rolled dice.

    Returns (dice_strings, positions, pc_position_map, action_class):
      dice_strings    — display strings for GM prompt injection
      positions       — list of position names PCs moved to
      pc_position_map — {char: position} for all PCs that moved
      action_class    — 'explore' or 'normal'

    Side-effect: sets pacer.ship_repaired when Starship Repair succeeds (Act 3).
    """
    dice_strings = []
    positions = []
    pc_position_map: dict[str, str] = {}
    logged_actions = []

    # Filter out incapacitated/dead PCs (wound_level >= 3 = incapacitated in WEG D6)
    pregens = _mod("pregens", PREGENS)
    able_chars = [c for c in pregens if _get_wound_level(c) < 3]
    if not able_chars:
        logger.warning("  [WARNING] All PCs incapacitated!")
        return dice_strings, positions, pc_position_map, "normal"
    # All able characters act every turn — standing guard is still an action
    chars = able_chars

    # Climax turn: draw from climax pool, fall back to normal
    act_climax = _mod("act_climax_actions", ACT_CLIMAX_ACTIONS)
    act_bot = _mod("act_bot_actions", ACT_BOT_ACTIONS)
    if is_climax:
        act_actions = act_climax.get(act_num, {})
        act_fallback = act_bot.get(act_num, {})
    else:
        act_actions = act_bot.get(act_num, {})
        act_fallback = {}

    # Build per-character recent action texts to avoid mindless repetition
    _hist_state = _load_game_state()
    _hist_log = _hist_state.get("action_log", []) if _hist_state else []

    for char in chars:
        recent_texts = {a["text"] for a in _hist_log[-12:]
                        if a.get("character") == char}
        # Priority: heal wounded > carry incapacitated > normal action
        heal_action = _check_heal_priority(char)
        carry_action = _check_carry_priority(char) if not heal_action else None
        if heal_action:
            action_type, text, skill, dice_override, difficulty, move_to = heal_action
        elif carry_action:
            action_type, text, skill, dice_override, difficulty, move_to = carry_action
        else:
            pool = act_actions.get(char, [])
            if not pool and act_fallback:
                pool = act_fallback.get(char, [])
            if not pool:
                continue
            # Position-aware selection: prefer reachable moves, avoid wasted turns
            action_type, text, skill, dice_override, difficulty, move_to = (
                _pick_reachable_action(char, pool, recent_texts=recent_texts)
            )

        # Log the action to game state (viewer key matches bot:slug format)
        bot_slug = char.lower().replace(" ", "-").replace("'", "")
        out = run_rpg_cmd([
            "log-action", "--viewer", f"bot:{bot_slug}",
            "--type", action_type, "--text", text,
        ])
        label = "[CLIMAX]" if is_climax else "[sim]"
        logger.info(f"  {label} {char} {action_type}: {text}")
        transcript.log_player_action("bot", char, action_type, text)
        logged_actions.append({"text": text})

        # Compute movement penalty if moving
        move_penalty = 0
        max_dist = 0
        if move_to:
            move_penalty, max_dist = _compute_move_penalty(char, move_to)
            if move_penalty >= 3:
                logger.info(f"  [BLOCKED] {char} can't reach {move_to} (too far to sprint)")
                move_to = None  # Skip the move
                move_penalty = 0
            elif move_penalty > 0:
                tier = _MOVE_TIER_LABELS.get(move_penalty, "?")
                logger.info(f"  [{tier}] {char} -> {move_to} (-{move_penalty}D)")

        # Move token if this action has a position hint
        if move_to:
            move_cmd = ["move-token", "--character", char, "--position", move_to]
            if max_dist > 0:
                move_cmd += ["--max-distance", str(max_dist)]
            run_rpg_cmd(move_cmd)
            logger.info(f"  [move] {char} -> {move_to}")
            positions.append(move_to)
            pc_position_map[char] = move_to

            # Auto-transfer if this position is a map connection exit
            _maybe_auto_transfer(char, move_to)

            # Move companion NPCs whose keywords appear in the action text
            text_lower = text.lower()
            moved_npcs = set()
            companion_kw = _mod("companion_keywords", COMPANION_NPC_KEYWORDS)
            for keyword, npc_names in companion_kw.items():
                if keyword in text_lower:
                    for npc_name in npc_names:
                        if npc_name not in moved_npcs:
                            run_rpg_cmd(["move-token", "--character", npc_name, "--position", move_to])
                            logger.info(f"  [move-npc] {npc_name} -> {move_to} (follows {char})")
                            moved_npcs.add(npc_name)

        # Spend CP/FP during climax for dramatic dice boost
        cp_spent = False
        if is_climax and skill:
            # Force-sensitive characters spend FP on Force skills
            if char == "Zeph Ando" and skill in ("Sense", "Control", "Alter"):
                out = run_rpg_cmd(["spend-fp", "--character", char])
                if "spent" in out:
                    cp_spent = True
                    logger.info(f"  [spend-fp] {char}: {out}")
            else:
                out = run_rpg_cmd(["spend-cp", "--character", char])
                if "spent" in out:
                    cp_spent = True
                    logger.info(f"  [spend-cp] {char}: {out}")

        # Pre-roll skill check if this action has one
        if skill:
            char_stats = _mod("char_stats", CHAR_STATS)
            result = pre_roll_skill_check(char, skill, difficulty,
                                          penalty=move_penalty, char_stats=char_stats)
            if "error" not in result:
                detail = result["detail"]
                if cp_spent:
                    detail += " [DOUBLED — CP/FP spent!]"
                dice_strings.append(detail)
                logger.info(f"  [dice] {detail}")
                # Apply wound on successful Blaster/Brawling/Lightsaber hits
                if skill in ("Blaster", "Brawling", "Lightsaber") and result.get("success"):
                    opponent = _pick_combat_opponent(act_num, text)
                    _apply_wound(opponent, 1)
                # Act 3: ship repair gate
                if (skill == "Starship Repair" and result.get("success")
                        and pacer is not None):
                    pacer.ship_repaired = True
                    logger.info(f"  [OBJECTIVE] Ship repaired by {char}!")
                # Healing: successful First Aid reduces ally wound level
                if skill == "First Aid" and result.get("success"):
                    # Find the wounded ally from the action text
                    for pc in pregens:
                        if pc != char and pc in text:
                            _heal_wound(pc, 1)
                            break
                dice_code = dice_override or char_stats.get(char, {}).get(skill, DEFAULT_DICE)
                transcript.log_dice_roll(
                    char, skill, dice_code,
                    result["total"], detail,
                    difficulty, result["success"])
                _log_dice_to_state(char, skill, result)

    # NPC counter-attack: one hostile NPC shoots at a random able PC each turn
    npc_pos = _mod("npc_starting_positions", NPC_STARTING_POSITIONS)
    hostile_npcs = npc_pos.get(act_num, {})
    hostile_names = [n for n, (_, color, _) in hostile_npcs.items()
                     if color == "#f54e4e" and _get_wound_level(n) < 3]
    able_targets = [c for c in pregens if _get_wound_level(c) < 3]
    if hostile_names and able_targets:
        attacker = random.choice(hostile_names)
        target = random.choice(able_targets)
        npc_attack = pre_roll_skill_check(attacker, "Blaster")
        pc_dodge = pre_roll_skill_check(target, "Dodge")
        if "error" not in npc_attack and "error" not in pc_dodge:
            hit = npc_attack["total"] > pc_dodge["total"]
            detail = (
                f"{attacker} fires at {target}: "
                f"{npc_attack['total']} vs dodge {pc_dodge['total']} "
                f"— {'HIT!' if hit else 'MISS'}"
            )
            dice_strings.append(detail)
            logger.info(f"  [npc-attack] {detail}")
            if hit:
                _apply_wound(target, 1)

    # NPC movement: hostile NPCs advance toward nearest PC, civilians react
    _move_npcs_dry_run(act_num, turn_num)

    action_class = _classify_actions(logged_actions)
    if action_class == "explore":
        logger.info(f"  [classify] EXPLORE — off-script action detected")
    return dice_strings, positions, pc_position_map, action_class


# Track ambient NPC route indices across turns (reset per act in the act loop)
_npc_roam_index: dict[str, int] = {}


def _move_npcs_dry_run(act_num: int, turn_num: int) -> None:
    """Move NPCs during dry-run: hostiles advance, civilians roam or flee."""
    # Combat reactions on turn 1 (hostiles engage, civilians flee/cover)
    combat_reactions = _mod("npc_combat_reactions", NPC_COMBAT_REACTIONS)
    reactions = combat_reactions.get(act_num, {})
    if turn_num == 1:
        for npc_name, (reaction, dest) in reactions.items():
            if _get_wound_level(npc_name) >= 3:
                continue
            run_rpg_cmd(["move-token", "--character", npc_name, "--position", dest])
            logger.info(f"  [npc-react] {npc_name} {reaction}s -> {dest}")

    # Hostile NPC advancement (one-shot routes toward PCs)
    hostile_routes = _mod("npc_hostile_advance", NPC_HOSTILE_ADVANCE)
    advancers = hostile_routes.get(act_num, {})
    for npc_name, route in advancers.items():
        if _get_wound_level(npc_name) >= 3:
            continue
        idx = _npc_roam_index.get(npc_name, 0)
        if idx < len(route):
            pos = route[idx]
            run_rpg_cmd(["move-token", "--character", npc_name, "--position", pos])
            _npc_roam_index[npc_name] = idx + 1
            logger.info(f"  [npc-advance] {npc_name} -> {pos}")

    # Ambient NPC routes (civilians cycle through positions on non-combat turns)
    ambient_routes = _mod("npc_ambient_routes", NPC_AMBIENT_ROUTES)
    roamers = ambient_routes.get(act_num, {})
    for npc_name, route in roamers.items():
        if _get_wound_level(npc_name) >= 3:
            continue
        idx = _npc_roam_index.get(npc_name, 0)
        pos = route[idx % len(route)]
        run_rpg_cmd(["move-token", "--character", npc_name, "--position", pos])
        _npc_roam_index[npc_name] = idx + 1


def _run_gm_turn(act_num: int, turn_num: int, transcript: TranscriptLogger,
                  extra_context: str = "", dice_results: list = None,
                  since_action: int = 0):
    """Execute one GM turn: build context, inject dice results, call bot.

    Args:
        since_action: Action-log index — only show actions after this so the
            GM doesn't repeat narration from previous turns.
    """
    logger.info(f"\n--- Act {act_num}, Turn {turn_num} ---")

    # Show thinking
    run_rpg_cmd(["update-scene", "--narration",
                 "The Game Master considers the situation... (thinking)"])

    act_times = _mod("act_times")
    state, context = build_context(since_action=since_action, act_times=act_times)
    if state is None:
        logger.error(f"  ERROR: {context}")
        transcript.log_session_event("error", {"message": context})
        return ""

    # Act kick only on turn 0 (cutscene opening); later turns just respond
    # to NEW actions — repeating the kick causes the GM to re-narrate the opening
    act_kicks = _mod("act_kicks")
    kick = get_act_kick(act_num, act_kicks=act_kicks) if turn_num == 0 else ""

    # Build DICE RESULTS section from pre-rolled results
    dice_section = ""
    if dice_results:
        dice_lines = "\n".join(f"  {r}" for r in dice_results)
        dice_section = (
            f"\nDICE RESULTS (already rolled — narrate around these):\n"
            f"{dice_lines}\n"
        )

    user_prompt = (
        f"{context}\n\n{kick}\n{extra_context}\n{dice_section}\n"
        "Call update_narration with dramatic narration, and log_action for each bot character."
    )

    messages = [
        {"role": "system", "content": GM_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    t0 = time.time()
    logger.info(f"  Sending to Ollama...")

    try:
        response = chat(messages)
    except Exception as e:
        logger.error(f"  ERROR calling Ollama: {e}")
        transcript.log_session_event("error", {"message": str(e)})
        return ""

    elapsed = time.time() - t0
    msg = response.get("message", {})
    logger.info(f"  Response in {elapsed:.0f}s")

    try:
        text, narration_from_tool = process_response(msg, messages, transcript)
    except Exception as e:
        logger.error(f"  ERROR processing GM response: {e}")
        transcript.log_session_event("error", {"message": f"process_response: {e}"})
        return ""

    # Detect filler narration from confused models
    def _is_filler(t: str) -> bool:
        if not t:
            return False
        low = t.lower()
        return any(p in low for p in (
            "considers the situation",
            "the scene has been set up",
            "what would you like to do",
            "waiting for the players",
            "can't perform the function",
            "i cannot perform",
        ))

    # Prefer narration from update_narration tool call, fall back to cleaned text
    raw_narration = narration_from_tool or clean_narration(text) or "(no narration)"
    if _is_filler(raw_narration):
        session_scene = state.get("session", {}).get("scene", "the scene") if state else "the scene"
        narration = f"The action intensifies in {session_scene}..."
        logger.info(f"  >> Replaced filler narration")
    else:
        narration = raw_narration
    transcript.log_narration(act_num, turn_num, narration, text)

    # If the tool call didn't fire (model refused or failed), push the
    # fallback narration to the overlay so it doesn't stay on "thinking..."
    if not narration_from_tool and narration and narration != "(no narration)":
        run_rpg_cmd(["update-scene", "--narration", narration[:500]])
        logger.info(f"  >> OVERLAY: auto-updated narration from bot text")

    if narration and narration != "(no narration)":
        logger.info(f"  GM: {narration[:100]}...")
        # Send narration to Twitch chat (best-effort — don't break game on failure)
        try:
            import twitch_client
            twitch_client.send_chat_message(f"[GM] {narration}")
        except Exception as e:
            logger.warning(f"  Twitch chat send failed: {e}")
    else:
        logger.info(f"  (no text response)")

    return text


def _get_available_characters():
    """Return list of bot-controlled characters (available for players)."""
    status = run_rpg_cmd(["status"])
    available = []
    pregens = _mod("pregens", PREGENS)
    for char in pregens:
        # Status shows "Name (bot)" or "Name (bot:slug)" — match either
        if f"{char} (bot)" in status or f"{char} (bot:" in status:
            available.append(char)
    return available


def _run_join_prompt(transcript: TranscriptLogger):
    """Announce available characters for viewers to join."""
    available = _get_available_characters()
    if not available:
        return
    char_list = ", ".join(available)
    msg = f"Characters available: {char_list}. Type !join [name] to play!"
    run_rpg_cmd(["update-scene", "--narration", msg])
    logger.info(f"  JOIN PROMPT: {msg}")
    transcript.log_join_prompt(available)


def _run_poll(poll: dict, transcript: TranscriptLogger, wait_secs: int = 5):
    """Run a chat-based poll. In dry-run, simulate responses."""
    question = poll["question"]
    options = poll["options"]

    run_rpg_cmd(["update-scene", "--narration", question])
    logger.info(f"  POLL: {question}")
    transcript.log_feedback_poll(question, options)

    # Wait for responses (short for dry run, longer for live)
    time.sleep(wait_secs)

    # Simulate poll responses for dry run
    simulated = {}
    for opt in ["1", "2", "3"]:
        simulated[opt] = random.randint(0, 3)
    transcript.log_feedback_response(question, simulated)
    winner = max(simulated, key=simulated.get)
    total = sum(simulated.values())
    if total > 0:
        pct = int(simulated[winner] / total * 100)
        result_msg = f"Poll results: {pct}% chose option {winner}"
    else:
        result_msg = "Poll results: no responses"
    run_rpg_cmd(["update-scene", "--narration", result_msg])
    logger.info(f"  POLL RESULT: {simulated} -> {result_msg}")


def _end_session(transcript: TranscriptLogger):
    """End session — calculate participation and gate persistence."""
    participation = transcript.calculate_participation()
    is_canon = participation["is_canon"]
    label = "CANON" if is_canon else "non-canon"
    logger.info(f"\n  Participation: {participation['real_actions']}/{participation['total_actions']} "
                f"real ({participation['ratio']:.0%}) -> {label}")
    transcript.log_session_event("participation", participation)

    canon_flag = "--canon" if is_canon else "--no-canon"
    out = run_rpg_cmd(["end-session", canon_flag])
    logger.info(f"  end-session: {out}")
    transcript.log_session_event("end", {"canon": is_canon})

    md_path = transcript.save_markdown()
    logger.info(f"  Transcript saved: {transcript.jsonl_path}")
    logger.info(f"  Markdown saved:   {md_path}")
    transcript.close()
    return md_path


def _write_closing_crawl(transcript: TranscriptLogger):
    """Generate and store closing crawl data for the show flow to display."""
    # Use module closing_crawl if available, otherwise fall back to hardcoded
    module_crawl = _mod("closing_crawl", None)
    if module_crawl and isinstance(module_crawl, dict) and module_crawl.get("paragraphs"):
        crawl_data = module_crawl
    else:
        # Build summary from transcript events
        narrations = []
        wounds = {}
        acts_completed = 0
        for ev in transcript.events:
            if ev.get("type") == "narration":
                narrations.append(ev.get("narration", ""))
            if ev.get("type") == "act_end":
                acts_completed = ev.get("data", {}).get("act", acts_completed)
            if ev.get("type") == "session_event" and ev.get("data", {}).get("event") == "wound":
                char = ev.get("data", {}).get("character", "")
                wounds[char] = ev.get("data", {}).get("level", 0)

        # Hardcoded fallback for Mos Eisley
        paragraphs = [
            "Our heroes fought through the cantina lockdown, "
            "navigated the dangerous streets of Mos Eisley, "
            "and battled their way to Docking Bay 87.",

            "Against all odds, they reached the Rusty Mynock "
            "and blasted free from the Imperial blockade. "
            "The stars of hyperspace welcome them... for now.",

            "What dangers await in the Outer Rim? "
            "Will the Empire's pursuit catch up? "
            "Find out next time on Star Wars: Game Night!",
        ]

        crawl_data = {
            "title": "STAR WARS",
            "subtitle": "Session Complete",
            "episodeTitle": "Escape from Mos Eisley",
            "paragraphs": paragraphs,
        }

    # Write directly to state file — session is already ended so update-scene
    # would reject the command. The show flow reads this field from game-state.json.
    state_path = os.environ.get(
        "RPG_STATE_FILE",
        "/home/node/.openclaw/rpg/state/game-state.json",
    )
    try:
        with open(state_path) as f:
            state = json.load(f)
        state["closing_crawl"] = crawl_data
        # Atomic write: temp file + os.replace to prevent corruption
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=os.path.dirname(state_path), suffix=".tmp"
        )
        try:
            with os.fdopen(tmp_fd, "w") as f:
                json.dump(state, f, indent=2)
                f.write("\n")
            os.replace(tmp_path, state_path)
        except BaseException:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise
        logger.info(f"\n  === CLOSING CRAWL ===")
        logger.info(f"  {crawl_data.get('subtitle', '')} — {crawl_data.get('episodeTitle', '')}")
        for p in crawl_data.get("paragraphs", []):
            logger.info(f"  {p}")
        logger.info(f"  ======================\n")
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning(f"  WARNING: Could not write closing crawl: {e}")


# ---------------------------------------------------------------------------
# Dry-run mode
# ---------------------------------------------------------------------------

def run_dry_session(adventure: str):
    """Full dry-run session: bot plays all characters through 3 acts."""
    session_id = f"session-{datetime.now().strftime('%Y-%m-%d-%H%M%S')}"
    transcript = TranscriptLogger(session_id)

    logger.info(f"=== DRY RUN: {adventure} (objective-based pacing) ===\n")
    transcript.log_session_event("start", {
        "mode": "dry-run",
        "adventure": adventure,
    })

    _init_session(adventure, transcript)

    total_turns = 0
    last_action_idx = 0  # track where GM left off in action_log

    num_acts = _mod("num_acts", 3)
    for act_num in range(1, num_acts + 1):
        if not _running:
            break

        logger.info(f"\n{'='*40}")
        logger.info(f"=== ACT {act_num} ===")
        logger.info(f"{'='*40}\n")

        # Set map and update scene
        _set_act_map(act_num, transcript)
        _update_scene_for_act(act_num)

        # Cutscene for act opening
        run_rpg_cmd(["set-mode", "--mode", "cutscene"])
        transcript.log_mode_change("cutscene", f"Act {act_num} opening")
        _run_gm_turn(act_num, 0, transcript,
                      "This is the act opening. Set the scene dramatically.",
                      since_action=last_action_idx)
        # Update action index after GM turn
        _st, _ = build_context()
        if _st:
            last_action_idx = len(_st.get("action_log", []))
        time.sleep(2)

        # Switch to RP mode
        run_rpg_cmd(["set-mode", "--mode", "rp"])
        transcript.log_mode_change("rp", f"Act {act_num} gameplay")

        # Objective-based turn loop — acts end when PCs complete objectives
        pacer = ActPacer(act_num)
        # Seed pc_positions from starting positions so all PCs are tracked
        start_pos = _mod("act_starting_positions", ACT_STARTING_POSITIONS).get(act_num, {})
        pacer.pc_positions = dict(start_pos)
        _npc_roam_index.clear()

        while not pacer.should_end_act() and _running:
            turn = pacer.turn + 1
            total_turns += 1

            # Simulate player actions — climax pool when objectives nearly met
            dice_strings, positions, pc_pos_map, action_class = \
                _simulate_player_actions(
                    act_num, turn, transcript,
                    is_climax=pacer.is_climax, pacer=pacer)
            pacer.record_turn(positions, pc_position_map=pc_pos_map)
            time.sleep(1)

            # GM responds with exploration kick + pacing hint
            extra = _EXPLORE_KICK if action_class == "explore" else ""
            extra += "\n" + pacer.pacing_hint()
            _run_gm_turn(act_num, turn, transcript,
                          extra_context=extra, dice_results=dice_strings,
                          since_action=last_action_idx)
            # Update action index after GM turn
            _st, _ = build_context()
            if _st:
                last_action_idx = len(_st.get("action_log", []))
            time.sleep(2)

            # Status line
            act3_extra = ""
            if act_num == 3:
                aboard = pacer._all_surviving_aboard()
                act3_extra = (f" repaired={pacer.ship_repaired}"
                              f" all_aboard={aboard}")
            logger.debug(f"  [pacer] turn={pacer.turn} visited={sorted(pacer.visited)} "
                        f"exit={pacer.reached_exit} climax_next={pacer.is_climax}"
                        f"{act3_extra}")

        # Log act summary
        logger.info(f"\n  ACT {act_num} COMPLETE: {pacer.turn} turns, "
                    f"visited={sorted(pacer.visited)}")
        transcript.log_session_event("act_end", {
            "act": act_num,
            "turns": pacer.turn,
            "reached_exit": pacer.reached_exit,
            "visited": sorted(pacer.visited),
        })

        # Between acts: join prompt + poll
        if act_num < 3 and _running:
            _run_join_prompt(transcript)
            time.sleep(2)
            _run_poll(BETWEEN_ACT_POLL, transcript, wait_secs=3)
            time.sleep(2)

    # Post-session poll
    if _running:
        _run_poll(POST_SESSION_POLL, transcript, wait_secs=3)

    # End
    md_path = _end_session(transcript)
    _write_closing_crawl(transcript)

    logger.info(f"\n{'='*40}")
    logger.info(f"=== DRY RUN COMPLETE ===")
    logger.info(f"  Total GM turns: {total_turns}")
    logger.info(f"  Transcript events: {len(transcript.events)}")
    logger.info(f"  Markdown: {md_path}")
    logger.info(f"{'='*40}\n")

    # Final state
    logger.info(run_rpg_cmd(["status"]))
    return md_path


# ---------------------------------------------------------------------------
# Live mode — dice rolling for player actions
# ---------------------------------------------------------------------------

# Keywords in action text that indicate a combat/skill check
_COMBAT_KEYWORDS = {"fire", "shoot", "blast", "attack", "punch", "kick",
                     "strike", "swing", "throw", "stab", "slash"}
_SKILL_KEYWORDS = {
    "dodge": "Dodge", "sneak": "Sneak", "hide": "Sneak",
    "search": "Search", "hack": "Computer Prog", "slice": "Computer Prog",
    "repair": "Droid Repair", "fix": "Starship Repair",
    "pilot": "Starship Piloting", "navigate": "Astrogation",
    "heal": "First Aid", "first aid": "First Aid",
    "bargain": "Bargain", "negotiate": "Bargain",
    "intimidate": "Intimidation", "threaten": "Intimidation",
    "sense": "Sense", "feel": "Sense",
    "lightsaber": "Lightsaber",
}


_HOSTILE_COLOR = "#f54e4e"  # Red NPCs are hostile


def _pick_combat_opponent(act_num: int, action_text: str) -> str:
    """Pick the most relevant hostile NPC for a combat roll.

    Checks the action text for NPC name mentions first, then falls
    back to the first hostile NPC in the act's starting positions.
    """
    npc_pos = _mod("npc_starting_positions", NPC_STARTING_POSITIONS)
    npcs = npc_pos.get(act_num, {})
    hostile = [name for name, (_, color, _) in npcs.items()
               if color == _HOSTILE_COLOR]

    # Check if the action text names a specific hostile NPC
    # Players can say "!do fire at Greevak" or "!do shoot the trooper"
    text_lower = action_text.lower()
    for name in hostile:
        # Match full name ("Lt. Hask") or any word ("hask", "greevak", "stormtrooper")
        if name.lower() in text_lower:
            return name
        for word in name.lower().replace(".", "").split():
            if len(word) > 2 and word in text_lower:
                return name

    # Also check non-hostile NPCs the player might target
    all_npcs = npc_pos.get(act_num, {})
    for name in all_npcs:
        if name.lower() in text_lower:
            return name

    # Fall back to act-appropriate primary hostile
    for name in hostile:
        if "lt." in name.lower() or "greevak" in name.lower():
            return name
    return hostile[0] if hostile else "Stormtrooper"


def _roll_dice_for_player_actions(new_actions, transcript, act_num,
                                   pacer: "ActPacer | None" = None):
    """Roll dice for player combat/skill actions in live mode.

    Returns list of dice result strings for the GM prompt.
    Side-effect: sets pacer.ship_repaired on successful Starship Repair.
    """
    dice_strings = []
    for a in new_actions:
        char = a.get("character", "")
        text_lower = a.get("text", "").lower()
        viewer = a.get("viewer", "")

        # Skip bot actions — bot dice are pre-rolled by _pre_roll_bot_actions()
        if viewer.startswith("bot"):
            continue

        # Resolve movement intent from natural language
        move_to, move_penalty = _resolve_player_movement(char, a.get("text", ""))
        if move_to:
            char_move_map = _mod("char_move", CHAR_MOVE)
            move_allowance = char_move_map.get(char, DEFAULT_MOVE)
            max_dist = move_allowance * 4
            move_cmd = ["move-token", "--character", char, "--position", move_to]
            if max_dist > 0:
                move_cmd += ["--max-distance", str(max_dist)]
            run_rpg_cmd(move_cmd)
            _invalidate_state_cache()
            tier = _MOVE_TIER_LABELS.get(move_penalty, "sprint")
            terrain = _load_current_terrain()
            pos_desc = move_to
            if terrain:
                pos_desc = terrain.get("positions", {}).get(move_to, {}).get("desc", move_to)
            dice_strings.append(f"{char} moves to {pos_desc} ({tier})")
            logger.info(f"  [move-player] {char} -> {move_to} ({tier})")
            _maybe_auto_transfer(char, move_to)

        # Check for combat action (blaster fire, etc.)
        if any(kw in text_lower for kw in _COMBAT_KEYWORDS):
            # Determine skill: default to Blaster for ranged, Brawling for melee
            if any(kw in text_lower for kw in ("punch", "kick", "strike", "swing", "stab")):
                skill = "Brawling"
            elif "lightsaber" in text_lower:
                skill = "Lightsaber"
            else:
                skill = "Blaster"

            opponent = _pick_combat_opponent(act_num, a.get("text", ""))

            # Roll PC attack (movement penalty applied if moving + fighting)
            result = pre_roll_skill_check(char, skill, penalty=move_penalty)
            if "error" not in result:
                # Roll NPC dodge
                npc_dodge = pre_roll_skill_check(opponent, "Dodge")
                hit = result["total"] > npc_dodge.get("total", 10)
                detail = (
                    f"{char} {skill}: {result['detail']} "
                    f"vs {opponent} Dodge: {npc_dodge.get('detail', '?')} "
                    f"— {'HIT!' if hit else 'MISS'}"
                )
                dice_strings.append(detail)
                logger.info(f"  [dice-live] {detail}")
                if hit:
                    _apply_wound(opponent, 1)
                cs = _mod("char_stats", CHAR_STATS)
                transcript.log_dice_roll(
                    char, skill,
                    cs.get(char, {}).get(skill, DEFAULT_DICE),
                    result["total"], detail, npc_dodge.get("total"),
                    hit)
                _log_dice_to_state(char, skill, result)
            continue

        # Check for skill-based action
        for kw, skill in _SKILL_KEYWORDS.items():
            if kw in text_lower:
                cs = _mod("char_stats", CHAR_STATS)
                # Movement penalty applied if moving + using skill
                result = pre_roll_skill_check(char, skill, difficulty=15,
                                              penalty=move_penalty,
                                              char_stats=cs)
                if "error" not in result:
                    dice_strings.append(result["detail"])
                    logger.info(f"  [dice-live] {result['detail']}")
                    if (skill == "Starship Repair" and result.get("success")
                            and pacer is not None):
                        pacer.ship_repaired = True
                        logger.info(f"  [OBJECTIVE] Ship repaired by {char}!")
                    transcript.log_dice_roll(
                        char, skill,
                        cs.get(char, {}).get(skill, DEFAULT_DICE),
                        result["total"], result["detail"],
                        15, result.get("success"))
                    _log_dice_to_state(char, skill, result)
                break

    return dice_strings


def _pre_roll_bot_actions(act_num: int, transcript: TranscriptLogger,
                          pacer: "ActPacer") -> list[str]:
    """Pre-roll dice for 1-2 bot character actions in live mode.

    Picks random actions from the bot action pool (same pools as dry-run),
    logs them to game state, and returns dice strings for the GM prompt.
    """
    dice_strings = []
    positions = []

    # Get bot-controlled characters that are still able to act
    status = run_rpg_cmd(["status"])
    pregens = _mod("pregens", PREGENS)
    bot_chars = [c for c in pregens
                 if f"{c} (bot:" in status and _get_wound_level(c) < 3]
    if not bot_chars:
        return dice_strings

    # All bot characters act every turn
    chars = bot_chars

    act_climax = _mod("act_climax_actions", ACT_CLIMAX_ACTIONS)
    act_bot = _mod("act_bot_actions", ACT_BOT_ACTIONS)
    is_climax = pacer.is_climax
    if is_climax:
        act_actions = act_climax.get(act_num, {})
        act_fallback = act_bot.get(act_num, {})
    else:
        act_actions = act_bot.get(act_num, {})
        act_fallback = {}

    # Build per-character recent action texts to avoid mindless repetition
    _hist_state = _load_game_state()
    _hist_log = _hist_state.get("action_log", []) if _hist_state else []

    pc_pos_map = {}
    for char in chars:
        recent_texts = {a["text"] for a in _hist_log[-12:]
                        if a.get("character") == char}
        # Priority: heal wounded > carry incapacitated > normal action
        heal_action = _check_heal_priority(char)
        carry_action = _check_carry_priority(char) if not heal_action else None
        if heal_action:
            action_type, text, skill, dice_override, difficulty, move_to = heal_action
        elif carry_action:
            action_type, text, skill, dice_override, difficulty, move_to = carry_action
        else:
            pool = act_actions.get(char, [])
            if not pool and act_fallback:
                pool = act_fallback.get(char, [])
            if not pool:
                continue
            action_type, text, skill, dice_override, difficulty, move_to = (
                _pick_reachable_action(char, pool, recent_texts=recent_texts)
            )

        # Log the action to game state (viewer key matches bot:slug format)
        bot_slug = char.lower().replace(" ", "-").replace("'", "")
        out = run_rpg_cmd([
            "log-action", "--viewer", f"bot:{bot_slug}",
            "--type", action_type, "--text", text,
        ])
        logger.info(f"  [bot-live] {char} {action_type}: {text}")
        transcript.log_player_action("bot", char, action_type, text)

        # Compute movement penalty if moving
        move_penalty = 0
        max_dist = 0
        if move_to:
            move_penalty, max_dist = _compute_move_penalty(char, move_to)
            if move_penalty >= 3:
                logger.info(f"  [BLOCKED] {char} can't reach {move_to} (too far to sprint)")
                move_to = None
                move_penalty = 0
            elif move_penalty > 0:
                tier = _MOVE_TIER_LABELS.get(move_penalty, "?")
                logger.info(f"  [{tier}] {char} -> {move_to} (-{move_penalty}D)")

        if move_to:
            move_cmd = ["move-token", "--character", char, "--position", move_to]
            if max_dist > 0:
                move_cmd += ["--max-distance", str(max_dist)]
            run_rpg_cmd(move_cmd)
            logger.info(f"  [move] {char} -> {move_to}")
            positions.append(move_to)

            # Auto-transfer if this position is a map connection exit
            _maybe_auto_transfer(char, move_to)

            # Move companion NPCs
            text_lower = text.lower()
            moved_npcs = set()
            companion_kw = _mod("companion_keywords", COMPANION_NPC_KEYWORDS)
            for keyword, npc_names in companion_kw.items():
                if keyword in text_lower:
                    for npc_name in npc_names:
                        if npc_name not in moved_npcs:
                            run_rpg_cmd(["move-token", "--character", npc_name, "--position", move_to])
                            logger.info(f"  [move-npc] {npc_name} -> {move_to}")
                            moved_npcs.add(npc_name)

        # Track PC position for pacer
        if move_to:
            pc_pos_map[char] = move_to

        if skill:
            char_stats = _mod("char_stats", CHAR_STATS)
            result = pre_roll_skill_check(char, skill, difficulty,
                                          penalty=move_penalty, char_stats=char_stats)
            if "error" not in result:
                dice_strings.append(result["detail"])
                logger.info(f"  [dice-bot] {result['detail']}")
                # Apply wound on successful combat hits
                if skill in ("Blaster", "Brawling", "Lightsaber") and result.get("success"):
                    opponent = _pick_combat_opponent(act_num, text)
                    _apply_wound(opponent, 1)
                # Act 3: ship repair gate
                if skill == "Starship Repair" and result.get("success"):
                    pacer.ship_repaired = True
                    logger.info(f"  [OBJECTIVE] Ship repaired by {char}!")
                # Healing: successful First Aid reduces ally wound level
                if skill == "First Aid" and result.get("success"):
                    pregens = _mod("pregens", PREGENS)
                    for pc in pregens:
                        if pc != char and pc in text:
                            _heal_wound(pc, 1)
                            break
                dice_code = dice_override or char_stats.get(char, {}).get(skill, DEFAULT_DICE)
                transcript.log_dice_roll(
                    char, skill, dice_code,
                    result["total"], result["detail"],
                    difficulty, result["success"])
                _log_dice_to_state(char, skill, result)

    # NPC counter-attack: one hostile NPC shoots at a random able PC each turn
    npc_pos = _mod("npc_starting_positions", NPC_STARTING_POSITIONS)
    hostile_npcs = npc_pos.get(act_num, {})
    hostile_names = [n for n, (_, color, _) in hostile_npcs.items()
                     if color == "#f54e4e" and _get_wound_level(n) < 3]
    pregens = _mod("pregens", PREGENS)
    able_targets = [c for c in pregens if _get_wound_level(c) < 3]
    if hostile_names and able_targets:
        attacker = random.choice(hostile_names)
        target = random.choice(able_targets)
        npc_attack = pre_roll_skill_check(attacker, "Blaster")
        pc_dodge = pre_roll_skill_check(target, "Dodge")
        if "error" not in npc_attack and "error" not in pc_dodge:
            hit = npc_attack["total"] > pc_dodge["total"]
            detail = (
                f"{attacker} fires at {target}: "
                f"{npc_attack['total']} vs dodge {pc_dodge['total']} "
                f"— {'HIT!' if hit else 'MISS'}"
            )
            dice_strings.append(detail)
            logger.info(f"  [npc-attack] {detail}")
            if hit:
                _apply_wound(target, 1)

    if positions:
        pacer.record_turn(positions, pc_position_map=pc_pos_map)

    return dice_strings


def run_live_session(adventure: str):
    """Live session loop — waits for real Twitch input, GM responds."""
    session_id = f"session-{datetime.now().strftime('%Y-%m-%d-%H%M%S')}"
    transcript = TranscriptLogger(session_id)

    logger.info(f"=== LIVE SESSION: {adventure} ===\n")
    transcript.log_session_event("start", {
        "mode": "live",
        "adventure": adventure,
    })

    _init_session(adventure, transcript)

    act_num = 1
    turn_num = 0
    last_action_count = 0
    last_gm_time = time.time()
    last_roam_time = time.time()
    roam_interval = int(os.environ.get("RPG_ROAM_INTERVAL", "30"))
    roam_index = {}  # tracks position in each NPC's route
    npcs_reacted = False  # True once NPCs have reacted to combat
    min_turn_cooldown = int(os.environ.get("RPG_TURN_COOLDOWN", "120"))
    gm_idle_threshold = int(os.environ.get("RPG_IDLE_THRESHOLD", "180"))
    poll_interval = int(os.environ.get("RPG_POLL_INTERVAL", "10"))
    pacer = ActPacer(act_num)

    _set_act_map(act_num, transcript)
    _update_scene_for_act(act_num)

    # Cutscene opening
    run_rpg_cmd(["set-mode", "--mode", "cutscene"])
    transcript.log_mode_change("cutscene", "Session opening")
    _run_gm_turn(act_num, 0, transcript,
                  "This is the session opening. Set the scene dramatically.",
                  since_action=last_action_count)
    # Update action index after GM turn
    _st, _ = build_context(adventure)
    if _st:
        last_action_count = len(_st.get("action_log", []))
    run_rpg_cmd(["set-mode", "--mode", "rp"])
    transcript.log_mode_change("rp", "Gameplay begins")
    _run_join_prompt(transcript)
    last_gm_time = time.time()

    logger.info(f"\n  Entering live polling loop (every {poll_interval}s)...")
    logger.info(f"  Ctrl+C to end session.\n")

    while _running:
        time.sleep(poll_interval)
        try:
            # Read current state
            state, context = build_context(adventure)
            if state is None:
                logger.error(f"  ERROR: {context}")
                continue

            session = state.get("session", {})
            mode = session.get("mode", "rp")
            current_act = session.get("act", act_num)

            # Check for act advancement
            if current_act != act_num:
                act_num = current_act
                pacer = ActPacer(act_num)
                turn_num = 0
                roam_index.clear()
                npcs_reacted = False
                logger.info(f"\n  ACT CHANGE -> Act {act_num}")
                _set_act_map(act_num, transcript)
                _update_scene_for_act(act_num)
                run_rpg_cmd(["set-mode", "--mode", "cutscene"])
                transcript.log_mode_change("cutscene", f"Act {act_num} opening")
                _run_gm_turn(act_num, 0, transcript,
                              "New act begins. Set the scene.",
                              since_action=last_action_count)
                run_rpg_cmd(["set-mode", "--mode", "rp"])
                transcript.log_mode_change("rp", f"Act {act_num} gameplay")
                _run_join_prompt(transcript)
                _run_poll(BETWEEN_ACT_POLL, transcript, wait_secs=30)
                last_gm_time = time.time()
                last_action_count = len(state.get("action_log", []))
                continue

            # NPC behavior — ambient roaming in RP mode, reactive in combat
            if time.time() - last_roam_time >= roam_interval:
                is_combat = mode == "combat" or state.get("combat_active")
                if is_combat and not npcs_reacted:
                    # Combat just started — NPCs react (one-time)
                    combat_react = _mod("npc_combat_reactions", NPC_COMBAT_REACTIONS)
                    reactions = combat_react.get(current_act, {})
                    for npc_name, (reaction, dest) in reactions.items():
                        run_rpg_cmd(["move-token", "--character", npc_name, "--position", dest])
                        logger.info(f"  [npc-react] {npc_name} {reaction}s -> {dest}")
                    npcs_reacted = True
                if is_combat:
                    # Hostile NPCs advance along routes every roam interval
                    hostile_routes = _mod("npc_hostile_advance", NPC_HOSTILE_ADVANCE)
                    advancers = hostile_routes.get(current_act, {})
                    for npc_name, route in advancers.items():
                        if _get_wound_level(npc_name) >= 3:
                            continue  # incapacitated
                        idx = roam_index.get(npc_name, 0)
                        if idx < len(route):
                            pos = route[idx]
                            run_rpg_cmd(["move-token", "--character", npc_name, "--position", pos])
                            roam_index[npc_name] = idx + 1
                            logger.info(f"  [npc-advance] {npc_name} -> {pos}")
                elif not is_combat:
                    # Peaceful — ambient roaming
                    npcs_reacted = False
                    ambient = _mod("npc_ambient_routes", NPC_AMBIENT_ROUTES)
                    roamers = ambient.get(current_act, {})
                    for npc_name, route in roamers.items():
                        idx = roam_index.get(npc_name, 0)
                        pos = route[idx % len(route)]
                        run_rpg_cmd(["move-token", "--character", npc_name, "--position", pos])
                        roam_index[npc_name] = idx + 1
                last_roam_time = time.time()

            # Count new actions
            actions = state.get("action_log", [])
            new_count = len(actions)

            # Combat mode: handle timers
            if mode == "combat":
                timer_status = run_rpg_cmd(["check-timer"])
                try:
                    timer = json.loads(timer_status)
                    if timer.get("expired"):
                        run_rpg_cmd(["auto-advance"])
                        logger.info(f"  >> AUTO-ADVANCE (timer expired)")
                except (json.JSONDecodeError, ValueError):
                    pass

            # GM responds if there are new player actions (with cooldown)
            time_since_last = time.time() - last_gm_time
            if new_count > last_action_count and time_since_last >= min_turn_cooldown:
                turn_num += 1
                # Read PC token positions from state for pacer exit detection
                pc_positions = []
                pc_pos_map = {}
                for slug, tok in state.get("tokens", {}).items():
                    if tok.get("type") == "pc":
                        pos_name = _position_name_from_token(state, tok)
                        pc_positions.append(pos_name)
                        char_name = tok.get("label", slug)
                        pc_pos_map[char_name] = pos_name
                pacer.record_turn(pc_positions, pc_position_map=pc_pos_map)
                new_actions = actions[last_action_count:]
                action_summary = "; ".join(
                    f"{a.get('character', '?')} {a.get('type', 'do')}s: {a.get('text', '...')}"
                    for a in new_actions
                )
                logger.info(f"  New actions ({new_count - last_action_count}): {action_summary[:100]}")

                # Roll dice for any combat/skill actions from real players
                dice_strings = _roll_dice_for_player_actions(
                    new_actions, transcript, act_num, pacer=pacer)

                # Pre-roll bot character actions with dice (like dry-run does)
                bot_dice = _pre_roll_bot_actions(act_num, transcript, pacer)
                dice_strings.extend(bot_dice)

                action_class = _classify_actions(new_actions)
                if action_class == "explore":
                    extra = _EXPLORE_KICK
                    logger.info(f"  [classify] EXPLORE — off-script action detected")
                else:
                    extra = "Respond to the recent player actions."
                extra += "\n" + pacer.pacing_hint()

                _run_gm_turn(act_num, turn_num, transcript, extra,
                              dice_results=dice_strings,
                              since_action=last_action_count)
                last_gm_time = time.time()
                # Re-read action count AFTER GM turn to include GM's own log_action calls
                post_state, _ = build_context(adventure)
                if post_state:
                    last_action_count = len(post_state.get("action_log", []))
                else:
                    last_action_count = new_count
            elif new_count > last_action_count:
                wait_remaining = int(min_turn_cooldown - time_since_last)
                logger.info(f"  New actions queued, cooldown {wait_remaining}s remaining")

            # Idle check: prompt quiet players (only after cooldown + idle threshold)
            elif time_since_last > gm_idle_threshold and mode == "rp":
                idle_check = run_rpg_cmd(["activity-summary"])
                turn_num += 1
                # Bot characters act to keep the scene alive
                bot_dice = _pre_roll_bot_actions(act_num, transcript, pacer)
                _run_gm_turn(act_num, turn_num, transcript,
                              "No new player actions. Prompt a quiet character or advance the scene.",
                              dice_results=bot_dice,
                              since_action=last_action_count)
                last_gm_time = time.time()
                # Update action count after idle GM turn
                post_state, _ = build_context(adventure)
                if post_state:
                    last_action_count = len(post_state.get("action_log", []))

            # Auto-advance act if objectives met (checked every poll, not just during cooldown)
            if pacer.should_end_act():
                if act_num < 3:
                    next_act = act_num + 1
                    logger.info(f"  [pacer] Objectives met — advancing to Act {next_act}")
                    _update_scene_for_act(next_act)
                else:
                    # Adventure complete — closing crawl and end session
                    logger.info(f"  [pacer] Act 3 objectives met — adventure complete!")
                    run_rpg_cmd(["set-mode", "--mode", "cutscene"])
                    _run_gm_turn(act_num, turn_num + 1, transcript,
                                  "The party has escaped Mos Eisley! Write an epic "
                                  "closing narration celebrating their victory.",
                                  since_action=last_action_count)
                    _write_closing_crawl(transcript)
                    break

            # Check if session ended externally
            if session.get("status") == "ended":
                logger.info(f"\n  Session ended externally.")
                break

        except Exception as e:
            logger.error(f"  [poll-error] {type(e).__name__}: {e}")
            continue

    # End session
    if _running:
        _run_poll(POST_SESSION_POLL, transcript, wait_secs=45)
    md_path = _end_session(transcript)

    logger.info(f"\n=== LIVE SESSION COMPLETE ===")
    logger.info(f"  Transcript: {md_path}")
    return md_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    parser = argparse.ArgumentParser(description="RPG session runner")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true",
                       help="Run a simulated session with bot players")
    group.add_argument("--live", action="store_true",
                       help="Run a live session waiting for Twitch input")
    parser.add_argument("--adventure", default="escape-from-mos-eisley",
                        help="Adventure module name (default: escape-from-mos-eisley)")
    args = parser.parse_args()

    if args.dry_run:
        run_dry_session(args.adventure)
    elif args.live:
        run_live_session(args.adventure)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
