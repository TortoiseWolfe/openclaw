#!/usr/bin/env python3
"""Chat duties for the ScriptHammer contest-vote push (Base44 x Nitro, voting closes Thu 3 Dec 2026, 6:59 PM Eastern).

Three duties, all off until stream_push.json says "enabled": true:
  1. PIN   one message at the start of each stream (Helix PUT /chat/pins, pinned until the stream ends).
  2. TIMER a message about every 20 minutes, rotating (a), (b), (c).
  3. !vote a reply, at most once a minute.
The timer and !vote run only while the channel is live and inside a stream's window. After the retire time the
pin comes off, the timer stops and !vote is dropped, for good.

usage:
  stream_push.py dry-run [--now 'YYYY-MM-DD HH:MM']   show every message, the rotation, !vote and the retire step; posts nothing
  stream_push.py status                               switch, windows and saved state; posts nothing
  stream_push.py run                                  refuses while the switch is off

Posts as the account whose token is in ~/.openclaw/.env (twitch_client.py). Reads chat anonymously (justinfan login).
The texts are Hatch's, word for word; do not edit them here without the same change in the hub's copy.
"""
import argparse
import json
import os
import random
import socket
import ssl
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
HERE = Path(__file__).parent
CONFIG_PATH = HERE / "stream_push.json"
STATE_PATH = Path(os.environ.get("HOME", "/home/node")) / ".openclaw" / "stream-push-state.json"

CHANNEL = "scripthammer"
TIMER_MINUTES = 20
VOTE_COOLDOWN_SECONDS = 60
TICK_SECONDS = 30
EARLY = timedelta(minutes=60)   # a stream may start this long before its listed time
LATE = timedelta(minutes=120)   # and run this long after it
RETIRE_AT = datetime(2026, 12, 3, 18, 59, tzinfo=ET)

PIN_TEXT = (
    "ScriptHammer — the robot-band concert game built on this channel — is in the Base44 × Nitro contest, "
    "and voting closes Dec 3. Play it free: scripthammer.base44.app — then vote: "
    "app.base44.com/launchpad/scripthammer (a free Base44 account is needed to vote; joining through this link "
    "gets you 30 bonus credits from Base44: "
    "app.base44.com/register?ref=PMMKTZ923JRZUKLG&source=referral_program)"
)
TIMER_TEXTS = (
    "Enjoying the build? ScriptHammer is live and free to play: scripthammer.base44.app — and it's in the "
    "Base44 contest. Votes close Dec 3: app.base44.com/launchpad/scripthammer",
    "Eight robot musicians, one soundboard, and the player runs the show. Play ScriptHammer free: "
    "scripthammer.base44.app | Contest vote (free account needed): app.base44.com/launchpad/scripthammer",
    "Voting for the Base44 × Nitro contest closes Dec 3 at 6:59 PM ET. ScriptHammer's page: "
    "app.base44.com/launchpad/scripthammer — new to Base44? Join free and get 30 bonus credits: "
    "app.base44.com/register?ref=PMMKTZ923JRZUKLG&source=referral_program",
)
VOTE_TEXT = (
    "Vote for ScriptHammer in the Base44 × Nitro contest (closes Dec 3): app.base44.com/launchpad/scripthammer — "
    "you'll need a free Base44 account; joining here gets you 30 bonus credits from Base44: "
    "app.base44.com/register?ref=PMMKTZ923JRZUKLG&source=referral_program — and the game itself is free to play: "
    "scripthammer.base44.app"
)
TIMER_LABELS = ("a", "b", "c")


@dataclass(frozen=True)
class Stream:
    key: str
    start: datetime
    end: datetime

    def active_at(self, now):
        return self.start - EARLY <= now <= self.end + LATE


def _et(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=ET)


STREAMS = (
    Stream("fri-27-nov", _et(2026, 11, 27, 18, 0), _et(2026, 11, 27, 21, 0)),
    Stream("sat-28-nov", _et(2026, 11, 28, 14, 0), _et(2026, 11, 28, 18, 0)),
    Stream("sun-29-nov", _et(2026, 11, 29, 10, 30), _et(2026, 11, 29, 11, 30)),
)


def stream_at(now):
    for s in STREAMS:
        if s.active_at(now):
            return s
    return None


def is_retired(now):
    return now >= RETIRE_AT + timedelta(minutes=1)


def timer_text(index):
    return TIMER_TEXTS[index % len(TIMER_TEXTS)]


def is_vote_command(text):
    return text.strip().lower() == "!vote"


def load_config(path=CONFIG_PATH):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return {"enabled": False}


def load_state(path=STATE_PATH):
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, ValueError):
        return {"streams": {}, "retired": False, "pin_message_id": None, "last_vote": 0.0}


