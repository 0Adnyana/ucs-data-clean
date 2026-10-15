import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from score_ucs import (  # noqa: E402
    DEFAULT_ONTOLOGY,
    DEFAULT_UCS,
    build_catalog,
    catalog_for,
    default_config,
    load_ontology,
    load_ucs,
    recover_category,
    score_text,
    split_labels,
)


class SplitLabelTests(unittest.TestCase):
    def test_split_labels(self) -> None:
        assert split_labels("Smoke detector, smoke alarm,Fire alarm") == [
            "Smoke detector, smoke alarm",
            "Fire alarm",
        ]
        assert split_labels("Waves, surf,Wind,Ocean") == ["Waves, surf", "Wind", "Ocean"]
        assert split_labels("Bark,Dog,Domestic_animals_and_pets,Animal") == [
            "Bark",
            "Dog",
            "Domestic_animals_and_pets",
            "Animal",
        ]
        assert split_labels("clock_alarm") == ["clock_alarm"]


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not DEFAULT_UCS.is_file():
            raise unittest.SkipTest(f"UCS list not found: {DEFAULT_UCS}")
        if not DEFAULT_ONTOLOGY.is_file():
            raise unittest.SkipTest(f"AudioSet ontology not found: {DEFAULT_ONTOLOGY}")
        depths, alias = load_ontology(DEFAULT_ONTOLOGY)
        cls.records = load_ucs(DEFAULT_UCS, None)
        cls.catalog = build_catalog(cls.records, depths, alias)
        cls.weights = default_config().weights

    def test_depth_and_bonus(self) -> None:
        catalog, weights = self.catalog, self.weights
        assert catalog.depth_of("Dog") == 2
        assert catalog.depth_of("Bark") == 3
        assert catalog.depth_of("Animal") == 0
        assert catalog.depth_of("Domestic_animals_and_pets") == 1
        assert catalog.depth_of("Dishes_and_pots_and_pans") == 2
        assert catalog.bonus_of("Dog") == 1.0 + weights.depth_step * catalog.depth_of("Dog")
        assert catalog.bonus_of("clock_alarm") == 1.0

    def test_exact_matches(self) -> None:
        catalog, weights = self.catalog, self.weights
        dog_bonus = catalog.bonus_of("Dog")
        dog = score_text(catalog, "dog")
        assert (dog.category, dog.subcategory) == ("ANIMALS", "DOG"), dog
        assert dog.score == weights.exact_sub * dog_bonus, dog
        heavier = score_text(catalog, "dog", weights=weights.with_values(exact_sub=10))
        assert (heavier.category, heavier.subcategory) == ("ANIMALS", "DOG"), heavier
        assert heavier.score == 10 * dog_bonus, heavier

        meow = score_text(catalog, "Meow")
        assert (meow.category, meow.subcategory) == ("ANIMALS", "CAT DOMESTIC"), meow

        bell = score_text(catalog, "Bell")
        assert (bell.category, bell.subcategory) == ("ALARMS", "BELL"), bell
        assert bell.score == weights.exact_sub * catalog.bonus_of("Bell"), bell

        sneeze = score_text(catalog, "sneezing")
        assert (sneeze.category, sneeze.subcategory) == ("HUMAN", "SNEEZE"), sneeze

    def test_predominant_label_bonus(self) -> None:
        catalog, weights = self.catalog, self.weights
        bell = score_text(catalog, "Bell")
        pp = score_text(catalog, "Bell", pp_labels="Bell")
        assert pp.score == bell.score + weights.pp_bonus, (bell.score, pp.score)
        assert (pp.category, pp.subcategory) == ("ALARMS", "BELL")
        pp_only = score_text(catalog, "", pp_labels="Bell")
        assert (pp_only.category, pp_only.subcategory, pp_only.score) == (
            "ALARMS",
            "BELL",
            bell.score + weights.pp_bonus,
        ), pp_only

    def test_ties_and_category_hint(self) -> None:
        catalog = self.catalog
        knock = score_text(catalog, "Knock")
        assert knock.status == "tie", knock
        opened = score_text(catalog, "Knock", on_tie="first")
        assert opened.status == "assigned" and opened.score == knock.score and opened.subcategory, opened
        knock_door = score_text(catalog, "Knock", category="DOORS")
        assert (knock_door.category, knock_door.subcategory) == ("DOORS", "KNOCK"), knock_door

        pour = score_text(catalog, "Pour", category="WATER")
        assert (pour.category, pour.subcategory) == ("WATER", "POUR"), pour

    def test_metadata_fields(self) -> None:
        catalog, weights = self.catalog, self.weights
        uploader = score_text(catalog, "", uploader_tags="doorbell")
        assert (uploader.category, uploader.subcategory, uploader.score) == (
            "BELLS",
            "DOORBELL",
            weights.uploader_tag,
        ), uploader
        quiet = score_text(catalog, "", uploader_tags="doorbell", weights=weights.with_values(uploader_tag=0))
        assert quiet.status == "below" and quiet.score == 0, quiet

        title = score_text(catalog, "", title="doorbell in the hallway")
        assert title.status == "below", title
        assert title.score == weights.title_match

        description = score_text(catalog, "", description="someone rings the doorbell")
        assert description.status == "below", description
        assert description.score == weights.description_match

    def test_category_words(self) -> None:
        catalog, weights = self.catalog, self.weights
        fire = score_text(catalog, "Fire")
        assert (fire.status, fire.category, fire.subcategory) == ("category", "FIRE", ""), fire
        alarm = score_text(catalog, "Alarm")
        assert (alarm.status, alarm.category, alarm.subcategory) == ("category", "ALARMS", ""), alarm
        clock_alarm = score_text(catalog, "clock_alarm")
        assert (clock_alarm.status, clock_alarm.category, clock_alarm.subcategory) == (
            "assigned",
            "ALARMS",
            "CLOCK",
        ), clock_alarm
        assert clock_alarm.score == weights.exact_sub * catalog.bonus_of("clock_alarm"), clock_alarm
        alarm_clock = score_text(catalog, "alarm clock")
        assert (alarm_clock.category, alarm_clock.subcategory) == ("ALARMS", "CLOCK"), alarm_clock
        clock_tick = score_text(catalog, "clock tick")
        assert (clock_tick.status, clock_tick.category, clock_tick.subcategory) == (
            "assigned",
            "CLOCKS",
            "TICK",
        ), clock_tick
        fire_alarm = score_text(catalog, "fire alarm")
        assert fire_alarm.status == "tie" and fire_alarm.subcategory == "", fire_alarm
        car_alarm = score_text(catalog, "car alarm")
        assert (car_alarm.status, car_alarm.category, car_alarm.subcategory) == ("category", "ALARMS", ""), car_alarm
        knock_door = score_text(catalog, "door_wood_knock")
        assert (knock_door.category, knock_door.subcategory) == ("DOORS", "KNOCK"), knock_door

    def test_dataset_label_lists(self) -> None:
        catalog = self.catalog
        breathing = score_text(catalog, "breathing")
        assert (breathing.status, breathing.category, breathing.subcategory) == ("category", "HUMAN", ""), breathing
        assert {item[1] for item in breathing.ties} == {"BREATH", "SNORE"}, breathing
        burp = score_text(catalog, "Burping, eructation,Speech")
        assert burp.status == "tie" and burp.subcategory == "", burp
        tick = score_text(catalog, "Tick-tock,Clock")
        assert (tick.category, tick.subcategory) == ("ALARMS", "CLOCK"), tick
        snore = score_text(catalog, "Snoring,Animal")
        assert (snore.category, snore.subcategory) == ("HUMAN", "SNORE"), snore
        plumbing = score_text(catalog, "Toilet flush,Water")
        assert (plumbing.category, plumbing.subcategory) == ("WATER", "PLUMBING"), plumbing
        drip = score_text(catalog, "Trickle, dribble,Speech")
        assert (drip.category, drip.subcategory) == ("VOICES", "HISTORICAL"), drip
        cat = score_text(catalog, "Cat")
        assert (cat.status, cat.category, cat.subcategory) == ("category", "ANIMALS", ""), cat
        assert {item[1] for item in cat.ties} == {"CAT DOMESTIC", "CAT WILD"}, cat
        purr = score_text(catalog, "Purr")
        assert purr.status == "tie" and purr.subcategory == "", purr
        storm = score_text(catalog, "Thunder,Rain,Water,Thunderstorm")
        assert (storm.category, storm.subcategory) == ("WEATHER", "THUNDER"), storm
        wet_thunder = score_text(catalog, "Rain,Thunderstorm,Thunder")
        assert (wet_thunder.category, wet_thunder.subcategory) == ("WEATHER", "THUNDER"), wet_thunder
        dry = score_text(catalog, "Thunder,Thunderstorm")
        assert (dry.category, dry.subcategory) == ("WEATHER", "THUNDER"), dry
        mechanisms = score_text(catalog, "Tick-tock,Clock,Mechanisms")
        assert (mechanisms.category, mechanisms.subcategory) == ("ALARMS", "CLOCK"), mechanisms
        cowbell = score_text(catalog, "Cowbell,Bell")
        assert (cowbell.category, cowbell.subcategory) == ("ALARMS", "BELL"), cowbell
        clapping = score_text(catalog, "Clapping")
        assert clapping.status == "tie" and clapping.subcategory == "", clapping
        chime = score_text(catalog, "Chime,Bell")
        assert chime.status == "tie" and chime.subcategory == "", chime
        crackling = score_text(catalog, "crackling_fire")
        assert (crackling.status, crackling.category, crackling.subcategory) == ("category", "FIRE", ""), crackling
        pouring = score_text(catalog, "pouring_water")
        assert (pouring.status, pouring.category, pouring.subcategory) == ("category", "WATER", ""), pouring
        drops = score_text(catalog, "water_drops")
        assert (drops.status, drops.category, drops.subcategory) == ("category", "WATER", ""), drops
        thunder_only = score_text(catalog, "Thunderstorm")
        assert thunder_only.subcategory == "" and thunder_only.category == "WEATHER", thunder_only

    def test_closed_catalog(self) -> None:
        catalog = self.catalog
        closed, _resolved, missing, borrowed = catalog_for(
            default_config(), self.records, catalog.depths, catalog.alias
        )
        assert missing == [] and any("DOORBELL" in note for note in borrowed), (missing, borrowed)
        doorbell = score_text(closed, "Doorbell")
        assert (doorbell.category, doorbell.subcategory) == ("DOORS", "DOORBELL"), doorbell
        allowed = {(entry.category, entry.subcategory) for entry in closed.entries}
        pig = recover_category(score_text(closed, "pig"), score_text(catalog, "pig"), allowed)
        assert (pig.status, pig.category, pig.subcategory) == ("category", "ANIMALS", ""), pig
        creak = recover_category(
            score_text(closed, "door_wood_creaks"), score_text(catalog, "door_wood_creaks"), allowed
        )
        assert (creak.status, creak.category) == ("category", "DOORS") and creak.subcategory == "", creak


if __name__ == "__main__":
    unittest.main()
