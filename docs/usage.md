# Usage

Paths are resolved from the repo root, so the working directory does not matter. The flags at the end cover the variants of each command.

## Score a manifest

```bash
python scripts/score_ucs.py manifests/slice/envsound_val.csv -o predictions.csv
```

Prints the [report](scoring.md#report). `-o` writes the same CSV plus `pred_category`, `pred_subcategory`, `pred_score`, `pred_status`, and `pred_evidence`. `Category` and `SubCategory` on that copy stay as they were.

Without `--no-audio`, the audio folder refreshes `Keywords` and the FSD50K metadata before scoring. A file that only has `filename`, `source`, and `path` can be scored the same way. Pass `--config` to use a file other than `configs/default.json`.

## Probe one keyword list

```bash
python scripts/score_ucs.py --keywords "Meow,Cat,Animal"
```

Prints the decision and the top candidates (`--top`, default 8). `--category` breaks a tie. `--pp`, `--uploader-tags`, `--title`, and `--description` are the FSD50K fields for that probe.

## Rebuild manifests

```bash
python scripts/score_ucs.py --make-manifests
```

Writes `manifests/slice/envsound_test.csv` only. Train and val stay as they are, so hand tags are not replaced. `--write-splits train,val,test`, or `"splits"` in the config, adds those files back.

Membership is the `filename`, `source`, and `path` already on the slice file. Keywords and FSD50K metadata come from `audio/`. `exists` is whether `audio/<path>` is a file. `--source-dir` defaults to `manifests/original-envsound/`. When `envsound_<split>.csv` exists there, `Category` and `SubCategory` are copied from it.

## Run an experiment

```bash
python scripts/score_ucs.py --experiment configs/default-open.json
```

Writes a fresh manifest set under `experiments/<name>/`. `manifests/slice/` stays unchanged. Repeat `--experiment` for several configs. `--experiment-dir configs` runs every JSON file in that directory except `configs/default.json`. `--experiment-name` builds one experiment from flags, or renames a single `--experiment` file. `--output-dir` changes the destination. A config may set `"output_dir"` itself.

`Category` and `SubCategory` in the experiment CSV are the scorer’s assignment. A blank prediction writes both fields empty. `config.json` is the resolved setup, including any closed pair the workbook does not contain. `report.txt` is the agreement report, one section per split.

By default an experiment scores test only. Train and val are copied from `manifests/slice/`. A config that lists those splits, or `--write-splits train,val,test`, scores them into the same folder. A split left off the list is still copied in.

## Check the scorer

```bash
python scripts/score_ucs.py --self-test
```

Checks the scorer against the full UCS list and prints the subcategory count.

## Convert with an LLM

```bash
python scripts/llm_convert.py manifests/slice/envsound_val.csv --dry-run
```

`--dry-run` prints one line per category and a token estimate. It does not call an API and it does not write a CSV.

An exact subcategory name or synonym stays with the scorer. The other rows are grouped by the `Category` on the row. Each group is one request. The system message is that category's subcategories as codes, and the user message is the keyword lines. The reply is `#1 01` or `#1 -`. The same keyword line is sent once. Wav files are not read. The system message is the same for every batch of a category, which is the prefix a provider can cache.

The UCS workbook has 753 subcategories. A category with more than `--codebook-limit` (48) of them, or a row with no category against that full list, does not get the whole list. Those lines carry the scorer's top `--top` candidates, and the model picks one of them.

A real run reads `OPENAI_API_KEY` and `OPENAI_MODEL` from the environment. A `.env` file at the repo root is loaded on startup. A variable already set in the shell stays as it is. `--model` overrides `OPENAI_MODEL`. `OPENAI_BASE_URL` sets the API root, and the default is `https://api.openai.com/v1`. Copy `.env.example` to `.env` and fill in the key and model. `-o` writes the same `pred_*` columns as the scorer. `Category` and `SubCategory` on that copy stay as they were.

```bash
python scripts/llm_convert.py manifests/slice/envsound_val.csv -o predictions.csv
python scripts/llm_convert.py --keywords "sheep" --category ANIMALS --dry-run
python scripts/llm_convert.py --self-test
```

| Flag | Use |
| --- | --- |
| `-o`, `--output` | CSV with `pred_*` columns. |
| `--config` | Taxonomy and weights. Default is `configs/default.json`. |
| `--dry-run` | Batches and a token estimate. No API call. |
| `--no-cascade` | Also send rows the scorer already matched exactly. |
| `--model`, `--base-url` | Model id and API root. |
| `--batch-size` | Keyword lines per request. Default 40. |
| `--codebook-limit` | Most subcategories in one system message. Default 48. |
| `--top` | Candidates on a line when the codebook does not fit. Default 8. |
| `--keywords`, `--category` | One keyword list. |
| `--ucs`, `--ontology` | UCS workbook and AudioSet ontology. |
| `--self-test` | Check batching against val without an API call. |

## Flags

| Flag | Use |
| --- | --- |
| `-o`, `--output` | CSV with `pred_*` columns. |
| `--config` | JSON config for a manifest score, a rebuild, or `--experiment-name`. |
| `--no-audio` | Score the columns already on the CSV. |
| `--audio`, `--ucs`, `--ontology` | Dataset root, UCS workbook, AudioSet ontology. |
| `--min-score`, `--on-tie` | Cutoff and tie handling. |
| `--set NAME=VALUE` | Override one weight or `min_score`. Repeatable. |
| `--taxonomy` | `open`, `closed`, `categories`, or `pairs`. |
| `--categories`, `--pairs` | Label lists for those taxonomy modes. |
| `--closed-slice` | Same as `--taxonomy closed`. |
| `--keywords` and `--category`, `--pp`, `--uploader-tags`, `--title`, `--description`, `--top` | One-off probe. |
| `--make-manifests`, `--write-splits`, `--source-dir`, `--manifest-dir` | Rebuild slice CSVs. |
| `--experiment`, `--experiment-dir`, `--experiment-name`, `--output-dir` | Write `experiments/<name>/`. |
| `--self-test` | Check the scorer and print the subcategory count. |
