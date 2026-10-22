import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_candidates import load_tables  # noqa: E402
from candidates import (  # noqa: E402
    allocate,
    bucket_flags,
    candidate_records,
    class_thresholds,
    decide_flag,
    draw_sample,
    parse_candidate_tags,
    split_stored_pairs,
    tag_mappings,
)
from make_master_manifest import split_labels  # noqa: E402


def _row(source, filename, keywords, category, subcategory):
    return {
        "source": source,
        "filename": filename,
        "Keywords": keywords,
        "Category": category,
        "SubCategory": subcategory,
    }


def _prediction(category, subcategory, ranks):
    row = {
        "source": "AudioSet",
        "filename": "clip.wav",
        "Keywords": "",
        "Category": category,
        "SubCategory": subcategory,
    }
    for index, (predicted_category, predicted_subcategory, confidence) in enumerate(ranks, start=1):
        row[f"model_prediction_{index}_category"] = predicted_category
        row[f"model_prediction_{index}_subcategory"] = predicted_subcategory
        row[f"model_confidence_{index}"] = str(confidence)
    return row


class BucketTests(unittest.TestCase):
    def test_rain_and_bird_suggestion_is_supported_by_rain(self) -> None:
        tags = [("Rain", "RAIN||GENERAL"), ("Bird", "BIRDS||SONGBIRD")]
        result = bucket_flags(tags, "RAIN||GENERAL")
        self.assertEqual(result["bucket_all"], "tag_supported")
        self.assertEqual(result["bucket_strict"], "tag_supported")
        self.assertEqual(result["support_level"], "exact")
        self.assertEqual(result["supporting_tags"], "Rain")

    def test_zipper_and_tap_suggestion_is_supported(self) -> None:
        tags = [("Zipper", "OBJECTS||ZIPPER"), ("Tap", "MECHANICAL||CLICK")]
        result = bucket_flags(tags, "OBJECTS||ZIPPER")
        self.assertEqual(result["bucket_all"], "tag_supported")
        self.assertEqual(result["supporting_tags"], "Zipper")

    def test_music_beside_another_candidate_is_not_strict_support(self) -> None:
        tags = [("Bird", "BIRDS||SONGBIRD"), ("Music", "MUSICAL||X")]
        result = bucket_flags(tags, "MUSICAL||X")
        self.assertEqual(result["bucket_all"], "tag_supported")
        self.assertEqual(result["bucket_strict"], "unsupported")
        self.assertEqual(result["supporting_tags"], "Music")

    def test_music_alone_still_counts_as_strict_support(self) -> None:
        result = bucket_flags([("Music", "MUSICAL||X")], "MUSICAL||X")
        self.assertEqual(result["bucket_strict"], "tag_supported")

    def test_category_only_water_supports_a_pour_suggestion(self) -> None:
        result = bucket_flags([("Water", "WATER||*")], "WATER||POUR")
        self.assertEqual(result["bucket_all"], "tag_supported")
        self.assertEqual(result["bucket_strict"], "tag_supported")
        self.assertEqual(result["support_level"], "category")
        self.assertEqual(result["supporting_tags"], "Water")

    def test_stored_pairs_keep_the_double_bar(self) -> None:
        self.assertEqual(
            split_stored_pairs("WATER||*|RAIN||GENERAL"),
            ["WATER||*", "RAIN||GENERAL"],
        )


class LabelMapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tables = load_tables()

    def test_domestic_animals_pets_stays_one_tag(self) -> None:
        keywords = "Domestic animals, pets,Dog"
        self.assertEqual(split_labels(keywords), ["Domestic animals, pets", "Dog"])
        mappings = tag_mappings("AudioSet", keywords, self.tables.effective, self.tables.parent_subs)
        tags = [tag for tag, _category, _subcategory in mappings]
        self.assertIn("Domestic animals, pets", tags)
        self.assertNotIn("pets", tags)

    def test_rain_maps_to_general_and_supports_that_suggestion(self) -> None:
        row = _row(
            "AudioSet",
            "rain.wav",
            "Rain,Bird vocalization, bird call, bird song",
            "BIRDS",
            "SONGBIRD",
        )
        record = candidate_records([row], self.tables.effective, self.tables.parent_subs)[0]
        self.assertIn("Rain>RAIN||GENERAL", record["candidates"])
        result = bucket_flags(parse_candidate_tags(record["candidates"]), "RAIN||GENERAL")
        self.assertEqual(result["bucket_all"], "tag_supported")
        self.assertEqual(result["supporting_tags"], "Rain")

    def test_zipper_and_tap_use_the_label_map(self) -> None:
        row = _row("AudioSet", "zip.wav", "Zipper (clothing),Tap", "MECHANICAL", "CLICK")
        record = candidate_records([row], self.tables.effective, self.tables.parent_subs)[0]
        result = bucket_flags(parse_candidate_tags(record["candidates"]), "OBJECTS||ZIPPER")
        self.assertEqual(result["bucket_all"], "tag_supported")
        self.assertEqual(result["supporting_tags"], "Zipper (clothing)")
        self.assertEqual(record["given_pair_in_candidates"], "True")

    def test_same_filename_in_two_sources_is_two_rows(self) -> None:
        effective = {
            ("FSD50K", "Dog"): ("primary", "ANIMALS", "DOG"),
            ("FoleySet", "Bark"): ("primary", "ANIMALS", "DOG"),
        }
        rows = [
            _row("FoleySet", "10000.wav", "Bark", "ANIMALS", "DOG"),
            _row("FSD50K", "10000.wav", "Dog", "ANIMALS", "DOG"),
        ]
        records = candidate_records(rows, effective, {})
        self.assertEqual(
            [(record["source"], record["filename"], record["candidates"]) for record in records],
            [
                ("FSD50K", "10000.wav", "Dog>ANIMALS||DOG"),
                ("FoleySet", "10000.wav", "Bark>ANIMALS||DOG"),
            ],
        )


