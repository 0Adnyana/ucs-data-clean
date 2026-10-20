# Usage

These are the manuals for the scripts, with paths given repo-relative.

- [`score_ucs`](scripts/score_ucs.md) — score keywords against the UCS list
- [`make_master_manifest`](scripts/make_master_manifest.md) — build manifests/master.csv from the dataset metadata in audio/
- [`make_label_map_base`](scripts/make_label_map_base.md) — build a label map of the unique keywords in audio/, assigning each label a role
- [`make_split_manifest`](scripts/make_split_manifest.md) — split a manifest into train, val, and test at 70/15/15
- [`make_envsound_foleyset`](scripts/make_envsound_foleyset.md) — build manifests/envsound-foleyset from blank-envsound plus FoleySet
- [`make_test_envsound_no_audioset`](scripts/make_test_envsound_no_audioset.md) — build the AudioSet ablation manifests under manifests/test-envsound-no-audioset/
- [`make_test_audio`](scripts/make_test_audio.md) — copy test-split wavs into test-audio/ for listening
