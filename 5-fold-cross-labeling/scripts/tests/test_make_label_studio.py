import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from make_label_studio import (  # noqa: E402
    DEFAULT_UCS,
    eval_fields,
    labeling_config,
    load_taxonomy,
    subcategory_hint,
)


def _write_ucs(directory: Path) -> Path:
    path = directory / "ucs.csv"
    path.write_text(
        "preamble\n"
        "note\n"
        "Category,SubCategory,Explanations,Synonyms - Comma Separated\n"
        'DIRT & SAND,DUST,"Fine dust.","Grit, Silt"\n'
        "AIR,BLOW,Steady air blows.,\n"
        "AIR,BLOW,duplicate ignored,\n",
        encoding="utf-8",
    )
    return path


class LabelStudioConfigTests(unittest.TestCase):
    def test_hint_joins_explanation_and_synonyms(self):
        assert subcategory_hint("Fine dust.", "Grit, Silt") == "Fine dust.  Synonyms: Grit, Silt"
        assert subcategory_hint("Steady air blows.", "") == "Steady air blows."
        assert subcategory_hint("", "Grit") == "Synonyms: Grit"

    def test_eval_hides_category_only_until_ambiguous(self):
        with tempfile.TemporaryDirectory() as tmp:
            categories = load_taxonomy(_write_ucs(Path(tmp)))
        assert list(categories) == ["DIRT & SAND", "AIR"]
        assert [leaf.name for leaf in categories["AIR"]] == ["BLOW"]
        assert categories["DIRT & SAND"][0].hint == "Fine dust.  Synonyms: Grit, Silt"

        config = labeling_config(categories, "eval")
        root = ET.fromstring(config)
        assert 'visibleWhen="choice-unselected"' in config
        assert 'whenChoiceValue="ambiguous"' in config
        assert 'hint="Fine dust.  Synonyms: Grit, Silt"' in config
        assert 'value="DIRT &amp; SAND"' in config
        ucs = root.find(".//*[@name='ucs']")
        category_only = root.find(".//*[@name='category_only']")
        assert ucs.attrib["leafsOnly"] == "true"
        assert "Category only" not in [choice.attrib["value"] for choice in ucs.iter("Choice")]
        assert [choice.attrib["value"] for choice in category_only] == ["DIRT & SAND", "AIR"]

        pile = labeling_config(categories, "pile")
        pile_root = ET.fromstring(pile)
        assert "$model_prediction_5_subcategory" in pile
        assert "$pile" in pile
        assert "verdict" not in pile
        assert "Keep" not in pile
        pile_ucs = pile_root.find(".//*[@name='ucs']")
        pile_category_only = pile_root.find(".//*[@name='category_only']")
        assert pile_ucs.attrib["leafsOnly"] == "true"
        assert 'hint="Fine dust.  Synonyms: Grit, Silt"' in pile
        assert [choice.attrib["value"] for choice in pile_category_only] == ["DIRT & SAND", "AIR"]

    def test_real_ucs_list_is_well_formed(self):
        categories = load_taxonomy(DEFAULT_UCS)
        config = labeling_config(categories, "eval")
        root = ET.fromstring(config)
        names = [node.attrib["name"] for node in root.iter() if "name" in node.attrib]
        assert names.count("ucs") == 1
        assert names.count("category_only") == 1
        clear = root.find(".//*[@name='ucs']")
        ambiguous = root.find(".//*[@name='category_only']")
        assert clear.attrib["leafsOnly"] == "true"
        assert len(list(clear)) == len(categories)
        assert len(list(ambiguous)) == len(categories)
        assert all(len(list(choice)) == 0 for choice in ambiguous)

        pile = labeling_config(categories, "pile")
        pile_root = ET.fromstring(pile)
        assert pile_root.find(".//*[@name='ucs']").attrib["leafsOnly"] == "true"
        assert "model_confidence_1" in pile
        assert "verdict" not in pile


if __name__ == "__main__":
    unittest.main()
