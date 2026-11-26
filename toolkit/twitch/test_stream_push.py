"""Tests for stream_push.py. Nothing here touches Twitch: every call goes to a fake."""
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import stream_push as sp

ET = sp.ET
DRAFT = Path(__file__).parent / "fixtures" / "stream_push_texts.md"


def make(live=True):
    sent, pinned, unpinned = [], [], []

    def send(text):
        sent.append(text)
        return f"m{len(sent)}"

    p = sp.Pusher(send, pinned.append, unpinned.append, lambda: live)
    return p, sent, pinned, unpinned


def at(day, h, m=0):
    return datetime(2026, 11, day, h, m, tzinfo=ET)


def test_texts_match_the_draft_word_for_word():
    body = DRAFT.read_text()
    quoted = re.findall(r'^"(.*)"$', body, flags=re.M)
    assert quoted == [sp.PIN_TEXT, *sp.TIMER_TEXTS, sp.VOTE_TEXT]


def test_every_text_fits_twitch():
    assert all(len(t) <= 500 for t in (sp.PIN_TEXT, sp.VOTE_TEXT, *sp.TIMER_TEXTS))


def test_pin_once_then_rotation_every_twenty_minutes():
    p, sent, pinned, _ = make()
    t = at(27, 18, 0)
    p.tick(t)
    assert sent == [sp.PIN_TEXT] and pinned == ["m1"]
    p.tick(t + timedelta(minutes=19))
    assert len(sent) == 1
    for n in range(1, 5):
        p.tick(t + timedelta(minutes=20 * n))
    assert sent[1:] == [sp.TIMER_TEXTS[0], sp.TIMER_TEXTS[1], sp.TIMER_TEXTS[2], sp.TIMER_TEXTS[0]]
    assert len(pinned) == 1


def test_each_stream_pins_again_and_starts_at_a():
    p, sent, _, _ = make()
    p.tick(at(27, 18))
    p.tick(at(27, 18, 20))
    p.tick(at(28, 14))
    p.tick(at(28, 14, 20))
    assert sent == [sp.PIN_TEXT, sp.TIMER_TEXTS[0], sp.PIN_TEXT, sp.TIMER_TEXTS[0]]


def test_nothing_while_offline_or_outside_a_window():
    p, sent, _, _ = make(live=False)
    p.tick(at(27, 18))
    assert sent == []
    p2, sent2, _, _ = make(live=True)
    p2.tick(at(27, 12))  # six hours early
    p2.tick(at(30, 18))  # a day with no stream
    assert sent2 == []


def test_vote_replies_only_live_in_a_window_with_a_cooldown():
    p, sent, _, _ = make()
    t = at(27, 19)
    assert p.on_chat("a", "!vote", t) is None  # live not yet confirmed by a tick
    p.tick(t)
    sent.clear()
    assert p.on_chat("a", "!VOTE ", t)
    assert sent == [sp.VOTE_TEXT]
    assert p.on_chat("b", "!vote", t + timedelta(seconds=30)) is None
    assert p.on_chat("b", "!vote", t + timedelta(seconds=61))
    assert p.on_chat("b", "vote please", t + timedelta(seconds=200)) is None
    assert p.on_chat("b", "!vote", at(30, 19)) is None  # outside every window


def test_retire_unpins_stops_timer_and_drops_vote():
    p, sent, _, unpinned = make()
    p.tick(at(29, 10, 30))
    p.is_live_cache = True
    before = datetime(2026, 12, 3, 18, 59, 0, tzinfo=ET)
    assert p.tick(before) == []
    assert not p.state["retired"]
    after = datetime(2026, 12, 3, 19, 0, 0, tzinfo=ET)
    lines = p.tick(after)
    assert unpinned == ["m1"] and p.state["retired"]
    assert any("unpinned" in x for x in lines) and any("!vote dropped" in x for x in lines)
    sent.clear()
    assert p.on_chat("a", "!vote", after + timedelta(minutes=1)) is None
    assert p.tick(after + timedelta(hours=1)) == [] and sent == []
    assert unpinned == ["m1"]


def test_failed_pin_still_posts_and_says_pin_by_hand():
    sent = []

    def bad_pin(_):
        raise RuntimeError("401 missing scope")

    p = sp.Pusher(lambda t: sent.append(t) or "m1", bad_pin, lambda m: None, lambda: True)
    lines = p.tick(at(27, 18))
    assert sent == [sp.PIN_TEXT] and any("PIN FAILED" in x for x in lines)
    p.tick(at(27, 18, 1))
    assert sent == [sp.PIN_TEXT]  # not posted again


def test_switch_is_off_in_the_committed_config_and_run_refuses():
    assert json.loads(sp.CONFIG_PATH.read_text()) == {"enabled": False}
    lines = []
    assert sp.run(out=lines.append) == 3 and "OFF" in lines[0]


def test_parse_privmsg():
    assert sp.parse_privmsg(":Viewer1!viewer1@viewer1.tmi.twitch.tv PRIVMSG #scripthammer :!vote") == ("viewer1", "!vote")
    assert sp.parse_privmsg("PING :tmi.twitch.tv") is None


def test_dry_run_posts_nothing_and_lists_everything(capsys):
    posted = sp.dry_run()
    out = capsys.readouterr().out
    assert "Switch: OFF" in out and "retire: unpinned" in out and "!vote after retire: no reply" in out
    # per stream: one pin then timers; each stream's first timer is (a)
    assert posted[0][1] == sp.PIN_TEXT
