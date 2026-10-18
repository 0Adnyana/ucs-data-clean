import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scoring"))

from score_ucs import (  # noqa: E402
    AudioIndex,
    audioset_keywords,
    foley_clip,
    foley_keywords,
    join_tags,
    predominant_labels,
)


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

    def test_foley_keywords(self) -> None:
        assert foley_keywords("Human", "Cough") == "Human,Cough"
        assert foley_keywords("Break/Drop", "PaperTear") == "Break/Drop,Paper Tear"
        assert foley_keywords("Footstep", "Walk") == "Footstep,Walk"
        clip = foley_clip(
            {
                "category": "Liquid",
                "sub-category": "Pour",
                "original-tags": "glass, pour, rinse",
                "description": "Pouring liquid into the sink",
            }
        )
        assert clip["Keywords"] == "Liquid,Pour"
        assert clip["uploader_tags"] == "glass,pour,rinse"
        assert clip["pp_labels"] == "" and clip["title"] == ""
        assert clip["description"] == "Pouring liquid into the sink"

    def test_index_apply(self) -> None:
        index = AudioIndex({("a.wav", "FSD50K"): {"Keywords": "Bell", "pp_labels": "Bell", "uploader_tags": "bell"}})
        row = {"filename": "a.wav", "source": "FSD50K", "Keywords": "Alarm"}
        assert index.apply(row) == "refreshed"
        assert row["Keywords"] == "Bell" and row["pp_labels"] == "Bell" and row["title"] == ""


if __name__ == "__main__":
    unittest.main()
