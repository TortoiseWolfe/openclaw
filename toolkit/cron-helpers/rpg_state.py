#!/usr/bin/env python3
"""
Star Wars D6 (West End Games) RPG game state manager.

Manages game sessions, player characters, initiative, and wound tracking
as JSON files in the clawd-twitch workspace. Called by the MoltBot agent
via the exec tool during Twitch chat game sessions.

Usage:
    rpg_state.py init --adventure escape-from-mos-eisley
    rpg_state.py join --viewer username --character "Kira Voss"
    rpg_state.py leave --viewer username
    rpg_state.py wound --character "Kira Voss" --level 2
    rpg_state.py initiative --characters "Kira Voss,Renn Darkhollow,Stormtrooper"
    rpg_state.py next-turn
    rpg_state.py award-cp --character "Kira Voss" --points 3
    rpg_state.py update-scene --act 2 --scene "Imperial Checkpoint" [--narration "..."]
    rpg_state.py switch-scene --map mos-eisley-streets.svg
    rpg_state.py transfer-token --character "Kira Voss" --to-map mos-eisley-streets.svg
    rpg_state.py set-camera --position cantina-door --zoom 2.0
    rpg_state.py set-camera --follow-party
    rpg_state.py set-mode --mode combat
    rpg_state.py check-timer
    rpg_state.py auto-advance
    rpg_state.py check-idle
    rpg_state.py activity-summary
    rpg_state.py end-session
    rpg_state.py status
"""

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# Static content — in the repo, COPY'd into the Docker image at /app/rpg/
_CONTENT_DIR = os.environ.get("RPG_CONTENT_DIR", "/app/rpg")
ADVENTURES_DIR = os.path.join(_CONTENT_DIR, "adventures")

# Runtime data — writable location for game state, player saves, session logs
_DATA_DIR = os.environ.get("RPG_DATA_DIR", "/home/node/.clawdbot/rpg")
STATE_DIR = os.path.join(_DATA_DIR, "state")
STATE_FILE = os.path.join(STATE_DIR, "game-state.json")
PLAYERS_DIR = os.path.join(_DATA_DIR, "players")
SESSIONS_DIR = os.path.join(_DATA_DIR, "sessions")

WOUND_LEVELS = ["healthy", "stunned", "wounded", "incapacitated", "mortally_wounded", "dead"]
MAPS_DIR = os.path.join(_CONTENT_DIR, "maps")


# ── Terrain loading and validation ──────────────────────────────────
_terrain_cache: dict[str, dict | None] = {}


def _load_terrain(map_image: str) -> dict | None:
    """Load terrain data for a map. Returns None if no terrain file exists."""
    if map_image in _terrain_cache:
        return _terrain_cache[map_image]
    base = map_image.rsplit(".", 1)[0] if "." in map_image else map_image
    terrain_path = os.path.join(MAPS_DIR, f"{base}-terrain.json")
    terrain = None
    if os.path.exists(terrain_path):
        with open(terrain_path) as f:
            terrain = json.load(f)
    _terrain_cache[map_image] = terrain
    return terrain


def _resolve_position(terrain: dict, name: str) -> tuple[int, int] | None:
    """Look up a named position, returning (x, y) or None."""
    pos = terrain.get("positions", {}).get(name)
    if pos:
        return (pos["x"], pos["y"])
    return None


def _point_in_rect(obs: dict, x: int, y: int) -> bool:
    return obs["x1"] <= x <= obs["x2"] and obs["y1"] <= y <= obs["y2"]


def _snap_to_nearest_edge(obs: dict, x: int, y: int) -> tuple[int, int]:
    """Push a point to the nearest edge of a rectangular obstacle (+ 25px margin)."""
    distances = [
        (abs(x - obs["x1"]), obs["x1"] - 25, y),
        (abs(x - obs["x2"]), obs["x2"] + 25, y),
        (abs(y - obs["y1"]), x, obs["y1"] - 25),
        (abs(y - obs["y2"]), x, obs["y2"] + 25),
    ]
    distances.sort(key=lambda d: d[0])
    return (int(distances[0][1]), int(distances[0][2]))


def _validate_position(terrain: dict, x: int, y: int) -> tuple[bool, int, int, str | None]:
    """Check if (x,y) is inside an obstacle. Returns (valid, snapped_x, snapped_y, obstacle_id)."""
    for obs in terrain.get("obstacles", []):
        if _point_in_rect(obs, x, y):
            sx, sy = _snap_to_nearest_edge(obs, x, y)
            return (False, sx, sy, obs["id"])
    return (True, x, y, None)


def _compute_party_centroid(state: dict) -> tuple[int, int] | None:
    """Average x,y of all visible PC tokens on the current map."""
    map_image = (state.get("map") or {}).get("image", "")
    tokens = state.get("tokens", {})
    xs, ys = [], []
    for t in tokens.values():
        if t.get("type") == "pc" and t.get("visible", True) and t.get("map_id") == map_image:
            xs.append(t["x"])
            ys.append(t["y"])
    if not xs:
        return None
    return (int(sum(xs) / len(xs)), int(sum(ys) / len(ys)))


def _update_camera_for_party(state: dict) -> None:
    """If camera is tracking the party, update camera position to party centroid."""
    camera = state.get("camera")
    if not camera or camera.get("target") != "party":
        return
    centroid = _compute_party_centroid(state)
    if centroid:
        camera["x"], camera["y"] = centroid


def _ensure_dirs() -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    os.makedirs(PLAYERS_DIR, exist_ok=True)
    os.makedirs(SESSIONS_DIR, exist_ok=True)


