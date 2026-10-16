import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from make_master_manifest import (  # noqa: E402
    COLUMNS,
    fill_ucs,
    load_label_map,
    rows_from_audio,
    ucs_for_keywords,
    write_manifest,
)


class MakeMasterManifestTests(unittest.TestCase):
    def test_rows_come_from_each_datasets_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp)
            (audio / "FSD50K" / "FSD50K.dev_audio").mkdir(parents=True)
            (audio / "FSD50K" / "FSD50K.dev_audio" / "64760.wav").write_bytes(b"")
            write_manifest(
                audio / "AudioSet" / "audios" / "balanced_train_segments.csv",
                ["filename", "human_labels"],
                [{"filename": "Ywaves.wav", "human_labels": "Water tap, faucet;Speech"}],
            )
            write_manifest(
                audio / "AudioSet" / "audios" / "eval_segments.csv",
                ["filename", "human_labels"],
                [],
            )
            write_manifest(
                audio / "ESC-50" / "meta" / "esc50.csv",
                ["filename", "category", "src_file"],
                [{"filename": "1-100032-A-0.wav", "category": "dog", "src_file": "100032"}],
            )
            write_manifest(
                audio / "FSD50K" / "FSD50K.ground_truth" / "dev.csv",
                ["fname", "labels"],
                [{"fname": "64760", "labels": "Bark,Dog"}],
            )
            write_manifest(
                audio / "FSD50K" / "FSD50K.ground_truth" / "eval.csv",
                ["fname", "labels"],
                [{"fname": "100032", "labels": "Chirp"}],
            )
            write_manifest(
                audio / "FoleySet" / "metadata" / "foleyset_metadata.csv",
                ["name", "category", "sub-category", "freesound-id"],
                [
                    {"name": "00002.wav", "category": "Break/Drop", "sub-category": "PaperTear", "freesound-id": "596862"},
                    {"name": "00003.wav", "category": "Human", "sub-category": "Cough", "freesound-id": "100032"},
                ],
            )
            rows, stats = rows_from_audio(audio)

        by_name = {row["filename"]: row for row in rows}
        assert [row["filename"] for row in rows] == ["Ywaves.wav", "1-100032-A-0.wav", "64760.wav", "100032.wav", "00002.wav"]
        assert list(by_name["Ywaves.wav"]) == list(COLUMNS)
        assert by_name["Ywaves.wav"]["Keywords"] == "Water tap, faucet,Speech"
        assert by_name["Ywaves.wav"]["source"] == "AudioSet"
        assert by_name["Ywaves.wav"]["path"] == "AudioSet/audios/balanced_train_segments/Ywaves.wav"
        assert by_name["Ywaves.wav"]["Category"] == "" and by_name["Ywaves.wav"]["exists"] == "False"
        assert by_name["1-100032-A-0.wav"]["Keywords"] == "dog"
        assert by_name["64760.wav"]["Keywords"] == "Bark,Dog"
        assert by_name["64760.wav"]["path"] == "FSD50K/FSD50K.dev_audio/64760.wav"
        assert by_name["64760.wav"]["exists"] == "True"
        assert by_name["100032.wav"]["path"] == "FSD50K/FSD50K.eval_audio/100032.wav"
        assert by_name["00002.wav"]["Keywords"] == "Break/Drop,Paper Tear"
        assert "00003.wav" not in by_name
        assert stats == {"foley_omitted": 1, "missing_wav": 4}

    def test_fill_ucs_uses_the_agreed_label(self) -> None:
        label_map = {
            ("FSD50K", "Bark"): ("primary", "ANIMALS", "DOG"),
            ("FSD50K", "Dog"): ("primary", "ANIMALS", "DOG"),
            ("FSD50K", "Animal"): ("parent", "ANIMALS", ""),
            ("FSD50K", "Music"): ("context", "", ""),
            ("AudioSet", "Waves, surf"): ("primary", "WATER", "SURF"),
            ("FSD50K", "Sneeze"): ("primary", "HUMAN", "SNEEZE"),
            ("FSD50K", "Breathing"): ("primary", "HUMAN", "BREATH"),
            ("FSD50K", "Crackle"): ("primary", "FIRE", "CRACKLE"),
            ("FSD50K", "Wind"): ("primary", "WIND", "GENERAL"),
            ("FSD50K", "Rain"): ("parent", "RAIN", ""),
            ("FSD50K", "Water"): ("parent", "WATER", ""),
            ("FSD50K", "Vehicle"): ("parent", "", ""),
        }
        rows = [
            {"source": "FSD50K", "Keywords": "Bark,Dog,Animal,Music", "Category": "OLD", "SubCategory": "OLD"},
            {"source": "AudioSet", "Keywords": "Waves, surf", "Category": "", "SubCategory": ""},
            {"source": "FSD50K", "Keywords": "Sneeze,Breathing", "Category": "", "SubCategory": ""},
            {"source": "FSD50K", "Keywords": "Crackle,Wind", "Category": "", "SubCategory": ""},
            {"source": "FSD50K", "Keywords": "Rain", "Category": "", "SubCategory": ""},
            {"source": "FSD50K", "Keywords": "Rain,Water", "Category": "", "SubCategory": ""},
            {"source": "FSD50K", "Keywords": "Vehicle", "Category": "", "SubCategory": ""},
            {"source": "FSD50K", "Keywords": "Music", "Category": "", "SubCategory": ""},
        ]
        counts, missing = fill_ucs(rows, label_map)
        assert rows[0]["Category"] == "ANIMALS" and rows[0]["SubCategory"] == "DOG"
        assert rows[1]["Category"] == "WATER" and rows[1]["SubCategory"] == "SURF"
        assert rows[2]["Category"] == "HUMAN" and rows[2]["SubCategory"] == ""
        assert rows[3]["Category"] == "" and rows[3]["SubCategory"] == ""
        assert rows[4]["Category"] == "RAIN" and rows[4]["SubCategory"] == ""
        assert rows[5]["Category"] == "" and rows[5]["SubCategory"] == ""
        assert rows[6]["Category"] == "" and rows[6]["SubCategory"] == ""
        assert rows[7]["Category"] == "" and rows[7]["SubCategory"] == ""
        assert counts == {"assigned": 2, "category": 2, "blank": 4, "unmapped": 0}
        assert missing == []

    def test_fill_ucs_skips_a_keyword_the_map_does_not_list(self) -> None:
        rows = [
            {"source": "ESC-50", "Keywords": "Cough", "Category": "", "SubCategory": ""},
            {"source": "FSD50K", "Keywords": "Bark,Bagpipes", "Category": "", "SubCategory": ""},
        ]
        label_map = {("FSD50K", "Bark"): ("primary", "ANIMALS", "DOG")}
        counts, missing = fill_ucs(rows, label_map)
        assert rows[0]["Category"] == "" and rows[0]["SubCategory"] == ""
        assert rows[1]["Category"] == "ANIMALS" and rows[1]["SubCategory"] == "DOG"
        assert counts["unmapped"] == 2
        assert missing == [("ESC-50", "Cough"), ("FSD50K", "Bagpipes")]

    def test_load_label_map_keeps_a_comma_inside_an_audioset_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "label_map.csv"
            write_manifest(
                path,
                ["source", "label", "role", "category", "subcategory"],
                [
                    {
                        "source": "AudioSet",
                        "label": "Waves, surf",
                        "role": "primary",
                        "category": "WATER",
                        "subcategory": "SURF",
                    }
                ],
            )
            label_map = load_label_map(path)
        assert ucs_for_keywords("AudioSet", "Waves, surf", label_map) == ("WATER", "SURF")

if __name__ == "__main__":
    unittest.main()
