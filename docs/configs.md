# Configs

`scoring/configs/default.json` is the scorer. A run with no `--config` loads that file. Any other JSON file inherits omitted fields from it, so a config only needs the fields it changes.

See [Scoring](scoring.md) for what each weight does, and [Usage](usage.md) for how a file is passed.

## Taxonomy

`taxonomy` controls which labels are eligible.

| Value | Eligible labels |
| --- | --- |
| `"closed"` | The pairs in `closed`, or the list in `scoring/configs/default.json` when the file omits `closed`. A pair missing from the workbook is skipped. `DOORS/DOORBELL` borrows synonyms from `BELLS/DOORBELL`. |
| `"open"` | Every subcategory in the UCS workbook. |
| `{"mode": "categories", "categories": ["ALARMS", "WATER"]}` | Every subcategory in the named categories. |
| `{"mode": "pairs", "pairs": ["ALARMS/BELL", "WATER/POUR"]}` | Only those pairs. `file` can point at a text list or a CSV with `Category` and `SubCategory`. A pair missing from the workbook is an error. |

## Shipped configs

| File | Taxonomy | Splits | What it changes |
| --- | --- | --- | --- |
| `scoring/configs/default.json` | closed | test | Baseline. `min_score` 2, ties blank. |
| `scoring/configs/default-auto.json` | closed | train, val, test | Same weights as default, all three splits. |
| `scoring/configs/default-open.json` | open | train, val, test | Same weights, every subcategory in the workbook. |
| `scoring/configs/closed-strict.json` | closed | test | `exact_sub` 8, `exact_syn` 4, `word` 0.5, `min_score` 4. |
| `scoring/configs/closed-recall.json` | closed | train, val, test | `min_score` 1, `uploader_tag` 0. |
| `scoring/configs/open-recall.json` | open | train, val, test | Same as closed-recall, against the full UCS list. |
| `scoring/configs/open-weighted.json` | open | train, val, test | `exact_sub` 8, `exact_syn` 2, `word` 0.25, `depth_step` 0.5, `uploader_tag` 0, `title_match` 0.5, `description_match` 0. |
| `scoring/configs/open-weighted-min075.json` | open | train, val, test | Same weights as open-weighted, `min_score` 0.75. |

Repeat `--experiment` for each file. The experiment folder is `scoring/experiments/<name>/`, from the config’s `name` field.
