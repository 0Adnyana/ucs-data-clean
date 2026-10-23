# Cross-labelling review

This folder is the listen queue from round 1. The root README is the keyword scorer. `5-fold-cross-labeling/README.md` is how the five piles and the probe were set up. This file is what to do with the flags.

Round 1 is finished. Each pile was predicted by a probe trained on the other four. Of 93,883 clips, the given label was the top prediction for 54.9% and in the top 5 for 81.0%. That run produced 23,225 flags (24.7%). A new probe waits until the labels change.

## How a clip got here

The probe writes a top 5. Each UCS pair has a threshold: the mean probability the model assigns to that pair on clips that already carry it. A clip is flagged when the highest-ranked pair above its own threshold is not the given label, and that pair's probability is higher than the given label's. If the given label is outside the top 5, its probability is taken as the rank-5 confidence. That value is an upper bound, so the stored margin is a lower bound on the real gap.

`margin` is suggested probability minus given probability. A larger number means the model is further from the label on the file. `review_batch1_tag_supported.csv` is sorted with the largest margin first. `review_queue.csv` is sorted the same way, with `tag_supported` before `unsupported`.

`flag_type` is how the suggestion sits next to the given label.

- `cross_category`: a different category.
- `within_category`: the same category, and a specific subcategory.
- `within_category_misc`: the same category, and the suggestion is MISC.

`bucket_strict` is the bucket used for review. `tag_supported` means a tag on the clip already names the suggestion. `unsupported` means none does. Generic tags do not count as support when the clip also mapped to some other pair. Those tags are Music, Speech, Animal, Domestic animals, pets, Vehicle, Human voice, Domestic sounds and home sounds, Wild animals, Mechanisms, Liquid, Water, Sound effect, and Environmental noise. `bucket_all` counts those generic tags as support. Leave it out of the listen order.

`source` plus `filename` is the clip. `filename` alone is not unique: the same wav name can exist in two datasets.

## What the 100-clip sample said

`precision_sample.csv` is a stratified draw of 100 flags (seed 0, on `bucket_strict` and `flag_type`). `precision_sample_labeled.csv.csv` is that draw after listening. The Label Studio project for it is `label-setup/`. The result was 26 wrong, 65 acceptable, and 9 unsure.

| Cell | Wrong / judged | Suggestion right when the label was wrong |
| --- | --- | --- |
| tag_supported × cross | 5/9 | 4/5 |
| tag_supported × within | 2/7 | 2/2 |
| unsupported × cross | 15/44 | 4/15 |
| unsupported × within | 4/18 | 3/4 |
| both MISC cells | 0/13 | |

A flag is a real label error about 31% of the time, so about 7,200 of the 23,225 flags are real errors, about 8% of the dataset. The range on that estimate is about 4,900 to 9,600.

Margin separates them. Precision was about 13% below 0.25, and 40 to 50% above it. Real errors had a higher median margin (0.40 against 0.23).

tag_supported × cross is the cell where the suggestion is usually the right fix. unsupported × cross holds most of the errors, and the suggestion is usually the wrong fix, so those clips need a label you choose. MISC-only flags were noise. 26 of the 65 acceptable labels had a better option. Those stay acceptable. Use `notes` when that pattern shows up.

Two clips in the sample were silent: FSD50K `316074.wav` and AudioSet `YBar1jMJv_Rw.wav`. FoleySet footsteps flagged as BODYFALL or ICE BREAK were labelled correctly. That is the model, not the label.

OBJECTS||WHEELED is a mapping bug. All 68 clips with that given label are AudioSet rock tagged `Music, Roll, Rock and roll`. The tag `Roll` was mapped to a rolling object, and 242 flags suggest WHEELED because of it. Do not fix those one by one while listening. The converter change is separate, and it may move only those 68 clips.

Six labels from the sample are real UCS pairs the probe never trained on: FOOD & DRINK||GLASSWARE, VEHICLES||DOOR, AMBIENCE||UNDERGROUND, GLASS||CRASH & DEBRIS, TRAINS||STEAM, and WIND||TONAL. Adding them, or mapping each to a trained pair, is still an open choice.

## Listen order

Skip `within_category_misc` (1,325 flags). Skip margin under 0.25.

