# Data

[Usage](usage.md) covers how to score these files. [Scoring](scoring.md) covers how a keyword becomes a UCS label.

## Slice files

| File | Rows | Use |
| --- | ---: | --- |
| `manifests/slice/envsound_train.csv` | 2019 | Examples for inventing rules and prompts. The filled subcategories came with the slice. Leave the empty ones unlabeled. |
| `manifests/slice/envsound_val.csv` | 140 | Score while the converter is still changing. Hand-label this. |
| `manifests/slice/envsound_test.csv` | 140 | Score once, after the converter is frozen. Hand-label this. |

Membership is `filename`, `source`, and `path`. `manifests/original-envsound/` holds the full lists those rows were drawn from: train 40642, val 8707, test 8708. `Category` and `SubCategory` on the slice were copied from there.

Rows that already have `SubCategory` are finished mappings. Use them as positive examples. Rows with an empty `SubCategory` are the cleaning task, and some of them do not belong to any subcategory in the closed list. Train has 1535 filled rows and 484 empty ones. Val and test each have 103 filled and 37 empty.

## Columns

| Column | Meaning |
| --- | --- |
| `filename` | Audio filename in the source dataset. |
| `Category` | UCS category. |
| `SubCategory` | UCS subcategory. Empty on the rows a converter is supposed to fill. |
| `Keywords` | Original dataset labels. This is the non-UCS input. |
| `source` | `AudioSet`, `ESC-50`, `FSD50K`, or `FoleySet`. |
| `path` | Path of the audio file relative to `audio/`. |
| `exists` | Whether that audio file was present when the manifest was built. |

AudioSet labels contain commas of their own (`Waves, surf`). In `Keywords`, the separator between labels is a comma that is not followed by a space. A comma followed by a space stays inside one label.

Scoring reads `pp_labels`, `uploader_tags`, `title`, and `description` from `audio/` unless you pass `--no-audio`, in which case it uses whatever is already on the CSV. The checked-in slice files do not have those columns.

## Where the keywords come from

| Source | File | Field |
| --- | --- | --- |
| AudioSet | `audio/AudioSet/audios/balanced_train_segments.csv` and `eval_segments.csv` | `human_labels` |
| ESC-50 | `audio/ESC-50/meta/esc50.csv` | `category` |
| FSD50K | `audio/FSD50K/FSD50K.ground_truth/dev.csv` and `eval.csv` | `labels` |
| FoleySet | `audio/FoleySet/metadata/foleyset_metadata.csv` | `category` and `sub-category` |

FSD50K also uses `audio/FSD50K/FSD50K.metadata`. `pp_pnp_ratings_FSD50K.json` supplies predominant labels (a rating of 1.0), including classes the ground truth later merged into a parent. `dev_clips_info_FSD50K.json` and `eval_clips_info_FSD50K.json` supply uploader tags, the title, and the description. A predominant label that is not already a keyword is scored as its own tag.

FoleySet free tags go in `uploader_tags`. The description goes in `description`. `Category` and `SubCategory` stay empty. A CamelCase subcategory is written with spaces (`PaperTear` becomes `Paper Tear`) so each word can match.

## envsound-foleyset

`manifests/envsound-foleyset/` is `manifests/blank-envsound/` plus FoleySet clips that do not reuse a Freesound id already in FSD50K or ESC-50. Shared uploads are dropped, including when the FoleySet segment and the existing clip are in different splits. AudioSet ids are YouTube ids and are not part of that check.

| File | Rows | blank-envsound | FoleySet |
| --- | ---: | ---: | ---: |
| `manifests/envsound-foleyset/envsound_train.csv` | 47450 | 40642 | 6808 |
| `manifests/envsound-foleyset/envsound_val.csv` | 9548 | 8707 | 841 |
| `manifests/envsound-foleyset/envsound_test.csv` | 9551 | 8708 | 843 |

Of 10000 FoleySet clips, 1508 were left out: 1426 shared with FSD50K only, 40 with ESC-50 only, and 42 with both. Rebuild with `python scripts/make_envsound_foleyset.py`.

## test-envsound-no-audioset

`manifests/test-envsound-no-audioset/` is an AudioSet ablation. All four folders use one test file: the original EnvSound test split with AudioSet removed. EnvSound labels stay the original `Category` and `SubCategory`. FoleySet labels come from `scoring/experiments/min075-envsound-foleyset/`. Counts and the size-matching rule are in that folder's README. Rebuild with `python scripts/make_test_envsound_no_audioset.py`.

Wav layout and file counts are in [audio/README.md](../audio/README.md).

## Closed taxonomy

The slice only contains these pairs. The scorer reads them from `closed` in `scoring/configs/default.json`. An empty subcategory is included everywhere except `WEATHER`. The scorer never assigns an empty subcategory; an empty value means no assignment.

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

Some sounds in the slice sit outside the listed subcategories on purpose. A pig filed under `ANIMALS` stays at the category.
