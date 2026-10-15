"""Copy test-split wavs into test-audio/ for listening.

Each file keeps the path it has under audio/. A destination file with the
same size and modification time is left in place. Files in the destination
that the manifest no longer lists are removed. A source that is not on disk
is counted and skipped.

test-audio/ is gitignored.

Usage:
  python scripts/make_test_audio.py
  python scripts/make_test_audio.py --dry-run
  python scripts/make_test_audio.py --manifest manifests/envsound-foleyset/envsound_test.csv
"""

from __future__ import annotations

import argparse
import csv
import os
import shutil
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "manifests" / "blank-envsound" / "envsound_test.csv"
DEFAULT_OUT = ROOT / "test-audio"
DEFAULT_AUDIO = ROOT / "audio"


@dataclass
class AudioPlan:
    copy: list[tuple[Path, Path]] = field(default_factory=list)
    current: int = 0
    missing: list[str] = field(default_factory=list)
    remove: list[Path] = field(default_factory=list)
    by_source: Counter[str] = field(default_factory=Counter)


def relative_audio_path(raw: str) -> Path:
    text = (raw or "").strip().replace("\\", "/")
    path = Path(text)
    if not text or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe audio path: {raw!r}")
    return path


def read_manifest(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise SystemExit(f"manifest not found: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "path" not in reader.fieldnames:
            raise SystemExit(f"{path} has no path column")
        return list(reader)


def already_current(src: Path, dst: Path) -> bool:
    if not dst.is_file():
        return False
    left, right = src.stat(), dst.stat()
    return left.st_size == right.st_size and left.st_mtime_ns == right.st_mtime_ns


def plan_test_audio(rows: list[dict[str, str]], audio_dir: Path, out_dir: Path) -> AudioPlan:
    plan = AudioPlan()
    keep: set[str] = set()
    for row in rows:
        rel = relative_audio_path(row.get("path") or "")
        key = rel.as_posix()
        if key in keep:
            continue
        keep.add(key)
        src = audio_dir / rel
        if not src.is_file():
            plan.missing.append(key)
            continue
        plan.by_source[row.get("source") or ""] += 1
        dst = out_dir / rel
        if already_current(src, dst):
            plan.current += 1
        else:
            plan.copy.append((src, dst))
    if out_dir.is_dir():
        for path in out_dir.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(out_dir).as_posix()
            if rel not in keep:
                plan.remove.append(path)
    return plan


def place(src: Path, dst: Path, link: bool) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    if link:
        try:
            os.link(src, dst)
            return
        except OSError:
            pass
    shutil.copy2(src, dst)


def prune_empty(root: Path) -> None:
    if not root.is_dir():
        return
    dirs = [path for path in root.rglob("*") if path.is_dir()]
    for path in sorted(dirs, key=lambda item: len(item.parts), reverse=True):
        if not any(path.iterdir()):
            path.rmdir()


def apply_plan(plan: AudioPlan, out_dir: Path, *, link: bool = False, dry_run: bool = False) -> None:
    if dry_run:
        return
    for src, dst in plan.copy:
        place(src, dst, link)
    for path in plan.remove:
        path.unlink()
    prune_empty(out_dir)


def report(out_dir: Path, plan: AudioPlan, dry_run: bool) -> None:
    prefix = "dry run " if dry_run else ""
    sources = ", ".join(f"{name} {count}" for name, count in sorted(plan.by_source.items()))
    print(
        f"{prefix}{out_dir}: copy {len(plan.copy)}, "
        f"current {plan.current}, missing {len(plan.missing)}, remove {len(plan.remove)}"
    )
    if sources:
        print(f"  on disk: {sources}")
    if plan.missing and len(plan.missing) <= 40:
        for rel in plan.missing:
            print(f"  missing {rel}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Copy test-split wavs into test-audio/ for listening.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST, help="CSV with a path column")
    parser.add_argument("--audio", type=Path, default=DEFAULT_AUDIO, help="Dataset root the path column is relative to")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Destination folder")
    parser.add_argument("--link", action="store_true", help="Hard-link files when the destination is on the same drive")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan without writing or deleting")
    args = parser.parse_args(argv)

    rows = read_manifest(args.manifest)
    try:
        plan = plan_test_audio(rows, args.audio, args.out)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    apply_plan(plan, args.out, link=args.link, dry_run=args.dry_run)
    report(args.out, plan, args.dry_run)


if __name__ == "__main__":
    main()