def _atomic_write(path: str, data: dict) -> None:
    """Write JSON atomically via temp file + rename."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(path), suffix=".tmp"
    )
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp_path, path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def _load_state() -> dict:
    """Load current game state, or return empty dict if none exists."""
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE) as f:
        return json.load(f)


def _save_state(state: dict) -> None:
    """Save game state atomically."""
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    _atomic_write(STATE_FILE, state)


def _slugify(name: str) -> str:
    """Convert a name to a filename-safe slug (no path separators)."""
    s = name.lower().replace(" ", "-").replace("'", "")
    return re.sub(r'[^a-z0-9\-]', '', s)


_SAFE_SLUG = re.compile(r'^[a-zA-Z0-9_\-]+$')


def _validate_slug(value: str, label: str) -> str:
    """Reject path traversal and special characters in path-forming inputs."""
    if not _SAFE_SLUG.match(value):
        print(f"ERROR: Invalid {label}: {value!r}", file=sys.stderr)
        sys.exit(1)
    return value


def _validate_map_filename(value: str, label: str) -> str:
    """Validate a map filename like 'mos-eisley-streets.svg'."""
    base = value.rsplit(".", 1)[0] if "." in value else value
    _validate_slug(base, label)
    return value


# Input length caps — prevent disk/memory DoS from untrusted input
_MAX_TEXT = 500
_MAX_NARRATION = 300
_MAX_CHARACTER = 50
_MAX_VIEWER = 25


# ── Commands ─────────────────────────────────────────────────────────────────


def _parse_pregen_characters(adventure_file: str) -> list[dict]:
    """Extract pre-gen characters with full stats from an adventure markdown file.

    Parses the "Pre-Generated Characters" section. Each character block:
        **Name** — Species class
        - Dex 3D+2, Kno 2D, Mec 4D, Per 3D, Str 2D+1, Tec 3D
        - Skills: Blaster 5D, Dodge 4D+2, ...
        - Gear: DL-44 heavy blaster, comlink, 500 credits
        - Background: ...

    Returns list of dicts with name, species_class, attributes, skills, gear, background.
    """
    import re
    characters: list[dict] = []
    in_pregen = False
    current: dict | None = None

    attr_abbrevs = {
        "dex": "Dexterity", "kno": "Knowledge", "mec": "Mechanical",
        "per": "Perception", "str": "Strength", "tec": "Technical",
    }

    def _parse_dice(s: str) -> str:
        """Normalize dice notation like '3D+2', '4D', '5D+1'."""
        m = re.match(r"(\d+)D(?:\+(\d+))?", s.strip(), re.IGNORECASE)
        if not m:
            return s.strip()
        count = m.group(1)
        mod = m.group(2)
        return f"{count}D+{mod}" if mod else f"{count}D"

    with open(adventure_file) as f:
        for line in f:
            if "Pre-Generated Characters" in line:
                in_pregen = True
                continue
            if not in_pregen:
                continue
            if line.startswith("## "):
                break  # next section

            # Character name line: **Name** — description
            m = re.match(r"\*\*(.+?)\*\*\s*[—–-]\s*(.+)", line)
            if m:
                if current:
                    characters.append(current)
                current = {
                    "name": m.group(1).strip(),
                    "species_class": m.group(2).strip(),
                    "attributes": {},
                    "skills": {},
                    "gear": [],
                    "background": "",
                }
                continue

            if not current:
                continue

            stripped = line.strip().lstrip("- ").strip()
            if not stripped:
                continue

            # Attribute line: Dex 3D+2, Kno 2D, ...
            attr_match = re.match(
                r"(Dex|Kno|Mec|Per|Str|Tec)\s+\d+D", stripped, re.IGNORECASE
            )
            if attr_match:
                for part in stripped.split(","):
                    part = part.strip()
                    am = re.match(r"(Dex|Kno|Mec|Per|Str|Tec)\s+(\d+D(?:\+\d+)?)", part, re.IGNORECASE)
                    if am:
                        full_name = attr_abbrevs.get(am.group(1).lower(), am.group(1))
                        current["attributes"][full_name] = _parse_dice(am.group(2))
                continue

            # Skills line
            if stripped.lower().startswith("skills:"):
                skill_text = stripped[7:].strip()
                for part in skill_text.split(","):
                    part = part.strip()
                    sm = re.match(r"(.+?)\s+(\d+D(?:\+\d+)?)\s*$", part)
                    if sm:
                        current["skills"][sm.group(1).strip()] = _parse_dice(sm.group(2))
                continue

            # Gear line
            if stripped.lower().startswith("gear:"):
                gear_text = stripped[5:].strip()
                current["gear"] = [g.strip() for g in gear_text.split(",") if g.strip()]
                continue

            # Background line
            if stripped.lower().startswith("background:"):
                current["background"] = stripped[11:].strip()
                continue

    if current:
        characters.append(current)

    return characters


def cmd_init(args: argparse.Namespace) -> None:
    """Initialize a new game session."""
    _ensure_dirs()

    _validate_slug(args.adventure, "adventure name")
    adventure_file = os.path.join(ADVENTURES_DIR, f"{args.adventure}.md")
    if not os.path.exists(adventure_file):
        print(f"ERROR: Adventure file not found: {adventure_file}", file=sys.stderr)
        sys.exit(1)

    now = datetime.now(timezone.utc).isoformat()
    session_id = f"session-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"

    state = {
        "session": {
            "id": session_id,
            "adventure": args.adventure,
            "act": 1,
            "scene": "Opening",
            "round": 0,
            "mode": "rp",
            "turn_started_at": None,
            "turn_timeout_secs": 120,
            "started_at": now,
            "status": "active",
        },
        "players": {},
        "npcs": {},
        "initiative_order": [],
        "combat_active": False,
        "narration": "",
        "dice_log": [],
        "last_updated": now,
    }

    # Auto-join pre-gen characters as bot-controlled PCs
    if getattr(args, "auto_join_bots", False):
        characters = _parse_pregen_characters(adventure_file)
        for char in characters:
            char_name = char["name"]
            slug = _slugify(char_name)
            player_file = os.path.join(PLAYERS_DIR, f"{slug}.json")
            # Preserve progression if player file already exists
            if os.path.exists(player_file):
                with open(player_file) as f:
                    existing = json.load(f)
                # Update template fields (skills/gear may change per module)
                existing["attributes"] = char.get("attributes", existing.get("attributes", {}))
                existing["skills"] = char.get("skills", existing.get("skills", {}))
                existing["gear"] = char.get("gear", existing.get("gear", []))
                existing["background"] = char.get("background", existing.get("background", ""))
                _atomic_write(player_file, existing)
                char_data = existing
            else:
                char_data = {
                    "name": char_name,
                    "species_class": char.get("species_class", ""),
                    "attributes": char.get("attributes", {}),
                    "skills": char.get("skills", {}),
                    "gear": char.get("gear", []),
                    "background": char.get("background", ""),
                    "created_by": "bot",
                    "created_at": now,
                    "character_points": 5,
                    "force_points": 1,
                    "dark_side_points": 0,
                    "sessions_played": 0,
                    "wound_level": 0,
                }
                _atomic_write(player_file, char_data)
            # Load from file — preserves wounds, CP, FP from last canon session
            state["players"][f"bot:{slug}"] = {
                "character": char_name,
                "wound_level": char_data.get("wound_level", 0),
                "character_points": char_data.get("character_points", 5),
                "force_points": char_data.get("force_points", 1),
                "dark_side_points": char_data.get("dark_side_points", 0),
                "bot_controlled": True,
                "gear": char.get("gear", []),
            }
            print(f"  Bot PC: {char_name} ({char.get('species_class', '?')})")

    _save_state(state)
    print(f"Session {session_id} initialized for adventure: {args.adventure}")
    if state["players"]:
        print(f"  {len(state['players'])} bot-controlled PCs ready for viewer takeover")


def cmd_join(args: argparse.Namespace) -> None:
    """Add a player to the current session.

    If the character is bot-controlled, the bot entry is removed and the
    viewer takes over. If claimed by another real viewer, it's denied.
    """
    state = _load_state()
    if not state.get("session"):
        print("ERROR: No active session. Run 'init' first.", file=sys.stderr)
        sys.exit(1)

    viewer = args.viewer.lower()[:_MAX_VIEWER]
    character = args.character[:_MAX_CHARACTER]
    slug = _slugify(character)

    # If this viewer already has a character, release it back to bot control
    if viewer in state.get("players", {}):
        old_char = state["players"][viewer]["character"]
        old_slug = _slugify(old_char)
        state["players"][f"bot:{old_slug}"] = {
            "character": old_char,
            "wound_level": state["players"][viewer].get("wound_level", 0),
            "character_points": state["players"][viewer].get("character_points", 5),
            "force_points": state["players"][viewer].get("force_points", 1),
            "dark_side_points": state["players"][viewer].get("dark_side_points", 0),
            "bot_controlled": True,
        }
        del state["players"][viewer]
        print(f"  {old_char} released back to bot control")

    # Check if the requested character is already claimed
    for v, p in state.get("players", {}).items():
        if p.get("character") == character and v != viewer:
            if p.get("bot_controlled"):
                # Bot is running this PC — viewer takes over
                del state["players"][v]
                print(f"  Transferring {character} from bot to {viewer}")
                break
            else:
                print(f"ERROR: {character} is already claimed by {v}", file=sys.stderr)
                sys.exit(1)

    # Load or create player character file
    player_file = os.path.join(PLAYERS_DIR, f"{slug}.json")

    if os.path.exists(player_file):
        with open(player_file) as f:
            char_data = json.load(f)
    else:
        # Create minimal character record — agent fills in details later
        char_data = {
            "name": character,
            "created_by": viewer,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "character_points": 5,
            "force_points": 1,
            "dark_side_points": 0,
            "wound_level": 0,
            "sessions_played": 0,
        }
        _atomic_write(player_file, char_data)

    state.setdefault("players", {})[viewer] = {
        "character": character,
        "template": slug,
        "wound_level": char_data.get("wound_level", 0),
        "character_points": char_data.get("character_points", 5),
        "force_points": char_data.get("force_points", 1),
        "dark_side_points": char_data.get("dark_side_points", 0),
        "joined_at": datetime.now(timezone.utc).isoformat(),
        "bot_controlled": False,
        "last_action_at": None,
        "consecutive_skips": 0,
        "status": "active",
    }
    _save_state(state)
    print(f"{viewer} joined as {character}")


def cmd_leave(args: argparse.Namespace) -> None:
    """Release a player's character back to bot control."""
    state = _load_state()
    viewer = args.viewer.lower()

    if viewer in state.get("players", {}):
        pdata = state["players"][viewer]
        char = pdata["character"]
        slug = _slugify(char)

        # Return character to bot control (preserving state)
        state["players"][f"bot:{slug}"] = {
            "character": char,
            "wound_level": pdata.get("wound_level", 0),
            "character_points": pdata.get("character_points", 5),
            "force_points": pdata.get("force_points", 1),
            "dark_side_points": pdata.get("dark_side_points", 0),
            "bot_controlled": True,
        }
        del state["players"][viewer]
        # Keep initiative position — bot plays the character's combat turn
        _save_state(state)
        print(f"{viewer} released {char} back to bot control")
    else:
        print(f"{viewer} is not in the session")


