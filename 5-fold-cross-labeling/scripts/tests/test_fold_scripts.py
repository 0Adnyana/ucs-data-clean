import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from create_validation_set import main as create_main  # noqa: E402
from create_validation_set import sample_recordings  # noqa: E402
from fold_csv import (  # noqa: E402
    COLUMNS,
    MASTER_COLUMNS,
    is_blank,
    promote_row,
    recording_id,
    row_keywords,
    row_ucs_pair,
    train_piles,
    write_csv,
)
from merge_pile_to_train import main as merge_main  # noqa: E402
from split_to_piles import assign_piles, main as split_main  # noqa: E402


def _row(filename, source, category="", subcategory="", keywords="", path=None):
    return {
        "filename": filename,
        "Category": category,
        "SubCategory": subcategory,
        "Keywords": keywords,
        "source": source,
        "path": path or f"{source}/{filename}",
        "exists": "True",
    }


def _read(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class RecordingIdTests(unittest.TestCase):
    def test_ids_follow_the_readme(self):
        foley = {"00001.wav": "396055"}
        assert recording_id(_row("Y--PJHxphWEs.wav", "AudioSet"), foley) == "AudioSet:--PJHxphWEs"
        assert recording_id(_row("1-101296-B-19.wav", "ESC-50"), foley) == "ESC-50:101296"
        assert recording_id(_row("10000.wav", "FSD50K"), foley) == "FSD50K:10000"
        assert recording_id(_row("00001.wav", "FoleySet"), foley) == "FoleySet:396055"

    def test_bad_filenames_stop(self):
        with self.assertRaises(SystemExit) as caught:
            recording_id(_row("nope.wav", "AudioSet"), {})
        assert "AudioSet" in str(caught.exception.code)
        with self.assertRaises(SystemExit) as caught:
            recording_id(_row("00001.wav", "FoleySet"), {})
        assert "foleyset_metadata" in str(caught.exception.code)

    def test_keyword_split_keeps_internal_commas(self):
        row = _row("a.wav", "AudioSet", keywords="Speech,Gush")
        assert row_keywords(row) == {("AudioSet", "Speech"), ("AudioSet", "Gush")}
        spaced = _row("b.wav", "AudioSet", keywords="Smoke detector, smoke alarm")
        assert row_keywords(spaced) == {("AudioSet", "Smoke detector, smoke alarm")}


class SampleTests(unittest.TestCase):
    def test_covers_a_rare_keyword_and_keeps_recordings_whole(self):
        groups = {}
        for index in range(20):
            name = f"c{index:02d}.wav"
            groups[f"id-{name}"] = [_row(name, "FSD50K", "MUSICAL", "SONG", "Music")]
        groups["rare"] = [_row("rare.wav", "AudioSet", "ALARMS", "SIREN", "Siren")]
        groups["blank"] = [_row("blank.wav", "ESC-50", "", "", "Quiet")]
        groups["multi"] = [
            _row("m1.wav", "FoleySet", "WATER", "POUR", "Pour"),
            _row("m2.wav", "FoleySet", "WATER", "POUR", "Pour"),
            _row("m3.wav", "FoleySet", "WATER", "POUR", "Pour"),
        ]
        selected = sample_recordings(groups, 4)
        assert selected == sample_recordings(groups, 4)
        chosen = []
        for recording in selected:
            chosen.extend(groups[recording])
        assert len(chosen) <= 4
        keywords = set()
        for row in chosen:
            keywords |= row_keywords(row)
        assert ("AudioSet", "Siren") in keywords
        assert ("ESC-50", "Quiet") in keywords
        multi = [row for row in chosen if row["filename"].startswith("m")]
        assert multi == [] or len(multi) == 3

    def test_does_not_exceed_the_budget_when_only_a_large_recording_remains(self):
        groups = {
            "big": [_row(f"{index}.wav", "FSD50K", "WATER", "", "Splash") for index in range(5)],
        }
        assert sample_recordings(groups, 2) == []

    def test_second_draw_is_a_subset_and_keeps_every_ucs_pair(self):
        groups = {}
        pairs = [("ALARMS", "SIREN"), ("ANIMALS", "DOG"), ("WATER", "FLOW"), ("MUSICAL", "SONG")]
        for category, subcategory in pairs:
            for clip in range(3):
                name = f"{category}-{clip}.wav"
                groups[f"id-{name}"] = [_row(name, "FSD50K", category, subcategory, category)]
        pool = sample_recordings(groups, 8, row_ucs_pair)
        chosen = sample_recordings({recording: groups[recording] for recording in pool}, 4, row_ucs_pair)
        assert set(chosen) <= set(pool)
        assert len(chosen) <= 4
        assert len(pool) <= 8

        def covered(ids):
            found = set()
            for recording in ids:
                for row in groups[recording]:
                    found |= row_ucs_pair(row)
            return found

        assert covered(pool) == set(pairs)
        assert covered(chosen) == set(pairs)


class PileAssignmentTests(unittest.TestCase):
    def test_spreads_a_category_and_puts_a_mixed_recording_with_the_rarer_one(self):
        groups = {}
        for index in range(5):
            groups[f"big-{index}"] = [_row(f"b{index}.wav", "FSD50K", "MUSICAL", "SONG", "Music")]
        groups["small-pure"] = [_row("s.wav", "FSD50K", "BULLETS", "RICOCHET", "Gunshot")]
        groups["mixed"] = [
            _row("m1.wav", "FoleySet", "BULLETS", "RICOCHET", "Gunshot"),
            _row("m2.wav", "FoleySet", "MUSICAL", "SONG", "Music"),
        ]
        groups["blank-0"] = [_row("z0.wav", "FSD50K", "", "", "Quiet")]
        groups["blank-1"] = [_row("z1.wav", "FSD50K", "", "", "Quiet")]
        assigned = assign_piles(groups)
        big_piles = [assigned[f"big-{index}"] for index in range(5)]
        assert big_piles == ["A", "B", "C", "D", "E"]
        assert assigned["mixed"] == "A"
        assert assigned["small-pure"] == "B"
        assert {assigned["blank-0"], assigned["blank-1"]} == {"A", "B"}
        assert train_piles("A") == ("B", "C", "D", "E")
        assert train_piles("B") == ("C", "D", "E", "A")

    def test_promote_replaces_only_when_human_category_is_filled(self):
        kept = promote_row(
            {
                "Category": "WATER",
                "SubCategory": "FLOW",
                "human_category": "",
                "human_subcategory": "POUR",
                "model_prediction_1_category": "WATER",
                "model_prediction_1_subcategory": "POUR",
                "model_confidence_1": "0.9",
            }
        )
        assert kept["Category"] == "WATER" and kept["SubCategory"] == "FLOW"
        assert kept["model_prediction_1_category"] == "" and kept["model_prediction_1_subcategory"] == ""
        assert kept["human_subcategory"] == ""
        replaced = promote_row(
            {
                "Category": "WATER",
                "SubCategory": "FLOW",
                "human_category": "WATER",
                "human_subcategory": "",
                "model_prediction_1_category": "WATER",
                "model_prediction_1_subcategory": "",
            }
        )
        assert replaced["Category"] == "WATER" and replaced["SubCategory"] == ""
        assert not is_blank(replaced)


class ScriptTests(unittest.TestCase):
    def _master(self, root: Path) -> Path:
        rows = []
        for index in range(6):
            rows.append(_row(f"c{index}.wav", "FSD50K", "MUSICAL", "SONG", "Music"))
        rows.append(_row("siren.wav", "FSD50K", "ALARMS", "SIREN", "Siren"))
        rows.append(_row("blank.wav", "FSD50K", "", "", "Quiet"))
        rows.append(_row("Y--PJHxphWEs.wav", "AudioSet", "WATER", "FLOW", "Speech,Gush"))
        rows.append(_row("1-101296-B-19.wav", "ESC-50", "ANIMALS", "DOG", "dog"))
        rows.append(_row("00001.wav", "FoleySet", "FOOTSTEPS", "WALK", "Walk"))
        rows.append(_row("00002.wav", "FoleySet", "FOOTSTEPS", "WALK", "Walk"))
        path = root / "master.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        foley = root / "foley.csv"
        with foley.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["name", "freesound-id"], lineterminator="\n")
            writer.writeheader()
            writer.writerow({"name": "00001.wav", "freesound-id": "396055"})
            writer.writerow({"name": "00002.wav", "freesound-id": "396055"})
        return path

    def test_create_split_and_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            master = self._master(root)
            out = root / "original"
            create_main(
                ["--master", str(master), "--foley", str(root / "foley.csv"), "--out", str(out), "--pool", "10", "--clips", "6"]
            )
            all_rows = _read(out / "all.csv")
            eval_rows = _read(out / "eval.csv")
            assert list(all_rows[0]) == COLUMNS
            assert list(eval_rows[0]) == MASTER_COLUMNS
            assert all(row["pile"] == "" for row in all_rows)
            assert 1 <= len(eval_rows) <= 6
            foley_eval = {row["filename"] for row in eval_rows if row["filename"] in {"00001.wav", "00002.wav"}}
            assert foley_eval in (set(), {"00001.wav", "00002.wav"})
            keywords = set()
            for row in eval_rows:
                keywords |= row_keywords(row)
            assert ("FSD50K", "Siren") in keywords
            assert ("FSD50K", "Quiet") in keywords
            pool_rows = _read(out / "eval-10.csv")
            assert {row["path"] for row in eval_rows} <= {row["path"] for row in pool_rows}
            assert list(pool_rows[0]) == MASTER_COLUMNS

            eval_rows[0]["Category"] = "HAND"
            eval_rows[0]["SubCategory"] = "CHECKED"
            write_csv(out / "eval.csv", eval_rows, MASTER_COLUMNS)
            with self.assertRaises(SystemExit) as caught:
                create_main(
                    [
                        "--master",
                        str(master),
                        "--foley",
                        str(root / "foley.csv"),
                        "--out",
                        str(out),
                        "--pool",
                        "10",
                        "--clips",
                        "6",
                    ]
                )
            assert "labels differ" in str(caught.exception.code)

            round_dir = root / "round-1"
            split_args = [
                "--all",
                str(out / "all.csv"),
                "--eval",
                str(out / "eval.csv"),
                "--pool",
                str(out / "eval-10.csv"),
                "--round",
                str(round_dir),
            ]
            split_main(split_args)
            kept = _read(out / "eval.csv")
            assert kept[0]["Category"] == "HAND"
            assert "human_category" not in kept[0]
            assigned = _read(out / "all.csv")
            assert {row["pile"] for row in assigned} <= {"eval", "sample", "A", "B", "C", "D", "E"}
            assert sum(1 for row in assigned if row["pile"] == "eval") == len(eval_rows)
            pool_only = {row["path"] for row in pool_rows} - {row["path"] for row in eval_rows}
            assert pool_only
            assert {row["pile"] for row in assigned if row["path"] in pool_only} == {"sample"}
            by_recording = {}
            for row in assigned:
                by_recording.setdefault(row["recording"], set()).add(row["pile"])
            assert all(len(piles) == 1 for piles in by_recording.values())

            pile_rows = {pile: _read(round_dir / pile / "pile.csv") for pile in "ABCDE"}
            train_rows = {pile: _read(round_dir / pile / "train.csv") for pile in "ABCDE"}
            assert sum(len(rows) for rows in pile_rows.values()) == len(assigned) - len(pool_rows)
            dealt_paths = {row["path"] for rows in pile_rows.values() for row in rows}
            assert dealt_paths.isdisjoint({row["path"] for row in pool_rows})
            for pile, rows in train_rows.items():
                assert all(row["pile"] not in {pile, "eval", "sample"} for row in rows)
                assert all(not is_blank(row) for row in rows)
                assert all(
                    row["human_category"] == ""
                    and row["model_prediction_1_category"] == ""
                    and row["model_prediction_1_subcategory"] == ""
                    for row in rows
                )
            blank_paths = {row["path"] for row in assigned if is_blank(row) and row["pile"] != "eval"}
            train_paths = {row["path"] for rows in train_rows.values() for row in rows}
            assert blank_paths.isdisjoint(train_paths)

            with self.assertRaises(SystemExit):
                split_main(split_args)

            pile_a = pile_rows["A"]
            if pile_a:
                pile_a[0]["human_category"] = "DOORS"
                pile_a[0]["human_subcategory"] = ""
                pile_a[0]["model_prediction_1_category"] = "MUSICAL"
                pile_a[0]["model_prediction_1_subcategory"] = "SONG"
                pile_a[0]["model_confidence_1"] = "0.8"
                write_csv(round_dir / "A" / "pile.csv", pile_a)
            dest = root / "round-2"
            merge_main(["--src", str(round_dir), "--dst", str(dest)])
            promoted = _read(dest / "A" / "pile.csv")
            if pile_a:
                assert promoted[0]["Category"] == "DOORS"
                assert promoted[0]["SubCategory"] == ""
                assert promoted[0]["human_category"] == ""
                assert promoted[0]["model_prediction_1_category"] == ""
                assert promoted[0]["model_prediction_1_subcategory"] == ""
                assert promoted[0]["pile"] == "A"
            next_train_paths = {row["path"] for row in _read(dest / "B" / "train.csv")}
            if pile_a:
                assert promoted[0]["path"] in next_train_paths
            assert _read(out / "eval.csv")[0]["Category"] == "HAND"
            with self.assertRaises(SystemExit) as caught:
                merge_main(["--src", str(round_dir), "--dst", str(dest)])
            assert "already exists" in str(caught.exception.code)

    def test_force_keeps_labels_already_on_all_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            master = self._master(root)
            out = root / "original"
            create_main(
                ["--master", str(master), "--foley", str(root / "foley.csv"), "--out", str(out), "--pool", "8", "--clips", "4"]
            )
            all_rows = _read(out / "all.csv")
            all_rows[0]["Category"] = "FILLED"
            all_rows[0]["SubCategory"] = "PAIR"
            write_csv(out / "all.csv", all_rows)
            create_main(
                [
                    "--master",
                    str(master),
                    "--foley",
                    str(root / "foley.csv"),
                    "--out",
                    str(out),
                    "--pool",
                    "8",
                    "--clips",
                    "4",
                    "--force",
                ]
            )
            kept = _read(out / "all.csv")
            assert kept[0]["Category"] == "FILLED" and kept[0]["SubCategory"] == "PAIR"
            assert kept[0]["pile"] == ""
            eval_rows = _read(out / "eval.csv")
            pool_rows = _read(out / "eval-8.csv")
            assert {row["path"] for row in eval_rows} <= {row["path"] for row in pool_rows}
            assert len(eval_rows) <= 4
            assert len(pool_rows) <= 8
            pairs = set()
            for row in eval_rows:
                pairs |= row_ucs_pair(row)
            pool_pairs = set()
            for row in pool_rows:
                pool_pairs |= row_ucs_pair(row)
            assert pairs <= pool_pairs


if __name__ == "__main__":
    unittest.main()
