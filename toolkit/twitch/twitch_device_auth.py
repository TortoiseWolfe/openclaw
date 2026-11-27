#!/usr/bin/env python3
"""Device-code sign-in for the contest-vote push's TurtleWolfe token. Prints no token, ever.

  twitch_device_auth.py start   ask Twitch for a device code; print the activate link and the code to type
  twitch_device_auth.py poll    wait for the click, check whose account it is, save the token, print account and scopes
  twitch_device_auth.py check   validate the saved token (account, scopes, seconds left); no secrets printed

The app's client id and secret come from the existing openclaw settings file (OLD_ENV). The new token goes to
NEW_ENV (mode 600), never over OLD_ENV, so the scripthammer token there is left alone. poll refuses to save a
token that is not TurtleWolfe's.
"""
import json
import os
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HOME = os.environ.get("HOME", "/home/node")
OLD_ENV = os.path.join(HOME, ".openclaw", ".env")
NEW_ENV = os.path.join(HOME, ".openclaw", "turtlewolfe.env")
STATE = os.path.join(HOME, ".openclaw", "turtlewolfe-device-state.json")
SCOPES = "user:write:chat moderator:manage:chat_messages"
NEEDED = set(SCOPES.split())
WANT_LOGIN = "turtlewolfe"
ID = "https://id.twitch.tv/oauth2"


def read_env(path):
    out = {}
    try:
        for line in open(path):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                out[k] = v.strip().strip("'\"")
    except FileNotFoundError:
        pass
    return out


def write_private(path, text):
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    os.replace(tmp, path)


def post(url, fields):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except Exception:
            return e.code, {}


def validate(access):
    req = urllib.request.Request(ID + "/validate", headers={"Authorization": "OAuth " + access})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError:
        return None


def start():
    cid = read_env(OLD_ENV).get("OPENCLAW_TWITCH_CLIENT_ID", "")
    code, d = post(ID + "/device", {"client_id": cid, "scopes": SCOPES})
    if code != 200:
        print("device request failed", code, d.get("message", ""))
        return 1
    write_private(STATE, json.dumps({"device_code": d["device_code"], "client_id": cid,
                                     "expires_at": time.time() + d["expires_in"], "interval": d.get("interval", 5)}))
    print("activate:", d["verification_uri"])
    print("code:", d["user_code"], "| expires in", d["expires_in"], "seconds")
    print("scopes asked:", SCOPES)
    return 0


def poll():
    st = json.load(open(STATE))
    secret = read_env(OLD_ENV).get("OPENCLAW_TWITCH_CLIENT_SECRET", "")
    last = None
    print(time.strftime("%-I:%M:%S %p"), "poll started", flush=True)
    while time.time() < st["expires_at"]:
        code, d = post(ID + "/token", {"client_id": st["client_id"], "scopes": SCOPES, "device_code": st["device_code"],
                                       "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
        if code == 200:
            v = validate(d["access_token"]) or {}
            login, scopes = v.get("login", ""), set(v.get("scopes", []))
            if login.lower() != WANT_LOGIN:
                print(f"REFUSED: the click was made as '{login}', not {WANT_LOGIN}. Nothing saved.")
                return 2
            if not NEEDED <= scopes:
                print(f"REFUSED: scopes missing: {sorted(NEEDED - scopes)}. Nothing saved.")
                return 2
            write_private(NEW_ENV, "\n".join([
                "OPENCLAW_TWITCH_ACCESS_TOKEN=" + d["access_token"],
                "OPENCLAW_TWITCH_REFRESH_TOKEN=" + d.get("refresh_token", ""),
                "OPENCLAW_TWITCH_CLIENT_ID=" + st["client_id"],
                "OPENCLAW_TWITCH_CLIENT_SECRET=" + secret,
                "OPENCLAW_TWITCH_EXPIRES_IN=" + str(d.get("expires_in", 0)),
                "OPENCLAW_TWITCH_OBTAINMENT_TIMESTAMP=" + str(int(time.time() * 1000)), ""]))
            os.remove(STATE)
            print(f"SAVED: account {login} (user id {v.get('user_id')}); scopes {sorted(scopes)}; file {NEW_ENV} (mode 600)")
            return 0
        stamp = time.strftime("%-I:%M:%S %p")
        if d.get("message") != last:  # log each change of Twitch's answer (never a token)
            print(f"{stamp} Twitch says: {code} {d.get('message', '')}", flush=True)
            last = d.get("message")
        if d.get("message") not in ("authorization_pending", "slow_down"):
            print("poll stopped:", code, d.get("message", ""))
            return 1
        time.sleep(st.get("interval", 5) + (5 if d.get("message") == "slow_down" else 0))
    print("the code expired before it was used")
    return 1


def check():
    v = validate(read_env(NEW_ENV).get("OPENCLAW_TWITCH_ACCESS_TOKEN", ""))
    if not v:
        print("token invalid or expired (refresh or sign in again)")
        return 1
    print(f"account {v.get('login')} (user id {v.get('user_id')}); scopes {sorted(v.get('scopes', []))}; expires in {v.get('expires_in')} s")
    return 0


if __name__ == "__main__":
    cmds = {"start": start, "poll": poll, "check": check}
    if len(sys.argv) != 2 or sys.argv[1] not in cmds:
        print(__doc__)
        sys.exit(1)
    sys.exit(cmds[sys.argv[1]]())
