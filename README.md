# ucs-data-clean

This repo converts non-UCS environmental-sound labels into [Universal Category System](https://universalcategorysystem.com) (UCS) `Category` and `SubCategory`.

Source labels live in `Keywords`. They come from AudioSet, ESC-50, and FSD50K. `scripts/score_ucs.py` scores those labels against `references/ucs-v8.2.1.xlsx` and writes a category and subcategory. Ontology depth comes from `references/audioset_ontology.json`. The checked-in CSVs under `manifests/slice/` are a small slice of that problem, so a cleaner can be written and scored without the full manifests in `manifests/original-envsound/`.

The scorer needs `openpyxl` to read the workbook.

## Three ways to convert

Use any of these. The rule scorer and an LLM prompt are the methods to develop. Manual tags exist so those two can be scored.

### 1. Rule-based scoring

`scripts/score_ucs.py` scores each row’s keywords against the allowed UCS labels and keeps the highest score. The keywords are the original dataset labels under `audio/`:

| Source | File | Field |
| --- | --- | --- |
| AudioSet | `audio/AudioSet/audios/balanced_train_segments.csv` and `eval_segments.csv` | `human_labels` |
| ESC-50 | `audio/ESC-50/meta/esc50.csv` | `category` |
| FSD50K | `audio/FSD50K/FSD50K.ground_truth/dev.csv` and `eval.csv` | `labels` |

FSD50K also uses `audio/FSD50K/FSD50K.metadata`. `pp_pnp_ratings_FSD50K.json` supplies predominant labels (a rating of 1.0), including classes the ground truth later merged into a parent. `dev_clips_info_FSD50K.json` and `eval_clips_info_FSD50K.json` supply uploader tags, the title, and the description. A predominant label that is not already a keyword is scored as its own tag.

Read `manifests/slice/envsound_train.csv` while you invent the rules. Change the script against `manifests/slice/envsound_val.csv`. Run `manifests/slice/envsound_test.csv` once, after you stop changing it.

A row is left blank when the best score is under `min_score`, or when the best subcategories sit in different categories and `on_tie` is `blank`. A tie inside one category keeps that category and leaves `SubCategory` blank. A tag that is a category name (`Fire`, `Alarm`, `Door`, `Water`, including the plural) does the same when no single subcategory outranks it. If the row already has a `Category` and exactly one tied subcategory is in that category, that one is kept. Some sounds in this slice are outside the listed subcategories on purpose (a pig filed under `ANIMALS` is not `DOG` or `CAT DOMESTIC`); the category is still filled.

### 2. LLM inferred

A prompt, written from the train rows, asks a model to infer UCS `Category` and `SubCategory` from the non-UCS keywords. Same split discipline as the rule script: develop on train, iterate on val, score test once.

### 3. Manual

Hand tags, and only on val and test. Together those splits are 280 rows, kept under 300 so both can be labeled by hand. Leave the empty train rows unlabeled.

Manual labels on val and test are the reference. Score the rule script and the LLM against them. While you are still changing a converter, score val. Score test after the converter is frozen.

## Splits

| File | Rows | Use |
| --- | ---: | --- |
| `manifests/slice/envsound_train.csv` | 2019 | Examples for inventing rules and prompts. The filled subcategories came with the slice. Leave the empty ones unlabeled. |
| `manifests/slice/envsound_val.csv` | 140 | Score while the converter is still changing. Hand-label this. |
| `manifests/slice/envsound_test.csv` | 140 | Score once, after you stop changing the converter. Hand-label this. |

Membership is `filename`, `source`, and `path` on those same files. The counts are 2019, 140, and 140.

`manifests/original-envsound/` holds the full envsound lists those rows were drawn from: `envsound_train.csv` (40642 rows), `envsound_val.csv` (8707), and `envsound_test.csv` (8708). A rebuild copies `Category` and `SubCategory` from there.

Each manifest has the same columns:

| Column | Meaning |
| --- | --- |
| `filename` | Audio filename in the source dataset. |
| `Category` | UCS category. |
| `SubCategory` | UCS subcategory. Empty on the rows a converter is supposed to fill. |
| `Keywords` | Original dataset labels. This is the non-UCS input. |
| `source` | `AudioSet`, `ESC-50`, or `FSD50K`. |
| `path` | Path of the audio file relative to `audio/`. |
| `exists` | Whether that audio file was present when the manifest was built. |

AudioSet labels contain commas of their own (`Waves, surf`). In `Keywords`, the separator between labels is a comma that is not followed by a space. A comma followed by a space stays inside one label.

Rows that already have `SubCategory` are finished mappings. Use them as positive examples. Rows with an empty `SubCategory` are the cleaning task, and some of them do not belong to any subcategory in the list. Train has 1535 filled rows and 484 empty ones. Val and test each have 103 filled rows and 37 empty ones.

Rebuilding a manifest also writes `pp_labels`, `uploader_tags`, `title`, and `description`. The checked-in files do not have those columns yet. A scoring run still reads them from `audio/` unless you pass `--no-audio`, in which case it uses whatever is already on the CSV.

## Closed taxonomy

Only these category / subcategory pairs are in the slice. The scorer reads them from `closed` in `configs/default.json`. A config with `"taxonomy": "closed"` uses that list, or its own `closed` list if it has one. An empty subcategory is included in the slice everywhere except `WEATHER`. The scorer never assigns an empty subcategory; an empty value means no assignment.

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

Train is capped at 80 rows per pair. Pairs with fewer than 80 rows ran out of source clips. Val and test give every pair at least 5 rows when the source split has them (`WATER/SURF` has 3), then give a few extra rows to the empty subcategories.

`DOORS/DOORBELL` is in this slice and is not in the UCS workbook (`BELLS/DOORBELL` is). A closed run scores it with the doorbell synonyms from `BELLS/DOORBELL`.

## How a row is scored

Each keyword is compared with every eligible subcategory. The highest score wins.

An exact subcategory name scores `exact_sub`. So does a tag whose words are a category name and a subcategory of that category: `clock alarm` is `ALARMS/CLOCK`. `fire alarm` stays unresolved, because neither word is a subcategory of the other category. An exact synonym scores `exact_syn`. That exact hit replaces word overlap for the same tag, so the matched words are not counted twice. A synonym or subcategory name also counts when one token of a longer label names that subcategory alone (`Burping, eructation` contains `Burping`), and a plural or `-ing` stem counts as that word (`sneezing` is `sneeze`). A shared word such as `open` or `trickle` stays a word hit. Each overlapping word in a synonym or the explanation adds `word`. Plural and `-ing` forms count as the same word once. Words shorter than 3 characters and a small stop list are ignored.

A label such as `door wood knock` uses the category word to choose between two subcategories that share a name (`DOORS/KNOCK`, not `WINDOWS/KNOCK`). `crackling fire`, `pouring water`, and `water drops` stay at the category, because the extra word still ties two subcategories. A word that is a synonym of more than one subcategory is left tied; the scorer does not pick one of those synonyms over the other.

AudioSet ontology depth multiplies those lexical points by `1 + depth_step * depth`. A root label is depth 0 and stays at x1. With the shipped `depth_step` of 0.25, depth 2 (Dog, Pour, Siren) is x1.5. Tags that are not in the ontology stay at x1.

A predominant label adds `pp_bonus` after the depth factor, and only for subcategories that tag already matched. An uploader tag, the title, and the description add their own weights when the subcategory name or a synonym matches as a whole phrase. Those three are not multiplied by depth.

`min_score` (default 2) is the cutoff under which the row stays blank. One unaided word at depth 0 is 1 point, so it stays blank. An exact synonym is 3 and clears the default cutoff. `on_tie` is `blank` or `first`. `blank` leaves the row empty when the leaders are in different categories. When they share a category, that category is kept and `SubCategory` stays empty. `first` keeps one leader, after sorting by score, then category, then subcategory. The existing `Category` is applied before that: if exactly one leader sits in the row’s category, that leader is kept.

## Configs

`configs/default.json` is the scorer. A run with no `--config` loads that file: closed taxonomy, the weights below, minimum score 2, ties left blank, and the test split only. Another JSON file only needs the fields it changes. Anything it omits stays as in `default.json`.

| File | Setup |
| --- | --- |
| `configs/default.json` | Closed slice, test only. This is the file other configs inherit. |
| `configs/default-open.json` | Same weights, every subcategory in the UCS workbook, test only. |
| `configs/closed-strict.json` | Closed slice. Exact names count more, word overlap counts less, `min_score` 4, test only. |
| `configs/default-auto.json` | Same closed scorer as `default.json`, with `splits` set to test, val, and train. Its `name` is `default`, so the experiment folder is `experiments/default/`. |
| `configs/open-weighted.json` | Full UCS list. Exact names and ontology depth count more, word overlap and description matches count less, `min_score` 2, all three splits. |

`--experiment-dir configs` skips `default.json` and runs every other JSON config in that directory.

`taxonomy` controls how open the label set is:

| Value | Eligible labels |
| --- | --- |
| `"closed"` | The category / subcategory pairs in the table above. A pair missing from the workbook is skipped. |
| `"open"` | Every subcategory in the UCS workbook. |
| `{"mode": "categories", "categories": ["ALARMS", "WATER"]}` | Every subcategory in the named categories. |
| `{"mode": "pairs", "pairs": ["ALARMS/BELL", "WATER/POUR"]}` | Only those pairs. `file` can point at a text list or a CSV with `Category` and `SubCategory`. A pair missing from the workbook is an error. |

`weights` replaces the scoring constants. Omit a key to keep its default. `--set exact_sub=8` overrides one value for that run. `--set min_score=4` overrides the cutoff the same way.

| Key | Default | Role |
| --- | ---: | --- |
| `exact_sub` | 5 | Tag equals the subcategory name. |
| `exact_syn` | 3 | Tag equals a synonym. |
| `word` | 1 | Each overlapping word in a synonym or the explanation. |
| `depth_step` | 0.25 | Ontology depth multiplies those points by `1 + depth_step * depth`. |
| `pp_bonus` | 2 | Added when the tag is an FSD50K predominant label. |
| `uploader_tag` | 2 | Subcategory or synonym matches an uploader tag. |
| `title_match` | 1 | Same match in the title. |
| `description_match` | 0.5 | Same match in the description. |

`--taxonomy`, `--categories`, `--pairs`, `--on-tie`, `--min-score`, and `--closed-slice` override the file the same way `--set` does. `--closed-slice` is `--taxonomy closed`.

## Score one manifest or one keyword list

Paths are resolved from the repo root, so the working directory does not matter.

```bash
python scripts/score_ucs.py manifests/slice/envsound_val.csv
python scripts/score_ucs.py manifests/slice/envsound_val.csv -o predictions.csv --config configs/closed-strict.json
python scripts/score_ucs.py --keywords "Meow,Cat,Animal"
python scripts/score_ucs.py --keywords "Siren" --pp "Siren" --title "police siren" --category ALARMS
python scripts/score_ucs.py --self-test
```

A manifest run prints a report: how many rows were `assigned`, `tie`, or `below`, then agreement with rows that already have a `SubCategory`. Rows with an empty gold subcategory are left out of that percentage. `-o` writes the same CSV plus `pred_category`, `pred_subcategory`, `pred_score`, `pred_status`, and `pred_evidence`. `Category` and `SubCategory` on that copy stay as they were.

`--keywords` prints the decision and the top candidates (`--top`, default 8). `--category` is used only to break a tie. `--pp`, `--uploader-tags`, `--title`, and `--description` are the FSD50K fields for that one probe.

`--no-audio` scores the columns already on the CSV. Without it, the audio folder refreshes `Keywords` and the FSD50K metadata before scoring. A file that only has `filename`, `source`, and `path` can be scored the same way; the labels are filled from `audio/`.

`--self-test` checks the scorer against the full UCS list and prints the subcategory count.

## Rebuilding the manifests

```bash
python scripts/score_ucs.py --make-manifests
```

That writes `manifests/slice/envsound_test.csv` only. Train and val are left as they are, so hand tags in those files are not replaced. Add them back with a flag or with `"splits"` in a config:

```bash
python scripts/score_ucs.py --make-manifests --write-splits train,val,test
python scripts/score_ucs.py --make-manifests --config configs/default-open.json
```

The config's `splits` list is used when `--write-splits` is omitted. Membership is the `filename`, `source`, and `path` already on the slice file. `Keywords` and the FSD50K metadata columns come from the label files under `audio/`. `exists` is whether `audio/<path>` is a file.

`--source-dir` defaults to `manifests/original-envsound/`. When `envsound_<split>.csv` exists there, `Category` and `SubCategory` are copied from that full list. Otherwise they stay as they are on the slice. Keywords still come from `audio/`.

## Experiments

Each config under `configs/` is one tagging setup. It chooses the weights, the minimum score, what happens on a tie, which splits to score, and how much of the UCS list is eligible. Running it writes a fresh manifest set a separate linear-probing project can train on. Those files go under `experiments/<name>/` and never replace `manifests/slice/`.

```bash
python scripts/score_ucs.py --experiment configs/default-open.json
python scripts/score_ucs.py --experiment-dir configs
python scripts/score_ucs.py --experiment-name open-min4 --taxonomy open --min-score 4 --set word=0.5
```

Repeat `--experiment` to run several configs. `--output-dir` changes the destination. A batch writes one subfolder per `name`. A config may set `"output_dir"` itself.

`Category` and `SubCategory` in the experiment CSV are the scorer's assignment. A blank prediction (under the minimum, or a tie when `on_tie` is `blank`) writes both fields empty. The copy used as input is unchanged, so the files in `manifests/slice/` remain the reference. `config.json` in the experiment folder is the resolved setup, including any closed pair the workbook does not contain. `report.txt` is the same agreement report as a one-file score, one section per split.

By default an experiment scores test only. Train and val in `experiments/<name>/` are copies of the files in `manifests/slice/`. A probe that should train on that setup's own tags lists those splits:

```json
"splits": ["train", "val", "test"]
```

`--write-splits train,val,test` does the same thing for one run. `configs/default-auto.json` is that list on the closed scorer. Listed splits are scored into `experiments/<name>/`. A split left off that list is copied from `manifests/slice/` into the same folder.
