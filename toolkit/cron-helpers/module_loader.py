#!/usr/bin/env python3
"""Load campaign and module data from JSON files.

Searches the campaign directory structure for module data.
Falls back gracefully when no module.json exists (caller uses hardcoded data).
"""

import json
import os
from dataclasses import dataclass, field

_CONTENT_DIR = os.environ.get("RPG_CONTENT_DIR", "/app/rpg")
CAMPAIGNS_DIR = os.path.join(_CONTENT_DIR, "campaigns")


@dataclass
class ActData:
    """Per-act module data."""
    name: str = ""
    map: str = ""
    map_name: str = ""
    terrain: str = ""
    time_of_day: str = ""
    kick: str = ""
    starting_positions: dict[str, str] = field(default_factory=dict)
    npc_positions: dict[str, dict] = field(default_factory=dict)
    exit_positions: set[str] = field(default_factory=set)
    pacer: dict = field(default_factory=dict)
    bot_actions: dict[str, list] = field(default_factory=dict)
    climax_actions: dict[str, list] = field(default_factory=dict)
    npc_combat_reactions: dict[str, dict] = field(default_factory=dict)
    npc_ambient_routes: dict[str, list] = field(default_factory=dict)
    companion_keywords: dict[str, list] = field(default_factory=dict)


def _action_dict_to_tuple(d: dict) -> tuple:
    """Convert a bot action dict from JSON to the tuple format the session runner expects.

    Tuple: (action_type, text, skill, dice_override, difficulty, move_to_position)
    """
    return (
        d.get("type", "do"),
        d.get("text", ""),
        d.get("skill"),
        d.get("dice_override"),
        d.get("difficulty"),
        d.get("move_to"),
    )


def _parse_act(raw: dict) -> ActData:
    """Parse a single act entry from module.json."""
    act = ActData(
        name=raw.get("name", ""),
        map=raw.get("map", ""),
        map_name=raw.get("map_name", ""),
        terrain=raw.get("terrain", ""),
        time_of_day=raw.get("time_of_day", ""),
        kick=raw.get("kick", ""),
        starting_positions=raw.get("starting_positions", {}),
        npc_positions=raw.get("npc_positions", {}),
        exit_positions=set(raw.get("exit_positions", [])),
        pacer=raw.get("pacer", {}),
        npc_combat_reactions=raw.get("npc_combat_reactions", {}),
        npc_ambient_routes=raw.get("npc_ambient_routes", {}),
        companion_keywords=raw.get("companion_keywords", {}),
    )
    # Convert bot action dicts to tuples
    for char, actions in raw.get("bot_actions", {}).items():
        act.bot_actions[char] = [_action_dict_to_tuple(a) for a in actions]
    for char, actions in raw.get("climax_actions", {}).items():
        act.climax_actions[char] = [_action_dict_to_tuple(a) for a in actions]
    return act


