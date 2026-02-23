#!/usr/bin/env python3
"""OBS WebSocket client for launch, monitoring, and stream control.

Connects to OBS Studio's built-in WebSocket server (v5, port 4455).
Also supports launching OBS via a host-side HTTP launcher.

Env vars:
  OBS_WS_HOST      - WebSocket host (default: host.docker.internal)
  OBS_WS_PORT      - WebSocket port (default: 4455)
  OBS_WS_PASSWORD   - WebSocket password (default: empty)
  OBS_LAUNCHER_URL  - Host launcher base URL (default: http://host.docker.internal:8100)
"""

import json
import os
import sys
import time
import urllib.request

import obsws_python as obs

WS_HOST = os.environ.get("OBS_WS_HOST", "host.docker.internal")
WS_PORT = int(os.environ.get("OBS_WS_PORT", "4455"))
WS_PASSWORD = os.environ.get("OBS_WS_PASSWORD", "")
LAUNCHER_URL = os.environ.get("OBS_LAUNCHER_URL", "http://host.docker.internal:8100")
TIMEOUT = 5


# ── Launch (via host HTTP launcher) ──────────────────────────────

def launch_obs(wait: bool = True, max_wait: int = 30) -> bool:
    """Ask host launcher to start OBS. Returns True if OBS is running."""
    try:
        req = urllib.request.Request(f"{LAUNCHER_URL}/launch", method="POST")
        resp = urllib.request.urlopen(req, timeout=TIMEOUT)
        data = json.loads(resp.read())
        if not wait:
            return data.get("running", False)
    except Exception as e:
        print(f"Launcher error: {e}", file=sys.stderr)
        return False

    # Wait for OBS WebSocket to become reachable
    for _ in range(max_wait):
        if is_connected():
            return True
        time.sleep(1)
    return False


def kill_obs() -> bool:
    """Ask host launcher to stop OBS."""
    try:
        req = urllib.request.Request(f"{LAUNCHER_URL}/kill", method="POST")
        resp = urllib.request.urlopen(req, timeout=TIMEOUT)
        data = json.loads(resp.read())
        return not data.get("running", True)
    except Exception as e:
        print(f"Launcher error: {e}", file=sys.stderr)
        return False


def launcher_status() -> dict:
    """Check OBS process status via host launcher."""
    try:
        resp = urllib.request.urlopen(f"{LAUNCHER_URL}/status", timeout=TIMEOUT)
        return json.loads(resp.read())
    except Exception as e:
        return {"running": False, "error": str(e)}


# ── WebSocket control ────────────────────────────────────────────

def _connect() -> obs.ReqClient:
    """Create a new OBS WebSocket connection."""
    return obs.ReqClient(host=WS_HOST, port=WS_PORT, password=WS_PASSWORD, timeout=TIMEOUT)


def is_connected() -> bool:
    """Check if OBS WebSocket is reachable."""
    try:
        cl = _connect()
        cl.get_version()
        cl.disconnect()
        return True
    except Exception:
        return False


def get_status() -> dict:
    """Get OBS streaming/recording status and current scene."""
    cl = _connect()
    try:
        stream = cl.get_stream_status()
        scene = cl.get_current_program_scene()
        version = cl.get_version()
        return {
            "connected": True,
            "obs_version": version.obs_version,
            "streaming": stream.output_active,
            "stream_duration": getattr(stream, "output_duration", 0),
            "current_scene": scene.scene_name,
        }
    finally:
        cl.disconnect()


def get_scenes() -> list[str]:
    """List available scene names."""
    cl = _connect()
    try:
        resp = cl.get_scene_list()
        return [s["sceneName"] for s in resp.scenes]
    finally:
        cl.disconnect()


def switch_scene(name: str) -> None:
    """Switch to a named scene."""
    cl = _connect()
    try:
        cl.set_current_program_scene(name)
    finally:
        cl.disconnect()


def is_streaming() -> bool:
    """Check if OBS is currently streaming."""
    cl = _connect()
    try:
        return cl.get_stream_status().output_active
    finally:
        cl.disconnect()


def start_streaming(verify_timeout: int = 15) -> None:
    """Start streaming and verify it actually went live.

    Args:
        verify_timeout: Max seconds to wait for stream to go live.

    Raises:
        RuntimeError: If stream fails to start within timeout.
    """
    cl = _connect()
    try:
        status = cl.get_stream_status()
        if status.output_active:
            print("Stream already active, stopping first...")
            cl.stop_stream()
            for _ in range(15):
                time.sleep(1)
                if not cl.get_stream_status().output_active:
                    break
            else:
                raise RuntimeError("Timed out waiting for existing stream to stop")
        cl.start_stream()
    finally:
        cl.disconnect()

    # Verify stream actually went live (new connection — OBS needs a moment)
    for i in range(verify_timeout):
        time.sleep(1)
        try:
            cl2 = _connect()
            try:
                if cl2.get_stream_status().output_active:
                    return
            finally:
                cl2.disconnect()
        except Exception:
            pass
    raise RuntimeError(
        f"Stream did not go live within {verify_timeout}s — "
        "check stream key, RTMP endpoint, and OBS stream settings"
    )


