#!/usr/bin/env python3
"""Multi-scene OBS show orchestrator.

Transitions through a sequence of show phases:
  Starting Soon (countdown) -> Intro video -> Episode -> Outro -> Stop

Each phase maps to a pre-configured OBS scene. Media-based phases
(Intro, Episode) wait for playback to finish; static phases (Starting
Soon, Outro) sleep for a fixed duration.

Env vars (all optional, sensible defaults):
  OBS_STARTING_SCENE    - Holding scene name (default: Starting Soon)
  OBS_STARTING_DURATION - Countdown seconds (default: 120)
  OBS_INTRO_SCENE       - Intro scene name (default: Stream Intro)
  OBS_INTRO_SOURCE      - Intro media source (default: IntroVideo)
  OBS_OUTRO_SCENE       - Outro scene name (default: Starting Soon)
  OBS_OUTRO_DURATION    - Outro seconds (default: 30)
  OBS_PLAYBACK_SCENE    - Episode scene (default: Episode Playback)
  OBS_MEDIA_SOURCE      - Episode media source (default: EpisodeVideo)
  OBS_STREAM_KEY        - Twitch stream key
  OBS_RENDERS_WIN_PREFIX - Windows UNC prefix for render paths
"""

import atexit
import glob
import os
import re
import signal
import sys
import time
from dataclasses import dataclass

sys.path.insert(0, "/app/toolkit/cron-helpers")

import obs_client
from path_utils import RENDERS_DIR, to_windows_path


def _fuzzy_find_episode_dir(base: str, slug: str) -> str | None:
    """Find episode directory, tolerating 'and'/'the' differences in slugs."""
    candidate = os.path.join(base, slug)
    if os.path.isdir(candidate):
        return candidate
    stripped = re.sub(r"-(?:and|the|a)-", "-", slug)
    if stripped != slug:
        candidate = os.path.join(base, stripped)
        if os.path.isdir(candidate):
            return candidate
    if os.path.isdir(base):
        for d in os.listdir(base):
            if re.sub(r"-(?:and|the|a)-", "-", d) == stripped:
                return os.path.join(base, d)
    return None


# ── Emergency stream shutdown on process kill ──────────────────
# If the cron job timeout kills us (SIGTERM), stop the stream first.
_stream_started_by_us = False


def _emergency_stop_stream(signum=None, frame=None) -> None:
    """Best-effort stream stop on process termination."""
    global _stream_started_by_us
    if not _stream_started_by_us:
        return
    try:
        print(f"\n!! Emergency stream stop (signal={signum}) ...", file=sys.stderr)
        obs_client.stop_streaming(verify_timeout=5)
        print("!! Stream stopped", file=sys.stderr)
    except Exception as e:
        # Last resort: fire and forget
        try:
            cl = obs_client._connect()
            cl.stop_stream()
            cl.disconnect()
        except Exception:
            pass
        print(f"!! Emergency stop error: {e}", file=sys.stderr)
    _stream_started_by_us = False
    if signum is not None:
        sys.exit(1)


signal.signal(signal.SIGTERM, _emergency_stop_stream)
atexit.register(_emergency_stop_stream)


@dataclass
class ShowPhase:
    """A single phase of the show."""
    name: str
    scene: str
    media_source: str | None = None
    video_file: str | None = None
    duration_sec: int | None = None
    volume_db: float = 0.0


def find_intro_video() -> str | None:
    """Find the most recent generic StreamIntro video (any naming convention)."""
    # Check _generic subdirectory first (new structure)
    generic_dir = os.path.join(RENDERS_DIR, "_generic")
    for pattern_name in ["SH-StreamIntro-*.mp4", "StreamIntro-narrated-*.mp4", "StreamIntro-*.mp4"]:
        matches = sorted(glob.glob(os.path.join(generic_dir, pattern_name)))
        if matches:
            return matches[-1]
    # Fall back to flat structure (legacy)
    for pattern_name in ["SH-StreamIntro-*.mp4", "StreamIntro-narrated-*.mp4", "StreamIntro-*.mp4"]:
        matches = sorted(glob.glob(os.path.join(RENDERS_DIR, pattern_name)))
        if matches:
            return matches[-1]
    return None