def save_state(state, path=STATE_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(path)


class Pusher:
    """The three duties. Twitch is reached only through `send`, `pin`, `unpin` and `live`, so tests and the dry run
    can hand in fakes and post nothing."""

    def __init__(self, send, pin, unpin, live, state=None, save=None):
        self.send, self.pin, self.unpin, self.live = send, pin, unpin, live
        self.state = state if state is not None else {"streams": {}, "retired": False, "pin_message_id": None, "last_vote": 0.0}
        self._save = save or (lambda s: None)
        self.is_live_cache = False
        self.log = []

    def _note(self, text):
        self.log.append(text)
        return text

    def tick(self, now):
        """One pass. Returns what was done, as plain lines."""
        done = []
        if is_retired(now):
            if not self.state["retired"]:
                if self.state["pin_message_id"]:
                    try:
                        self.unpin(self.state["pin_message_id"])
                        done.append(self._note("retire: unpinned the pin message"))
                    except Exception as e:  # the pin may already be gone (the stream ended)
                        done.append(self._note(f"retire: unpin skipped ({e})"))
                self.state["retired"] = True
                self.state["pin_message_id"] = None
                self._save(self.state)
                done.append(self._note("retire: timer stopped, !vote dropped"))
            self.is_live_cache = False
            return done
        stream = stream_at(now)
        if stream is None:
            self.is_live_cache = False
            return done
        self.is_live_cache = bool(self.live())
        if not self.is_live_cache:
            return done
        entry = self.state["streams"].setdefault(stream.key, {"pinned": False, "last_timer": None, "next_index": 0})
        if not entry["pinned"]:
            message_id = self.send(PIN_TEXT)
            entry["pinned"] = True
            entry["last_timer"] = now.timestamp()
            done.append(self._note(f"{stream.key}: posted the pin message"))
            try:
                self.pin(message_id)
                self.state["pin_message_id"] = message_id
                done.append(self._note(f"{stream.key}: pinned it"))
            except Exception as e:
                done.append(self._note(f"{stream.key}: PIN FAILED ({e}); the message is posted, pin it by hand"))
            self._save(self.state)
        elif now.timestamp() - entry["last_timer"] >= TIMER_MINUTES * 60:
            index = entry["next_index"]
            self.send(timer_text(index))
            entry["next_index"] = index + 1
            entry["last_timer"] = now.timestamp()
            done.append(self._note(f"{stream.key}: timer ({TIMER_LABELS[index % 3]})"))
            self._save(self.state)
        return done

    def on_chat(self, user, text, now):
        """A chat line. Answers !vote only while live in a window, before retire, once a minute."""
        if not is_vote_command(text) or is_retired(now) or stream_at(now) is None or not self.is_live_cache:
            return None
        if now.timestamp() - self.state["last_vote"] < VOTE_COOLDOWN_SECONDS:
            return None
        self.send(VOTE_TEXT)
        self.state["last_vote"] = now.timestamp()
        self._save(self.state)
        return self._note(f"!vote from {user}: replied")


def parse_privmsg(line):
    """':user!user@user.tmi.twitch.tv PRIVMSG #chan :text' -> (user, text) or None."""
    if " PRIVMSG " not in line:
        return None
    if line.startswith("@"):
        line = line.split(" ", 1)[1]
    prefix, _, rest = line.partition(" PRIVMSG ")
    _, _, text = rest.partition(" :")
    return prefix.lstrip(":").split("!", 1)[0].lower(), text.strip()


def read_chat(channel, on_message, stop, host="irc.chat.twitch.tv", port=6697):
    """Anonymous, read-only chat loop (justinfan login cannot post). Reconnects after a drop."""
    while not stop.is_set():
        try:
            s = ssl.create_default_context().wrap_socket(socket.create_connection((host, port), timeout=30), server_hostname=host)
            s.settimeout(5)
            s.sendall(f"PASS SCHMOOPIIE\r\nNICK justinfan{random.randint(10000, 99999)}\r\nJOIN #{channel}\r\n".encode())
            buf = b""
            while not stop.is_set():
                try:
                    data = s.recv(4096)
                except (TimeoutError, socket.timeout):
                    continue
                if data == b"":
                    break
                buf += data
                while b"\r\n" in buf:
                    raw, buf = buf.split(b"\r\n", 1)
                    line = raw.decode("utf-8", "replace")
                    if line.startswith("PING"):
                        s.sendall(b"PONG :tmi.twitch.tv\r\n")
                    m = parse_privmsg(line)
                    if m:
                        on_message(*m)
        except OSError:
            stop.wait(5)


def dry_run(start_now=None, out=print):
    """Walk every stream with a fake clock and fake Twitch, printing exactly what would post. Posts nothing."""
    posted = []

    def make(now_box):
        def send(text):
            posted.append((now_box[0], text))
            return f"fake-{len(posted)}"
        return send

    for text in (PIN_TEXT, VOTE_TEXT, *TIMER_TEXTS):
        if len(text) > 500:
            raise SystemExit(f"a text is {len(text)} characters; Twitch allows 500")
    out(f"Account: the token's own account (config says {CHANNEL}); channel twitch.tv/{CHANNEL}")
    out(f"Switch: {'ON' if load_config().get('enabled') else 'OFF'} (stream_push.json)")
    out(f"Retire: after {RETIRE_AT.strftime('%a %-d %b %Y %-I:%M %p')} Eastern (acts from {(RETIRE_AT + timedelta(minutes=1)).strftime('%-I:%M %p')})")
    out("")
    now_box = [None]
    cur = [None]  # the stream being walked; the fake channel is live from its listed start to its listed end
    p = Pusher(make(now_box), lambda mid: out(f"      [pin {mid}]"), lambda mid: out(f"      [unpin {mid}]"),
               lambda: cur[0].start <= now_box[0] <= cur[0].end)
    for s in STREAMS:
        cur[0] = s
        out(f"== {s.key}: listed {s.start.strftime('%a %-I:%M %p')} to {s.end.strftime('%-I:%M %p')} Eastern; "
            f"duties run from {(s.start - EARLY).strftime('%-I:%M %p')} to {(s.end + LATE).strftime('%-I:%M %p')} while live")
        t = s.start - EARLY
        last = None
        while t <= s.end + LATE:
            now_box[0] = t
            before = len(posted)
            for line in p.tick(t):
                out(f"  {t.strftime('%a %-I:%M %p')}  {line}")
            if len(posted) > before:
                last = t
                out(f"      {len(posted[-1][1])} chars: {posted[-1][1]}")
            t += timedelta(seconds=TICK_SECONDS)
        # a viewer types !vote mid-stream, twice in a row, then once outside any window
        mid = s.start + timedelta(minutes=5)
        p.state["last_vote"] = 0.0
        p.is_live_cache = True
        for offset in (0, 20, 90):
            r = p.on_chat("viewer1", "!vote", mid + timedelta(seconds=offset))
            out(f"  !vote at +{offset}s: {'REPLY: ' + posted[-1][1] if r else 'no reply (cooldown)'}")
        out("")
    outside = RETIRE_AT - timedelta(days=2)
    p.is_live_cache = True
    out(f"  !vote outside every window ({outside.strftime('%a %-d %b %-I:%M %p')}): "
        f"{'REPLY' if p.on_chat('viewer1', '!vote', outside) else 'no reply'}")
    out("== retire")
    p.state["pin_message_id"] = "fake-pin"
    for line in p.tick(RETIRE_AT - timedelta(seconds=30)):
        out(f"  {(RETIRE_AT - timedelta(seconds=30)).strftime('%a %-d %b %-I:%M:%S %p')}  {line}")
    out(f"  {RETIRE_AT.strftime('%a %-d %b %-I:%M:%S %p')}  (the last minute of voting, nothing retires yet)")
    after = RETIRE_AT + timedelta(minutes=1)
    for line in p.tick(after):
        out(f"  {after.strftime('%a %-d %b %-I:%M:%S %p')}  {line}")
    p.is_live_cache = True
    out(f"  !vote after retire: {'REPLY' if p.on_chat('viewer1', '!vote', after + timedelta(minutes=5)) else 'no reply (dropped)'}")
    out(f"  a later pass does nothing: {p.tick(after + timedelta(hours=1))}")
    return posted


def run(out=print):
    if not load_config().get("enabled"):
        out("OFF: stream_push.json has enabled false. Nothing runs. Use dry-run to see what would post.")
        return 3
    import twitch_client as tc
    state = load_state()
    pusher = Pusher(tc.send_chat_message_get_id, tc.pin_chat_message, tc.unpin_chat_message, tc.is_channel_live,
                    state=state, save=save_state)
    stop = threading.Event()
    threading.Thread(target=read_chat, args=(CHANNEL, lambda u, t: pusher.on_chat(u, t, datetime.now(ET)), stop),
                     daemon=True).start()
    while True:
        try:
            for line in pusher.tick(datetime.now(ET)):
                out(f"{datetime.now(ET).isoformat(timespec='seconds')} {line}")
        except Exception as e:
            out(f"tick failed: {e}")
        if state["retired"]:
            stop.set()
            out("retired; exiting")
            return 0
        time.sleep(TICK_SECONDS)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["dry-run", "status", "run"])
    args = ap.parse_args(argv)
    if args.command == "dry-run":
        dry_run()
        return 0
    if args.command == "status":
        print(f"switch: {'ON' if load_config().get('enabled') else 'OFF'}")
        print(f"state file: {STATE_PATH} ({'exists' if STATE_PATH.exists() else 'not yet written'})")
        return 0
    return run()


if __name__ == "__main__":
    sys.exit(main())