def stop_streaming(verify_timeout: int = 15) -> None:
    """Stop streaming and verify it actually stopped.

    Args:
        verify_timeout: Max seconds to wait for stream to stop.

    Raises:
        RuntimeError: If stream fails to stop within timeout.
    """
    cl = _connect()
    try:
        status = cl.get_stream_status()
        if not status.output_active:
            return  # already stopped
        cl.stop_stream()
    finally:
        cl.disconnect()

    for i in range(verify_timeout):
        time.sleep(1)
        try:
            cl2 = _connect()
            try:
                if not cl2.get_stream_status().output_active:
                    return
            finally:
                cl2.disconnect()
        except Exception:
            pass
    raise RuntimeError(f"Stream did not stop within {verify_timeout}s")


def set_stream_service(service_type: str, settings: dict) -> None:
    """Set the stream service (e.g. Twitch RTMP destination and stream key)."""
    cl = _connect()
    try:
        cl.set_stream_service_settings(
            ss_type=service_type,
            ss_settings=settings,
        )
    finally:
        cl.disconnect()


def get_stream_service() -> dict:
    """Get current stream service settings."""
    cl = _connect()
    try:
        resp = cl.get_stream_service_settings()
        return {
            "type": resp.stream_service_type,
            "settings": resp.stream_service_settings,
        }
    finally:
        cl.disconnect()


def set_source_visibility(scene: str, source: str, visible: bool) -> None:
    """Toggle a source's visibility in a scene."""
    cl = _connect()
    try:
        item_id = cl.get_scene_item_id(scene, source).scene_item_id
        cl.set_scene_item_enabled(scene, item_id, visible)
    finally:
        cl.disconnect()


# ── Scene / source setup ──────────────────────────────────────────

def create_scene(name: str) -> None:
    """Create a new scene (no-op if it already exists)."""
    cl = _connect()
    try:
        existing = [s["sceneName"] for s in cl.get_scene_list().scenes]
        if name in existing:
            return
        cl.create_scene(name)
    finally:
        cl.disconnect()


def create_media_source(scene: str, source: str) -> None:
    """Create a media source in a scene (no-op if it already exists).

    After creation, sets the scene item transform to fill the canvas.
    """
    cl = _connect()
    try:
        # Check if source already exists in scene
        try:
            item_id = cl.get_scene_item_id(scene, source).scene_item_id
            # Source exists - ensure it's enabled and fullscreen
            cl.set_scene_item_enabled(scene, item_id, True)
            _set_fullscreen_transform(cl, scene, item_id)
            return
        except Exception:
            pass

        # Create the input
        try:
            resp = cl.create_input(scene, source, "ffmpeg_source", {"local_file": ""}, True)
            item_id = resp.scene_item_id
            # Set transform to fill canvas
            _set_fullscreen_transform(cl, scene, item_id)
        except Exception as e:
            print(f"Failed to create media source '{source}' in scene '{scene}': {e}",
                  file=sys.stderr)
    finally:
        cl.disconnect()


def _set_fullscreen_transform(cl: obs.ReqClient, scene: str, item_id: int) -> None:
    """Set a scene item to fill the canvas (1920x1080 assumed)."""
    try:
        # Get video settings for base resolution
        video = cl.get_video_settings()
        width = video.base_width
        height = video.base_height
    except Exception:
        # Fallback to 1080p
        width, height = 1920, 1080

    # Set transform: position at origin, bounds to fill canvas
    cl.set_scene_item_transform(
        scene,
        item_id,
        {
            "positionX": 0,
            "positionY": 0,
            "boundsType": "OBS_BOUNDS_SCALE_INNER",
            "boundsWidth": width,
            "boundsHeight": height,
            "boundsAlignment": 0,
        },
    )


def ensure_playback_scene(scene: str, source: str) -> None:
    """Create the playback scene and media source if they don't exist."""
    create_scene(scene)
    create_media_source(scene, source)


