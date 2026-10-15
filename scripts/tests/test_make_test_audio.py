import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from make_test_audio import (  # noqa: E402
    apply_plan,
    plan_test_audio,
    relative_audio_path,
)


def _touch(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


class MakeTestAudioTests(unittest.TestCase):
    def test_relative_path_rejects_escape(self) -> None:
        assert relative_audio_path(r"FSD50K\a.wav").as_posix() == "FSD50K/a.wav"
        with self.assertRaisesRegex(ValueError, "unsafe"):
            relative_audio_path("../secret.wav")
        with self.assertRaisesRegex(ValueError, "unsafe"):
            relative_audio_path("")

    def test_copy_skip_and_remove(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "audio"
            out = root / "test-audio"
            _touch(audio / "ESC-50" / "audio" / "a.wav", b"aaa")
            _touch(audio / "FSD50K" / "b.wav", b"bbb")
            _touch(out / "ESC-50" / "audio" / "stale.wav", b"old")
            _touch(out / "gone" / "only.txt", b"x")
            rows = [
                {"path": "ESC-50/audio/a.wav", "source": "ESC-50"},
                {"path": "FSD50K/b.wav", "source": "FSD50K"},
                {"path": "ESC-50/audio/missing.wav", "source": "ESC-50"},
                {"path": "ESC-50/audio/a.wav", "source": "ESC-50"},
            ]
            plan = plan_test_audio(rows, audio, out)
            assert len(plan.copy) == 2
            assert plan.current == 0
            assert plan.missing == ["ESC-50/audio/missing.wav"]
            assert {path.name for path in plan.remove} == {"stale.wav", "only.txt"}
            assert plan.by_source["ESC-50"] == 1 and plan.by_source["FSD50K"] == 1

            apply_plan(plan, out, dry_run=True)
            assert (out / "gone" / "only.txt").is_file()
            assert not (out / "FSD50K" / "b.wav").is_file()

            apply_plan(plan, out)
            assert (out / "ESC-50" / "audio" / "a.wav").read_bytes() == b"aaa"
            assert (out / "FSD50K" / "b.wav").read_bytes() == b"bbb"
            assert not (out / "ESC-50" / "audio" / "stale.wav").exists()
            assert not (out / "gone").exists()

            again = plan_test_audio(rows, audio, out)
            assert again.copy == [] and again.current == 2 and again.remove == []

            _touch(audio / "FSD50K" / "b.wav", b"bbbb")
            changed = plan_test_audio(rows, audio, out)
            assert [src.name for src, _dst in changed.copy] == ["b.wav"]
            assert changed.current == 1
