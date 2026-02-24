#!/usr/bin/env python3
"""Generate an SVG map template from a reference image.

Embeds a prepared PNG/JPEG as a base layer in an SVG with empty overlay
layers for collision geometry, zones, positions, and decorative elements.
The result is a template ready for tracing in Inkscape or by hand-editing XML.

Usage:
    python3 map_base_builder.py \\
        --input rpg/maps/source/cantina-weg-prepared.png \\
        --output remotion/public/game/maps/cantina-expanded.svg \\
        --name "Chalmun's Spaceport Cantina" \\
        --image-opacity 0.35

If the base64-encoded image exceeds --max-embed-kb (default 3072 KB),
the image is saved alongside the SVG as an external file and referenced
via a relative <image href="...">.

Stdlib only — no pip dependencies.
"""

import argparse
import base64
import mimetypes
import os
import sys
import textwrap


SVG_TEMPLATE = textwrap.dedent("""\
<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg"
     xmlns:xlink="http://www.w3.org/1999/xlink"
     viewBox="0 0 {width} {height}"
     width="{width}" height="{height}">

  <defs>
    <!-- 40px alignment grid -->
    <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
      <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#444" stroke-width="0.3" opacity="0.15"/>
    </pattern>

    <!-- Ambient lighting -->
    <radialGradient id="light" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#ffd700" stop-opacity="0.06"/>
      <stop offset="100%" stop-color="#000" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="dim-light" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#ff6600" stop-opacity="0.04"/>
      <stop offset="100%" stop-color="#000" stop-opacity="0"/>
    </radialGradient>
  </defs>

  <!-- Background -->
  <rect width="{width}" height="{height}" fill="#1a1410"/>

  <!-- LAYER 1: Reference image (base layer) -->
  <g id="base-layer">
    <image x="{img_x}" y="{img_y}" width="{img_w}" height="{img_h}"
           href="{img_href}"
           opacity="{opacity}"
           preserveAspectRatio="xMidYMid meet"/>
  </g>

  <!-- LAYER 2: Collision geometry (trace walls here) -->
  <!-- Set opacity="0.15" while authoring, "0" for production -->
  <!-- Each rect/polygon id should match an obstacle id in the terrain JSON -->
  <g id="collision-geometry" opacity="0" fill="red" stroke="red" stroke-width="1">
    <!-- Example:
    <rect id="wall-north" x="0" y="0" width="1920" height="20"/>
    <rect id="bar-counter-left" x="600" y="300" width="200" height="20"/>
    -->
  </g>

  <!-- LAYER 3: Zone boundaries (trace zone extents here) -->
  <!-- Useful for visualizing zone groupings from terrain JSON -->
  <g id="zones" opacity="0" stroke-width="2" fill-opacity="0.05">
    <!-- Example:
    <rect id="zone-vestibule" x="800" y="900" width="300" height="160"
          fill="blue" stroke="blue"/>
    -->
  </g>

  <!-- LAYER 4: Position markers (authoring aid) -->
  <!-- Crosshairs at each named position from terrain JSON -->
  <g id="positions" opacity="0" stroke="#0f0" stroke-width="1" fill="none">
    <!-- Example:
    <circle id="pos-entrance" cx="960" cy="1040" r="8"/>
    <line x1="952" y1="1040" x2="968" y2="1040"/>
    <line x1="960" y1="1032" x2="960" y2="1048"/>
    -->
  </g>

  <!-- LAYER 5: Decorative elements -->
  <g id="decorative">
    <text x="{title_x}" y="24" text-anchor="middle"
          font-family="'Palatino Linotype','Book Antiqua',Palatino,serif"
          font-size="18" fill="#ffd700" font-weight="bold"
          letter-spacing="2">{title}</text>

    <!-- Ambient lighting overlays -->
    <circle cx="960" cy="540" r="500" fill="url(#light)"/>

    <!-- Alignment grid -->
    <rect width="{width}" height="{height}" fill="url(#grid)"/>

    <!-- Scale reference -->
    <text x="{width_minus_10}" y="{height_minus_16}" text-anchor="end"
          font-family="monospace" font-size="10" fill="#666">~5 meters</text>
  </g>

</svg>
""")


