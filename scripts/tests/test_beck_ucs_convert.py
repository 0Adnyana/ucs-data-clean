import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from beck_ucs_convert import (  # noqa: E402
    DEFAULT_CONFIG,
    DEFAULT_UCS,
    classify_tag,
    label_keywords,
    load_config,
    load_ucs_lookups,
    resolve,
)


class ResolveTests(unittest.TestCase):
    def test_unanimous_pair_ignores_position(self) -> None:
        paper, blank, decision = resolve(
            [
                {"cat": "ANIMALS", "sub": "DOG", "idx": 0},
                {"cat": "WATER", "sub": None, "idx": 1},
                {"cat": "ANIMALS", "sub": "DOG", "idx": 2},
            ],
            "MISCELLANEOUS",
        )
        self.assertEqual(decision, "assigned")
        self.assertEqual(paper, ("ANIMALS", "DOG"))
        self.assertEqual(blank, paper)

    def test_category_tie_is_empty_and_paper_keeps_the_rightmost_tag(self) -> None:
        paper, blank, decision = resolve(
            [
                {"cat": "WATER", "sub": "POUR", "idx": 0},
                {"cat": "WIND", "sub": "GUST", "idx": 1},
            ],
            "MISCELLANEOUS",
        )
        self.assertEqual(decision, "category_tie")
        self.assertEqual(paper, ("WIND", "GUST"))
        self.assertEqual(blank, ("", None))

    def test_subcategory_tie_keeps_the_category(self) -> None:
        paper, blank, decision = resolve(
            [
                {"cat": "ANIMALS", "sub": "DOG", "idx": 0},
                {"cat": "ANIMALS", "sub": "CAT DOMESTIC", "idx": 1},
            ],
            "MISCELLANEOUS",
        )
        self.assertEqual(decision, "subcategory_tie")
        self.assertEqual(paper, ("ANIMALS", "CAT DOMESTIC"))
        self.assertEqual(blank, ("ANIMALS", None))

    def test_specificity_drops_category_only_tags(self) -> None:
        paper, blank, decision = resolve(
            [
                {"cat": "DOORS", "sub": None, "idx": 0},
                {"cat": "DOORS", "sub": "KNOCK", "idx": 1},
                {"cat": "FOLEY", "sub": None, "idx": 2},
            ],
            "MISCELLANEOUS",
        )
        self.assertEqual(decision, "assigned")
        self.assertEqual(blank, ("DOORS", "KNOCK"))
        self.assertEqual(paper, blank)

    def test_no_mapped_tag_stays_miscellaneous(self) -> None:
        paper, blank, decision = resolve([], "MISCELLANEOUS")
        self.assertEqual(decision, "unmapped")
        self.assertEqual(paper, ("MISCELLANEOUS", None))
        self.assertEqual(blank, paper)


class CascadeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        config = load_config(DEFAULT_CONFIG)
        cls.lookups = load_ucs_lookups(config, DEFAULT_UCS)
        cls.default = config["defaults"]["default_category"]

    def test_synonym_tie_keeps_the_earlier_category(self) -> None:
        subcat_to_cat, valid_categories, manual_map, synonym_map = self.lookups
        category, subcategory = classify_tag(
            "Goat", subcat_to_cat, valid_categories, manual_map, self.default, synonym_map
        )
        # AMBIENCE-FARM and ANIMALS-FARM both list Goat once. Equal counts keep the earlier category.
        self.assertEqual((category, subcategory), ("AMBIENCE", "FARM"))

    def test_published_goat_row_follows_the_synonym_and_specificity(self) -> None:
        paper, blank, decision = label_keywords(
            "Goat,Domestic animals, pets,Livestock, farm animals, working animals,Animal",
            self.lookups,
            self.default,
            ",",
        )
        self.assertEqual(decision, "assigned")
        self.assertEqual(paper, ("AMBIENCE", "FARM"))
        self.assertEqual(blank, paper)

    def test_wind_is_the_manual_category_with_no_subcategory(self) -> None:
        paper, blank, decision = label_keywords("Wind", self.lookups, self.default, ",")
        self.assertEqual(decision, "assigned")
        self.assertEqual(paper, ("WIND", None))
        self.assertEqual(blank, paper)


if __name__ == "__main__":
    unittest.main()
