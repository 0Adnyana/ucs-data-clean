The listen queue from round 1, and the rule that corrections wait in an overrides file instead of on `pile.csv`, is in [candidates/README.md](candidates/README.md).

### Workflow

#### First time

1. Label everything with the labeling script. This is the only time it runs. Its output is `Category` and `SubCategory`, and that is what the first probe trains on.
2. Hand-check a sample of recordings before training. Draw about 3000 clips first, whole recordings only, spread across UCS pairs so each `Category` and `SubCategory` that exists is in the sample. Write that file as `eval-3000.csv`. Then draw about 700 clips from those 3000 the same way, and write them as `eval.csv`. Listen to `eval.csv`. This tells you how often the script is wrong, and catches a rule that always mislabels one category. A model trained on that mistake will agree with it, so step 4 will not flag it. Write what you hear in `Category` and `SubCategory` on `eval.csv`, including when you agree with the script. When you find a bad rule, search the other rows with that script pair and write the correction in the human columns there. Leave `Category` and `SubCategory` as the script wrote them on those other rows. Set the whole 3000 aside and never train on them. Every probe scores `eval.csv` against `Category` and `SubCategory`.
3. Split the rest into 5 piles. The rest is every recording that is not in `eval-3000.csv`. Each recording stays in one pile. Spread each category across the piles. A category with fewer recordings than piles will be missing from some piles, and those piles will flag it because the model never saw it. For each probe, `train.csv` is the other four piles and `pile.csv` is the held-out pile. `all.csv` is not an input to the probe.
4. Train one probe per folder. It fits on `train.csv` and scores `eval.csv` against `Category` and `SubCategory`. It trains on `Category` and `SubCategory` only. Write its top 5 onto `pile.csv` as `model_prediction_1_category`, `model_prediction_1_subcategory`, and `model_confidence_1` through rank 5. Listen where the first pair is not the current `Category` and `SubCategory`, highest `model_confidence_1` first. If the current pair is still in the top 5 and the clip is genuinely ambiguous, leave the human columns empty. Rows with both `Category` and `SubCategory` empty are not part of this queue. Write corrections in the human columns on `pile.csv`. When the same mistake keeps showing up, find the other rows with that `Category` and `SubCategory` and fill their human columns on the `pile.csv` that holds them. The model only chooses what you listen to.
5. Repeat from the promoted piles until it is not worth it. Disagreements never fully hit zero. Stop when most flagged clips are the model's fault. `eval.csv` shows this too: if the model disagrees with it about as often as with the pile labels, the flags are the model's.
6. Train the final model on `Category` and `SubCategory` from all 5 piles. The reported score is `eval.csv` from step 2, against `Category` and `SubCategory`. Run this once, when you stop.

#### Later rounds

A second script builds the next round. It is not the labeling script. It reads the five `pile.csv` files, and where `human_category` is filled, that pair becomes `Category` and `SubCategory`. Where it is empty, the training label stays as it was. It then writes a new `train.csv` and `pile.csv` for each probe, with the same recordings in the same roles. Human and model columns start empty. `eval.csv` is not run through this script. Then repeat step 4.

### Patterns to watch

- It keeps mixing up two similar categories. Check the training rows for those two. Write the corrected pair in the human columns, add more examples, or merge the two.
- It fails on a category with few training clips. Collect more clips for it, or augment the ones you have.
- It fails in certain conditions, like noisy, very short, or quiet clips. Add more of those to training, or simulate them with augmentation.
- Your hand label was wrong. This happens. Fixing `Category` and `SubCategory` on `eval.csv` is fine, since you are correcting the answer key.
- The current `Category` and `SubCategory` were in its top 5 and the clip is genuinely ambiguous. That may be acceptable, depending on your use.

### Folder structure

scripts/ — scripts for this pipeline
candidates/ — round-1 candidate sets, flags, and the listen queue. See `candidates/README.md`
splits/original-labeled/all.csv — setup only. Every master row, script labels in `Category` and `SubCategory`. The probe never reads this
splits/original-labeled/eval-3000.csv — the 3000-clip sample. `eval.csv` is drawn from this. None of these clips are dealt into A–E. The probe does not read this file
splits/original-labeled/eval.csv — the 700 hand-checked recordings, taken from `eval-3000.csv`. The eval set for every probe and for the final model. Score it against `Category` and `SubCategory`
splits/round-X/Y/train.csv — the other four piles. Fit the probe on this
splits/round-X/Y/pile.csv — pile Y. Write predictions here, then listen and correct

Y is A, B, C, D, or E. Probe A trains on B+C+D+E, probe B on C+D+E+A, and so on. `eval.csv` is the same eval set for all five.

### CSV

`eval.csv` and `eval-3000.csv` have the master header and nothing after it: `filename`, `Category`, `SubCategory`, `Keywords`, `source`, `path`, `exists`. The probe scores `Category` and `SubCategory` on `eval.csv`. `train.csv`, `pile.csv`, and `all.csv` share one longer header. The first seven columns are that same master header. `path` is the row id. `filename` is not unique: `10000.wav` is an FSD50K clip and a FoleySet clip. `train.csv` leaves out rows where `Category` and `SubCategory` are both empty, so the probe can train on every row it is given. `pile.csv` keeps those rows.

- `filename`, `Keywords`, `source`, `path`, `exists` — copied from master and then left alone
- `Category`, `SubCategory` — the training label. In round 1 this is the script. Later rounds keep it, or replace it with a human correction. An empty `SubCategory` means the label is the category only. The probe trains on these two columns and nothing else
- `recording` — the group that stays in one pile, or in the hand-checked set
- `pile` — `A`, `B`, `C`, `D`, `E`, `eval`, or `sample`. `eval` is the 700. `sample` is the rest of `eval-3000.csv`. Neither is trained on
- `model_prediction_1_category`, `model_prediction_1_subcategory`, and `model_confidence_1` through rank 5 — the top 5 from the probe that held this pile out, best first. Each rank is a category, a subcategory, and how sure the model is of that pair. An empty subcategory is a category-only guess. Sort the listen queue by `model_confidence_1`. Empty until that round's probe has run
- `human_category`, `human_subcategory` — the correction written this round on `pile.csv`. Empty means no correction. `eval.csv` does not have these columns

A row is blank when `Category` and `SubCategory` are both empty. Blank rows stay out of the listen queue and out of training until a later round promotes a human label into them. A filled category with an empty subcategory is a real label. The top guess disagrees with it when the category or the subcategory differs.

`recording` is filled once, while building `all.csv`:

- AudioSet: `AudioSet:` plus the video id, the filename without the leading `Y` and `.wav`
- ESC-50: `ESC-50:` plus the Freesound id, the second field of the filename (`1-101296-B-19.wav` is `101296`)
- FSD50K: `FSD50K:` plus the filename without `.wav`
- FoleySet: `FoleySet:` plus `freesound-id` from `audio/FoleySet/metadata/foleyset_metadata.csv`, matched on `filename`

`all.csv` keeps every master row, including the ones copied into the 3000. The piles are the recordings that are not in that sample, and the round folders are built from the piles. Human columns are copied onto `pile.csv` only. `train.csv` leaves them empty. The promotion script reads the five `pile.csv` files, takes `human_category` and `human_subcategory` when `human_category` is filled, even if `human_subcategory` is empty, and otherwise keeps `Category` and `SubCategory`. The new round's files start with empty human and model columns.
