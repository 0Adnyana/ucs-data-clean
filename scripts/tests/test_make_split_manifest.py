import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from make_split_manifest import (  # noqa: E402
    CHECK_FILE,
    SPLIT_FILES,
    allocate,
    main,
    pick_check,
    split_manifest,
    write_manifest,
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


class MakeSplitManifestTests(unittest.TestCase):
    def assert_exits(self, call, text: str) -> None:
        with self.assertRaises(SystemExit) as caught:
            call()
        self.assertIn(text, str(caught.exception.code))

    def test_allocate_hits_the_ratio(self) -> None:
        assert allocate(0) == (0, 0, 0)
        assert allocate(1) == (1, 0, 0)
        assert allocate(3) == (2, 1, 0)
        assert allocate(5) == (3, 1, 1)
        assert allocate(20) == (14, 3, 3)
        assert sum(allocate(97)) == 97

    def test_each_row_lands_in_one_split(self) -> None:
        rows = [_row("ANIMALS", "DOG", "AudioSet" if index % 2 == 0 else "FoleySet", f"{index}.wav") for index in range(20)]
        rows += [_row("WATER", "", "FSD50K", f"c{index}.wav") for index in range(10)]
        rows += [_row("", "", "ESC-50", f"b{index}.wav") for index in range(10)]
        result = split_manifest(rows)
        seen: set[int] = set()
        for name in ("train", "val", "test"):
            for row in result.splits[name]:
                assert id(row) not in seen
                seen.add(id(row))
        assert seen == {id(row) for row in rows}
        dog = [row for row in rows if row["SubCategory"] == "DOG"]
        dog_test = [row for row in result.splits["test"] if row["SubCategory"] == "DOG"]
        assert len(dog_test) == allocate(len(dog))[2]
        sources = {row["source"] for row in dog_test}
        assert sources == {"AudioSet", "FoleySet"}

    def test_check_is_a_subset_of_test(self) -> None:
        rows = [_row("ANIMALS", "DOG", "AudioSet" if index < 10 else "FSD50K", f"{index}.wav") for index in range(20)]
        rows += [_row("MECHANICAL", "GEARS", "AudioSet", f"g{index}.wav") for index in range(5)]
        result = split_manifest(rows)
        test_paths = {row["path"] for row in result.splits["test"]}
        assert {row["path"] for row in result.check} <= test_paths
        assert all(row["Category"] == "" and row["SubCategory"] == "" for row in result.check)
        labeled = [row for row in result.splits["test"] if row["SubCategory"] == "DOG"]
        assert labeled and all(row["Category"] == "ANIMALS" for row in labeled)
        dog_check = [row for row in result.check if row["filename"][:1].isdigit()]
        assert len(dog_check) == 2
        assert {row["source"] for row in dog_check} == {"AudioSet", "FSD50K"}
        gear_check = [row for row in result.check if row["filename"].startswith("g")]
        assert len(gear_check) == 1
        assert ("MECHANICAL/GEARS", 1) in result.short

    def test_pick_check_fills_when_the_source_repeats(self) -> None:
        rows = [_row("ANIMALS", "DOG", "AudioSet", f"{index}.wav") for index in range(4)]
        picked = pick_check(rows)
        assert len(picked) == 2
        assert picked[0]["filename"] == "0.wav"
        assert picked[1]["filename"] == "1.wav"

    def test_main_writes_splits_and_optional_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            master = root / "master.csv"
            first = root / "split-a"
            second = root / "split-b"
            write_manifest(
                master,
                ["filename", "Category", "SubCategory", "Keywords", "source", "path", "exists"],
                [_row("ANIMALS", "DOG", "AudioSet", f"{index}.wav") for index in range(20)],
            )
            main(["--master", str(master), "--out", str(first)])
            assert (first / SPLIT_FILES["train"]).is_file()
            assert (first / SPLIT_FILES["val"]).is_file()
            assert (first / SPLIT_FILES["test"]).is_file()
            assert not (first / CHECK_FILE).exists()
            main(["--master", str(master), "--out", str(second), "--check"])
            assert (first / SPLIT_FILES["train"]).is_file()
            with (second / CHECK_FILE).open(newline="", encoding="utf-8") as handle:
                check_rows = list(csv.DictReader(handle))
            with (second / SPLIT_FILES["test"]).open(newline="", encoding="utf-8") as handle:
                test_rows = list(csv.DictReader(handle))
            assert len(check_rows) == 2
            assert all(row["Category"] == "" and row["SubCategory"] == "" for row in check_rows)
            assert all(row["Category"] == "ANIMALS" and row["SubCategory"] == "DOG" for row in test_rows)
            test_paths = {row["path"] for row in test_rows}
            assert {row["path"] for row in check_rows} <= test_paths

    def test_main_rejects_a_missing_file_or_column(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = root / "missing.csv"
            self.assert_exits(lambda: main(["--master", str(missing), "--out", str(root / "out")]), "not found")
            bare = root / "bare.csv"
            write_manifest(bare, ["filename"], [{"filename": "a.wav"}])
            self.assert_exits(lambda: main(["--master", str(bare), "--out", str(root / "out")]), "missing columns")


if __name__ == "__main__":
    unittest.main()