def find_episode_intro(episode_name: str) -> str | None:
    """Find the per-episode intro video by episode slug.

    Args:
        episode_name: Episode slug (e.g., 'python-for-beginners')

    Returns:
        Path to the episode-specific intro, or None if not found.
    """
    # Check topic folders first (renders/{series}/{slug}/)
    for series_dir in sorted(glob.glob(os.path.join(RENDERS_DIR, "*", episode_name))):
        pattern = os.path.join(series_dir, "intro-*.mp4")
        matches = sorted(glob.glob(pattern))
        if matches:
            return matches[-1]
    # Check flat episode subdirectory (legacy)
    episode_dir = os.path.join(RENDERS_DIR, episode_name)
    pattern = os.path.join(episode_dir, "intro-*.mp4")
    matches = sorted(glob.glob(pattern))
    if matches:
        return matches[-1]
    # Fall back to flat file naming (legacy)
    pattern = os.path.join(RENDERS_DIR, f"{episode_name}-intro-*.mp4")
    matches = sorted(glob.glob(pattern))
    if matches:
        return matches[-1]
    # Fuzzy fallback: tolerate 'and'/'the' differences in slug
    for series_base in sorted(glob.glob(os.path.join(RENDERS_DIR, "*"))):
        if not os.path.isdir(series_base):
            continue
        match = _fuzzy_find_episode_dir(series_base, episode_name)
        if match:
            hits = sorted(glob.glob(os.path.join(match, "intro-*.mp4")))
            if hits:
                return hits[-1]
    match = _fuzzy_find_episode_dir(RENDERS_DIR, episode_name)
    if match:
        hits = sorted(glob.glob(os.path.join(match, "intro-*.mp4")))
        if hits:
            return hits[-1]
    return None


def find_holding_screen() -> str | None:
    """Find the most recent HoldingScreen video."""
    generic_dir = os.path.join(RENDERS_DIR, "_generic")
    for pattern_name in ["SH-HoldingScreen-*.mp4", "HoldingScreen-*.mp4"]:
        matches = sorted(glob.glob(os.path.join(generic_dir, pattern_name)))
        if matches:
            return matches[-1]
    # Fall back to flat structure (legacy)
    for pattern_name in ["SH-HoldingScreen-*.mp4", "HoldingScreen-*.mp4"]:
        matches = sorted(glob.glob(os.path.join(RENDERS_DIR, pattern_name)))
        if matches:
            return matches[-1]
    return None


def find_episode_outro(episode_name: str) -> str | None:
    """Find the per-episode outro video by episode slug.

    Args:
        episode_name: Episode slug (e.g., 'python-for-beginners')

    Returns:
        Path to the episode-specific outro, or None if not found.
    """
    # Check topic folders first (renders/{series}/{slug}/)
    for series_dir in sorted(glob.glob(os.path.join(RENDERS_DIR, "*", episode_name))):
        pattern = os.path.join(series_dir, "outro-*.mp4")
        matches = sorted(glob.glob(pattern))
        if matches:
            return matches[-1]
    # Check flat episode subdirectory (legacy)
    episode_dir = os.path.join(RENDERS_DIR, episode_name)
    pattern = os.path.join(episode_dir, "outro-*.mp4")
    matches = sorted(glob.glob(pattern))
    if matches:
        return matches[-1]
    # Fall back to flat file naming (legacy)
    pattern = os.path.join(RENDERS_DIR, f"{episode_name}-outro-*.mp4")
    matches = sorted(glob.glob(pattern))
    if matches:
        return matches[-1]
    # Fuzzy fallback: tolerate 'and'/'the' differences in slug
    for series_base in sorted(glob.glob(os.path.join(RENDERS_DIR, "*"))):
        if not os.path.isdir(series_base):
            continue
        match = _fuzzy_find_episode_dir(series_base, episode_name)
        if match:
            hits = sorted(glob.glob(os.path.join(match, "outro-*.mp4")))
            if hits:
                return hits[-1]
    match = _fuzzy_find_episode_dir(RENDERS_DIR, episode_name)
    if match:
        hits = sorted(glob.glob(os.path.join(match, "outro-*.mp4")))
        if hits:
            return hits[-1]
    return None


def ensure_scenes(phases: list[ShowPhase]) -> None:
    """Create any missing OBS scenes required by the show phases."""
    try:
        available = obs_client.get_scenes()
    except Exception as e:
        print(f"ERROR: Cannot list OBS scenes: {e}", file=sys.stderr)
        sys.exit(1)

    required = {p.scene for p in phases}
    missing = required - set(available)
    for name in sorted(missing):
        print(f"  Creating scene: {name}")
        obs_client.create_scene(name)


