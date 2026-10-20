Same test in every folder: `manifests/original-envsound/envsound_test.csv` with AudioSet removed (5260 rows, FSD50K and ESC-50). EnvSound `Category` and `SubCategory` are the original labels. FoleySet labels are the UCS labels in `scoring/experiments/min075-envsound-foleyset/`.

| Folder | Train | Val |
| --- | ---: | ---: |
| `1-original` | 40642, including 16096 AudioSet | 8707, including 3448 AudioSet |
| `2-no-audioset` | 24546 | 5259 |
| `3-audioset-same-size` | 24546, including 4951 AudioSet | 5259, including 1059 AudioSet |
| `4-no-audioset-foleyset` | 31354, including 6808 FoleySet | 6100, including 841 FoleySet |

`3-audioset-same-size` is drawn from the original split, so AudioSet clips stay eligible, but each `Category`/`SubCategory` has the same count as `2-no-audioset`. Pairs that exist only on AudioSet are in `1-original` only (113 train, 110 val). Within a pair, sources are kept in proportion and clips are evenly spaced by path.

`4-no-audioset-foleyset` is `2-no-audioset` plus the FoleySet train and val splits. 4454 of 6808 train clips and 546 of 841 val clips have a Category; the rest were ties or below the cutoff and stay blank. The 843 FoleySet test clips are left out.

Rebuild with `python scripts/make_test_envsound_no_audioset.py`.
