# ucs-data-clean

Converts non-UCS environmental-sound labels into [Universal Category System](https://universalcategorysystem.com) (UCS) `Category` and `SubCategory`.

Keywords come from AudioSet, ESC-50, and FSD50K. `scripts/score_ucs.py` scores them against `references/ucs-v8.2.1.xlsx`. The files to score are `manifests/slice/envsound_train.csv`, `envsound_val.csv`, and `envsound_test.csv`. The scorer needs `openpyxl`.

## Getting started

The loop is: score val, read the agreement, check a keyword that went wrong, then save the setup as an experiment and compare reports.

**1. Score val.**

```bash
pip install openpyxl
python scripts/score_ucs.py manifests/slice/envsound_val.csv
```

This loads `configs/default.json`: the closed taxonomy below, minimum score 2, ties left blank. The printout counts rows that were `assigned`, kept at `category` only, `tie`, or `below` the cutoff. `exact category/subcategory` is agreement with rows that already have a `SubCategory`. Those filled rows are the reference. Use val while you are still changing the scorer.

**2. Check a keyword that looks wrong.**

Copy the `Keywords` cell from that row:

```bash
python scripts/score_ucs.py --keywords "Siren" --category ALARMS
```

This prints the decision and the top candidates. `--category` is used only when several subcategories tie.

**3. Save the setup.**

```bash
python scripts/score_ucs.py --experiment configs/default-open.json
```

This writes `experiments/default-open/`: one CSV per file the config scores, plus `config.json` and `report.txt`. `Category` and `SubCategory` in those CSVs are the scorer’s assignment. `manifests/slice/` stays as labeled. Read `report.txt` the same way as the val printout. `exact category/subcategory` is the number to compare from one config to the next.

A config’s `splits` list is which of train, val, and test get scored. Files left off that list are copied into the experiment folder from the slice. `configs/default.json` scores test only. A config that should label every file lists all three.

**4. Change the scorer and run it again.**

Copy a JSON file under `configs/`, change `min_score`, `weights`, or `taxonomy`, and pass it to `--experiment`. Compare the new `report.txt` with the last one.

Score `manifests/slice/envsound_test.csv` once you stop changing the config. Train is the set of examples for inventing rules and for an LLM prompt. Hand tags belong on val and test (280 rows). Leave the empty train rows unlabeled.

Match rules are in [docs/scoring.md](docs/scoring.md). The slice files, columns, and audio sources are in [docs/data.md](docs/data.md). Flags are in [docs/usage.md](docs/usage.md).

## Configs

A run with no `--config` uses `configs/default.json`. That file is a closed taxonomy: only the pairs below are eligible, `min_score` is 2, ties are left blank, and only the test file is scored. An empty subcategory means no assignment.

| Category | Subcategories |
| --- | --- |
| `ALARMS` | `BELL`, `SIREN`, `BUZZER` |
| `ANIMALS` | `DOG`, `CAT DOMESTIC` |
| `CLOCKS` | `TICK` |
| `DOORS` | `KNOCK`, `DOORBELL`, `SLIDING` |
| `FIRE` | `CRACKLE`, `SIZZLE` |
| `HUMAN` | `BREATH`, `COUGH`, `SNEEZE`, `BURP`, `SNORE` |
| `WATER` | `POUR`, `DRIP`, `SURF` |
| `WEATHER` | `STORM`, `THUNDER` |

Other files under `configs/` inherit anything they omit from `default.json`. Taxonomy modes, weights, and the shipped configs are in [docs/configs.md](docs/configs.md).

## How a row is scored

Each keyword is compared with every eligible subcategory. An exact subcategory name scores 5, an exact synonym scores 3, and each shared word scores 1. AudioSet ontology depth multiplies those points (`depth_step` 0.25, so depth 2 is x1.5). The row stays blank under `min_score` (default 2). When the best subcategories are in different categories, the row stays blank. When they share a category, that category is kept and `SubCategory` stays empty.

The full weights, tie cases, and report lines are in [docs/scoring.md](docs/scoring.md).