def _wait_for_media_end(source: str, max_duration_sec: int,
                        check_stream: bool = False) -> None:
    """Poll media status every 10s until ended or timeout.

    Args:
        source: OBS media source name.
        max_duration_sec: Expected video duration (timeout = this + 60s).
        check_stream: If True, also verify stream is still live every 30s.
    """
    poll_interval = 10
    elapsed = 0
    timeout = max_duration_sec + 60  # safety buffer
    consecutive_errors = 0
    max_consecutive_errors = 5

    while elapsed < timeout:
        time.sleep(poll_interval)
        elapsed += poll_interval
        try:
            ms = obs_client.get_media_status(source)
            consecutive_errors = 0
            state = ms.get("state", "")
            if state == "OBS_MEDIA_STATE_ENDED":
                print(f"    Media finished")
                return
            cursor_sec = (ms.get("cursor", 0) or 0) / 1000
            duration = (ms.get("duration", 0) or 0) / 1000
            print(f"    {int(cursor_sec // 60)}:{int(cursor_sec % 60):02d}"
                  f" / {int(duration // 60)}:{int(duration % 60):02d}")
        except Exception as e:
            consecutive_errors += 1
            print(f"    (poll error {consecutive_errors}/{max_consecutive_errors}: {e})",
                  file=sys.stderr)
            if consecutive_errors >= max_consecutive_errors:
                print(f"    ABORT: {max_consecutive_errors} consecutive poll failures — "
                      "OBS WebSocket likely down", file=sys.stderr)
                return

        # Periodically verify stream is still live
        if check_stream and elapsed % 30 == 0:
            try:
                if not obs_client.is_streaming():
                    print("    WARNING: Stream dropped! Attempting restart...",
                          file=sys.stderr)
                    try:
                        obs_client.start_streaming()
                        print("    Stream restarted (verified)")
                    except Exception as restart_err:
                        print(f"    Stream restart failed: {restart_err}",
                              file=sys.stderr)
            except Exception:
                pass  # stream check is best-effort

    print(f"    Timeout waiting for media end ({timeout}s)", file=sys.stderr)


def run_phase(phase: ShowPhase, check_stream: bool = False) -> None:
    """Execute a single show phase.

    Args:
        phase: The show phase to execute.
        check_stream: If True, monitor stream health during media waits.
    """
    print(f"\n>> Phase: {phase.name}")
    print(f"   Scene: {phase.scene}")

    obs_client.switch_scene(phase.scene)

    if phase.media_source and phase.video_file:
        win_path = to_windows_path(phase.video_file)
        print(f"   Media: {phase.media_source} -> {win_path}")

        # Loop the video if phase has a fixed duration (e.g., 30s holding screen over 120s countdown)
        should_loop = phase.duration_sec is not None
        obs_client.create_media_source(phase.scene, phase.media_source)
        obs_client.set_media_source(phase.media_source, win_path, looping=should_loop)
        obs_client.set_input_volume(phase.media_source, phase.volume_db)
        time.sleep(1)
        obs_client.trigger_media_action(
            phase.media_source, "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_RESTART",
        )

    if phase.duration_sec is not None and phase.media_source and phase.video_file:
        # Play looping video for fixed duration (e.g., Starting Soon with holding screen)
        print(f"   Playing for {phase.duration_sec}s ...")
        time.sleep(phase.duration_sec)
    elif phase.duration_sec is not None:
        print(f"   Waiting {phase.duration_sec}s ...")
        time.sleep(phase.duration_sec)
    elif phase.media_source and phase.video_file:
        # Wait for video to finish
        _wait_for_media_end(phase.media_source, 3600,
                            check_stream=check_stream)

    print(f"   Phase complete: {phase.name}")


