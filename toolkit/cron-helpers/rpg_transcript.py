#!/usr/bin/env python3
"""Persistent JSONL transcript logger for RPG sessions.

Each event is one JSON line, flushed immediately (crash-safe).
At session end, generates a human-readable Markdown transcript.

Output files (in /home/node/.clawdbot/rpg/sessions/):
  {session-id}.jsonl          — raw event log (streaming)
  {session-id}-transcript.md  — human-readable (generated at end)
"""

import json
import os
from datetime import datetime, timezone

_DATA_DIR = os.environ.get("RPG_DATA_DIR", "/home/node/.clawdbot/rpg")
SESSIONS_DIR = os.path.join(_DATA_DIR, "sessions")


class TranscriptLogger:
    """Append-only JSONL transcript for RPG sessions."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        os.makedirs(SESSIONS_DIR, exist_ok=True)
        self.jsonl_path = os.path.join(SESSIONS_DIR, f"{session_id}.jsonl")
        self.events = []
        self._file = open(self.jsonl_path, "a")

    def _write(self, event: dict):
        event["timestamp"] = datetime.now(timezone.utc).isoformat()
        event["session_id"] = self.session_id
        line = json.dumps(event, ensure_ascii=False)
        self._file.write(line + "\n")
        self._file.flush()
        self.events.append(event)

    def log_narration(self, act, turn, narration, raw_response=""):
        self._write({
            "type": "narration",
            "act": act,
            "turn": turn,
            "narration": narration,
            "raw_response": raw_response,
        })

    def log_tool_call(self, tool_name, args, result):
        self._write({
            "type": "tool_call",
            "tool": tool_name,
            "args": args,
            "result": str(result)[:500],
        })

    def log_dice_roll(self, character, skill, dice, total, detail,
                      difficulty=None, success=None):
        self._write({
            "type": "dice_roll",
            "character": character,
            "skill": skill,
            "dice": dice,
            "total": total,
            "detail": detail,
            "difficulty": difficulty,
            "success": success,
        })

    def log_player_action(self, viewer, character, action_type, text):
        self._write({
            "type": "player_action",
            "viewer": viewer,
            "character": character,
            "action_type": action_type,
            "text": text,
        })

    def log_scene_change(self, act, scene, map_name=""):
        self._write({
            "type": "scene_change",
            "act": act,
            "scene": scene,
            "map": map_name,
        })

    def log_mode_change(self, mode, reason=""):
        self._write({
            "type": "mode_change",
            "mode": mode,
            "reason": reason,
        })

    def log_combat_event(self, event_type, data=None):
        self._write({
            "type": "combat_event",
            "event": event_type,
            **(data or {}),
        })

    def log_session_event(self, event_type, data=None):
        self._write({
            "type": "session_event",
            "event": event_type,
            **(data or {}),
        })

    def log_join_prompt(self, available_characters):
        self._write({
            "type": "join_prompt",
            "available": available_characters,
        })

    def log_feedback_poll(self, question, options):
        self._write({
            "type": "feedback_poll",
            "question": question,
            "options": options,
        })

    def log_feedback_response(self, question, responses):
        self._write({
            "type": "feedback_response",
            "question": question,
            "responses": responses,
        })

    # ------------------------------------------------------------------
    # Participation analysis
    # ------------------------------------------------------------------

    def calculate_participation(self) -> dict:
        """Calculate real vs bot participation from logged player_action events.

        Bot viewers are "bot" or "bot:{slug}" (bot-controlled PCs).
        Any other viewer is a real Twitch player.
        """
        total = 0
        real = 0
        real_viewers = set()
        for ev in self.events:
            if ev.get("type") != "player_action":
                continue
            total += 1
            viewer = ev.get("viewer", "")
            if viewer == "bot" or viewer.startswith("bot:"):
                continue
            real += 1
            real_viewers.add(viewer)
        ratio = real / total if total > 0 else 0.0
        return {
            "total_actions": total,
            "real_actions": real,
            "bot_actions": total - real,
            "ratio": ratio,
            "is_canon": ratio >= 0.5,
            "real_viewers": list(real_viewers),
        }

    # ------------------------------------------------------------------
    # Markdown generation
    # ------------------------------------------------------------------

    def generate_markdown(self):
        """Generate a human-readable Markdown transcript from the events."""
        lines = [f"# Session Transcript: {self.session_id}\n"]
        current_act = 0

        for ev in self.events:
            etype = ev.get("type", "")
            ts = ev.get("timestamp", "")[:19]

            if ev.get("act") and ev["act"] != current_act:
                current_act = ev["act"]
                lines.append(f"\n## Act {current_act}\n")

            if etype == "narration":
                lines.append(f"**[Turn {ev.get('turn', '?')}] GM Narration** ({ts})")
                lines.append(f"> {ev.get('narration', '')}\n")

            elif etype == "dice_roll":
                result_str = ""
                if ev.get("success") is True:
                    result_str = "SUCCESS"
                elif ev.get("success") is False:
                    result_str = "FAILED"
                diff = f"vs {ev['difficulty']} " if ev.get("difficulty") else ""
                lines.append(
                    f"  - Roll: {ev.get('character', '?')} — "
                    f"{ev.get('skill', '?')} ({ev.get('dice', '?')}): "
                    f"**{ev.get('total', '?')}** {diff}{result_str}"
                )

            elif etype == "player_action":
                verb = "says" if ev.get("action_type") == "say" else "does"
                viewer = ev.get("viewer", "")
                viewer_tag = f" [{viewer}]" if viewer and viewer != "bot" else ""
                lines.append(
                    f"  - **{ev.get('character', '?')}**{viewer_tag} {verb}: "
                    f"{ev.get('text', '')}"
                )

            elif etype == "scene_change":
                map_str = f" — {ev.get('map', '')}" if ev.get("map") else ""
                lines.append(
                    f"\n---\n*Scene: Act {ev.get('act')} — "
                    f"{ev.get('scene', 'unknown')}{map_str}*\n"
                )

            elif etype == "mode_change":
                reason = f" ({ev.get('reason')})" if ev.get("reason") else ""
                lines.append(f"*Mode: {ev.get('mode', '?')}{reason}*\n")

            elif etype == "combat_event":
                event = ev.get("event", "")
                extra = {k: v for k, v in ev.items()
                         if k not in ("type", "event", "timestamp", "session_id")}
                lines.append(f"  - Combat: {event} {json.dumps(extra) if extra else ''}")

            elif etype == "session_event":
                event = ev.get("event", "")
                extra = {k: v for k, v in ev.items()
                         if k not in ("type", "event", "timestamp", "session_id")}
                lines.append(f"*Session: {event}*" +
                             (f" {json.dumps(extra)}" if extra else ""))

            elif etype == "join_prompt":
                chars = ev.get("available", [])
                lines.append(f"\n**JOIN NOW!** Characters available: {', '.join(chars)}\n")

            elif etype == "feedback_poll":
                lines.append(f"\n**POLL:** {ev.get('question', '')}")
                for opt in ev.get("options", []):
                    lines.append(f"  - {opt}")
                lines.append("")

            elif etype == "feedback_response":
                lines.append(
                    f"**Poll results:** {ev.get('question', '')} — "
                    f"{json.dumps(ev.get('responses', {}))}\n"
                )

            elif etype == "tool_call":
                # Skip verbose tool calls in markdown (they're in JSONL)
                pass

        return "\n".join(lines)

    def save_markdown(self):
        """Write the Markdown transcript to disk. Returns the path."""
        md = self.generate_markdown()
        md_path = os.path.join(SESSIONS_DIR, f"{self.session_id}-transcript.md")
        with open(md_path, "w") as f:
            f.write(md)
        return md_path

    def close(self):
        if self._file and not self._file.closed:
            self._file.close()
