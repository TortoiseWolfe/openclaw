#!/usr/bin/env python3
"""One-time migration: rewrite candle JSON files to short-key schema.

Old schema: {"date", "open", "high", "low", "close"} with string values,
            top-level "pair" key.
New schema: {"date", "o", "h", "l", "c"} with numeric values,
            top-level "symbol" key.

Run once, then delete this script. Safe to re-run (idempotent).
"""

import json
import os
import sys

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "trading-data", "data")


def migrate_file(path):
    """Migrate a single candle file. Returns (migrated_count, already_ok)."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    changed = False

    # Fix top-level key: "pair" → "symbol"
    if "pair" in data and "symbol" not in data:
        data["symbol"] = data.pop("pair")
        changed = True

    # Fix candle keys and values
    migrated = 0
    new_candles = []
    for c in data.get("candles", []):
        if "open" in c:
            new_candles.append({
                "date": c["date"],
                "o": float(c["open"]),
                "h": float(c["high"]),
                "l": float(c["low"]),
                "c": float(c["close"]),
                **({} if "volume" not in c else {"v": int(float(c["volume"]))}),
            })
            migrated += 1
            changed = True
        elif isinstance(c.get("o"), str):
            new_candles.append({
                "date": c["date"],
                "o": float(c["o"]),
                "h": float(c["h"]),
                "l": float(c["l"]),
                "c": float(c["c"]),
                **({} if "v" not in c else {"v": int(float(c["v"]))}),
            })
            migrated += 1
            changed = True
        else:
            new_candles.append(c)

    if changed:
        data["candles"] = new_candles
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)

    return migrated, not changed


def main():
    if not os.path.isdir(DATA_DIR):
        print(f"ERROR: {DATA_DIR} not found", file=sys.stderr)
        sys.exit(1)

    total_files = 0
    total_migrated = 0
    total_ok = 0

    for asset_class in ["forex", "stocks", "crypto"]:
        class_dir = os.path.join(DATA_DIR, asset_class)
        if not os.path.isdir(class_dir):
            continue
        for fname in sorted(os.listdir(class_dir)):
            if not fname.endswith("-daily.json"):
                continue
            path = os.path.join(class_dir, fname)
            total_files += 1
            try:
                migrated, already_ok = migrate_file(path)
                if already_ok:
                    total_ok += 1
                    print(f"  OK  {asset_class}/{fname}")
                else:
                    total_migrated += 1
                    print(f"  FIX {asset_class}/{fname} ({migrated} candles)")
            except Exception as e:
                print(f"  ERR {asset_class}/{fname}: {e}", file=sys.stderr)

    # Also check historical/
    hist_dir = os.path.join(DATA_DIR, "historical")
    if os.path.isdir(hist_dir):
        for asset_class in ["forex", "stocks", "crypto"]:
            class_dir = os.path.join(hist_dir, asset_class)
            if not os.path.isdir(class_dir):
                continue
            for fname in sorted(os.listdir(class_dir)):
                if not fname.endswith("-daily.json"):
                    continue
                path = os.path.join(class_dir, fname)
                total_files += 1
                try:
                    migrated, already_ok = migrate_file(path)
                    if already_ok:
                        total_ok += 1
                    else:
                        total_migrated += 1
                        print(f"  FIX historical/{asset_class}/{fname} ({migrated} candles)")
                except Exception as e:
                    print(f"  ERR historical/{asset_class}/{fname}: {e}", file=sys.stderr)

    print(f"\n{total_files} files: {total_migrated} migrated, {total_ok} already OK")


if __name__ == "__main__":
    main()