def cmd_wound(args: argparse.Namespace) -> None:
    """Set wound level for a character (player or NPC)."""
    state = _load_state()
    character = args.character
    level = args.level

    if level < 0 or level >= len(WOUND_LEVELS):
        print(f"ERROR: Wound level must be 0-{len(WOUND_LEVELS)-1}", file=sys.stderr)
        sys.exit(1)

    # Check players first
    for viewer, pdata in state.get("players", {}).items():
        if pdata.get("character") == character:
            pdata["wound_level"] = level
            _save_state(state)
            print(f"{character} wound level: {WOUND_LEVELS[level]}")
            return

    # Check NPCs
    slug = _slugify(character)
    if slug in state.get("npcs", {}):
        state["npcs"][slug]["wound_level"] = level
        _save_state(state)
        print(f"NPC {character} wound level: {WOUND_LEVELS[level]}")
        return

    # Add as new NPC
    state.setdefault("npcs", {})[slug] = {
        "name": character,
        "wound_level": level,
        "status": "dead" if level >= 5 else "active",
    }
    _save_state(state)
    print(f"NPC {character} added with wound level: {WOUND_LEVELS[level]}")


def cmd_initiative(args: argparse.Namespace) -> None:
    """Set initiative order for combat."""
    state = _load_state()
    characters = [c.strip() for c in args.characters.split(",") if c.strip()]

    state["initiative_order"] = characters
    state["combat_active"] = True
    state["session"]["round"] = 1
    state["session"]["mode"] = "combat"
    state["session"]["turn_started_at"] = datetime.now(timezone.utc).isoformat()
    if hasattr(args, "timeout") and args.timeout is not None:
        state["session"]["turn_timeout_secs"] = args.timeout
    # Auto-zoom to combat area
    centroid = _compute_party_centroid(state)
    if centroid:
        state["camera"] = {"x": centroid[0], "y": centroid[1], "zoom": 2.5, "target": "combat"}
    _save_state(state)
    timeout = state["session"].get("turn_timeout_secs", 120)
    print(f"Combat started! Initiative: {' > '.join(characters)} ({timeout}s per turn)")


def cmd_next_turn(args: argparse.Namespace) -> None:
    """Advance to next turn in initiative order."""
    state = _load_state()
    order = state.get("initiative_order", [])

    if not order:
        print("No initiative order set. Use 'initiative' first.")
        return

    # Reset skips for the character who just took their turn
    leaving = order[0]
    for _v, p in state.get("players", {}).items():
        if p.get("character") == leaving:
            p["consecutive_skips"] = 0
            break

    # Rotate: move first to last
    state["initiative_order"] = order[1:] + [order[0]]
    # If we rotated back to the start, increment round
    if state["initiative_order"][0] == order[0]:
        state["session"]["round"] = state["session"].get("round", 1) + 1
        print(f"Round {state['session']['round']}!")

    # Reset turn timer
    state["session"]["turn_started_at"] = datetime.now(timezone.utc).isoformat()

    current = state["initiative_order"][0]

    # Auto-switch map if current character is on a different map
    _auto_switch_map_for_character(state, current)

    _save_state(state)
    print(f"Turn: {current}")