def create_browser_source(
    scene: str, source: str, url: str,
    width: int = 1920, height: int = 1080,
) -> None:
    """Create a browser source in a scene (no-op if it already exists).

    Browser sources render a web page as an OBS input — ideal for
    overlays, crawl animations, and live game state displays.
    """
    cl = _connect()
    try:
        # Check if source already exists in scene
        try:
            item_id = cl.get_scene_item_id(scene, source).scene_item_id
            cl.set_scene_item_enabled(scene, item_id, True)
            _set_fullscreen_transform(cl, scene, item_id)
            # Ensure audio is routed through OBS mixer (not desktop audio)
            cl.set_input_settings(source, {"reroute_audio": True}, overlay=True)
            # Route audio to stream output (not just meters)
            try:
                cl.set_input_audio_monitor_type(source, "OBS_MONITORING_TYPE_MONITOR_AND_OUTPUT")
            except Exception:
                pass  # older OBS versions may not support this
            return
        except Exception:
            pass

        try:
            resp = cl.create_input(
                scene, source, "browser_source",
                {
                    "url": url,
                    "width": width,
                    "height": height,
                    "reroute_audio": True,
                },
                True,
            )
            _set_fullscreen_transform(cl, scene, resp.scene_item_id)
            # Route audio to stream output (not just meters)
            try:
                cl.set_input_audio_monitor_type(source, "OBS_MONITORING_TYPE_MONITOR_AND_OUTPUT")
            except Exception:
                pass
        except Exception as e:
            print(
                f"Failed to create browser source '{source}' in scene '{scene}': {e}",
                file=sys.stderr,
            )
    finally:
        cl.disconnect()


def set_browser_source_url(source: str, url: str) -> None:
    """Update the URL on an existing browser source."""
    cl = _connect()
    try:
        cl.set_input_settings(source, {"url": url}, overlay=True)
    finally:
        cl.disconnect()


def refresh_browser_source(source: str) -> None:
    """Force a browser source to reload its page."""
    cl = _connect()
    try:
        cl.press_input_properties_button(source, "refreshnocache")
    finally:
        cl.disconnect()


def create_text_source(
    scene: str, source: str, text: str,
    font_size: int = 48, color: int = 0xFFFFFFFF,
) -> None:
    """Create a GDI+ text source in a scene (no-op if it already exists)."""
    cl = _connect()
    try:
        try:
            cl.get_scene_item_id(scene, source)
            # Already exists — just update the text
            cl.set_input_settings(source, {"text": text}, overlay=True)
            return
        except Exception:
            pass

        try:
            cl.create_input(
                scene, source, "text_gdiplus_v2",
                {
                    "text": text,
                    "font": {"face": "Arial", "size": font_size},
                    "color": color,
                },
                True,
            )
        except Exception as e:
            print(
                f"Failed to create text source '{source}' in scene '{scene}': {e}",
                file=sys.stderr,
            )
    finally:
        cl.disconnect()


def update_text_source(source: str, text: str) -> None:
    """Update the text on an existing text source."""
    cl = _connect()
    try:
        cl.set_input_settings(source, {"text": text}, overlay=True)
    finally:
        cl.disconnect()


# ── Media control ─────────────────────────────────────────────────

def set_media_source(source: str, file_path: str, looping: bool = False) -> None:
    """Set the file path on a media source and trigger playback.

    After setting the path, triggers a RESTART action to ensure OBS
    loads and plays the new file.
    """
    cl = _connect()
    try:
        cl.set_input_settings(
            source,
            {"local_file": file_path, "looping": looping},
            overlay=True,
        )
        # Give OBS time to recognize the file, then restart playback
        import time
        time.sleep(0.5)
        cl.trigger_media_input_action(
            source, "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_RESTART"
        )
    finally:
        cl.disconnect()


def set_input_volume(source: str, db: float) -> None:
    """Set the volume of an input source in dB (0 = unity, -6 = half, etc.)."""
    cl = _connect()
    try:
        cl.set_input_volume(source, vol_db=db)
    finally:
        cl.disconnect()


def trigger_media_action(source: str, action: str) -> None:
    """Trigger a media action (restart, play, pause, stop, next, previous)."""
    cl = _connect()
    try:
        cl.trigger_media_input_action(source, action)
    finally:
        cl.disconnect()


def get_media_status(source: str) -> dict:
    """Get media playback state and cursor position."""
    cl = _connect()
    try:
        status = cl.get_media_input_status(source)
        return {
            "state": status.media_state,
            "cursor": status.media_cursor,
            "duration": status.media_duration,
        }
    finally:
        cl.disconnect()


# ── CLI ──────────────────────────────────────────────────────────

