# audio

Local copies of the wav files named in `manifests/manual/`. A row’s file is `audio/` plus its `path` column.

```text
audio/AudioSet/audios/balanced_train_segments/*.wav
audio/AudioSet/audios/eval_segments/*.wav
audio/ESC-50/audio/*.wav
audio/FSD50K/FSD50K.dev_audio/*.wav
audio/FSD50K/FSD50K.eval_audio/*.wav
```

The slice points at 2299 files: 2019 train, 140 val, 140 test.

| Source | Directory under `audio/` | Files in the slice |
| --- | --- | ---: |
| AudioSet | `AudioSet/audios/balanced_train_segments/` | 491 |
| AudioSet | `AudioSet/audios/eval_segments/` | 386 |
| ESC-50 | `ESC-50/audio/` | 222 |
| FSD50K | `FSD50K/FSD50K.dev_audio/` | 884 |
| FSD50K | `FSD50K/FSD50K.eval_audio/` | 316 |

These recordings are the thing being labeled. `Keywords` is the non-UCS text from the source dataset. UCS `Category` and `SubCategory` are what a converter writes.

What you need depends on the method:

- **Manual.** Listen to val and test only (280 files) while you tag them. Train is not hand-labeled.
- **LLM inferred.** Read the keywords, and open the wav when the prompt uses the recording.
- **Rule-based scoring.** The script reads each source’s labels from the files in this folder, and for FSD50K also the clip title, description, uploader tags, and predominant labels. Use a wav when you want to check a rule against the sound.

The wavs are not part of the slice export. Which file belongs in train, val, or test is the CSVs in `splits/`.
