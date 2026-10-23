# Precision sample

`label_studio.xml` is the labeling config. `tasks.json` is the 100 clips. Paste the config into a project and import `tasks.json`. Set `LABEL_STUDIO_LOCAL_FILES_DOCUMENT_ROOT` to the parent repository, the folder that contains `audio/`, and turn local file serving on. The player loads `audio/` plus `path`.

In the data manager, hide `suggested`. This file has no `model_prediction_*` columns. `suggested` is the model’s pick.

## Rules

Write these down before you listen. They belong in the thesis appendix.

`label_wrong` = 1: the given label doesn’t describe the predominant sound. A sound librarian would move this file.

`label_wrong` = 0: the given label is an acceptable UCS label for the predominant sound, even if the suggestion is also acceptable.

`label_wrong` = ?: you can’t tell (too quiet, too mixed, unrecognisable sound). Don’t force a 0 or 1.

MISC counts as wrong only if a specific subcategory clearly fits.

## Listen

The screen starts with the clip, `Category`, `SubCategory`, and `Keywords`. Fill `label_wrong`.

`suggested` then appears. Fill `predominant_is`: `given`, `suggested`, `other`, or `unclear`.

If you chose `other`, fill `human_category` and `human_subcategory`. The picker stores that pair on `human_pair`: the first item is the category, the second is the subcategory.

Use `notes` for a pattern. Examples: rock music again, speech over everything.
