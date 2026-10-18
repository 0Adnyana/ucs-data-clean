import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "mapping"))

from make_label_map_base import Hierarchy, role_for_label, unique_label_rows  # noqa: E402
from make_master_manifest import rows_from_audio, write_manifest  # noqa: E402


class MakeLabelMapBaseTests(unittest.TestCase):
    def test_unique_labels_follow_the_master_keywords(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp)
            (audio / "FSD50K" / "FSD50K.dev_audio").mkdir(parents=True)
            write_manifest(
                audio / "AudioSet" / "audios" / "balanced_train_segments.csv",
                ["filename", "human_labels"],
                [
                    {"filename": "Ywaves.wav", "human_labels": "Waves, surf;Speech"},
                    {"filename": "Yagain.wav", "human_labels": "Speech"},
                ],
            )
            write_manifest(
                audio / "AudioSet" / "audios" / "eval_segments.csv",
                ["filename", "human_labels"],
                [],
            )
            write_manifest(
                audio / "ESC-50" / "meta" / "esc50.csv",
                ["filename", "category", "src_file"],
                [{"filename": "1-200000-A-0.wav", "category": "dog", "src_file": "200000"}],
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
            audio_rows, _stats = rows_from_audio(audio)

        label_map = {
            ("AudioSet", "Waves, surf"): ("primary", "WATER", "SURF"),
            ("FSD50K", "Bark"): ("primary", "ANIMALS", "DOG"),
        }
        rows = unique_label_rows(audio_rows, label_map)
        assert [(row["source"], row["label"]) for row in rows] == [
            ("AudioSet", "Speech"),
            ("AudioSet", "Waves, surf"),
            ("ESC-50", "dog"),
            ("FSD50K", "Bark"),
            ("FSD50K", "Chirp"),
            ("FSD50K", "Dog"),
            ("FoleySet", "Break/Drop"),
            ("FoleySet", "Paper Tear"),
        ]
        by_key = {(row["source"], row["label"]): row for row in rows}
        assert by_key[("AudioSet", "Waves, surf")]["role"] == "primary"
        assert by_key[("AudioSet", "Waves, surf")]["category"] == "WATER"
        assert by_key[("AudioSet", "Waves, surf")]["subcategory"] == "SURF"
        assert by_key[("FSD50K", "Bark")]["role"] == "primary"
        assert by_key[("FSD50K", "Bark")]["subcategory"] == "DOG"
        assert by_key[("FSD50K", "Dog")]["role"] == "parent"
        assert by_key[("AudioSet", "Speech")]["role"] == "context"
        assert by_key[("AudioSet", "Speech")]["category"] == ""
        assert by_key[("FoleySet", "Break/Drop")]["role"] == "group"
        assert by_key[("FoleySet", "Paper Tear")]["role"] == "primary"
        assert by_key[("FoleySet", "Paper Tear")]["subcategory"] == ""
        assert by_key[("ESC-50", "dog")]["role"] == "primary"
        assert ("FoleySet", "Cough") not in by_key

    def test_role_follows_the_source_structure(self) -> None:
        hierarchy = Hierarchy(
            [
                {"id": "music", "name": "Music", "child_ids": ["genre", "vocal"]},
                {"id": "genre", "name": "Music genre", "child_ids": ["afro", "vocal", "classical"]},
                {"id": "afro", "name": "Afrobeat", "child_ids": []},
                {"id": "vocal", "name": "Vocal music", "child_ids": ["capella"]},
                {"id": "capella", "name": "A capella", "child_ids": []},
                {"id": "classical", "name": "Classical music", "child_ids": ["opera"]},
                {"id": "opera", "name": "Opera", "child_ids": []},
                {"id": "human", "name": "Human sounds", "child_ids": ["voice", "crowd"]},
                {"id": "voice", "name": "Human voice", "child_ids": ["speech"]},
                {"id": "speech", "name": "Speech", "child_ids": ["babble"]},
                {"id": "babble", "name": "Babbling", "child_ids": []},
                {"id": "noise", "name": "Noise", "child_ids": ["hum"]},
                {"id": "hum", "name": "Mains hum", "child_ids": []},
                {"id": "crowd", "name": "Human group actions", "child_ids": ["hubbub"]},
                {"id": "hubbub", "name": "Hubbub, speech noise, speech babble", "child_ids": []},
                {"id": "things", "name": "Sounds of things", "child_ids": ["dog"]},
                {"id": "animal", "name": "Animal", "child_ids": ["dog"]},
                {"id": "dog", "name": "Dog", "child_ids": ["bark"]},
                {"id": "bark", "name": "Bark", "child_ids": []},
            ]
        )
        # Hubbub's other parent is Noise. The Human sounds link keeps it a sound.
        hierarchy.parents["hubbub"].append("noise")
        groups = {"Liquid"}
        cases = [
            ("AudioSet", "Music", "context"),
            ("AudioSet", "Afrobeat", "context"),
            ("AudioSet", "Vocal music", "context"),
            ("AudioSet", "A capella", "primary"),
            ("AudioSet", "Opera", "context"),
            ("AudioSet", "Speech", "context"),
            ("AudioSet", "Babbling", "primary"),
            ("AudioSet", "Mains hum", "context"),
            ("AudioSet", "Hubbub, speech noise, speech babble", "primary"),
            ("AudioSet", "Dog", "parent"),
            ("AudioSet", "Bark", "primary"),
            ("FSD50K", "Electric_guitar", "primary"),
            ("ESC-50", "dog", "primary"),
            ("FoleySet", "Liquid", "group"),
            ("FoleySet", "Pour", "primary"),
        ]
        # Electric guitar is not in this tiny graph, so an unknown class stays primary.
        for source, label, role in cases:
            assert role_for_label(source, label, groups, hierarchy) == role, (source, label)


if __name__ == "__main__":
    unittest.main()