@dataclass
class ModuleData:
    """Structured access to module.json data."""
    name: str = ""
    slug: str = ""
    num_acts: int = 3
    pregens: list[str] = field(default_factory=list)
    healers: set[str] = field(default_factory=set)
    vehicle_tokens: set[str] = field(default_factory=set)
    ship_positions: set[str] = field(default_factory=set)
    char_stats: dict[str, dict] = field(default_factory=dict)
    npc_stats: dict[str, dict] = field(default_factory=dict)
    char_move: dict[str, int] = field(default_factory=dict)
    closing_crawl: dict = field(default_factory=dict)
    _acts: dict[int, ActData] = field(default_factory=dict)

    def get_act(self, act_num: int) -> ActData | None:
        return self._acts.get(act_num)

    @property
    def act_maps(self) -> dict[int, tuple[str, str]]:
        """Return {act_num: (map_image, map_name)} matching ACT_MAPS format."""
        return {n: (a.map, a.map_name) for n, a in self._acts.items()}

    @property
    def act_map_terrain(self) -> dict[int, str]:
        """Return {act_num: terrain_image} matching ACT_MAP_TERRAIN format."""
        return {n: (a.terrain or a.map) for n, a in self._acts.items()}

    @property
    def act_times(self) -> dict[int, str]:
        """Return {act_num: time_of_day} matching ACT_TIMES format."""
        return {n: a.time_of_day for n, a in self._acts.items()}

    @property
    def act_kicks(self) -> dict[int, str]:
        """Return {act_num: kick_text} matching ACT_KICKS format."""
        return {n: a.kick for n, a in self._acts.items()}

    @property
    def act_starting_positions(self) -> dict[int, dict]:
        return {n: a.starting_positions for n, a in self._acts.items()}

    @property
    def npc_starting_positions(self) -> dict[int, dict]:
        """Return NPC positions in the tuple format: {act: {npc: (pos, color, hidden)}}."""
        result = {}
        for n, a in self._acts.items():
            act_npcs = {}
            for npc, data in a.npc_positions.items():
                act_npcs[npc] = (data["position"], data["color"], data.get("hidden", False))
            result[n] = act_npcs
        return result

    @property
    def act_bot_actions(self) -> dict[int, dict]:
        return {n: a.bot_actions for n, a in self._acts.items()}

    @property
    def act_climax_actions(self) -> dict[int, dict]:
        return {n: a.climax_actions for n, a in self._acts.items()}

    @property
    def act_exit_positions(self) -> dict[int, set]:
        return {n: a.exit_positions for n, a in self._acts.items()}

    @property
    def npc_combat_reactions(self) -> dict[int, dict]:
        """Return NPC combat reactions in tuple format: {act: {npc: (reaction, position)}}."""
        result = {}
        for n, a in self._acts.items():
            act_reactions = {}
            for npc, data in a.npc_combat_reactions.items():
                act_reactions[npc] = (data["reaction"], data["position"])
            result[n] = act_reactions
        return result

    @property
    def npc_ambient_routes(self) -> dict[int, dict]:
        return {n: a.npc_ambient_routes for n, a in self._acts.items()}

    @property
    def companion_keywords(self) -> dict[str, list]:
        """Merge companion keywords from all acts."""
        merged = {}
        for a in self._acts.values():
            merged.update(a.companion_keywords)
        return merged


def _parse_module(raw: dict) -> ModuleData:
    """Parse a module.json dict into a ModuleData instance."""
    module = ModuleData(
        name=raw.get("name", ""),
        slug=raw.get("slug", ""),
        num_acts=raw.get("acts", 3),
        pregens=raw.get("pregens", []),
        healers=set(raw.get("healers", [])),
        vehicle_tokens=set(raw.get("vehicle_tokens", [])),
        ship_positions=set(raw.get("ship_positions", [])),
        char_stats=raw.get("char_stats", {}),
        npc_stats=raw.get("npc_stats", {}),
        char_move=raw.get("char_move", {}),
        closing_crawl=raw.get("closing_crawl", {}),
    )
    for act_key, act_raw in raw.get("act_data", {}).items():
        module._acts[int(act_key)] = _parse_act(act_raw)
    return module


def find_module(adventure_slug: str) -> ModuleData | None:
    """Search campaigns/ for a module matching the adventure slug.

    Returns a ModuleData instance or None if not found.
    """
    if not os.path.isdir(CAMPAIGNS_DIR):
        return None
    for campaign_name in os.listdir(CAMPAIGNS_DIR):
        modules_dir = os.path.join(CAMPAIGNS_DIR, campaign_name, "modules")
        if not os.path.isdir(modules_dir):
            continue
        for module_name in os.listdir(modules_dir):
            module_json = os.path.join(modules_dir, module_name, "module.json")
            if not os.path.isfile(module_json):
                continue
            try:
                with open(module_json) as f:
                    raw = json.load(f)
                if raw.get("slug") == adventure_slug:
                    return _parse_module(raw)
            except (json.JSONDecodeError, KeyError):
                continue
    return None


def load_campaign(campaign_slug: str) -> dict | None:
    """Load a campaign.json by slug."""
    campaign_dir = os.path.join(CAMPAIGNS_DIR, campaign_slug)
    campaign_json = os.path.join(campaign_dir, "campaign.json")
    if not os.path.isfile(campaign_json):
        return None
    try:
        with open(campaign_json) as f:
            return json.load(f)
    except (json.JSONDecodeError, KeyError):
        return None
