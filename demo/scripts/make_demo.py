"""Build the demo video from the captured clips (capture.py): voice-over, captions, music,
title and result cards. Output: demo/out/invoiceflow-demo.mp4 (1920x1080, about 2 minutes).

    uv run --no-project --with edge-tts --with imageio-ffmpeg --with numpy         python demo/scripts/make_demo.py

Voice: Microsoft neural TTS through edge-tts (needs internet; only the narration text is sent).
Set VOICE=en-US-AvaNeural etc. to change it. Adapted from the WatchOnce demo pipeline.
"""

import json
import os
import re
import subprocess
import wave
from dataclasses import dataclass, field
from pathlib import Path

import imageio_ffmpeg
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "demo" / "out" / "raw"
EDIT = ROOT / "demo" / "out" / "edit"
OUT = ROOT / "demo" / "out" / "invoiceflow-demo.mp4"
MARKS = json.loads((RAW / "marks.json").read_text(encoding="utf-8"))
FF = imageio_ffmpeg.get_ffmpeg_exe()
VOICE = os.environ.get("VOICE", "en-US-AndrewNeural")
W, H, FPS = 1920, 1080, 30
BG = "0x06201e"
FONT = "'C\\:/Windows/Fonts/seguisb.ttf'"
FONT_BOLD = "'C\\:/Windows/Fonts/segoeuib.ttf'"
LEAD, TAIL = 0.35, 0.65  # silence before / after each voice line


@dataclass
class Sub:
    clip: str
    start: float
    end: float
    speed: float | None = None  # None: stretch to fill the segment


@dataclass
class Segment:
    name: str
    voice: str = ""
    caption: str = ""
    subs: list[Sub] = field(default_factory=list)
    kind: str = "screen"  # screen | popup | card
    pip: Sub | None = None  # extension counters shown in the corner
    card: tuple[str, str, str] = ("", "", "")
    min_seconds: float = 0.0


c, k, o = MARKS["clerk"], MARKS["controller"], MARKS["odoo"]
SEGMENTS = [
    Segment("00-title", kind="card", min_seconds=4.0,
            card=("InvoiceFlow", "Invoices in. Approved bills out.", "An AI accounts-payable agent")),
    Segment("01-problem",
            "Every month, finance teams type hundreds of supplier invoices into their ERP, check each one against the purchase order, and chase managers for approval. It's slow, and every mistake costs real money.",
            "Accounts payable: slow, manual, and risky",
            [Sub("clerk", c["start"], c["signed_in"] + 1.2)]),
    Segment("02-upload",
            "Ayesha, from accounts, uploads this morning's invoices. PDFs, and even a photo taken on a phone.",
            "Upload PDFs and phone photos",
            [Sub("clerk", c["upload"], c["uploaded"] + 1.0)]),
    Segment("03-reading",
            "InvoiceFlow reads each one with Gemini, then checks it against the ERP: the vendor, the purchase order, the goods that actually arrived, and every bill already in the books.",
            "AI reads. Rules check against Odoo.",
            [Sub("clerk", c["uploaded"] + 1.0, c["processed"])]),
    Segment("04-sorted",
            "Two minutes later, all five are sorted. Two small, clean invoices went straight through, and are already posted. One needs a manager. Two were stopped.",
            "Sorted: posted, awaiting approval, needs review",
            [Sub("clerk", c["processed"], c["inbox_read"])]),
    Segment("05-evidence",
            "Every value the AI reads has to be found on the page. Hover over a field, and you see exactly where it came from. If it isn't on the page, it's thrown out, so the AI can't make numbers up.",
            "Every value is grounded on the page",
            [Sub("clerk", c["review"], c["review_end"])]),
    Segment("06-duplicate",
            "This one is the same invoice, sent again with the number written differently. Caught as a duplicate.",
            "Duplicate caught, even with a new number format",
            [Sub("clerk", c["duplicate"], c["duplicate_end"])]),
    Segment("07-bank",
            "And this one asks to be paid into a new bank account, with hidden text telling the AI to approve it. The AI only reads. Rules decide. It's blocked until someone calls the supplier.",
            "Bank account changed + hidden prompt injection: blocked",
            [Sub("clerk", c["bank"], c["bank_end"])]),
    Segment("08-approve",
            "The large invoice needs a manager. Bilal sees the reasons, and approves it with one click. The person who uploaded it can't approve their own invoice.",
            "One-click approval, with separation of duties",
            [Sub("controller", k["approvals"], k["posted"])]),
    Segment("09-odoo",
            "It lands in Odoo as a vendor bill, linked to the purchase order, with the original PDF attached.",
            "Posted to Odoo, linked to the PO, PDF attached",
            [Sub("odoo", o["bill"], o["bill_end"])]),
    Segment("10-results",
            "Tested on ninety-seven invoices, including twelve trick invoices built to fool it. Zero false approvals.",
            kind="card", min_seconds=5.0,
            card=("0 false approvals", "100% correct decisions on 97 test invoices", "Duplicates · bank-account fraud · price and quantity checks · prompt injection")),
    Segment("11-end", "InvoiceFlow. AI reads, rules decide, and people approve the exceptions.", kind="card", min_seconds=5.0,
            card=("InvoiceFlow", "AI reads. Rules decide. People approve exceptions.", "github.com/khurram-Shahid09/Invoice-flow")),
]
  # fmt: skip


