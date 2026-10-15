import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from score_ucs import (  # noqa: E402
    MANIFEST_COLUMNS,
    ROOT,
    AudioIndex,
    audioset_keywords,
    join_tags,
    predominant_labels,
    rows_from_audio,
    select_manifest_rows,
)

FULL = [
    {
        "filename": "a.wav",
        "Category": "ANIMALS",
        "SubCategory": "DOG",
        "Keywords": "Dog",
        "source": "ESC-50",
        "path": "ESC-50/a.wav",
        "exists": "True",
        "uploader_tags": "dog",
    },
    {
        "filename": "b.wav",
        "Category": "HUMAN",
        "SubCategory": "",
        "Keywords": "Cough",
        "source": "ESC-50",
        "path": "ESC-50/b.wav",
        "exists": "True",
        "uploader_tags": "",
    },
    {
        "filename": "c.wav",
        "Category": "WATER",
        "SubCategory": "POUR",
        "Keywords": "Pour",
        "source": "AudioSet",
        "path": "AudioSet/c.wav",
        "exists": "True",
        "uploader_tags": "",
    },
]
FIELDS = list(FULL[0])
SPLIT = [
    {"filename": "b.wav", "source": "ESC-50", "path": "ESC-50/b.wav"},
    {"filename": "a.wav", "source": "ESC-50", "path": "ESC-50/a.wav"},
]


class ManifestJoinTests(unittest.TestCase):
    def test_split_order_and_columns(self) -> None:
        out_fields, rows = select_manifest_rows(SPLIT, FULL, FIELDS)
        assert out_fields[: len(MANIFEST_COLUMNS)] == MANIFEST_COLUMNS, out_fields
        assert out_fields[-1] == "uploader_tags"
        assert [row["filename"] for row in rows] == ["b.wav", "a.wav"]
        assert rows[0]["Keywords"] == "Cough" and rows[0]["SubCategory"] == ""
        assert rows[1]["uploader_tags"] == "dog"

    def test_missing_split_row(self) -> None:
        missing = [{"filename": "missing.wav", "source": "ESC-50", "path": "ESC-50/missing.wav"}]
        with self.assertRaisesRegex(ValueError, "not in the full manifest"):
            select_manifest_rows(missing, FULL, FIELDS)

    def test_duplicate_source_row(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate"):
            select_manifest_rows(SPLIT, FULL + [dict(FULL[0])], FIELDS)


class AudioHelperTests(unittest.TestCase):
    def test_label_formatting(self) -> None:
        assert audioset_keywords("Speech;Fire alarm") == "Speech,Fire alarm"
        assert audioset_keywords("Water tap, faucet;Speech") == "Water tap, faucet,Speech"
        assert join_tags(["air", "alarm", "door, bell"]) == "air,alarm,door  bell"
        labels = predominant_labels(
            {"/m/bell": [1.0, 1.0, -1], "/m/oven": [0.5, 0.5], "/m/alarm": [1.0]},
            {"/m/bell": "Bell", "/m/oven": "Microwave_oven", "/m/alarm": "Alarm"},
            ["Microwave_oven", "Bell", "Alarm"],
        )
        assert labels == "Bell,Alarm", labels

    def test_index_apply(self) -> None:
        index = AudioIndex({("a.wav", "FSD50K"): {"Keywords": "Bell", "pp_labels": "Bell", "uploader_tags": "bell"}})
        row = {"filename": "a.wav", "source": "FSD50K", "Keywords": "Alarm"}
        assert index.apply(row) == "refreshed"
        assert row["Keywords"] == "Bell" and row["pp_labels"] == "Bell" and row["title"] == ""

    def test_rows_from_audio(self) -> None:
        index = AudioIndex(
            {
                ("a.wav", "ESC-50"): {
                    "Keywords": "dog",
                    "pp_labels": "",
                    "uploader_tags": "",
                    "title": "",
                    "description": "",
                }
            }
        )
        prior = [
            {
                "filename": "a.wav",
                "Category": "ANIMALS",
                "SubCategory": "DOG",
                "Keywords": "Dog",
                "source": "ESC-50",
                "path": "old/a.wav",
                "exists": "False",
            }
        ]
        split = [{"filename": "a.wav", "source": "ESC-50", "path": "ESC-50/audio/a.wav"}]
        fields, rows = rows_from_audio(split, prior, index, ROOT / "audio")
        assert rows[0]["path"] == "ESC-50/audio/a.wav"
        assert (rows[0]["Category"], rows[0]["SubCategory"]) == ("ANIMALS", "DOG")
        assert rows[0]["Keywords"] == "dog"
        assert "pp_labels" in fields
        _fields, blank = rows_from_audio(split, [], index, ROOT / "audio")
        assert blank[0]["Category"] == "" and blank[0]["SubCategory"] == ""


if __name__ == "__main__":
    unittest.main()
