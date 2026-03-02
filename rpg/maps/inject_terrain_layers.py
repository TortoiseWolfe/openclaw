#!/usr/bin/env python3
"""Inject terrain JSON data into SVG map files as visible overlay layers.

Reads each *-terrain.json, generates SVG elements for obstacles, positions,
and connections, then injects them into the matching SVG file.

Usage:
    python3 inject_terrain_layers.py                    # all maps
    python3 inject_terrain_layers.py cantina-expanded   # single map
"""

import json
import os
import re
import sys

MAPS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(os.path.dirname(MAPS_DIR))  # rpg/maps/ → rpg/ → repo root
SVG_DIR = os.path.join(REPO_DIR, "remotion", "public", "game", "maps")


def load_terrain(slug: str) -> dict | None:
    for suffix in ["-enhanced-terrain.json", "-terrain.json"]:
        path = os.path.join(MAPS_DIR, f"{slug}{suffix}")
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    return None


def generate_layers(terrain: dict) -> str:
    """Generate SVG group elements from terrain data."""
    lines = []
    connections = terrain.get("connections", {})
    positions = terrain.get("positions", {})
    obstacles = terrain.get("obstacles", [])

    # --- Collision geometry layer ---
    lines.append('  <g id="collision-geometry" opacity="0.55" '
                 'stroke="#ff4444" stroke-width="4" stroke-dasharray="6,3">')
    for obs in obstacles:
        x, y = obs["x1"], obs["y1"]
        w, h = obs["x2"] - obs["x1"], obs["y2"] - obs["y1"]
        lines.append(f'    <rect id="{obs["id"]}" x="{x}" y="{y}" '
                     f'width="{w}" height="{h}" fill="rgba(255,68,68,0.1)"/>')
    lines.append('  </g>')
    lines.append('')

    # --- Positions layer ---
    lines.append('  <g id="positions" opacity="0.7" fill="none" stroke-width="1">')

    # Connection positions (doors/exits) — bright cyan, larger, labeled
    for name, conn in connections.items():
        pos = positions.get(name)
        if not pos:
            continue
        cx, cy = pos["x"], pos["y"]
        lines.append(f'    <circle cx="{cx}" cy="{cy}" r="20" '
                     f'stroke="#00ffff" stroke-width="3" fill="rgba(0,255,255,0.15)"/>')
        lines.append(f'    <line x1="{cx-26}" y1="{cy}" x2="{cx+26}" y2="{cy}" stroke="#00ffff" stroke-width="2"/>')
        lines.append(f'    <line x1="{cx}" y1="{cy-26}" x2="{cx}" y2="{cy+26}" stroke="#00ffff" stroke-width="2"/>')
        lines.append(f'    <text x="{cx}" y="{cy-26}" text-anchor="middle" '
                     f'font-family="monospace" font-size="14" fill="#00ffff" '
                     f'font-weight="bold" stroke="#000" stroke-width="3" '
                     f'paint-order="stroke">{name}</text>')

    # Regular positions — green crosshairs
    for name, pos in positions.items():
        if name in connections:
            continue  # already drawn as connection
        cx, cy = pos["x"], pos["y"]
        lines.append(f'    <circle cx="{cx}" cy="{cy}" r="10" stroke="#00cc44" stroke-width="1.5"/>')
        lines.append(f'    <line x1="{cx-15}" y1="{cy}" x2="{cx+15}" y2="{cy}" stroke="#00cc44" stroke-width="1.2"/>')
        lines.append(f'    <line x1="{cx}" y1="{cy-15}" x2="{cx}" y2="{cy+15}" stroke="#00cc44" stroke-width="1.2"/>')

    lines.append('  </g>')

    return "\n".join(lines)


def inject_into_svg(svg_path: str, layers_svg: str) -> bool:
    """Inject terrain layers into SVG, replacing any existing ones."""
    with open(svg_path) as f:
        content = f.read()

    # Remove existing terrain layers if present
    content = re.sub(
        r'\s*<g id="collision-geometry"[^>]*>.*?</g>',
        '', content, flags=re.DOTALL)
    content = re.sub(
        r'\s*<g id="collision-geometry"[^>]*/>\s*',
        '', content)
    content = re.sub(
        r'\s*<g id="positions"[^>]*>.*?</g>',
        '', content, flags=re.DOTALL)
    content = re.sub(
        r'\s*<g id="positions"[^>]*/>\s*',
        '', content)
    content = re.sub(
        r'\s*<g id="zones"[^>]*>.*?</g>',
        '', content, flags=re.DOTALL)
    content = re.sub(
        r'\s*<g id="zones"[^>]*/>\s*',
        '', content)

    # Inject before </svg>
    closing = '</svg>'
    if closing not in content:
        print(f"  WARNING: no </svg> found in {svg_path}")
        return False

    content = content.replace(closing, f"\n{layers_svg}\n{closing}")

    with open(svg_path, 'w') as f:
        f.write(content)

    return True


def process_map(slug: str) -> None:
    terrain = load_terrain(slug)
    if not terrain:
        print(f"  SKIP: no terrain JSON for {slug}")
        return

    svg_name = terrain.get("map", f"{slug}.svg")
    svg_path = os.path.join(SVG_DIR, svg_name)
    if not os.path.exists(svg_path):
        print(f"  SKIP: SVG not found: {svg_path}")
        return

    layers = generate_layers(terrain)
    if inject_into_svg(svg_path, layers):
        n_obs = len(terrain.get("obstacles", []))
        n_pos = len(terrain.get("positions", {}))
        n_conn = len(terrain.get("connections", {}))
        print(f"  {svg_name}: {n_obs} obstacles, {n_pos} positions, {n_conn} exits")


def main() -> None:
    if len(sys.argv) > 1:
        slugs = sys.argv[1:]
    else:
        # Find all terrain JSONs
        slugs = set()
        for f in os.listdir(MAPS_DIR):
            if f.endswith("-terrain.json"):
                slug = f.replace("-enhanced-terrain.json", "").replace("-terrain.json", "")
                slugs.add(slug)
        slugs = sorted(slugs)

    print(f"Injecting terrain layers into {len(slugs)} maps...")
    for slug in slugs:
        print(f"\n  Processing: {slug}")
        process_map(slug)
    print("\nDone.")


if __name__ == "__main__":
    main()
