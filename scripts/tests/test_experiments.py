import argparse
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scoring"))

from score_ucs import (  # noqa: E402
    DEFAULT_WRITE_SPLITS,
    ROOT,
    SPLIT_NAMES,
    Prediction,
    allowlist_for,
    apply_cli,
    assert_outside_manifests,
    copy_manual_manifests,
    default_config,
    labeled_rows,
    manual_splits_to_copy,
    parse_experiment,
    parse_split_list,
    restrict_records,
)


def _cli(**overrides: object) -> argparse.Namespace:
    base: dict[str, object] = {"write_splits": None}
    base.update(overrides)
    return argparse.Namespace(**base)


class ExperimentTests(unittest.TestCase):
    def assert_exits(self, call, text: str) -> None:
        with self.assertRaises(SystemExit) as caught:
            call()
        self.assertIn(text, str(caught.exception.code))

    def test_splits(self) -> None:
        assert DEFAULT_WRITE_SPLITS == ("test",)
        assert "train" not in DEFAULT_WRITE_SPLITS and "val" not in DEFAULT_WRITE_SPLITS
        assert parse_split_list("val,train") == ("train", "val")
        self.assert_exits(lambda: parse_split_list("holdout"), "unknown split")

    def test_parse_experiment(self) -> None:
        builtin = default_config()
        assert builtin.name == "default"
        assert builtin.splits == ("test",)
        assert builtin.taxonomy == "closed"
        assert default_config() is builtin
        plain = parse_experiment({"name": "plain"})
        assert plain.splits == builtin.splits
        assert plain.taxonomy == builtin.taxonomy
        assert plain.weights == builtin.weights
        closed = parse_experiment(
            {
                "name": "closed-strict",
                "taxonomy": "closed",
                "splits": ["val", "test"],
                "min_score": 4,
                "weights": {"exact_sub": 9, "word": 0.5},
                "on_tie": "blank",
            }
        )
        assert closed.splits == ("val", "test")
        assert closed.weights.exact_sub == 9 and closed.weights.word == 0.5
        assert closed.weights.pp_bonus == builtin.weights.pp_bonus
        assert closed.closed == builtin.closed
        assert ("ALARMS", "BELL") in builtin.closed and ("DOORS", "DOORBELL") in builtin.closed
        assert len(builtin.closed) == 21
        assert closed.min_score == 4
        self.assert_exits(
            lambda: parse_experiment({"name": "bad", "splits": ["train", "holdout"]}), "unknown split"
        )
        self.assert_exits(lambda: parse_experiment({"name": "bad", "mystery": 1}), "unknown settings")

    def test_apply_cli(self) -> None:
        plain = parse_experiment({"name": "plain"})
        overridden = apply_cli(plain, _cli(write_splits="train,val,test"))
        assert overridden.splits == SPLIT_NAMES
        assert overridden.weights == plain.weights and overridden.min_score == plain.min_score

    def test_taxonomy_restriction(self) -> None:
        records = [
            ("ANIMALS", "DOG", "a dog", "dog,puppy"),
            ("BELLS", "DOORBELL", "a doorbell", "doorbell"),
        ]
        categories = parse_experiment(
            {"name": "animals", "taxonomy": {"mode": "categories", "categories": ["animals"]}}
        )
        assert allowlist_for(categories, records) == {("ANIMALS", "DOG")}
        pairs = parse_experiment({"name": "dog", "taxonomy": {"mode": "pairs", "pairs": ["ANIMALS/DOG"]}})
        chosen, resolved, missing = restrict_records(records, allowlist_for(pairs, records))
        assert chosen == [records[0]] and resolved == {("ANIMALS", "DOG")} and missing == []
        kept, kept_pairs, skipped = restrict_records(
            records, {("ANIMALS", "DOG"), ("NOPE", "MISSING")}, on_missing="skip"
        )
        assert kept == [records[0]] and kept_pairs == {("ANIMALS", "DOG")} and skipped == [("NOPE", "MISSING")]
        self.assert_exits(lambda: restrict_records(records, {("NOPE", "MISSING")}), "not in the UCS list")

    def test_labeled_rows_copy(self) -> None:
        row = {"Category": "ANIMALS", "SubCategory": "DOG", "Keywords": "dog"}
        prediction = Prediction(category="ALARMS", subcategory="BELL", status="assigned", score=3)
        [labeled] = labeled_rows([row], [prediction])
        assert (labeled["Category"], labeled["SubCategory"]) == ("ALARMS", "BELL")
        assert row["SubCategory"] == "DOG"

    def test_output_outside_manifests(self) -> None:
        slice_dir = ROOT / "manifests" / "slice"
        self.assert_exits(lambda: assert_outside_manifests(slice_dir, slice_dir), "slice")
        self.assert_exits(lambda: assert_outside_manifests(slice_dir / "nested", slice_dir), "slice")
        assert_outside_manifests(ROOT / "scoring" / "experiments" / "demo", slice_dir)

    def test_copy_manual_manifests(self) -> None:
        assert manual_splits_to_copy(("test",)) == ("train", "val")
        assert manual_splits_to_copy(("val", "test")) == ("train",)
        assert manual_splits_to_copy(SPLIT_NAMES) == ()
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp)
            source = root / "manual"
            source.mkdir()
            (source / "envsound_train.csv").write_text("filename\na.wav\n", encoding="utf-8")
            (source / "envsound_val.csv").write_text("filename\nb.wav\n", encoding="utf-8")
            out = root / "experiments" / "demo"
            copied = copy_manual_manifests(out, source, ("train", "val"))
            assert [path.name for path in copied] == ["envsound_train.csv", "envsound_val.csv"]
            assert (out / "envsound_train.csv").read_text(encoding="utf-8") == "filename\na.wav\n"
            assert copy_manual_manifests(out, source, ()) == []
            self.assert_exits(lambda: copy_manual_manifests(out, source, ("test",)), "missing")


if __name__ == "__main__":
    unittest.main()
