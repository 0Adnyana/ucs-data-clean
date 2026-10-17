# make_envsound_foleyset

## Name

`make_envsound_foleyset` — build manifests/envsound-foleyset from blank-envsound plus FoleySet

## Synopsis

```
python scripts/make_envsound_foleyset.py
```

## Description

Reads the three `manifests/blank-envsound/` splits and the FoleySet metadata, and writes `envsound_train.csv`, `envsound_val.csv`, and `envsound_test.csv` to `manifests/envsound-foleyset/`. Each output holds the blank-envsound rows of that split, cut to the manifest and metadata columns, followed by the FoleySet clips whose `split` names it. A FoleySet clip is left out when its `freesound-id` matches an FSD50K `fname` or an ESC-50 `src_file` in the source metadata under `audio/`, whatever split either clip is in; AudioSet ids are not compared. The blank-envsound manifests and everything under `audio/` are left unchanged; the row counts of the last build are in [Data](../data.md).

The script prints how many FoleySet clips were left out, which split the shared uploads sit in, and one line per output with its row counts and the number of FoleySet audio files missing. It has no argument parser and ignores any arguments given. Every path is fixed and anchored at the repo root through the location of `scripts/score_ucs.py`, so the working directory does not matter.

## Options

None.

## Files

`manifests/blank-envsound/envsound_train.csv`, `envsound_val.csv`, and `envsound_test.csv` — base rows.

`audio/FoleySet/metadata/foleyset_metadata.csv` — FoleySet clips, splits, and Freesound ids.

`audio/FSD50K/FSD50K.ground_truth/dev.csv` and `eval.csv` — FSD50K Freesound ids.

`audio/ESC-50/meta/esc50.csv` — ESC-50 Freesound ids.

`audio/FoleySet/audio/` — checked for each kept clip to fill `exists`.

`manifests/envsound-foleyset/envsound_train.csv`, `envsound_val.csv`, and `envsound_test.csv` — output, overwritten.

## Exit status

0 on success.

1 when the program stops with a message on stderr. The messages are:

- `FoleySet split must be train, val, or test, got '<split>'`
- `blank-envsound <split> is missing columns: <columns>`

The missing-columns check runs split by split, so the outputs for earlier splits are already written when it fails. A missing input file ends the program with an uncaught `FileNotFoundError` traceback and status 1.

## See also

[Data](../data.md), [score_ucs](score_ucs.md), [make_split_manifest](make_split_manifest.md)