def build_phases(episode_video: str, episode_name: str | None = None) -> list[ShowPhase]:
    """Build the show phase list with optional per-episode branding.

    Args:
        episode_video: Path to the main episode content video.
        episode_name: Episode slug (e.g., 'python-for-beginners') for
            per-episode intro/outro lookup. If None, uses generic intro.
    """
    # Find per-episode intro, fall back to generic
    intro_video = None
    if episode_name:
        intro_video = find_episode_intro(episode_name)
        if intro_video:
            print(f"  Using per-episode intro: {os.path.basename(intro_video)}")
    if not intro_video:
        intro_video = find_intro_video()
        if intro_video:
            print(f"  Using generic intro: {os.path.basename(intro_video)}")

    # Find per-episode outro
    outro_video = None
    if episode_name:
        outro_video = find_episode_outro(episode_name)
        if outro_video:
            print(f"  Using per-episode outro: {os.path.basename(outro_video)}")

    # Find holding screen for Starting Soon phase
    holding_video = find_holding_screen()
    if holding_video:
        print(f"  Using holding screen: {os.path.basename(holding_video)}")

    phases = []

    # Starting Soon: play holding screen video if available, otherwise just wait
    if holding_video:
        phases.append(ShowPhase(
            name="Starting Soon",
            scene=os.environ.get("OBS_STARTING_SCENE", "Starting Soon"),
            media_source="HoldingVideo",
            video_file=holding_video,
            duration_sec=int(os.environ.get("OBS_STARTING_DURATION", "120")),
        ))
    else:
        phases.append(ShowPhase(
            name="Starting Soon",
            scene=os.environ.get("OBS_STARTING_SCENE", "Starting Soon"),
            duration_sec=int(os.environ.get("OBS_STARTING_DURATION", "120")),
        ))

    if intro_video:
        phases.append(ShowPhase(
            name="Intro",
            scene=os.environ.get("OBS_INTRO_SCENE", "Stream Intro"),
            media_source=os.environ.get("OBS_INTRO_SOURCE", "IntroVideo"),
            video_file=intro_video,
        ))
    else:
        print("  (No intro video found, skipping Intro phase)")

    phases.append(ShowPhase(
        name="Episode",
        scene=os.environ.get("OBS_PLAYBACK_SCENE", "Episode Playback"),
        media_source=os.environ.get("OBS_MEDIA_SOURCE", "EpisodeVideo"),
        video_file=episode_video,
    ))

    # Outro: use per-episode video if available, otherwise static holding screen
    if outro_video:
        phases.append(ShowPhase(
            name="Outro",
            scene=os.environ.get("OBS_OUTRO_SCENE",
                                 os.environ.get("OBS_STARTING_SCENE", "Starting Soon")),
            media_source=os.environ.get("OBS_OUTRO_SOURCE", "OutroVideo"),
            video_file=outro_video,
        ))
    else:
        phases.append(ShowPhase(
            name="Outro",
            scene=os.environ.get("OBS_OUTRO_SCENE",
                                 os.environ.get("OBS_STARTING_SCENE", "Starting Soon")),
            duration_sec=int(os.environ.get("OBS_OUTRO_DURATION", "30")),
        ))

    return phases


