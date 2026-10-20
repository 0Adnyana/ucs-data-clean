import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from make_test_envsound_no_audioset import (  # noqa: E402
    build,
    evenly_spaced,
    main,
    source_quotas,
)


def _row(category: str, subcategory: str, source: str, name: str) -> dict[str, str]:
    return {
        "filename": name,
        "Category": category,
        "SubCategory": subcategory,
        "Keywords": name,
        "source": source,
        "path": f"{source}/{name}",
        "exists": "True",
    }


def _splits() -> dict[str, list[dict[str, str]]]:
    train = [_row("ANIMALS", "DOG", "FSD50K", f"f{index}.wav") for index in range(6)]
    train += [_row("ANIMALS", "DOG", "AudioSet", f"a{index}.wav") for index in range(6)]
    train += [_row("TOOLS", "POWER", "AudioSet", "only-audioset.wav")]
    val = [_row("WATER", "", "ESC-50", f"e{index}.wav") for index in range(4)]
    val += [_row("WATER", "", "AudioSet", f"w{index}.wav") for index in range(2)]
    test = [_row("ANIMALS", "DOG", "FSD50K", "test-dog.wav"), _row("WEATHER", "RAIN", "AudioSet", "test-as.wav")]
    return {"train": train, "val": val, "test": test}


def _foley() -> dict[str, list[dict[str, str]]]:
    return {
        "train": [_row("FOOTSTEPS", "HUMAN", "FoleySet", "00001.wav")],
        "val": [_row("", "", "FoleySet", "00002.wav")],
        "test": [_row("HUMAN", "SNORE", "FoleySet", "00003.wav")],
    }


class MakeTestEnvSoundNoAudioSetTests(unittest.TestCase):
    def test_source_quotas_keep_a_small_source(self) -> None:
        quotas = source_quotas({"FSD50K": 10, "ESC-50": 1, "AudioSet": 1}, 10)
        assert quotas == {"FSD50K": 8, "ESC-50": 1, "AudioSet": 1}
        assert sum(source_quotas({"AudioSet": 3, "FSD50K": 5}, 4).values()) == 4

    def test_evenly_spaced_does_not_repeat(self) -> None:
        rows = [_row("ANIMALS", "DOG", "FSD50K", f"{index}.wav") for index in range(8)]
        picked = evenly_spaced(rows, 4)
        assert len(picked) == len({row["path"] for row in picked}) == 4

    def test_folders_share_one_test_and_match_pair_counts(self) -> None:
        folders = build(_splits(), _foley())
        test = folders["2-no-audioset"]["test"]
        assert [row["filename"] for row in test] == ["test-dog.wav"]
        for name, splits in folders.items():
            assert splits["test"] == test, name
            assert all(row["source"] != "AudioSet" for row in splits["test"])

        no_audio = folders["2-no-audioset"]
        same = folders["3-audioset-same-size"]
        assert len(same["train"]) == len(no_audio["train"]) == 6
        assert len(same["val"]) == len(no_audio["val"]) == 4
        assert any(row["source"] == "AudioSet" for row in same["train"])
        assert all(row["SubCategory"] != "POWER" for row in same["train"])
        assert {row["Category"] for row in folders["1-original"]["train"]} >= {"ANIMALS", "TOOLS"}

        foley_train = [row for row in folders["4-no-audioset-foleyset"]["train"] if row["source"] == "FoleySet"]
        assert [row["Category"] for row in foley_train] == ["FOOTSTEPS"]
        assert folders["4-no-audioset-foleyset"]["test"] == test
        assert all(row["filename"] != "00003.wav" for split in folders["4-no-audioset-foleyset"].values() for row in split)

    def test_main_writes_identical_test_files(self) -> None:
        import csv
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = root / "original"
            foley = root / "foley"
            out = root / "out"
            for directory, splits in ((original, _splits()), (foley, _foley())):
                directory.mkdir()
                for name, rows in splits.items():
                    path = directory / f"envsound_{name}.csv"
                    with path.open("w", newline="", encoding="utf-8") as handle:
                        writer = csv.DictWriter(
                            handle,
                            fieldnames=list(rows[0]),
                            lineterminator="\n",
                        )
                        writer.writeheader()
                        writer.writerows(rows)
            main(["--original", str(original), "--foley", str(foley), "--out", str(out)])
            tests = [(out / name / "envsound_test.csv").read_bytes() for name in (
                "1-original",
                "2-no-audioset",
                "3-audioset-same-size",
                "4-no-audioset-foleyset",
            )]
            assert tests[0] == tests[1] == tests[2] == tests[3]
            train = (out / "4-no-audioset-foleyset" / "envsound_train.csv").read_text(encoding="utf-8")
            assert "FOOTSTEPS" in train
            assert "only-audioset.wav" not in (out / "3-audioset-same-size" / "envsound_train.csv").read_text(encoding="utf-8")
