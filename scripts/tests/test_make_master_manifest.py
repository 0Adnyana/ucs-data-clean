import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from make_master_manifest import COLUMNS, master_rows, write_manifest  # noqa: E402


class MakeMasterManifestTests(unittest.TestCase):
    def test_concatenates_splits_without_a_split_column(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp)
            write_manifest(
                src / "envsound_train.csv",
                list(COLUMNS) + ["pp_labels"],
                [
                    {
                        "filename": "a.wav",
                        "Category": "ANIMALS",
                        "SubCategory": "DOG",
                        "Keywords": "Bark,Dog",
                        "source": "FSD50K",
                        "path": "FSD50K/FSD50K.dev_audio/a.wav",
                        "exists": "True",
                        "pp_labels": "Bark",
                    }
                ],
            )
            write_manifest(
                src / "envsound_val.csv",
                list(COLUMNS),
                [
                    {
                        "filename": "b.wav",
                        "Category": "WATER",
                        "SubCategory": "",
                        "Keywords": "Waves, surf",
                        "source": "AudioSet",
                        "path": "AudioSet/audios/eval_segments/b.wav",
                        "exists": "False",
                    }
                ],
            )
            write_manifest(
                src / "envsound_test.csv",
                list(COLUMNS),
                [
                    {
                        "filename": "c.wav",
                        "Category": "HUMAN",
                        "SubCategory": "COUGH",
                        "Keywords": "Cough",
                        "source": "ESC-50",
                        "path": "ESC-50/audio/c.wav",
                        "exists": "True",
                    }
                ],
            )
            rows = master_rows(src)

        assert [row["filename"] for row in rows] == ["a.wav", "b.wav", "c.wav"]
        assert list(rows[0]) == list(COLUMNS)
        assert "pp_labels" not in rows[0]
        assert rows[0]["Category"] == "" and rows[0]["SubCategory"] == ""
        assert rows[2]["Category"] == "" and rows[2]["SubCategory"] == ""
        assert rows[0]["Keywords"] == "Bark,Dog"
        assert rows[1]["Keywords"] == "Waves, surf"


if __name__ == "__main__":
    unittest.main()