def run(args: list[str], cwd: Path = EDIT) -> None:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise SystemExit(f"command failed: {' '.join(args[:6])} ...\n{result.stderr[-3000:]}")


def duration(path: Path) -> float:
    out = subprocess.run([FF, "-i", str(path)], capture_output=True, text=True).stderr
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def make_voice(seg: Segment) -> Path | None:
    if not seg.voice:
        return None
    path = EDIT / "voice" / f"{seg.name}.mp3"
    stamp = path.with_suffix(".txt")
    key = f"{VOICE}|{seg.voice}"
    if not (path.exists() and stamp.exists() and stamp.read_text(encoding="utf-8") == key):
        path.parent.mkdir(parents=True, exist_ok=True)
        run(["edge-tts", "--voice", VOICE, "--rate=-4%", "--text", seg.voice, "--write-media", str(path)])
        stamp.write_text(key, encoding="utf-8")
    return path


def text_file(name: str, text: str) -> str:
    (EDIT / "text").mkdir(exist_ok=True)
    (EDIT / "text" / name).write_text(text, encoding="utf-8")
    return f"text/{name}"


def build_segment(seg: Segment, voice: Path | None) -> tuple[Path, float]:
    total = max(seg.min_seconds, (duration(voice) + LEAD + TAIL) if voice else 0)
    out = EDIT / "segments" / f"{seg.name}.mp4"
    out.parent.mkdir(exist_ok=True)
    args = [FF, "-y", "-hide_banner"]
    filters: list[str] = []

    if seg.kind == "card":
        title, line, small = seg.card
        args += ["-f", "lavfi", "-i", f"color=c={BG}:s={W}x{H}:r={FPS}:d={total}"]
        filters.append(
            f"[0:v]drawtext=fontfile={FONT_BOLD}:textfile={text_file(seg.name + '-1.txt', title)}:fontsize=140:fontcolor=white:x=(w-tw)/2:y=h/2-170,"
            f"drawtext=fontfile={FONT}:textfile={text_file(seg.name + '-2.txt', line)}:fontsize=58:fontcolor=0x5eead4:x=(w-tw)/2:y=h/2+20,"
            f"drawtext=fontfile={FONT}:textfile={text_file(seg.name + '-3.txt', small)}:fontsize=34:fontcolor=0x94a3b8:x=(w-tw)/2:y=h/2+120,"
            f"fade=t=in:st=0:d=0.6,fade=t=out:st={total - 0.6}:d=0.6[v]"
        )
        next_input = 1
    else:
        fixed = sum((s.end - s.start) / s.speed for s in seg.subs if s.speed)
        stretch = sum(s.end - s.start for s in seg.subs if not s.speed)
        auto = max(0.6, stretch / max(total - fixed, 0.5)) if stretch else 1.0
        speeds = [s.speed or auto for s in seg.subs]
        for s in seg.subs:
            args += ["-ss", f"{s.start}", "-to", f"{s.end}", "-i", str(RAW / f"{s.clip}.webm")]
        parts = []
        for i, (s, speed) in enumerate(zip(seg.subs, speeds, strict=True)):
            if seg.kind == "popup":
                scale = "crop=320:300:0:0,scale=800:750:flags=lanczos"
            else:
                scale = "scale=1728:1080:flags=lanczos"
            filters.append(f"[{i}:v]setpts=(PTS-STARTPTS)/{speed:.4f},fps={FPS},{scale},setsar=1[p{i}]")
            parts.append(f"[p{i}]")
        filters.append(f"{''.join(parts)}concat=n={len(parts)}:v=1:a=0[cat]")
        if seg.kind == "popup":
            filters.append(f"[cat]pad={W}:{H}:(ow-iw)/2:(oh-ih)/2-20:color={BG}[base]")
        else:
            filters.append(f"[cat]pad={W}:{H}:(ow-iw)/2:0:color={BG}[base]")
        next_input = len(seg.subs)
        last = "base"
        if seg.pip:
            p = seg.pip
            args += ["-ss", f"{p.start}", "-to", f"{p.end}", "-i", str(RAW / f"{p.clip}.webm")]
            filters.append(
                f"[{next_input}:v]setpts=(PTS-STARTPTS)/{speeds[0]:.4f},fps={FPS},crop=320:168:0:0,"
                f"scale=640:336:flags=lanczos,pad=652:348:6:6:color=0x2563eb[pip]"
            )
            filters.append(f"[{last}][pip]overlay=x=W-96-652-24:y=H-348-170:shortest=0[withpip]")
            last = "withpip"
            next_input += 1
        caption = text_file(seg.name + ".txt", seg.caption)
        filters.append(
            f"[{last}]tpad=stop_mode=clone:stop_duration=30,trim=duration={total},setpts=PTS-STARTPTS,"
            f"drawtext=fontfile={FONT}:textfile={caption}:fontsize=46:fontcolor=white:"
            f"box=1:boxcolor=0x06201e@0.85:boxborderw=22:x=(w-tw)/2:y=h-110-th[v]"
        )

    if voice:
        args += ["-i", str(voice)]
        delay = int(LEAD * 1000)
        filters.append(f"[{next_input}:a]aresample=48000,adelay={delay}|{delay},apad,atrim=0:{total}[a]")
    else:
        args += ["-f", "lavfi", "-t", f"{total}", "-i", "anullsrc=r=48000:cl=stereo"]
        filters.append(f"[{next_input}:a]atrim=0:{total}[a]")

    args += [
        "-filter_complex", ";".join(filters), "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-t", f"{total}", str(out),
    ]  # fmt: skip
    run(args)
    return out, total