def build_series_phases(
    episodes: list[tuple[str, str, int]],
) -> list[ShowPhase]:
    """Build show phases for a multi-episode series stream.

    Flow: Starting Soon -> [Intro -> Content -> Outro] x N -> Stop

    Args:
        episodes: List of (episode_name, video_path, duration_sec) tuples.
    """
    # Find holding screen for Starting Soon
    holding_video = find_holding_screen()
    if holding_video:
        print(f"  Using holding screen: {os.path.basename(holding_video)}")

    phases = []

    # Starting Soon (once, at the beginning)
    if holding_video:
        phases.append(ShowPhase(
            name="Starting Soon",
            scene=os.environ.get("OBS_STARTING_SCENE", "Starting Soon"),
            media_source="HoldingVideo",
            video_file=holding_video,
            duration_sec=int(os.environ.get("OBS_STARTING_DURATION", "120")),
        ))
    else:
        phases.append(ShowPhase(
            name="Starting Soon",
            scene=os.environ.get("OBS_STARTING_SCENE", "Starting Soon"),
            duration_sec=int(os.environ.get("OBS_STARTING_DURATION", "120")),
        ))

    # Per-episode phases
    for i, (ep_name, ep_video, _dur) in enumerate(episodes, 1):
        print(f"\n  Episode {i}/{len(episodes)}: {ep_name}")

        # Per-episode intro
        intro_video = find_episode_intro(ep_name)
        if intro_video:
            print(f"    Intro: {os.path.basename(intro_video)}")
            phases.append(ShowPhase(
                name=f"Intro ({ep_name})",
                scene=os.environ.get("OBS_INTRO_SCENE", "Stream Intro"),
                media_source=os.environ.get("OBS_INTRO_SOURCE", "IntroVideo"),
                video_file=intro_video,
            ))
        else:
            # Fall back to generic intro for first episode only
            if i == 1:
                generic_intro = find_intro_video()
                if generic_intro:
                    print(f"    Intro: {os.path.basename(generic_intro)} (generic)")
                    phases.append(ShowPhase(
                        name=f"Intro ({ep_name})",
                        scene=os.environ.get("OBS_INTRO_SCENE", "Stream Intro"),
                        media_source=os.environ.get("OBS_INTRO_SOURCE", "IntroVideo"),
                        video_file=generic_intro,
                    ))

        # Episode content
        phases.append(ShowPhase(
            name=f"Episode: {ep_name}",
            scene=os.environ.get("OBS_PLAYBACK_SCENE", "Episode Playback"),
            media_source=os.environ.get("OBS_MEDIA_SOURCE", "EpisodeVideo"),
            video_file=ep_video,
        ))

        # Per-episode outro — only for the last episode in the series.
        # Mid-series outros have stale "next episode" info baked in from render time
        # (e.g., shows "Up Next: React Hooks" between Python episodes).
        if i == len(episodes):
            outro_video = find_episode_outro(ep_name)
            if outro_video:
                print(f"    Outro: {os.path.basename(outro_video)}")
                phases.append(ShowPhase(
                    name=f"Outro ({ep_name})",
                    scene=os.environ.get("OBS_OUTRO_SCENE",
                                         os.environ.get("OBS_STARTING_SCENE", "Starting Soon")),
                    media_source=os.environ.get("OBS_OUTRO_SOURCE", "OutroVideo"),
                    video_file=outro_video,
                ))

    return phases


def run_series_show(
    episodes: list[tuple[str, str, int]],
    stream: bool = True,
) -> None:
    """Orchestrate a multi-episode series stream.

    Args:
        episodes: List of (episode_name, video_path, duration_sec) tuples.
        stream: Whether to go live on Twitch.
    """
    print("=" * 60)
    print("SERIES SHOW FLOW")
    print("=" * 60)
    total_dur = sum(d for _, _, d in episodes)
    print(f"Episodes: {len(episodes)}")
    for i, (name, path, dur) in enumerate(episodes, 1):
        print(f"  {i}. {name} ({dur // 60}:{dur % 60:02d})")
    print(f"Total content: {total_dur // 60}:{total_dur % 60:02d}")
    print(f"Stream: {stream}")

    # 1. Launch OBS
    print("\nLaunching OBS ...")
    if not obs_client.launch_obs():
        print("ERROR: Could not launch OBS", file=sys.stderr)
        sys.exit(1)
    print("OBS connected")

    # 2. Build phase list
    phases = build_series_phases(episodes)
    print(f"\nShow phases ({len(phases)} total):")
    for p in phases:
        print(f"  {p.name}")

    # 3. Ensure scenes exist
    ensure_scenes(phases)
    print("All scenes ready")

    # 4. Set stream key and go live (or join existing stream)
    global _stream_started_by_us
    already_live = False
    if stream:
        try:
            already_live = obs_client.is_streaming()
        except Exception:
            pass
        if already_live:
            print("\nStream already live — joining existing stream")
        else:
            stream_key = os.environ.get("OBS_STREAM_KEY", "")
            if stream_key:
                print("\nSetting Twitch stream key ...")
                obs_client.set_stream_service("rtmp_common", {
                    "service": "Twitch",
                    "key": stream_key,
                })
            print("Starting Twitch stream ...")
            obs_client.start_streaming()
            _stream_started_by_us = True
            print("LIVE on Twitch (verified)")
    else:
        print("\n(--no-stream: skipping Twitch stream)")

    # 5. Execute all phases — finally block ensures stream stops
    try:
        for phase in phases:
            run_phase(phase, check_stream=stream)
    except Exception as e:
        print(f"\nERROR during show: {e}", file=sys.stderr)
    finally:
        # 6. Stop streaming when show is done
        if stream and not already_live:
            print("\nStopping stream ...")
            try:
                obs_client.stop_streaming()
                _stream_started_by_us = False
                print("Stream stopped (verified)")
            except Exception as e:
                print(f"ERROR: stop_streaming failed: {e}", file=sys.stderr)
        elif stream and already_live:
            print("\n(Stream was already live before show — leaving it running)")

    print("\n" + "=" * 60)
    print(f"SERIES COMPLETE ({len(episodes)} episodes)")
    print("=" * 60)