class FlagTests(unittest.TestCase):
    def test_suggestion_above_its_threshold_is_flagged(self) -> None:
        rain = _prediction(
            "RAIN",
            "GENERAL",
            [("RAIN", "GENERAL", 0.50), ("BIRDS", "SONGBIRD", 0.20), ("WATER", "POUR", 0.10), ("WIND", "GUST", 0.05), ("MISC", "MISC", 0.01)],
        )
        birds = _prediction(
            "BIRDS",
            "SONGBIRD",
            [("RAIN", "GENERAL", 0.70), ("BIRDS", "SONGBIRD", 0.20), ("WATER", "POUR", 0.05), ("WIND", "GUST", 0.03), ("MISC", "MISC", 0.01)],
        )
        birds["filename"] = "birds.wav"
        thresholds = class_thresholds([rain, birds])
        self.assertIsNone(decide_flag(rain, thresholds))
        flagged = decide_flag(birds, thresholds)
        self.assertIsNotNone(flagged)
        assert flagged is not None
        self.assertEqual(flagged["suggested"], "RAIN||GENERAL")
        self.assertEqual(flagged["flag_type"], "cross_category")
        self.assertEqual(flagged["margin"], "0.500000")

    def test_rank_five_bounds_a_missing_given_label(self) -> None:
        cat = _prediction(
            "ANIMALS",
            "CAT",
            [("ANIMALS", "CAT", 0.10), ("ANIMALS", "DOG", 0.05), ("WATER", "POUR", 0.04), ("WIND", "GUST", 0.03), ("MISC", "MISC", 0.01)],
        )
        dog = _prediction(
            "ANIMALS",
            "DOG",
            [("ANIMALS", "CAT", 0.40), ("WATER", "POUR", 0.20), ("WIND", "GUST", 0.10), ("BIRDS", "SONGBIRD", 0.08), ("MISC", "MISC", 0.05)],
        )
        dog["filename"] = "dog.wav"
        thresholds = class_thresholds([cat, dog])
        flagged = decide_flag(dog, thresholds)
        self.assertIsNotNone(flagged)
        assert flagged is not None
        self.assertEqual(flagged["suggested"], "ANIMALS||CAT")
        self.assertEqual(flagged["flag_type"], "within_category")
        self.assertEqual(flagged["margin"], "0.350000")

    def test_misc_suggestion_in_the_same_category_is_its_own_flag_type(self) -> None:
        specific = _prediction(
            "VOICES",
            "MISC",
            [("VOICES", "MISC", 0.20), ("VOICES", "SINGING", 0.10), ("WATER", "POUR", 0.05), ("WIND", "GUST", 0.04), ("MISC", "MISC", 0.01)],
        )
        singing = _prediction(
            "VOICES",
            "SINGING",
            [("VOICES", "MISC", 0.80), ("VOICES", "SINGING", 0.10), ("WATER", "POUR", 0.04), ("WIND", "GUST", 0.03), ("MISC", "MISC", 0.01)],
        )
        singing["filename"] = "sing.wav"
        thresholds = class_thresholds([specific, singing])
        flagged = decide_flag(singing, thresholds)
        self.assertIsNotNone(flagged)
        assert flagged is not None
        self.assertEqual(flagged["flag_type"], "within_category_misc")

    def test_sample_is_stratified_and_repeatable(self) -> None:
        rows = []
        for flag_type in ("cross_category", "within_category", "within_category_misc"):
            for index in range(10):
                rows.append(
                    {
                        "source": "AudioSet",
                        "filename": f"{flag_type}-{index:02d}.wav",
                        "bucket_strict": "tag_supported",
                        "flag_type": flag_type,
                        "margin": "0.200000",
                    }
                )
        quota = allocate({(row["bucket_strict"], row["flag_type"]): 10 for row in rows[:3]}, 10, 2)
        self.assertEqual(sum(quota.values()), 10)
        first = draw_sample(rows, total=10, minimum=2, seed=0)
        second = draw_sample(rows, total=10, minimum=2, seed=0)
        self.assertEqual(
            [(row["flag_type"], row["filename"]) for row in first],
            [(row["flag_type"], row["filename"]) for row in second],
        )
        self.assertEqual(len(first), 10)
        counts = {}
        for row in first:
            counts[row["flag_type"]] = counts.get(row["flag_type"], 0) + 1
        self.assertTrue(all(count >= 2 for count in counts.values()))


if __name__ == "__main__":
    unittest.main()