1. `review_batch1_tag_supported.csv`. 1,909 clips, all `tag_supported`, margin at least 0.25, no MISC. The first 983 have margin at least 0.5. Listen to those first. The file is already sorted that way. 1,271 are cross-category and 638 are within-category. AudioSet has 909 and FSD50K has 1,000. ESC-50 and FoleySet have no strict tag support, so they are absent here.
2. unsupported × cross, taken from `review_queue.csv`, highest margin first. 812 clips are at least 0.7, and 2,514 are at least 0.5. Time-box this pass. Choose the label yourself. On the sample the suggestion was the right fix for 4 of 15 wrong labels.
3. unsupported × within, if time is left. 1,160 of those have margin at least 0.5.

## Label Studio

`label-setup/label_studio.xml` is the labeling config. It reads `filename`, `path`, `Category`, `SubCategory`, `Keywords`, and `suggested`, which `review_batch1_tag_supported.csv` has on every row. Paste the XML into a project and import that CSV. `label-setup/tasks.json` is only the 100-clip sample.

Set `LABEL_STUDIO_LOCAL_FILES_DOCUMENT_ROOT` to the parent repository, the folder that contains `audio/`, and turn local file serving on. The player loads `audio/` plus `path`. Every file in the batch is already under that `audio/` directory. This folder's move into `5-fold-cross-labeling/` does not change that path.

The listening rules are written out in `label-setup/README.md`. In short: the screen starts with the clip and the given label, and `suggested` stays hidden until `label_wrong` is filled. Hide `suggested` in the data manager.

- `label_wrong` = 1: a sound librarian would move this file. The given label does not describe the predominant sound.
- `label_wrong` = 0: the given label is an acceptable UCS label for the predominant sound, even when the suggestion is also acceptable.
- `label_wrong` = ?: you cannot tell. Too quiet, too mixed, or unrecognisable. Do not force a 0 or a 1.
- MISC counts as wrong only when a specific subcategory clearly fits.

Then set `predominant_is` to `given`, `suggested`, `other`, or `unclear`. `other` needs a category and subcategory from the picker. The picker stores that pair on `human_pair`.

## What is allowed to change a label

Nothing in this folder is a new training label. A suggestion is accepted only after the clip has been heard. A checked rule fix is the other way a label moves. Accepting suggestions in bulk would train the next probe on what this one already believes.

Corrections wait in an overrides file. They do not get typed into the split CSVs. `5-fold-cross-labeling/README.md` still says to write `human_category` on `pile.csv`. That is not this round.

Before round 2, one script applies four changes, in this order: removals (missing, unreadable, or silent files), the WHEELED converter fix, the out-of-class mapping, then overrides. The same recording stays in the same pile. These scripts are not in the repo yet, and neither is the silent-file check or the Label Studio export converter.

The human-verified test set is a separate random draw of clips that were not flagged and not reviewed. It is the check that cleaning helped. It is not a source of training labels.

Do not retrain on the round-1 labels. Do not fix AudioSet comma-splitting in the same change as WHEELED. That split would move many labels at once, so it stays its own measured change.

## Files

| File | What it is |
| --- | --- |
| `review_queue.csv` | All 23,225 flags |
| `review_batch1_tag_supported.csv` | First listen file, 1,909 clips |
| `precision_sample.csv` | The 100-clip draw |
| `precision_sample_labeled.csv.csv` | That draw after listening |
| `label-setup/` | Label Studio config, the 100 tasks, and the listening rules |
| `summary.txt` | Flag counts, bucket counts, and the WHEELED note |
| `bucket_summary.csv` | The same bucket counts as a table |
| `supported_pairs.csv` | Given label, suggestion, and the tag that supported it |
| `candidates.csv` | Candidate pairs per clip, from the label maps. No labels were written |
| `candidates_report.txt` | Check that replaying the label maps reproduces `Category` and `SubCategory` |
| `candidates_mismatch.csv` | Rows where that replay disagreed. The report count is 0 |

`5-fold-cross-labeling/scripts/build_candidates.py` writes the candidate sets. `5-fold-cross-labeling/scripts/cross_label_flags.py` writes the flags, the buckets, the queue, and the 100-clip draw. Both write into this folder unless `--output` is set. `review_batch1_tag_supported.csv` is a cut of `review_queue.csv` and is not rewritten by either script.
