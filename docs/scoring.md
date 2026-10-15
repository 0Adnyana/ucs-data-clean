# Scoring

`scripts/score_ucs.py` compares each keyword with every eligible subcategory. The highest score wins. Weights and the cutoff live in [configs](configs.md). Eligible labels depend on the taxonomy mode described there.

## What each match is worth

| Match | Weight | What counts |
| --- | --- | --- |
| Exact subcategory name | `exact_sub` (5) | The tag is the subcategory, or its words are a category name plus a subcategory of that category (`clock alarm` is `ALARMS/CLOCK`). |
| Exact synonym | `exact_syn` (3) | The tag equals a synonym. This replaces word overlap for the same tag, so the matched words are not counted twice. |
| Shared word | `word` (1) | Each overlapping word in a synonym or the explanation. |
| Ontology depth | `depth_step` (0.25) | Multiplies the lexical points above by `1 + depth_step * depth`. |
| Predominant label | `pp_bonus` (2) | Added after the depth factor, and only for subcategories that tag already matched. |
| Uploader tag | `uploader_tag` (2) | The subcategory name or a synonym matches an uploader tag as a whole phrase. |
| Title | `title_match` (1) | Same whole-phrase match in the title. |
| Description | `description_match` (0.5) | Same whole-phrase match in the description. |

Depth multiplies the lexical points only.

A synonym or subcategory name also counts when one token of a longer label names it (`Burping, eructation` contains `Burping`). A plural or `-ing` stem counts as that word (`sneezing` is `sneeze`). Words shorter than 3 characters and a small stop list are ignored.

## Depth

AudioSet ontology depth comes from `references/audioset_ontology.json`. A root label is depth 0 and stays at x1. With the shipped `depth_step` of 0.25, depth 2 (Dog, Pour, Siren) is x1.5. Tags that are not in the ontology stay at x1.

## Ties and blanks

`min_score` (default 2) is the cutoff. One unaided word at depth 0 is 1 point, so it stays blank. An exact synonym is 3 and clears the default cutoff.

`on_tie` is `blank` or `first`.

- `blank` leaves the row empty when the leaders are in different categories. When they share a category, that category is kept and `SubCategory` stays empty.
- `first` keeps one leader, after sorting by score, then category, then subcategory.

The existing `Category` is applied before that. If exactly one leader sits in the row’s category, that leader is kept.

A few patterns resolve to a category with an empty subcategory:

- A tag that is a category name (`Fire`, `Alarm`, `Door`, `Water`, including the plural), when no single subcategory outranks it.
- A word that is a synonym of more than one subcategory stays tied.
- A longer label whose extra word still ties two subcategories (`crackling fire`, `pouring water`, `water drops`).

A category word in a longer label chooses between two subcategories that share a name: `door wood knock` is `DOORS/KNOCK`. Two category words that do not form a category-plus-subcategory pair stay unresolved (`fire alarm`).

## Report

A manifest run prints how many rows were `assigned`, `category`, `tie`, or `below`, then agreement on rows that already have a `SubCategory`.