def build_svg(
    input_path: str,
    output_path: str,
    name: str,
    width: int = 1920,
    height: int = 1080,
    img_x: int = 0,
    img_y: int = 0,
    img_w: int | None = None,
    img_h: int | None = None,
    opacity: float = 0.35,
    max_embed_kb: int = 3072,
) -> None:
    """Build an SVG template with the reference image as base layer."""

    with open(input_path, "rb") as f:
        raw = f.read()

    size_kb = len(raw) / 1024
    mime, _ = mimetypes.guess_type(input_path)
    if not mime:
        ext = os.path.splitext(input_path)[1].lower()
        mime = {"png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(
            ext, "image/png"
        )

    # Decide embed vs external
    b64 = base64.b64encode(raw).decode("ascii")
    b64_kb = len(b64) / 1024

    if b64_kb > max_embed_kb:
        # Save external copy next to the SVG
        ext = mimetypes.guess_extension(mime) or ".png"
        base_name = os.path.splitext(os.path.basename(output_path))[0]
        ext_filename = f"{base_name}-base{ext}"
        ext_path = os.path.join(os.path.dirname(output_path), ext_filename)
        with open(ext_path, "wb") as f:
            f.write(raw)
        img_href = ext_filename
        print(f"Image too large for embed ({b64_kb:.0f} KB > {max_embed_kb} KB)")
        print(f"Saved external: {ext_path}")
    else:
        img_href = f"data:{mime};base64,{b64}"
        print(f"Embedded image: {size_kb:.0f} KB raw, {b64_kb:.0f} KB base64")

    svg = SVG_TEMPLATE.format(
        width=width,
        height=height,
        img_x=img_x,
        img_y=img_y,
        img_w=img_w or width,
        img_h=img_h or height,
        img_href=img_href,
        opacity=opacity,
        title=name.upper() + " — Mos Eisley, Tatooine",
        title_x=width // 2,
        width_minus_10=width - 10,
        height_minus_16=height - 16,
    )

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        f.write(svg)

    print(f"SVG written: {output_path} ({len(svg) / 1024:.0f} KB)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate SVG map template from a reference image"
    )
    parser.add_argument("--input", required=True, help="Path to prepared PNG/JPEG")
    parser.add_argument("--output", required=True, help="Output SVG path")
    parser.add_argument(
        "--name",
        default="Chalmun's Spaceport Cantina",
        help="Map title",
    )
    parser.add_argument("--width", type=int, default=1920, help="Canvas width")
    parser.add_argument("--height", type=int, default=1080, help="Canvas height")
    parser.add_argument(
        "--image-x", type=int, default=0, help="Image X offset on canvas"
    )
    parser.add_argument(
        "--image-y", type=int, default=0, help="Image Y offset on canvas"
    )
    parser.add_argument(
        "--image-width", type=int, default=None, help="Image width (default=canvas)"
    )
    parser.add_argument(
        "--image-height", type=int, default=None, help="Image height (default=canvas)"
    )
    parser.add_argument(
        "--image-opacity", type=float, default=0.35, help="Base layer opacity"
    )
    parser.add_argument(
        "--max-embed-kb",
        type=int,
        default=3072,
        help="Max base64 size before using external file (KB)",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(f"ERROR: Input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    build_svg(
        input_path=args.input,
        output_path=args.output,
        name=args.name,
        width=args.width,
        height=args.height,
        img_x=args.image_x,
        img_y=args.image_y,
        img_w=args.image_width,
        img_h=args.image_height,
        opacity=args.image_opacity,
        max_embed_kb=args.max_embed_kb,
    )


if __name__ == "__main__":
    main()