def cmd_end_combat(args: argparse.Namespace) -> None:
    """End combat, clear initiative."""
    state = _load_state()
    state["combat_active"] = False
    state["initiative_order"] = []
    state["session"]["round"] = 0
    state["session"]["mode"] = "rp"
    state["session"]["turn_started_at"] = None
    # Zoom back out, follow party
    centroid = _compute_party_centroid(state)
    if centroid:
        state["camera"] = {"x": centroid[0], "y": centroid[1], "zoom": 1.0, "target": "party"}
    else:
        w = (state.get("map") or {}).get("width", 1920)
        h = (state.get("map") or {}).get("height", 1080)
        state["camera"] = {"x": w // 2, "y": h // 2, "zoom": 1.0, "target": "overview"}
    _save_state(state)
    print("Combat ended.")


def cmd_award_cp(args: argparse.Namespace) -> None:
    """Award Character Points to a player character."""
    state = _load_state()
    character = args.character
    points = args.points

    for viewer, pdata in state.get("players", {}).items():
        if pdata.get("character") == character:
            pdata["character_points"] = pdata.get("character_points", 0) + points
            _save_state(state)
            print(f"{character} awarded {points} CP (total: {pdata['character_points']})")
            return

    print(f"ERROR: Character {character} not found in session", file=sys.stderr)
    sys.exit(1)


def cmd_spend_cp(args: argparse.Namespace) -> None:
    """Spend Character Points for a player character."""
    state = _load_state()
    character = args.character
    cost = args.points

    for viewer, pdata in state.get("players", {}).items():
        if pdata.get("character") == character:
            current = pdata.get("character_points", 0)
            if current < cost:
                print(f"ERROR: {character} has {current} CP, needs {cost}", file=sys.stderr)
                sys.exit(1)
            pdata["character_points"] = current - cost
            _save_state(state)
            print(f"{character} spent {cost} CP (remaining: {pdata['character_points']})")
            return

    print(f"ERROR: Character {character} not found in session", file=sys.stderr)
    sys.exit(1)


def cmd_spend_fp(args: argparse.Namespace) -> None:
    """Spend Force Points for a player character."""
    state = _load_state()
    character = args.character
    cost = args.points

    for viewer, pdata in state.get("players", {}).items():
        if pdata.get("character") == character:
            current = pdata.get("force_points", 0)
            if current < cost:
                print(f"ERROR: {character} has {current} FP, needs {cost}", file=sys.stderr)
                sys.exit(1)
            pdata["force_points"] = current - cost
            _save_state(state)
            print(f"{character} spent {cost} FP (remaining: {pdata['force_points']})")
            return

    print(f"ERROR: Character {character} not found in session", file=sys.stderr)
    sys.exit(1)


def cmd_update_scene(args: argparse.Namespace) -> None:
    """Update the current scene description."""
    state = _load_state()
    if not state.get("session"):
        print("ERROR: No active session.", file=sys.stderr)
        sys.exit(1)

    if args.act is not None:
        state["session"]["act"] = args.act
    if args.scene is not None:
        state["session"]["scene"] = args.scene[:_MAX_NARRATION]
    if args.narration is not None:
        state["narration"] = args.narration[:_MAX_NARRATION]
    if args.map is not None:
        _validate_map_filename(args.map, "map filename")
        existing = state.get("map") or {}
        if isinstance(existing, str):
            existing = {"image": existing}
        existing["image"] = args.map
        existing.setdefault("name", args.map)
        existing.setdefault("width", 1200)
        existing.setdefault("height", 900)
        state["map"] = existing

    if getattr(args, "closing_crawl", None) is not None:
        try:
            state["closing_crawl"] = json.loads(args.closing_crawl)
        except json.JSONDecodeError as e:
            print(f"ERROR: Invalid closing crawl JSON: {e}", file=sys.stderr)
            sys.exit(1)

    _save_state(state)
    print(f"Scene updated: Act {state['session']['act']} - {state['session']['scene']}")


def cmd_set_map(args: argparse.Namespace) -> None:
    """Set the current map image and optionally reset token positions."""
    state = _load_state()
    if not state.get("session"):
        print("ERROR: No active session.", file=sys.stderr)
        sys.exit(1)

    _validate_map_filename(args.image, "map image")
    terrain = _load_terrain(args.terrain) if getattr(args, "terrain", None) else None
    state["map"] = {
        "image": args.image,
        "name": args.name or args.image,
        "width": args.width or (terrain or {}).get("width", 1200),
        "height": args.height or (terrain or {}).get("height", 900),
    }
    if args.clear_tokens:
        state["tokens"] = {}
    # Reset camera to overview on map change
    w = state["map"]["width"]
    h = state["map"]["height"]
    state["camera"] = {"x": w // 2, "y": h // 2, "zoom": 1.0, "target": "overview"}
    _save_state(state)
    print(f"Map set: {args.name or args.image} ({state['map']['width']}x{state['map']['height']})")


def cmd_move_token(args: argparse.Namespace) -> None:
    """Place or move a character token on the map."""
    state = _load_state()
    if not state.get("session"):
        print("ERROR: No active session.", file=sys.stderr)
        sys.exit(1)

    name = args.character
    slug = _slugify(name)

    # Load terrain for the current map
    map_image = (state.get("map") or {}).get("image", "")
    terrain = _load_terrain(map_image) if map_image else None

    # Resolve position: --position (named) or --x/--y (raw pixels)
    x, y = args.x, args.y
    if args.position:
        if not terrain:
            print(f"WARNING: No terrain data for '{map_image}', cannot resolve position '{args.position}'", file=sys.stderr)
            sys.exit(1)
        resolved = _resolve_position(terrain, args.position)
        if not resolved:
            available = sorted(terrain.get("positions", {}).keys())
            print(f"ERROR: Unknown position '{args.position}'. Available: {', '.join(available)}", file=sys.stderr)
            sys.exit(1)
        x, y = resolved
        print(f"Position '{args.position}' -> ({x}, {y})")
    elif x is not None and y is not None:
        # Validate raw coordinates against obstacles
        if terrain:
            valid, sx, sy, obs_id = _validate_position(terrain, x, y)
            if not valid:
                print(f"WARNING: ({x},{y}) inside obstacle '{obs_id}', snapping to ({sx},{sy})")
                x, y = sx, sy
    else:
        print("ERROR: Provide --position or --x and --y", file=sys.stderr)
        sys.exit(1)

    # Validate movement distance if --max-distance is set
    if args.max_distance is not None:
        tokens = state.get("tokens", {})
        if slug in tokens:
            old = tokens[slug]
            dx = x - old["x"]
            dy = y - old["y"]
            dist = int((dx * dx + dy * dy) ** 0.5)
            if dist > args.max_distance:
                print(f"BLOCKED: {name} can't move {dist}px (max {args.max_distance}px)")
                sys.exit(1)

    # Determine token type and color
    if args.type:
        token_type = args.type
    else:
        is_player = False
        for _v, p in state.get("players", {}).items():
            if p.get("character") == name:
                is_player = True
                break
        token_type = "pc" if is_player else "npc"

    default_colors = {"pc": "#4e9af5", "npc": "#f54e4e", "vehicle": "#8899aa"}
    tokens = state.setdefault("tokens", {})
    tokens[slug] = {
        "name": name,
        "x": x,
        "y": y,
        "map_id": (state.get("map") or {}).get("image", ""),
        "type": token_type,
        "color": args.color or default_colors.get(token_type, "#f54e4e"),
        "visible": not args.hidden,
    }
    _update_camera_for_party(state)
    _save_state(state)
    vis = "hidden" if args.hidden else "visible"
    print(f"Token {name} -> ({x}, {y}) [{vis}]")


def cmd_remove_token(args: argparse.Namespace) -> None:
    """Remove a token from the map."""
    state = _load_state()
    slug = _slugify(args.character)
    tokens = state.get("tokens", {})
    if slug in tokens:
        del tokens[slug]
        _save_state(state)
        print(f"Token removed: {args.character}")
    else:
        print(f"Token not found: {args.character}")


def cmd_switch_scene(args: argparse.Namespace) -> None:
    """Switch the active map without destroying tokens.

    Tokens on the old map stay in state but won't render on the overlay
    (overlay filters by map_id). Tokens on the new map become visible.
    """
    state = _load_state()
    if not state.get("session"):
        print("ERROR: No active session.", file=sys.stderr)
        sys.exit(1)

    old_map = (state.get("map") or {}).get("image", "(none)")
    _validate_map_filename(args.map, "map filename")
    terrain = _load_terrain(args.map)

    state["map"] = {
        "image": args.map,
        "name": args.name or args.map.rsplit(".", 1)[0].replace("-", " ").title(),
        "width": args.width or (terrain or {}).get("width", 1200),
        "height": args.height or (terrain or {}).get("height", 900),
    }
    _save_state(state)
    print(f"Scene switch: {old_map} → {args.map} ({state['map']['name']})")


def cmd_transfer_token(args: argparse.Namespace) -> None:
    """Move a token from its current map to another map.

    Resolves the landing position from --position, or falls back to
    the terrain connection lookup (exit position on source map →
    entry position on target map).
    """
    state = _load_state()
    if not state.get("session"):
        print("ERROR: No active session.", file=sys.stderr)
        sys.exit(1)

    slug = _slugify(args.character)
    tokens = state.get("tokens", {})
    token = tokens.get(slug)
    if not token:
        print(f"ERROR: No token for '{args.character}'", file=sys.stderr)
        sys.exit(1)

    source_map = token.get("map_id", "")
    _validate_map_filename(args.to_map, "target map")
    target_map = args.to_map

    # Resolve landing position
    x, y = None, None
    landing_pos = args.position

    if not landing_pos:
        # Look up connection from source terrain
        source_terrain = _load_terrain(source_map) if source_map else None
        if source_terrain:
            connections = source_terrain.get("connections", {})
            # Find a connection that leads to target_map from a position near the token
            best_conn = None
            best_dist = float("inf")
            for pos_name, conn in connections.items():
                if conn["map"] == target_map:
                    pos = source_terrain.get("positions", {}).get(pos_name)
                    if pos:
                        dx = token["x"] - pos["x"]
                        dy = token["y"] - pos["y"]
                        dist = (dx * dx + dy * dy) ** 0.5
                        if dist < best_dist:
                            best_dist = dist
                            best_conn = conn
            if best_conn:
                landing_pos = best_conn["position"]

    if not landing_pos:
        print(f"ERROR: No --position given and no connection from '{source_map}' to '{target_map}'", file=sys.stderr)
        sys.exit(1)

    # Resolve the landing position on the target map's terrain
    target_terrain = _load_terrain(target_map)
    if target_terrain:
        resolved = _resolve_position(target_terrain, landing_pos)
        if resolved:
            x, y = resolved
        else:
            available = sorted(target_terrain.get("positions", {}).keys())
            print(f"ERROR: Unknown position '{landing_pos}' on {target_map}. Available: {', '.join(available)}", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"ERROR: No terrain data for '{target_map}'", file=sys.stderr)
        sys.exit(1)

    # Update the token
    old_pos = f"({token['x']},{token['y']})"
    token["x"] = x
    token["y"] = y
    token["map_id"] = target_map
    _save_state(state)
    print(f"{args.character}: {source_map} {old_pos} → {target_map} ({landing_pos}: {x},{y})")


def _auto_switch_map_for_character(state: dict, character: str) -> None:
    """If the character's token is on a different map, switch the active map."""
    slug = _slugify(character)
    token = state.get("tokens", {}).get(slug)
    if not token:
        return
    current_map = (state.get("map") or {}).get("image", "")
    token_map = token.get("map_id", "")
    if token_map and token_map != current_map:
        terrain = _load_terrain(token_map)
        state["map"] = {
            "image": token_map,
            "name": (terrain or {}).get("map", token_map).rsplit(".", 1)[0].replace("-", " ").title(),
            "width": (terrain or {}).get("width", 1200),
            "height": (terrain or {}).get("height", 900),
        }
        print(f"  MAP SWITCH: {current_map} → {token_map} (following {character})")


def cmd_list_positions(args: argparse.Namespace) -> None:
    """List available named positions for the current map."""
    state = _load_state()
    map_image = (state.get("map") or {}).get("image", "")
    if not map_image:
        print("ERROR: No map set. Use set-map first.", file=sys.stderr)
        sys.exit(1)
    terrain = _load_terrain(map_image)
    if not terrain:
        print(f"No terrain data for '{map_image}'")
        return
    positions = terrain.get("positions", {})
    zones = terrain.get("zones", {})
    # Show positions grouped by zone
    shown = set()
    for zone_name, zone in sorted(zones.items()):
        print(f"\n{zone_name}: {zone.get('desc', '')}")
        for pname in zone.get("positions", []):
            pos = positions.get(pname)
            if pos:
                print(f"  {pname:25s} ({pos['x']:4d},{pos['y']:4d})  {pos.get('desc', '')}")
                shown.add(pname)
    # Show any positions not in a zone
    ungrouped = sorted(set(positions.keys()) - shown)
    if ungrouped:
        print("\nother:")
        for pname in ungrouped:
            pos = positions[pname]
            print(f"  {pname:25s} ({pos['x']:4d},{pos['y']:4d})  {pos.get('desc', '')}")


def cmd_set_camera(args: argparse.Namespace) -> None:
    """Set camera position and zoom for the overlay pan/zoom engine."""
    state = _load_state()
    if not state.get("session"):
        print("ERROR: No active session.", file=sys.stderr)
        sys.exit(1)

    camera = state.get("camera", {"x": 960, "y": 540, "zoom": 1.0, "target": "overview"})

    if args.follow_party:
        camera["target"] = "party"
        centroid = _compute_party_centroid(state)
        if centroid:
            camera["x"], camera["y"] = centroid
            print(f"Camera following party at ({camera['x']}, {camera['y']})")
        else:
            print("WARNING: No PC tokens visible, camera centered on map")
    elif args.position:
        map_image = (state.get("map") or {}).get("image", "")
        terrain = _load_terrain(map_image) if map_image else None
        if not terrain:
            print(f"ERROR: No terrain for '{map_image}'", file=sys.stderr)
            sys.exit(1)
        resolved = _resolve_position(terrain, args.position)
        if not resolved:
            available = sorted(terrain.get("positions", {}).keys())
            print(f"ERROR: Unknown position '{args.position}'. Available: {', '.join(available[:20])}", file=sys.stderr)
            sys.exit(1)
        camera["x"], camera["y"] = resolved
        camera["target"] = args.position
        print(f"Camera -> {args.position} ({camera['x']}, {camera['y']})")
    elif args.preset:
        map_image = (state.get("map") or {}).get("image", "")
        terrain = _load_terrain(map_image) if map_image else None
        presets = (terrain or {}).get("camera_presets", {})
        preset = presets.get(args.preset)
        if not preset:
            available = sorted(presets.keys()) if presets else ["(none)"]
            print(f"ERROR: Unknown preset '{args.preset}'. Available: {', '.join(available)}", file=sys.stderr)
            sys.exit(1)
        camera["x"] = preset["x"]
        camera["y"] = preset["y"]
        camera["zoom"] = preset.get("zoom", camera.get("zoom", 1.0))
        camera["target"] = args.preset
        print(f"Camera preset '{args.preset}' -> ({camera['x']},{camera['y']}) zoom {camera['zoom']}")
    elif args.x is not None and args.y is not None:
        camera["x"] = args.x
        camera["y"] = args.y
        camera["target"] = "manual"
        print(f"Camera -> ({camera['x']}, {camera['y']})")

    if args.zoom is not None:
        camera["zoom"] = max(0.5, min(5.0, args.zoom))
        if not args.follow_party and not args.position and not args.preset and args.x is None:
            # Zoom-only change
            print(f"Camera zoom -> {camera['zoom']}")

    state["camera"] = camera
    _save_state(state)


# Map legend data — WEG numbered locations for each map
_MAP_LEGENDS: dict[str, list[tuple[str, str]]] = {
    "mos-eisley-streets-1.png": [
        ("1", "Docking Bay 94"),
        ("6", "Docking Bay 86"),
        ("7", "Docking Bay 87 ★"),
        ("8", "Mos Eisley Inn"),
        ("9", "Tatooine Militia"),
        ("10", "Dewback Stables"),
        ("11", "Regional Gov. Offices"),
        ("12", "Power Station"),
        ("13", "Jabba's Townhouse"),
        ("14", "Street Corner Preacher"),
        ("16", "Mos Eisley Cantina"),
        ("17", "Jawa Traders"),
        ("19", "Kayson's Weapon Shop"),
        ("21", "Docking Bay 92"),
    ],
    "cantina.png": [
        ("", "Main bar — Wuher the bartender"),
        ("", "Booths — shady deals and quiet conversations"),
        ("", "Band stage — Figrin D'an's usual spot"),
        ("", "Back exit — leads to alley behind cantina"),
    ],
    "docking-bay-87.svg": [
        ("", "Blast door — entrance from the street"),
        ("", "The Rusty Mynock (YT-1300) — needs Repair 15"),
        ("", "Fuel lines — cover, but explosive hazard"),
        ("", "Cargo area — crates for cover"),
    ],
}


def cmd_map_legend(args: argparse.Namespace) -> None:
    """Print the location legend for the current map."""
    state = _load_state()
    map_image = (state.get("map") or {}).get("image", "")
    map_name = (state.get("map") or {}).get("name", map_image)

    legend = _MAP_LEGENDS.get(map_image)
    if not legend:
        print(f"[{map_name}] No legend available for this map.")
        return

    lines = [f"[{map_name}]"]
    for num, desc in legend:
        if num:
            lines.append(f"  {num:>2}. {desc}")
        else:
            lines.append(f"  • {desc}")
    lines.append("★ = Your destination")
    print("\n".join(lines))


def cmd_set_crawl(args: argparse.Namespace) -> None:
    """Set the opening crawl text for the Star Wars D6 (West End Games) intro."""
    state = _load_state()
    if not state.get("session"):
        print("ERROR: No active session.", file=sys.stderr)
        sys.exit(1)

    crawl = state.get("crawl", {})
    if args.title is not None:
        crawl["title"] = args.title
    if args.subtitle is not None:
        crawl["subtitle"] = args.subtitle
    if args.episode is not None:
        crawl["episode"] = args.episode
    if args.episode_title is not None:
        crawl["episodeTitle"] = args.episode_title
    if args.text is not None:
        # Split on pipe character for multiple paragraphs
        crawl["paragraphs"] = [p.strip() for p in args.text.split("|") if p.strip()]

    state["crawl"] = crawl
    _save_state(state)
    print(f"Crawl set: {crawl.get('episodeTitle', crawl.get('title', 'Star Wars D6'))}")


def _find_character_file(character: str) -> dict | None:
    """Load a character's full data from their player file."""
    slug = _slugify(character)
    pf = os.path.join(PLAYERS_DIR, f"{slug}.json")
    if os.path.exists(pf):
        with open(pf) as f:
            return json.load(f)
    return None


def _find_viewer_character(state: dict, viewer: str) -> str | None:
    """Get the character name for a viewer from the session state."""
    viewer = viewer.lower()
    pdata = state.get("players", {}).get(viewer)
    if pdata:
        return pdata.get("character")
    return None


def cmd_sheet(args: argparse.Namespace) -> None:
    """Display a character sheet. Use --viewer OR --character."""
    state = _load_state()
    character = args.character

    # If viewer specified, look up their character
    if not character and args.viewer:
        character = _find_viewer_character(state, args.viewer)
        if not character:
            print(f"ERROR: Viewer '{args.viewer}' has no character in this session.", file=sys.stderr)
            sys.exit(1)

    if not character:
        print("ERROR: Provide --character or --viewer", file=sys.stderr)
        sys.exit(1)

    char_data = _find_character_file(character)
    if not char_data:
        print(f"ERROR: No character file for '{character}'", file=sys.stderr)
        sys.exit(1)

    # Get live session data (wound level, CP, etc.)
    session_info = {}
    for v, p in state.get("players", {}).items():
        if p.get("character") == character:
            session_info = p
            break

    wl = session_info.get("wound_level", char_data.get("wound_level", 0))
    cp = session_info.get("character_points", char_data.get("character_points", 5))
    fp = session_info.get("force_points", char_data.get("force_points", 1))

    print(f"=== {char_data['name']} ===")
    if char_data.get("species_class"):
        print(f"  {char_data['species_class']}")
    print(f"  Health: {WOUND_LEVELS[wl]} | CP: {cp} | FP: {fp}")

    attrs = char_data.get("attributes", {})
    if attrs:
        print("\nAttributes:")
        for attr, dice in attrs.items():
            print(f"  {attr}: {dice}")

    skills = char_data.get("skills", {})
    if skills:
        print("\nSkills:")
        for skill, dice in skills.items():
            print(f"  {skill}: {dice}")

    gear = char_data.get("gear", [])
    if gear:
        print(f"\nGear: {', '.join(gear)}")

    if char_data.get("background"):
        print(f"\nBackground: {char_data['background']}")


def cmd_skill_check(args: argparse.Namespace) -> None:
    """Look up a character's dice for a skill or attribute.

    Outputs the dice notation and character name for use with rpg_dice_roll.
    Viewers use: !roll blaster  (agent calls skill-check, then rpg_dice_roll)
    """
    state = _load_state()
    character = args.character

    # If viewer specified, look up their character
    if not character and args.viewer:
        character = _find_viewer_character(state, args.viewer)
        if not character:
            print(f"ERROR: Viewer '{args.viewer}' has no character.", file=sys.stderr)
            sys.exit(1)

    if not character:
        print("ERROR: Provide --character or --viewer", file=sys.stderr)
        sys.exit(1)

    char_data = _find_character_file(character)
    if not char_data:
        print(f"ERROR: No character file for '{character}'", file=sys.stderr)
        sys.exit(1)

    skill_name = args.skill.strip()
    skill_lower = skill_name.lower()

    # Search skills first (case-insensitive)
    skills = char_data.get("skills", {})
    for sk, dice in skills.items():
        if sk.lower() == skill_lower:
            print(json.dumps({
                "character": character,
                "skill": sk,
                "dice": dice,
                "type": "skill",
            }))
            return

    # Fall back to attributes
    attrs = char_data.get("attributes", {})
    for attr, dice in attrs.items():
        if attr.lower() == skill_lower:
            print(json.dumps({
                "character": character,
                "skill": attr,
                "dice": dice,
                "type": "attribute",
            }))
            return

    # Fuzzy match: check if skill_lower is a substring
    for sk, dice in {**skills, **attrs}.items():
        if skill_lower in sk.lower() or sk.lower() in skill_lower:
            print(json.dumps({
                "character": character,
                "skill": sk,
                "dice": dice,
                "type": "skill" if sk in skills else "attribute",
                "fuzzy": True,
            }))
            return

    # Not found — list available skills
    available = list(skills.keys()) + list(attrs.keys())
    print(f"ERROR: '{skill_name}' not found for {character}.", file=sys.stderr)
    print(f"Available: {', '.join(available)}", file=sys.stderr)
    sys.exit(1)


def cmd_log_action(args: argparse.Namespace) -> None:
    """Log a player action (!say or !do) to the game state.

    Keeps a rolling buffer of the last 20 actions so the overlay
    can display them without unbounded growth.

    In combat mode, validates that it's the viewer's character's turn.
    In cutscene mode, rejects all player actions.
    """
    state = _load_state()
    if not state.get("session"):
        print("ERROR: No active session.", file=sys.stderr)
        sys.exit(1)

    viewer = args.viewer.lower()
    character = _find_viewer_character(state, viewer)
    if not character:
        print(f"ERROR: Viewer '{viewer}' has no character.", file=sys.stderr)
        sys.exit(1)

    mode = state.get("session", {}).get("mode", "rp")

    # Cutscene mode: no player actions allowed
    if mode == "cutscene":
        print(f"BLOCKED: The GM is narrating — please wait.")
        sys.exit(1)

    # Combat mode: validate it's this character's turn
    if mode == "combat" and state.get("combat_active"):
        order = state.get("initiative_order", [])
        if order and order[0] != character:
            print(f"BLOCKED: Not your turn — it's {order[0]}'s turn.")
            sys.exit(1)

    now = datetime.now(timezone.utc).isoformat()

    # Update player activity tracking
    for _v, p in state.get("players", {}).items():
        if p.get("character") == character:
            p["last_action_at"] = now
            p["consecutive_skips"] = 0
            if p.get("status") in ("idle", "afk"):
                p["status"] = "active"
                p["bot_controlled"] = False
            break

    action = {
        "viewer": viewer[:_MAX_VIEWER],
        "character": character,
        "type": args.type,  # "say" or "do"
        "text": args.text[:_MAX_TEXT],
        "timestamp": now,
    }

    log = state.setdefault("action_log", [])
    log.append(action)

    _save_state(state)
    print(json.dumps(action))


def cmd_log_dice(args: argparse.Namespace) -> None:
    """Log a dice roll result to game state for overlay SFX + popup."""
    state = _load_state()
    if not state.get("session"):
        print("ERROR: No active session.", file=sys.stderr)
        sys.exit(1)

    success_val = None
    if args.success is not None:
        success_val = args.success == "true"

    entry = {
        "character": args.character[:_MAX_CHARACTER],
        "skill": args.skill[:_MAX_CHARACTER],
        "total": args.total,
        "detail": args.detail[:_MAX_TEXT],
        "difficulty": args.difficulty,
        "success": success_val,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    log = state.setdefault("dice_log", [])
    log.append(entry)
    # Keep last 20 — overlay only needs the latest entry
    if len(log) > 20:
        state["dice_log"] = log[-20:]
    _save_state(state)
    print(json.dumps(entry))


def cmd_set_mode(args: argparse.Namespace) -> None:
    """Set the game mode: rp (free-form), combat (strict turns), cutscene (GM only)."""
    state = _load_state()
    if not state.get("session"):
        print("ERROR: No active session.", file=sys.stderr)
        sys.exit(1)
    state["session"]["mode"] = args.mode
    if args.mode == "combat" and not state.get("combat_active"):
        print("WARNING: Combat mode set but no initiative order. Use 'initiative' to start combat.")
    _save_state(state)
    print(f"Mode: {args.mode}")


def cmd_check_timer(args: argparse.Namespace) -> None:
    """Check the turn timer status. Returns JSON."""
    state = _load_state()
    session = state.get("session", {})
    order = state.get("initiative_order", [])

    if not state.get("combat_active") or not order:
        print(json.dumps({"combat_active": False, "expired": False}))
        return

    turn_started = session.get("turn_started_at")
    timeout = session.get("turn_timeout_secs", 120)
    current = order[0]

    if not turn_started:
        print(json.dumps({
            "combat_active": True, "current_character": current,
            "expired": False, "remaining_secs": timeout,
        }))
        return

    started = datetime.fromisoformat(turn_started)
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    remaining = max(0, timeout - elapsed)

    print(json.dumps({
        "combat_active": True,
        "current_character": current,
        "turn_started_at": turn_started,
        "timeout_secs": timeout,
        "elapsed_secs": round(elapsed),
        "remaining_secs": round(remaining),
        "expired": elapsed >= timeout,
    }))


def cmd_auto_advance(args: argparse.Namespace) -> None:
    """Auto-advance if the turn timer has expired.

    Increments consecutive_skips for the timed-out character.
    2 skips = idle, 3+ = afk (bot takes over).
    """
    state = _load_state()
    session = state.get("session", {})
    order = state.get("initiative_order", [])

    if not state.get("combat_active") or not order:
        print(json.dumps({"action": "none", "reason": "not in combat"}))
        return

    turn_started = session.get("turn_started_at")
    timeout = session.get("turn_timeout_secs", 120)

    if not turn_started:
        print(json.dumps({"action": "none", "reason": "no timer set"}))
        return

    started = datetime.fromisoformat(turn_started)
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()

    if elapsed < timeout:
        print(json.dumps({
            "action": "none", "reason": "timer not expired",
            "remaining_secs": round(timeout - elapsed),
        }))
        return

    # Timer expired — advance turn
    timed_out = order[0]
    skips = 0
    became_afk = False

    for viewer, p in state.get("players", {}).items():
        if p.get("character") == timed_out:
            p["consecutive_skips"] = p.get("consecutive_skips", 0) + 1
            skips = p["consecutive_skips"]
            if skips >= 3:
                p["status"] = "afk"
                p["bot_controlled"] = True
                became_afk = True
            elif skips >= 2:
                p["status"] = "idle"
            break

    # Rotate initiative
    state["initiative_order"] = order[1:] + [order[0]]
    if state["initiative_order"][0] == order[0]:
        state["session"]["round"] = session.get("round", 1) + 1

    state["session"]["turn_started_at"] = datetime.now(timezone.utc).isoformat()
    state["narration"] = f"{timed_out} hesitates, losing their moment..."

    next_up = state["initiative_order"][0]

    # Auto-switch map if next character is on a different map
    _auto_switch_map_for_character(state, next_up)

    _save_state(state)
    result = {
        "action": "advanced",
        "timed_out": timed_out,
        "skips": skips,
        "became_afk": became_afk,
        "next_character": next_up,
    }
    print(json.dumps(result))


def cmd_check_idle(args: argparse.Namespace) -> None:
    """Check for idle or AFK players. Returns JSON array."""
    state = _load_state()
    issues = []
    for viewer, p in state.get("players", {}).items():
        skips = p.get("consecutive_skips", 0)
        status = p.get("status", "active")
        if status in ("idle", "afk") or skips >= 2:
            issues.append({
                "viewer": viewer,
                "character": p.get("character", "?"),
                "consecutive_skips": skips,
                "status": status,
                "bot_controlled": p.get("bot_controlled", False),
                "last_action_at": p.get("last_action_at"),
            })
    print(json.dumps(issues))


def cmd_activity_summary(args: argparse.Namespace) -> None:
    """Summarize player activity from the action log.

    Returns action counts per character for the GM to assess
    spotlight balance in RP mode.
    """
    state = _load_state()
    log = state.get("action_log", [])

    # Count actions per character
    counts: dict[str, dict] = {}
    for viewer, p in state.get("players", {}).items():
        char = p.get("character", "?")
        counts[char] = {"actions": 0, "last_action": p.get("last_action_at")}

    for entry in log:
        char = entry.get("character", "?")
        if char in counts:
            counts[char]["actions"] += 1
            counts[char]["last_action"] = entry.get("timestamp")

    print(json.dumps(counts, indent=2))


def cmd_end_session(args: argparse.Namespace) -> None:
    """End the current session. Only persist to player files if --canon."""
    state = _load_state()
    if not state.get("session"):
        print("No active session to end.")
        return

    is_canon = getattr(args, "canon", False)
    state["session"]["status"] = "ended"
    state["session"]["ended_at"] = datetime.now(timezone.utc).isoformat()
    state["session"]["canon"] = is_canon

    # Only persist progression to player files for canon sessions
    if is_canon:
        for viewer, pdata in state.get("players", {}).items():
            slug = _slugify(pdata.get("character", ""))
            pf = os.path.join(PLAYERS_DIR, f"{slug}.json")
            if os.path.exists(pf):
                with open(pf) as f:
                    cd = json.load(f)
                cd["sessions_played"] = cd.get("sessions_played", 0) + 1
                cd["wound_level"] = pdata.get("wound_level", 0)
                cd["character_points"] = pdata.get("character_points", 0)
                cd["force_points"] = pdata.get("force_points", 0)
                cd["dark_side_points"] = pdata.get("dark_side_points", 0)
                _atomic_write(pf, cd)

    _save_state(state)

    # Write session recap stub
    session_id = state["session"]["id"]
    recap_file = os.path.join(SESSIONS_DIR, f"{session_id}.md")
    canon_label = "CANON" if is_canon else "non-canon"
    if not os.path.exists(recap_file):
        adventure = state["session"].get("adventure", "unknown")
        players = ", ".join(
            f"{p.get('character', '?')} ({v})"
            for v, p in state.get("players", {}).items()
        )
        with open(recap_file, "w") as f:
            f.write(f"# {session_id}\n\n")
            f.write(f"**Adventure:** {adventure}\n")
            f.write(f"**Canon:** {canon_label}\n")
            f.write(f"**Players:** {players}\n")
            f.write(f"**Acts completed:** {state['session'].get('act', '?')}\n\n")
            f.write("## Recap\n\n_TODO: Write session recap_\n")

    if is_canon:
        print(f"Session ended (CANON). Player files updated. Recap: {recap_file}")
    else:
        print(f"Session ended ({canon_label}). Player files unchanged. Recap: {recap_file}")


def cmd_status(args: argparse.Namespace) -> None:
    """Print current game state summary."""
    state = _load_state()
    if not state.get("session"):
        print("No active session.")
        return

    s = state["session"]
    print(f"Session: {s['id']} ({s['status']})")
    print(f"Adventure: {s['adventure']}")
    print(f"Scene: Act {s['act']} - {s['scene']}")

    if state.get("narration"):
        narr = state["narration"][:100]
        print(f"Narration: {narr}{'...' if len(state['narration']) > 100 else ''}")

    players = state.get("players", {})
    if players:
        print(f"\nPlayers ({len(players)}):")
        for viewer, p in players.items():
            wl = WOUND_LEVELS[p.get("wound_level", 0)]
            cp = p.get("character_points", 0)
            print(f"  {p['character']} ({viewer}) - {wl}, {cp} CP")

    npcs = state.get("npcs", {})
    active_npcs = {k: v for k, v in npcs.items() if v.get("status") != "dead"}
    if active_npcs:
        print(f"\nActive NPCs ({len(active_npcs)}):")
        for slug, npc in active_npcs.items():
            wl = WOUND_LEVELS[npc.get("wound_level", 0)]
            print(f"  {npc['name']} - {wl}")

    mode = s.get("mode", "rp")
    print(f"Mode: {mode}")

    if state.get("combat_active"):
        order = state.get("initiative_order", [])
        rnd = s.get("round", 0)
        print(f"\nCombat Round {rnd}: {' > '.join(order)}")
        if order:
            turn_started = s.get("turn_started_at")
            timeout = s.get("turn_timeout_secs", 120)
            timer_info = ""
            if turn_started:
                started = datetime.fromisoformat(turn_started)
                elapsed = (datetime.now(timezone.utc) - started).total_seconds()
                remaining = max(0, timeout - elapsed)
                timer_info = f" ({round(remaining)}s remaining)"
            print(f"Current turn: {order[0]}{timer_info}")

    # Show idle/afk players
    for viewer, p in state.get("players", {}).items():
        if p.get("status") in ("idle", "afk"):
            print(f"  WARNING: {p.get('character', '?')} is {p['status']} "
                  f"({p.get('consecutive_skips', 0)} skips)")


# ── CLI ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Star Wars D6 (West End Games) RPG game state manager")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Initialize a new game session")
    p_init.add_argument("--adventure", required=True, help="Adventure slug (e.g. escape-from-mos-eisley)")
    p_init.add_argument("--auto-join-bots", action="store_true",
                         help="Auto-join pre-gen characters as bot-controlled PCs")

    p_join = sub.add_parser("join", help="Add a player to the session")
    p_join.add_argument("--viewer", required=True, help="Twitch viewer username")
    p_join.add_argument("--character", required=True, help="Character name")

    p_leave = sub.add_parser("leave", help="Remove a player from the session")
    p_leave.add_argument("--viewer", required=True, help="Twitch viewer username")

    p_wound = sub.add_parser("wound", help="Set wound level for a character")
    p_wound.add_argument("--character", required=True, help="Character name")
    p_wound.add_argument("--level", required=True, type=int, help="Wound level (0=healthy, 5=dead)")

    p_init_order = sub.add_parser("initiative", help="Set initiative order")
    p_init_order.add_argument("--characters", required=True, help="Comma-separated character names in order")
    p_init_order.add_argument("--timeout", type=int, help="Turn timeout in seconds (default 90)")

    sub.add_parser("next-turn", help="Advance to next turn")
    sub.add_parser("end-combat", help="End combat and clear initiative")

    p_award = sub.add_parser("award-cp", help="Award Character Points")
    p_award.add_argument("--character", required=True, help="Character name")
    p_award.add_argument("--points", required=True, type=int, help="Points to award")

    p_spend_cp = sub.add_parser("spend-cp", help="Spend Character Points")
    p_spend_cp.add_argument("--character", required=True, help="Character name")
    p_spend_cp.add_argument("--points", type=int, default=1, help="Points to spend (default 1)")

    p_spend_fp = sub.add_parser("spend-fp", help="Spend Force Points")
    p_spend_fp.add_argument("--character", required=True, help="Character name")
    p_spend_fp.add_argument("--points", type=int, default=1, help="Points to spend (default 1)")

    p_scene = sub.add_parser("update-scene", help="Update current scene")
    p_scene.add_argument("--act", type=int, help="Act number")
    p_scene.add_argument("--scene", help="Scene name")
    p_scene.add_argument("--narration", help="Scene narration text")
    p_scene.add_argument("--map", help="Map filename")
    p_scene.add_argument("--closing-crawl", help="Closing crawl data (JSON string)")

    p_map = sub.add_parser("set-map", help="Set the current map image")
    p_map.add_argument("--image", required=True, help="Map image filename (in rpg/maps/)")
    p_map.add_argument("--name", help="Display name for the map")
    p_map.add_argument("--terrain", help="Map image name for terrain lookup (reads width/height)")
    p_map.add_argument("--width", type=int, help="Map width in pixels (default 1200)")
    p_map.add_argument("--height", type=int, help="Map height in pixels (default 900)")
    p_map.add_argument("--clear-tokens", action="store_true", help="Remove all tokens")

    p_token = sub.add_parser("move-token", help="Place or move a token on the map")
    p_token.add_argument("--character", required=True, help="Character name")
    p_token.add_argument("--position", help="Named position (e.g. 'entrance', 'bar-stool-l3')")
    p_token.add_argument("--x", type=int, help="X position in pixels (use --position instead)")
    p_token.add_argument("--y", type=int, help="Y position in pixels (use --position instead)")
    p_token.add_argument("--color", help="Token color (hex, e.g. #4e9af5)")
    p_token.add_argument("--type", choices=["pc", "npc", "vehicle"], help="Token type (default: auto-detect pc/npc)")
    p_token.add_argument("--hidden", action="store_true", help="Token not visible to players")
    p_token.add_argument("--max-distance", type=int, default=None,
                          help="Max pixel distance allowed (rejects if exceeded)")

    p_rmtoken = sub.add_parser("remove-token", help="Remove a token from the map")
    p_rmtoken.add_argument("--character", required=True, help="Character name")

    p_switch = sub.add_parser("switch-scene", help="Switch active map (keeps all tokens)")
    p_switch.add_argument("--map", required=True, help="Target map image filename")
    p_switch.add_argument("--name", help="Display name for the map")
    p_switch.add_argument("--width", type=int, help="Map width in pixels")
    p_switch.add_argument("--height", type=int, help="Map height in pixels")

    p_transfer = sub.add_parser("transfer-token", help="Move a token to another map")
    p_transfer.add_argument("--character", required=True, help="Character name")
    p_transfer.add_argument("--to-map", required=True, help="Target map image filename")
    p_transfer.add_argument("--position", help="Landing position on target map (auto-detected from connections if omitted)")

    sub.add_parser("list-positions", help="List named positions for current map")

    p_cam = sub.add_parser("set-camera", help="Set camera position/zoom for overlay")
    p_cam.add_argument("--position", help="Named position to center on")
    p_cam.add_argument("--preset", help="Camera preset name from terrain data")
    p_cam.add_argument("--x", type=int, help="X center in map pixels")
    p_cam.add_argument("--y", type=int, help="Y center in map pixels")
    p_cam.add_argument("--zoom", type=float, help="Zoom level (1.0=fit, 2.5=combat)")
    p_cam.add_argument("--follow-party", action="store_true",
                        help="Track party centroid (auto-updates on token moves)")

    sub.add_parser("map-legend", help="Print location legend for current map")

    p_crawl = sub.add_parser("set-crawl", help="Set opening crawl text")
    p_crawl.add_argument("--title", help="Main title (default: STAR WARS)")
    p_crawl.add_argument("--subtitle", help="Subtitle under main title")
    p_crawl.add_argument("--episode", help="Episode number/label")
    p_crawl.add_argument("--episode-title", help="Episode title")
    p_crawl.add_argument("--text", help="Crawl paragraphs (pipe-separated)")

    p_sheet = sub.add_parser("sheet", help="Display a character sheet")
    p_sheet.add_argument("--character", help="Character name")
    p_sheet.add_argument("--viewer", help="Viewer username (looks up their character)")

    p_skill = sub.add_parser("skill-check", help="Look up dice for a skill/attribute")
    p_skill.add_argument("--skill", required=True, help="Skill or attribute name")
    p_skill.add_argument("--character", help="Character name")
    p_skill.add_argument("--viewer", help="Viewer username (looks up their character)")

    p_action = sub.add_parser("log-action", help="Log a player !say or !do action")
    p_action.add_argument("--viewer", required=True, help="Viewer username")
    p_action.add_argument("--type", required=True, choices=["say", "do"],
                           help="Action type: say (dialogue) or do (action)")
    p_action.add_argument("--text", required=True, help="What the character says or does")

    p_dice = sub.add_parser("log-dice", help="Log a dice roll for overlay SFX")
    p_dice.add_argument("--character", required=True, help="Character who rolled")
    p_dice.add_argument("--skill", required=True, help="Skill or attribute rolled")
    p_dice.add_argument("--total", required=True, type=int, help="Roll total")
    p_dice.add_argument("--detail", required=True, help="Formatted roll detail string")
    p_dice.add_argument("--difficulty", type=int, default=None, help="Target difficulty")
    p_dice.add_argument("--success", choices=["true", "false"], default=None,
                         help="Whether the roll succeeded")

    p_mode = sub.add_parser("set-mode", help="Set game mode (rp/combat/cutscene)")
    p_mode.add_argument("--mode", required=True, choices=["rp", "combat", "cutscene"],
                         help="Game mode: rp (free-form), combat (strict turns), cutscene (GM only)")

    sub.add_parser("check-timer", help="Check turn timer status (JSON)")
    sub.add_parser("auto-advance", help="Auto-advance if turn timer expired")
    sub.add_parser("check-idle", help="Check for idle/AFK players (JSON)")
    sub.add_parser("activity-summary", help="Player activity counts (JSON)")

    p_end = sub.add_parser("end-session", help="End the current session")
    p_end.add_argument("--canon", action="store_true", default=False,
                        help="Persist state to player files (canon session)")
    p_end.add_argument("--no-canon", dest="canon", action="store_false",
                        help="Discard state changes (non-canon session)")
    sub.add_parser("status", help="Show current game state")

    args = parser.parse_args()

    commands = {
        "init": cmd_init,
        "join": cmd_join,
        "leave": cmd_leave,
        "wound": cmd_wound,
        "initiative": cmd_initiative,
        "next-turn": cmd_next_turn,
        "end-combat": cmd_end_combat,
        "award-cp": cmd_award_cp,
        "spend-cp": cmd_spend_cp,
        "spend-fp": cmd_spend_fp,
        "update-scene": cmd_update_scene,
        "set-map": cmd_set_map,
        "move-token": cmd_move_token,
        "remove-token": cmd_remove_token,
        "switch-scene": cmd_switch_scene,
        "transfer-token": cmd_transfer_token,
        "list-positions": cmd_list_positions,
        "set-camera": cmd_set_camera,
        "map-legend": cmd_map_legend,
        "set-crawl": cmd_set_crawl,
        "sheet": cmd_sheet,
        "skill-check": cmd_skill_check,
        "log-action": cmd_log_action,
        "log-dice": cmd_log_dice,
        "set-mode": cmd_set_mode,
        "check-timer": cmd_check_timer,
        "auto-advance": cmd_auto_advance,
        "check-idle": cmd_check_idle,
        "activity-summary": cmd_activity_summary,
        "end-session": cmd_end_session,
        "status": cmd_status,
    }

    fn = commands.get(args.command)
    if fn:
        fn(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
