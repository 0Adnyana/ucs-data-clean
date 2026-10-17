# make_test_audio

## Name

`make_test_audio` — copy test-split wavs into test-audio/ for listening

## Synopsis

```
python scripts/make_test_audio.py [--manifest csv] [--audio dir] [--out dir] [--link] [--dry-run]
```

## Description

Reads the `path` column of a manifest and copies each listed file from the audio directory to the same relative path under the output directory. A path listed twice is copied once. A destination file with the same size and modification time as its source is kept, and a source that is not on disk is counted and skipped. Destination files the manifest no longer lists are removed, then empty directories under the output directory are removed. The manifest and the audio directory are left unchanged.

The script prints one line with the output directory and the copy, current, missing, and remove counts, then the per-`source` count of files on disk. When 40 or fewer sources are missing, each missing path is printed too. The defaults are anchored at the repo root. A relative path given on the command line is used as given, relative to the working directory, not the repo root.

## Options

**--manifest** *csv*

CSV with a `path` column, each path relative to the audio directory. Default is `manifests/blank-envsound/envsound_test.csv`.

```bash
python scripts/make_test_audio.py --manifest manifests/envsound-foleyset/envsound_test.csv
```

**--audio** *dir*

Dataset root that the `path` column is relative to. Default is `audio/`.

```bash
python scripts/make_test_audio.py --audio audio
```

**--out** *dir*

Destination folder, created if needed. Default is `test-audio/`.

```bash
python scripts/make_test_audio.py --out test-audio
```

**--link**

Hard-links each file instead of copying it, and falls back to a copy when the link fails, such as across drives. Off by default.

```bash
python scripts/make_test_audio.py --link
```

**--dry-run**

Prints the plan, prefixed with `dry run`, without copying, linking, or deleting anything. Off by default.

```bash
python scripts/make_test_audio.py --dry-run
```

## Files

`manifests/blank-envsound/envsound_test.csv` — default `--manifest`.

`audio/` — default `--audio`.

`test-audio/` — default `--out`, gitignored.

## Exit status

0 on success.

2 on an argument error from argparse, such as an unknown option.

1 when the program stops with a message on stderr, before anything is written. The messages are:

- `manifest not found: <path>`
- `<path> has no path column`
- `unsafe audio path: '<value>'`, for an empty, absolute, or `..` path in the manifest

## See also

[Data](../data.md), [make_split_manifest](make_split_manifest.md), [make_envsound_foleyset](make_envsound_foleyset.md)
