"""Assemble the Cadence film from captured frames.

frames/<scene>/ (+timings.json) -> per-scene clips -> xfade crossfades ->
caption overlays -> synthesized score -> out/cadence.mp4

Usage: python assemble.py
"""
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FRAMES = ROOT / "frames"
CLIPS = ROOT / "clips"
CAPS = ROOT / "caps"
OUT = ROOT / "out"
W, H, FPS = 1920, 1080, 30
CRF = 18


def run(args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def build_clip(scene: str, hold: float = 0.5) -> float:
    """frames -> clips/<scene>.mp4 at 30fps 1080p. Holds the last frame for
    `hold` s (screencast emits no frames while static). Returns duration."""
    d = FRAMES / scene
    timings = json.loads((d / "timings.json").read_text())
    if len(timings) < 2:
        raise SystemExit(f"scene {scene}: too few frames")
    lines = []
    for i in range(len(timings) - 1):
        dur = max(timings[i + 1]["t"] - timings[i]["t"], 1 / 120)
        lines.append(f"file '{(d / timings[i]['file']).as_posix()}'")
        lines.append(f"duration {dur:.4f}")
    last = (d / timings[-1]["file"]).as_posix()
    lines.append(f"file '{last}'")
    lines.append(f"duration {max(hold, 0.05):.4f}")
    lines.append(f"file '{last}'")
    concat = d / "concat.txt"
    concat.write_text("\n".join(lines))
    total = timings[-1]["t"]
    clip = CLIPS / f"{scene}.mp4"
    if os.environ.get("SKIP_CLIPS") == "1" and clip.exists():
        return total
    CLIPS.mkdir(exist_ok=True)
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
          f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0xf9f9f9,"
          f"fps={FPS},format=yuv420p")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
         "-vf", vf, "-c:v", "libx264", "-crf", str(CRF), "-preset", "fast",
         str(clip)])
    return total


def main():
    film = json.loads((ROOT / "film.json").read_text())
    T = film["transition"]
    scenes = film["scenes"]
    OUT.mkdir(exist_ok=True)

    # 1) build clips, compute trimmed durations + global starts
    meta = []
    gstart = 0.0
    for i, sc in enumerate(scenes):
        full = build_clip(sc["name"], sc.get("hold", 0.6)) + sc.get("hold", 0.6)
        head, tail = sc.get("head", 0), sc.get("tail", 0)
        dur = max(full - head - tail, 0.4)
        meta.append({"name": sc["name"], "head": head, "dur": dur, "gstart": gstart})
        gstart += dur - (T if i < len(scenes) - 1 else 0)
        print(f"  clip {sc['name']}: full {full:.2f}s trimmed {dur:.2f}s @ {meta[i]['gstart']:.2f}s")

    # 2) xfade chain (trim each input with -ss/-t)
    inputs = []
    for m in meta:
        inputs += ["-ss", f"{m['head']}", "-t", f"{m['dur']}",
                   "-i", str(CLIPS / f"{m['name']}.mp4")]
    fc, prev, acc = [], "[0:v]", meta[0]["dur"]
    for i in range(1, len(meta)):
        off = acc - T
        out = f"[x{i}]"
        fc.append(f"{prev}[{i}:v]xfade=transition=fade:duration={T}:offset={off:.3f}{out}")
        prev = out
        acc = acc + meta[i]["dur"] - T
    filt = ";".join(fc) if fc else "[0:v]null[x0]"
    vlabel = prev if fc else "[0:v]"
    novo = OUT / "novo.mp4"
    run(["ffmpeg", "-y", *inputs, "-filter_complex", filt,
         "-map", vlabel, "-c:v", "libx264", "-crf", str(CRF), "-preset", "fast",
         "-pix_fmt", "yuv420p", str(novo)])
    total = acc
    print(f"  concatenated: {total:.2f}s")

    # 3) caption overlays (fade in/out, bottom-center)
    gscene = {m["name"]: m["gstart"] for m in meta}
    cap_inputs, cap_filters, prev = [], [], "[0:v]"
    caps = [c for c in film["captions"] if (CAPS / f"{c['id']}.png").exists()]
    for i, c in enumerate(caps):
        # loop the PNG across the timeline (bounded to total, so ffmpeg ends),
        # otherwise the timed overlay has no frame to show
        cap_inputs += ["-loop", "1", "-t", f"{total:.2f}",
                       "-i", str(CAPS / f"{c['id']}.png")]
    for i, c in enumerate(caps):
        start = gscene[c["scene"]] + c["at"]
        end = start + c["dur"]
        fin, fout = 0.25, 0.3
        src = f"[{i + 1}:v]"
        faded = f"[cf{i}]"
        cap_filters.append(
            f"{src}scale=iw/2:ih/2,format=rgba,fade=t=in:st={start:.2f}:d={fin}:alpha=1,"
            f"fade=t=out:st={end - fout:.2f}:d={fout}:alpha=1{faded}")
        out = f"[v{i}]"
        cap_filters.append(
            f"{prev}{faded}overlay=(W-w)/2:H-h-96:enable='between(t,{start:.2f},{end:.2f})'{out}")
        prev = out
    capped = OUT / "capped.mp4"
    if caps:
        run(["ffmpeg", "-y", "-i", str(novo), *cap_inputs,
             "-filter_complex", ";".join(cap_filters), "-map", prev,
             "-c:v", "libx264", "-crf", str(CRF), "-preset", "fast",
             "-pix_fmt", "yuv420p", "-shortest", str(capped)])
    else:
        capped = novo

    # 4) score + mux
    score = OUT / "score.wav"
    py = os.environ.get("PY", str(ROOT.parent / ".venv" / "bin" / "python"))
    run([py, str(ROOT / "score.py"), f"{total:.2f}", str(score)])
    final = OUT / "cadence.mp4"
    run(["ffmpeg", "-y", "-i", str(capped), "-i", str(score),
         "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
         "-shortest", str(final)])
    print(f"\nFILM: {final}  ({total:.1f}s, {W}x{H})")


if __name__ == "__main__":
    main()