def run_show(
    episode_video: str,
    duration_sec: int = 0,
    stream: bool = True,
    episode_name: str | None = None,
) -> None:
    """Orchestrate the full show.

    Args:
        episode_video: Path to the episode MP4 (Docker path).
        duration_sec: Episode duration in seconds (for logging only).
        stream: Whether to go live on Twitch.
        episode_name: Episode slug for per-episode intro/outro lookup.
    """
    print("=" * 60)
    print("SHOW FLOW")
    print("=" * 60)
    print(f"Episode: {episode_video}")
    if episode_name:
        print(f"Episode name: {episode_name}")
    print(f"Duration: {duration_sec // 60}:{duration_sec % 60:02d}")
    print(f"Stream: {stream}")

    # 1. Launch OBS
    print("\nLaunching OBS ...")
    if not obs_client.launch_obs():
        print("ERROR: Could not launch OBS", file=sys.stderr)
        sys.exit(1)
    print("OBS connected")

    # 2. Build phase list
    phases = build_phases(episode_video, episode_name)
    print(f"\nShow phases: {' -> '.join(p.name for p in phases)}")

    # 3. Ensure scenes exist (create if missing)
    ensure_scenes(phases)
    print("All scenes ready")

    # 4. Set stream key and go live (or join existing stream)
    global _stream_started_by_us
    already_live = False
    if stream:
        try:
            already_live = obs_client.is_streaming()
        except Exception:
            pass
        if already_live:
            print("\nStream already live — joining existing stream")
        else:
            stream_key = os.environ.get("OBS_STREAM_KEY", "")
            if stream_key:
                print("\nSetting Twitch stream key ...")
                obs_client.set_stream_service("rtmp_common", {
                    "service": "Twitch",
                    "key": stream_key,
                })
            print("Starting Twitch stream ...")
            obs_client.start_streaming()
            _stream_started_by_us = True
            print("LIVE on Twitch (verified)")
    else:
        print("\n(--no-stream: skipping Twitch stream)")

    # 5. Execute phases — finally block ensures stream stops
    try:
        for phase in phases:
            run_phase(phase, check_stream=stream)
    except Exception as e:
        print(f"\nERROR during show: {e}", file=sys.stderr)
    finally:
        # 6. Stop streaming
        if stream and not already_live:
            print("\nStopping stream ...")
            try:
                obs_client.stop_streaming()
                _stream_started_by_us = False
                print("Stream stopped (verified)")
            except Exception as e:
                print(f"ERROR: stop_streaming failed: {e}", file=sys.stderr)
        elif stream and already_live:
            print("\n(Stream was already live before show — leaving it running)")

    print("\n" + "=" * 60)
    print("SHOW COMPLETE")
    print("=" * 60)


def main() -> None:
    """CLI entry point for standalone testing."""
    import argparse
    parser = argparse.ArgumentParser(description="Multi-scene OBS show flow")
    parser.add_argument("--episode-video", required=True,
                        help="Path to episode MP4")
    parser.add_argument("--episode-name",
                        help="Episode slug for per-episode branding (e.g., python-for-beginners)")
    parser.add_argument("--duration", type=int, default=0,
                        help="Episode duration in seconds")
    parser.add_argument("--no-stream", action="store_true",
                        help="Preview without going live")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show phases and validate scenes, don't execute")
    args = parser.parse_args()

    if args.dry_run:
        phases = build_phases(args.episode_video, args.episode_name)
        print(f"Phases: {' -> '.join(p.name for p in phases)}")
        for p in phases:
            print(f"  {p.name}: scene={p.scene} media={p.media_source} "
                  f"duration={p.duration_sec}s video={p.video_file}")
        print("\nEnsuring scenes ...")
        ensure_scenes(phases)
        print("All scenes ready")
        return

    run_show(args.episode_video, args.duration, stream=not args.no_stream,
             episode_name=args.episode_name)


if __name__ == "__main__":
    main()