COMMANDS = {
    "status": "Show OBS status (WebSocket)",
    "scenes": "List available scenes",
    "switch": "Switch scene (usage: switch <name>)",
    "start": "Start streaming",
    "stop": "Stop streaming",
    "set-media": "Set media source file (usage: set-media <source> <path>)",
    "play": "Play/restart a media source (usage: play <source>)",
    "media-status": "Get media playback status (usage: media-status <source>)",
    "setup": "Create playback scene and media source",
    "add-browser": "Add browser source (usage: add-browser <scene> <source> <url>)",
    "set-browser-url": "Update browser URL (usage: set-browser-url <source> <url>)",
    "refresh-browser": "Reload a browser source (usage: refresh-browser <source>)",
    "add-text": "Add text source (usage: add-text <scene> <source> <text>)",
    "set-text": "Update text content (usage: set-text <source> <text>)",
    "launch": "Launch OBS via host launcher",
    "kill": "Kill OBS via host launcher",
    "launcher-status": "Check host launcher status",
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print("Usage: obs_client.py <command>")
        for cmd, desc in COMMANDS.items():
            print(f"  {cmd:20s} {desc}")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "status":
        try:
            s = get_status()
            print(json.dumps(s, indent=2))
        except Exception as e:
            print(f"OBS not reachable: {e}", file=sys.stderr)
            sys.exit(1)

    elif cmd == "scenes":
        for name in get_scenes():
            print(f"  {name}")

    elif cmd == "switch":
        if len(sys.argv) < 3:
            print("Usage: obs_client.py switch <scene_name>", file=sys.stderr)
            sys.exit(1)
        switch_scene(sys.argv[2])
        print(f"Switched to: {sys.argv[2]}")

    elif cmd == "start":
        start_streaming()
        print("Streaming started")

    elif cmd == "stop":
        stop_streaming()
        print("Streaming stopped")

    elif cmd == "setup":
        scene = os.environ.get("OBS_PLAYBACK_SCENE", "Episode Playback")
        source = os.environ.get("OBS_MEDIA_SOURCE", "EpisodeVideo")
        ensure_playback_scene(scene, source)
        print(f"Scene '{scene}' with source '{source}' ready")

    elif cmd == "set-media":
        if len(sys.argv) < 4:
            print("Usage: obs_client.py set-media <source> <path>", file=sys.stderr)
            sys.exit(1)
        set_media_source(sys.argv[2], sys.argv[3])
        print(f"Set {sys.argv[2]} → {sys.argv[3]}")

    elif cmd == "play":
        if len(sys.argv) < 3:
            print("Usage: obs_client.py play <source>", file=sys.stderr)
            sys.exit(1)
        trigger_media_action(
            sys.argv[2], "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_RESTART",
        )
        print(f"Playing: {sys.argv[2]}")

    elif cmd == "media-status":
        if len(sys.argv) < 3:
            print("Usage: obs_client.py media-status <source>", file=sys.stderr)
            sys.exit(1)
        s = get_media_status(sys.argv[2])
        print(json.dumps(s, indent=2))

    elif cmd == "add-browser":
        if len(sys.argv) < 5:
            print("Usage: obs_client.py add-browser <scene> <source> <url>", file=sys.stderr)
            sys.exit(1)
        create_browser_source(sys.argv[2], sys.argv[3], sys.argv[4])
        print(f"Browser source '{sys.argv[3]}' added to '{sys.argv[2]}'")

    elif cmd == "set-browser-url":
        if len(sys.argv) < 4:
            print("Usage: obs_client.py set-browser-url <source> <url>", file=sys.stderr)
            sys.exit(1)
        set_browser_source_url(sys.argv[2], sys.argv[3])
        print(f"Updated browser URL: {sys.argv[3]}")

    elif cmd == "refresh-browser":
        if len(sys.argv) < 3:
            print("Usage: obs_client.py refresh-browser <source>", file=sys.stderr)
            sys.exit(1)
        refresh_browser_source(sys.argv[2])
        print(f"Refreshed: {sys.argv[2]}")

    elif cmd == "add-text":
        if len(sys.argv) < 5:
            print("Usage: obs_client.py add-text <scene> <source> <text>", file=sys.stderr)
            sys.exit(1)
        create_text_source(sys.argv[2], sys.argv[3], " ".join(sys.argv[4:]))
        print(f"Text source '{sys.argv[3]}' added to '{sys.argv[2]}'")

    elif cmd == "set-text":
        if len(sys.argv) < 4:
            print("Usage: obs_client.py set-text <source> <text>", file=sys.stderr)
            sys.exit(1)
        update_text_source(sys.argv[2], " ".join(sys.argv[3:]))
        print(f"Updated text: {sys.argv[2]}")

    elif cmd == "launch":
        ok = launch_obs()
        print(f"OBS running: {ok}")
        if not ok:
            sys.exit(1)

    elif cmd == "kill":
        ok = kill_obs()
        print(f"OBS stopped: {ok}")

    elif cmd == "launcher-status":
        s = launcher_status()
        print(json.dumps(s, indent=2))


if __name__ == "__main__":
    main()
