# Label comparison

Same clips, same train/val/test split, two UCS labelings. Train one model on each folder. A gap in micro F1 is the labels.

`original-envsound-old-labels/` uses `Category` and `SubCategory` from `manifests/original-envsound/`. `original-envsound-new-labels/` uses `Category` and `SubCategory` from `manifests/new-split/`. `filename`, `Keywords`, `source`, `path`, and `exists` are identical, and the rows are in the same order. The split is the original-envsound split, not the 70/15/15 cut in new-split.

| File | Rows |
| --- | ---: |
| `envsound_train.csv` | 40125 |
| `envsound_val.csv` | 8569 |
| `envsound_test.csv` | 8598 |

57,292 rows in each folder. 39,293 have a different `Category` or `SubCategory`. 17,999 match.

## Clips left out

`original-envsound/` has 58,057 rows. 765 have no row in new-split, so they are in neither folder here.

630 are ESC-50 clips whose Freesound id (`src_file`) is already an FSD50K clip. `make_master_manifest` drops the ESC-50 row and keeps the FSD50K wav, so the ESC-50 filename is absent. 617 of those FSD50K files were already in original-envsound and are in these folders under `source` `FSD50K`. The other 13 FSD50K counterparts are in new-split only, so they are absent here too. The ESC-50 wavs are on disk. They are 5-second excerpts of the same Freesound upload.

135 are AudioSet balanced-train clips that are not in the current `balanced_train_segments.csv` or `eval_segments.csv`. `exists` is false, and the wav is not under `audio/`.
