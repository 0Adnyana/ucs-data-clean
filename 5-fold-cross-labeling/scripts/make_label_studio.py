"""Write a Label Studio config for one of the two listen jobs.

``pile`` is the mismatch queue. Import a row only when its current pair is
not in the model's top 5. The config shows that pair and the top 5, then the
same searchable list as ``eval``. ``clear`` stores the taxonomy path in
``human_category`` and ``human_subcategory``. ``ambiguous`` stores the
category only, so ``human_subcategory`` stays empty.

``eval`` is the hand check of ``splits/original-labeled/eval.csv``. There is
no model and no human columns. A searchable category to subcategory list
records what you hear. Hover a subcategory for its description. ``clear``
requires a subcategory. ``ambiguous`` replaces that list with the categories
alone, so ``SubCategory`` stays empty. The lists are UCS v8.2.1.

Both configs play ``/data/local-files/?d=audio/$path``. ``path`` is the CSV
column, so import ``eval.csv`` or a ``pile.csv`` directly. The wav is
``audio/<path>`` in this repo. Start Label Studio with local file serving on
and ``LABEL_STUDIO_LOCAL_FILES_DOCUMENT_ROOT`` set to the repo root. The
setup preview fills ``$path`` with sample text and that URL 404s. Open an
imported row to hear the clip.

Usage:
  python 5-fold-cross-labeling/scripts/make_label_studio.py --mode eval -o 5-fold-cross-labeling/label_studio_eval.xml
  python 5-fold-cross-labeling/scripts/make_label_studio.py -o 5-fold-cross-labeling/label_studio.xml
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import sys
from collections import OrderedDict
from pathlib import Path
from typing import NamedTuple
from urllib.parse import quote

from fold_csv import ROOT, display, resolve_under_root

DEFAULT_UCS = (
    ROOT
    / "references"
    / "beck_lerch_tools"
    / "ucs-sfx-tools-main"
    / "UCS_Convert"
    / "UCS_v8.2.1_Full_List.csv"
)

STYLE = """\
  <Style>
    .meta { display: flex; gap: 1.5rem; align-items: flex-start; }
    .col { flex: 1; min-width: 0; }
  </Style>"""

PILE_CONFIG = """\
<View>
{style}

  <Header value="$filename"/>
  <Audio name="audio" value="/data/local-files/?d=audio/$path" zoom="true"/>

  <View className="meta">
    <View className="col">
      <Header value="Source" size="5"/>
      <Text name="source" value="$source"/>
      <Header value="Pile" size="5"/>
      <Text name="pile" value="$pile"/>
      <Header value="Path" size="5"/>
      <Text name="path_text" value="$path"/>
      <Header value="Keywords" size="5"/>
      <Text name="keywords" value="$Keywords"/>
    </View>
    <View className="col">
      <Header value="Current label" size="5"/>
      <Text name="category" value="$Category"/>
      <Text name="subcategory" value="$SubCategory"/>
      <Header value="Model top 5" size="5"/>
      <Header value="1" size="5"/>
      <Text name="p1_category" value="$model_prediction_1_category"/>
      <Text name="p1_subcategory" value="$model_prediction_1_subcategory"/>
      <Text name="p1_confidence" value="$model_confidence_1"/>
      <Header value="2" size="5"/>
      <Text name="p2_category" value="$model_prediction_2_category"/>
      <Text name="p2_subcategory" value="$model_prediction_2_subcategory"/>
      <Text name="p2_confidence" value="$model_confidence_2"/>
      <Header value="3" size="5"/>
      <Text name="p3_category" value="$model_prediction_3_category"/>
      <Text name="p3_subcategory" value="$model_prediction_3_subcategory"/>
      <Text name="p3_confidence" value="$model_confidence_3"/>
      <Header value="4" size="5"/>
      <Text name="p4_category" value="$model_prediction_4_category"/>
      <Text name="p4_subcategory" value="$model_prediction_4_subcategory"/>
      <Text name="p4_confidence" value="$model_confidence_4"/>
      <Header value="5" size="5"/>
      <Text name="p5_category" value="$model_prediction_5_category"/>
      <Text name="p5_subcategory" value="$model_prediction_5_subcategory"/>
      <Text name="p5_confidence" value="$model_confidence_5"/>
    </View>
  </View>

  <Header value="What you hear"/>
{fields}
</View>
"""

EVAL_CONFIG = """\
<View>
{style}

  <Header value="$filename"/>
  <Audio name="audio" value="/data/local-files/?d=audio/$path" zoom="true"/>

  <View className="meta">
    <View className="col">
      <Header value="Source" size="5"/>
      <Text name="source" value="$source"/>
      <Header value="Path" size="5"/>
      <Text name="path_text" value="$path"/>
      <Header value="Keywords" size="5"/>
      <Text name="keywords" value="$Keywords"/>
    </View>
    <View className="col">
      <Header value="Script label" size="5"/>
      <Text name="category" value="$Category"/>
      <Text name="subcategory" value="$SubCategory"/>
    </View>
  </View>

  <Header value="What you hear"/>
{fields}
</View>
"""

CONFIGS = {"pile": PILE_CONFIG, "eval": EVAL_CONFIG}


class Leaf(NamedTuple):
    name: str
    hint: str


def subcategory_hint(explanation: str, synonyms: str) -> str:
    explanation = " ".join(explanation.split())
    synonyms = " ".join(synonyms.split())
    if explanation and synonyms:
        return f"{explanation}  Synonyms: {synonyms}"
    if explanation:
        return explanation
    if synonyms:
        return f"Synonyms: {synonyms}"
    return ""


def load_taxonomy(path: Path) -> OrderedDict[str, list[Leaf]]:
    """Category to subcategories, in file order. The UCS list has a two-line preamble."""
    if not path.is_file():
        raise SystemExit(f"file not found: {display(path)}")
    with path.open(newline="", encoding="utf-8") as handle:
        next(handle)
        next(handle)
        rows = list(csv.DictReader(handle))
    if not rows or "Category" not in rows[0] or "SubCategory" not in rows[0]:
        raise SystemExit(f"{display(path)} is missing Category or SubCategory")
    categories: OrderedDict[str, list[Leaf]] = OrderedDict()
    for row in rows:
        category = (row.get("Category") or "").strip()
        subcategory = (row.get("SubCategory") or "").strip()
        if not category or not subcategory:
            continue
        subs = categories.setdefault(category, [])
        if any(item.name == subcategory for item in subs):
            continue
        subs.append(
            Leaf(
                subcategory,
                subcategory_hint(
                    (row.get("Explanations") or "").strip(),
                    (row.get("Synonyms - Comma Separated") or "").strip(),
                ),
            )
        )
    if not categories:
        raise SystemExit(f"{display(path)} has no categories")
    return categories


def _choice(value: str, *, hint: str = "") -> str:
    suffix = f' hint="{html.escape(hint, quote=True)}"' if hint else ""
    return f'        <Choice value="{html.escape(value, quote=True)}"{suffix}/>'


def taxonomy_xml(categories: OrderedDict[str, list[Leaf]], *, hints: bool = False) -> str:
    blocks: list[str] = []
    for category, subs in categories.items():
        children = "\n".join(_choice(sub.name, hint=sub.hint if hints else "") for sub in subs)
        blocks.append(
            f'      <Choice value="{html.escape(category, quote=True)}">\n{children}\n      </Choice>'
        )
    return "\n".join(blocks)


def eval_fields(categories: OrderedDict[str, list[Leaf]]) -> str:
    """Searchable subcategory list, or categories alone when the clip is ambiguous."""
    count = sum(len(subs) for subs in categories.values())
    categories_xml = "\n".join(_choice(category) for category in categories)
    return f"""\
  <!-- UCS list: {len(categories)} categories, {count} subcategories. Hover a subcategory for its description. -->
  <Header value="UCS Category → SubCategory (type to search)"/>
  <Taxonomy name="ucs" toName="audio" leafsOnly="true" showFullPath="true" maxUsages="1"
            placeholder="Search UCS…" required="true"
            visibleWhen="choice-unselected" whenTagName="subcategory_clear" whenChoiceValue="ambiguous">
{taxonomy_xml(categories, hints=True)}
  </Taxonomy>
  <Choices name="subcategory_clear" toName="audio" choice="single-radio" showInline="true" required="true">
    <Choice value="clear"/>
    <Choice value="ambiguous" hint="Select the category only"/>
  </Choices>
  <View visibleWhen="choice-selected" whenTagName="subcategory_clear" whenChoiceValue="ambiguous">
    <Header value="Category only (type to search)"/>
    <Taxonomy name="category_only" toName="audio" leafsOnly="true" maxUsages="1"
              placeholder="Search category…" required="true">
{categories_xml}
    </Taxonomy>
  </View>"""


def labeling_config(categories: OrderedDict[str, list[Leaf]], mode: str) -> str:
    return CONFIGS[mode].format(style=STYLE, fields=eval_fields(categories))


def audio_url(path: str) -> str:
    """Label Studio local-file URL for ``audio/<path>`` under the repo root."""
    relative = path.strip().lstrip("/")
    if not relative or relative.startswith("..") or "/../" in f"/{relative}/":
        raise SystemExit(f"refusing audio path {path!r}")
    return "/data/local-files/?d=" + quote(f"audio/{relative}", safe="/")


def load_tasks(path: Path) -> tuple[list[dict[str, dict[str, str]]], int]:
    """One Label Studio task per CSV row, with ``audio`` added from ``path``."""
    if not path.is_file():
        raise SystemExit(f"file not found: {display(path)}")
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or "path" not in rows[0]:
        raise SystemExit(f"{display(path)} is missing path")
    tasks: list[dict[str, dict[str, str]]] = []
    missing = 0
    for row in rows:
        relative = (row.get("path") or "").strip()
        if not relative:
            raise SystemExit(f"{display(path)} has a row with an empty path")
        if not (ROOT / "audio" / relative).is_file():
            missing += 1
        data = {"audio": audio_url(relative)}
        data.update(row)
        tasks.append({"data": data})
    return tasks, missing


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Write a Label Studio config or a task file for the listen queue.")
    parser.add_argument("--mode", choices=tuple(CONFIGS), default="pile", help="pile review, or eval.csv hand labels")
    parser.add_argument("--ucs", type=Path, default=DEFAULT_UCS, help="UCS category list CSV")
    parser.add_argument("--tasks", type=Path, default=None, help="CSV to turn into Label Studio tasks; skips the XML")
    parser.add_argument("-o", "--output", type=Path, default=None, help="file to write (default: stdout)")
    args = parser.parse_args(argv)

    if args.tasks is not None:
        tasks, missing = load_tasks(resolve_under_root(args.tasks))
        payload = json.dumps(tasks, indent=2, ensure_ascii=False) + "\n"
        note = f"{len(tasks)} tasks"
        if missing:
            note += f", {missing} missing wavs"
        if args.output is None:
            print(payload, end="")
            print(note, file=sys.stderr)
            return
        output = resolve_under_root(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
        print(f"wrote {display(output)} ({note})")
        return

    config = labeling_config(load_taxonomy(resolve_under_root(args.ucs)), args.mode)
    if args.output is None:
        print(config, end="")
        return
    output = resolve_under_root(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(config, encoding="utf-8")
    print(f"wrote {display(output)}")


if __name__ == "__main__":
    main()