def make_music(seconds: float) -> Path:
    """A quiet pad (Am - F - C - G), synthesized: no licensing questions."""
    rate = 44100
    t = np.arange(int(seconds * rate)) / rate
    chords = [(110.0, 220.0, 261.63, 329.63), (87.31, 174.61, 220.0, 261.63),
              (130.81, 196.0, 261.63, 329.63), (98.0, 196.0, 246.94, 293.66)]  # fmt: skip
    bar = 4.0
    signal = np.zeros_like(t)
    for n in range(int(seconds / bar) + 2):
        notes = chords[n % len(chords)]
        start = n * bar - 1.0
        local = t - start
        env = np.clip(local / 1.5, 0, 1) * np.clip((bar + 1.0 - local) / 1.5, 0, 1)
        env = 0.5 - 0.5 * np.cos(np.pi * env)
        for f in notes:
            signal += env * (np.sin(2 * np.pi * f * t) + 0.25 * np.sin(2 * np.pi * 2 * f * t + 0.3))
    signal *= 1 + 0.08 * np.sin(2 * np.pi * 0.2 * t)
    signal /= np.max(np.abs(signal)) + 1e-9
    fade = np.clip(t / 3, 0, 1) * np.clip((seconds - t) / 4, 0, 1)
    pcm = (signal * fade * 0.5 * 32767).astype(np.int16)
    path = EDIT / "music.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return path


def main() -> None:
    EDIT.mkdir(parents=True, exist_ok=True)
    built = []
    for seg in SEGMENTS:
        voice = make_voice(seg)
        path, seconds = build_segment(seg, voice)
        built.append((path, seconds))
        print(f"{seg.name:14s} {seconds:5.1f}s", flush=True)
    listing = EDIT / "segments.txt"
    listing.write_text("".join(f"file '{p.as_posix()}'\n" for p, _ in built), encoding="utf-8")
    joined = EDIT / "joined.mp4"
    run([FF, "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(joined)])
    total = sum(s for _, s in built)
    music = make_music(total)
    run([
        FF, "-y", "-i", str(joined), "-i", str(music), "-filter_complex",
        "[1:a]aresample=48000,volume=0.10[m];[0:a][m]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]",
        "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", str(OUT),
    ])  # fmt: skip
    (EDIT / "timeline.json").write_text(
        json.dumps([{"segment": s.name, "seconds": round(d, 2)} for s, (_, d) in zip(SEGMENTS, built, strict=True)], indent=2)
    )
    print(f"\n{OUT} ({total:.0f}s)")


if __name__ == "__main__":
    main()
