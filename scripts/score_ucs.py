"""Score non-UCS keywords against the Universal Category System.

Each source tag is compared with every UCS subcategory in
``UCS v8.2.1 Full List.xlsx``. The highest score wins. A row is left
blank when the best score is under the config's ``min_score``, or when
two subcategories in different categories still tie. A tie inside one
category keeps that category and leaves SubCategory blank. A tag that
is a category name (``Fire``, ``Alarm``, ``Door``, ``Water``, and the
same with a plural) does the same when no single subcategory outranks
it. A tag whose words are a category name and a subcategory of that
category scores as that pair (``clock alarm`` is ALARMS/CLOCK). Two
category words that do not form such a pair (``fire alarm``) stay
unresolved. If the row already has a Category and exactly one tied
subcategory is in that category, that one is kept.

An exact synonym or subcategory name counts when it is one token of a
longer label, and a plural or ``-ing`` stem counts as that word
(``sneezing`` is ``sneeze``). A token that is a synonym of more than
one subcategory stays a word hit. A category word in a longer label
chooses a shared subcategory name (``door wood knock`` is DOORS/KNOCK).

The points, the cutoff, tie handling, and the default taxonomy live in
``configs/default.json``. That file is what a run uses when no other
config is passed. An exact subcategory or synonym is a fixed score.
Each overlapping word in a synonym or the explanation adds ``word``.
Ontology depth multiplies those points by ``1 + depth_step * depth``.
A predominant label adds ``pp_bonus`` afterwards, and only for
subcategories the tag already matched. An uploader tag, the title, and
the description add their own weights when the subcategory name or a
synonym matches.

Depth comes from the AudioSet ontology. A root label is depth 0 and
stays at x1. With the shipped ``depth_step`` of 0.25, depth 2 (Dog,
Pour, Siren) is x1.5. Tags that are not in the ontology stay at x1.

An exact name or synonym replaces word overlap for that same tag, so
the matched words are not counted twice. The depth factor multiplies
that tag's lexical points. PP is added afterwards, and only for
subcategories the tag already matched.

The tags themselves come from the dataset files under ``audio/``, which is
the layout the UCS paper converts:

  AudioSet   ``audio/AudioSet/audios/*_segments.csv`` ``human_labels``
  ESC-50     ``audio/ESC-50/meta/esc50.csv`` ``category``
  FSD50K     ``audio/FSD50K/FSD50K.ground_truth/{dev,eval}.csv`` ``labels``

FSD50K also contributes the metadata shipped beside those wavs.
``pp_pnp_ratings_FSD50K.json`` supplies predominant labels (a rating of
1.0), including classes that the ground truth later merged into a parent.
A predominant label that is not already a keyword is scored as its own
tag. ``dev_clips_info_FSD50K.json`` and ``eval_clips_info_FSD50K.json``
supply uploader tags, the title, and the description. A match there is the subcategory name or a synonym as a whole phrase.
The points are ``uploader_tag``, ``title_match``, and ``description_match``
in ``configs/default.json``.
Those fields are also read from the manifest when the audio folder is
not used (``--no-audio``).

``--make-manifests`` reads ``splits/train.csv``, ``splits/val.csv``, and
``splits/test.csv``. Each row is only ``filename``, ``source``, and ``path``.
Keywords and the FSD50K metadata columns come from the dataset files
above. ``exists`` is whether ``audio/<path>`` is on disk. Category and
SubCategory are kept from the manifest already in ``manifests/manual/``
when that file is there. ``--source-dir`` can point at full
``envsound_*.csv`` lists instead. By default only
``manifests/manual/envsound_test.csv`` is written. Train and val stay
untouched so hand tags are not replaced. ``--write-splits`` or a config
``splits`` list adds them back.

An experiment config (see ``configs/``) changes the weights, the minimum
score, tie handling, and how much of the UCS list is eligible. Each
experiment writes its own manifests under ``experiments/<name>/`` and does
not modify ``manifests/manual/``. Those copies are what a separate
linear-probing project trains and compares. A split the config does not
list is copied from ``manifests/manual/`` into that same output folder, so
train and val are present even when only test is scored.

Usage:
  python scripts/score_ucs.py --make-manifests
  python scripts/score_ucs.py --make-manifests --write-splits train,val,test
  python scripts/score_ucs.py --experiment configs/default-open.json
  python scripts/score_ucs.py --experiment-dir configs
  python scripts/score_ucs.py --experiment-name open-min4 --taxonomy open --min-score 4
  python scripts/score_ucs.py manifests/manual/envsound_test.csv --config configs/default-open.json
  python scripts/score_ucs.py --keywords "Meow,Cat,Animal"
  python scripts/score_ucs.py --self-test
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import re
import shutil
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field, replace
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_UCS = ROOT / "UCS v8.2.1 Full List.xlsx"
DEFAULT_ONTOLOGY = Path(__file__).resolve().parent / "audioset_ontology.json"
DEFAULT_SPLITS = ROOT / "splits"
DEFAULT_MANIFESTS = ROOT / "manifests" / "manual"
DEFAULT_AUDIO = ROOT / "audio"
# Optional full envsound_*.csv lists, looked up beside this repo.
# They are not part of the audio tree.
DEFAULT_SOURCE = ROOT.parent
DEFAULT_CONFIG = ROOT / "configs" / "default.json"
SPLIT_NAMES = ("train", "val", "test")
# Train and val are hand-tagged. Nothing writes them unless asked.
DEFAULT_WRITE_SPLITS = ("test",)
TAXONOMY_MODES = ("open", "closed", "categories", "pairs")
WEIGHT_NAMES = (
    "exact_sub",
    "exact_syn",
    "word",
    "depth_step",
    "pp_bonus",
    "uploader_tag",
    "title_match",
    "description_match",
)
CONFIG_KEYS = frozenset(
    {"name", "note", "taxonomy", "closed", "min_score", "on_tie", "weights", "splits", "output_dir"}
)
MANIFEST_COLUMNS = [
    "filename",
    "Category",
    "SubCategory",
    "Keywords",
    "source",
    "path",
    "exists",
]
META_COLUMNS = ["pp_labels", "uploader_tags", "title", "description"]


def as_finite(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SystemExit(f"{name} must be a number")
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise SystemExit(f"{name} must be finite")
    return number


@dataclass(frozen=True)
class Weights:
    """Points added or multiplied while one tag is scored against one subcategory.

    The numbers come from ``configs/default.json``, not from this class.
    """

    exact_sub: float
    exact_syn: float
    word: float
    depth_step: float
    pp_bonus: float
    uploader_tag: float
    title_match: float
    description_match: float

    def with_values(self, **changes: object) -> Weights:
        unknown = sorted(set(changes) - set(WEIGHT_NAMES))
        if unknown:
            raise SystemExit(f"unknown weight: {', '.join(unknown)}")
        return replace(self, **{key: as_finite(key, value) for key, value in changes.items()})

STOP = frozenset(
    """
    a an the of or and to in on for with from by at as is are be was were
    this that these those it its into over under than then not but if so
    such also other would could should may might can will just only all
    any some no nor per via out up down off about onto within without
    between among across after before during while where when which who
    what how their them they his her she him you your our we do does did
    have has had been being because both each few more most same too very
    own now here there than etc see
    """.split()
)


@dataclass(frozen=True)
class Entry:
    category: str
    subcategory: str
    sub_key: str


@dataclass
class Catalog:
    entries: list[Entry]
    sub_index: dict[str, list[int]]
    syn_index: dict[str, list[int]]
    word_index: dict[str, list[int]]
    depths: dict[str, int]
    alias: dict[str, str]
    # Whole-tag names that mean a category: "fire", and "alarm" for ALARMS.
    category_alias: dict[str, str] = field(default_factory=dict)

    def depth_of(self, raw_tag: str) -> int | None:
        key = norm_phrase(raw_tag)
        name = self.alias.get(key)
        if name is None:
            return None
        return self.depths[name]

    def bonus_of(self, raw_tag: str, depth_step: float | None = None) -> float:
        if depth_step is None:
            depth_step = default_config().weights.depth_step
        depth = self.depth_of(raw_tag)
        if depth is None:
            return 1.0
        return 1.0 + depth_step * depth


@dataclass
class Prediction:
    category: str = ""
    subcategory: str = ""
    score: float = 0.0
    status: str = "below"
    evidence: str = ""
    ranked: list[tuple[str, str, float, str]] = field(default_factory=list)
    # Every subcategory that shares the best score. Empty when nothing matched.
    ties: list[tuple[str, str, float]] = field(default_factory=list)


def norm_phrase(text: str) -> str:
    text = text.lower().replace("_", " ").replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def split_labels(text: str) -> list[str]:
    """Split a keyword list.

    AudioSet labels contain commas of their own ("Waves, surf"). In these
    manifests the separator between labels is a comma that is not followed
    by a space. Commas inside a label are followed by a space.
    """
    text = (text or "").strip()
    if not text:
        return []
    return [part.strip() for part in re.split(r",(?=\S)", text) if part.strip()]


def content_words(phrase: str) -> list[str]:
    words: list[str] = []
    for word in phrase.split():
        if len(word) < 3 or word in STOP or word in words:
            continue
        words.append(word)
    return words


def word_forms(word: str) -> set[str]:
    """Plural and -ing variants, so "sneezing" overlaps "sneeze" once."""
    forms = {word}
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        forms.add(word[:-1])
    if len(word) > 5 and word.endswith("ing"):
        stem = word[:-3]
        if len(stem) >= 3:
            forms.add(stem)
            if stem[-1] not in "aeiou":
                forms.add(stem + "e")
    if len(word) > 4 and word.endswith("e") and not word.endswith("ee"):
        stem = word[:-1]
        if len(stem) >= 3:
            forms.add(stem)
            forms.add(stem + "ing")
    return {form for form in forms if len(form) >= 3 and form not in STOP}


def category_alias_keys(category: str) -> set[str]:
    """Forms that name a category by themselves: FIRE, and ALARMS as alarm."""
    key = norm_phrase(category)
    if not key:
        return set()
    keys = {key}
    # "alarms" -> "alarm". Leave "glass" and "weather" alone.
    if len(key) > 4 and key.endswith("s") and not key.endswith("ss"):
        keys.add(key[:-1])
    return keys


def alias_keys(name: str) -> set[str]:
    keys = {norm_phrase(name)}
    if ", " in name:
        swapped = re.sub(r"\band and\b", "and", name.replace(", ", " and "), flags=re.I)
        keys.add(norm_phrase(swapped))
    return {key for key in keys if key}


def load_ontology(path: Path) -> tuple[dict[str, int], dict[str, str]]:
    depths = json.loads(path.read_text(encoding="utf-8"))
    alias: dict[str, str] = {}
    for name in depths:
        for key in alias_keys(name):
            previous = alias.get(key)
            if previous is None or depths[name] > depths[previous]:
                alias[key] = name
    return depths, alias


def load_ucs(path: Path, allowed: set[tuple[str, str]] | None) -> list[tuple[str, str, str, str]]:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook.active
        rows = sheet.iter_rows(values_only=True)
        header = None
        for row in rows:
            if row and row[0] == "Category":
                header = [cell or "" for cell in row]
                break
        if header is None:
            raise SystemExit(f"no header row in {path}")
        index = {name: pos for pos, name in enumerate(header) if name}
        needed = ("Category", "SubCategory", "Explanations", "Synonyms - Comma Separated")
        missing = [name for name in needed if name not in index]
        if missing:
            raise SystemExit(f"{path} is missing columns: {', '.join(missing)}")
        parsed: list[tuple[str, str, str, str]] = []
        for row in rows:
            if not row or not row[0] or not row[1]:
                continue
            category = str(row[index["Category"]]).strip()
            subcategory = str(row[index["SubCategory"]]).strip()
            if not category or not subcategory or category == "Category":
                continue
            if allowed is not None and (category, subcategory) not in allowed:
                continue
            explanation = row[index["Explanations"]] or ""
            synonyms = row[index["Synonyms - Comma Separated"]] or ""
            parsed.append((category, subcategory, str(explanation), str(synonyms)))
        return parsed
    finally:
        workbook.close()


def build_catalog(
    records: list[tuple[str, str, str, str]],
    depths: dict[str, int],
    alias: dict[str, str],
) -> Catalog:
    entries: list[Entry] = []
    sub_index: dict[str, list[int]] = defaultdict(list)
    syn_index: dict[str, list[int]] = defaultdict(list)
    word_index: dict[str, list[int]] = defaultdict(list)
    indexed_words: set[tuple[str, int]] = set()

    def add_word(form: str, idx: int) -> None:
        if (form, idx) in indexed_words:
            return
        indexed_words.add((form, idx))
        word_index[form].append(idx)

    for category, subcategory, explanation, synonyms in records:
        sub_key = norm_phrase(subcategory)
        if not sub_key:
            continue
        idx = len(entries)
        entries.append(Entry(category, subcategory, sub_key))
        sub_index[sub_key].append(idx)
        for piece in synonyms.split(","):
            key = norm_phrase(piece)
            if not key or key == sub_key:
                continue
            syn_index[key].append(idx)
            for word in content_words(key):
                for form in word_forms(word):
                    add_word(form, idx)
        for word in content_words(norm_phrase(explanation)):
            for form in word_forms(word):
                add_word(form, idx)

    owners: dict[str, set[str]] = defaultdict(set)
    for entry in entries:
        for alias_key in category_alias_keys(entry.category):
            owners[alias_key].add(entry.category)
    category_alias = {alias_key: next(iter(names)) for alias_key, names in owners.items() if len(names) == 1}
    return Catalog(
        entries,
        dict(sub_index),
        dict(syn_index),
        dict(word_index),
        depths,
        alias,
        category_alias,
    )


def _ngram_hits(text: str, catalog: Catalog) -> set[int]:
    tokens = [word for word in norm_phrase(text).split() if word not in STOP and len(word) >= 2]
    found: set[int] = set()
    count = len(tokens)
    for length in range(1, 5):
        if length > count:
            break
        for start in range(count - length + 1):
            gram = " ".join(tokens[start : start + length])
            found.update(catalog.sub_index.get(gram, ()))
            found.update(catalog.syn_index.get(gram, ()))
    return found


def _format_evidence(reasons: list[tuple[float, str]]) -> str:
    parts = [text for _, text in sorted(reasons, key=lambda item: item[0], reverse=True)]
    evidence = "; ".join(parts)
    if len(evidence) > 500:
        return evidence[:497] + "..."
    return evidence


def _named_category(catalog: Catalog, key: str) -> tuple[str, str] | None:
    """Return ``(category, matched form)`` when a tag names one category.

    The whole tag counts (``Fire``, ``Alarm``). So does a longer tag that
    contains one category word (``car alarm``, ``crackling fire``). Two
    category words (``fire alarm``, ``clock alarm``) stay unresolved here.
    ``_paired_subcategory`` can still match ``clock alarm`` to ALARMS/CLOCK.
    """
    direct = catalog.category_alias.get(key)
    if direct:
        return direct, key
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for word in content_words(key):
        category = catalog.category_alias.get(word)
        if category and category not in seen:
            seen.add(category)
            found.append((category, word))
    if len(found) == 1:
        return found[0]
    return None


def _paired_subcategory(catalog: Catalog, key: str) -> int | None:
    """Return the subcategory named by a category word plus that subcategory.

    ``clock alarm`` is ALARMS/CLOCK: ``alarm`` names ALARMS, and the
    remaining word is that category's subcategory. ``clock`` also names
    CLOCKS, which has no subcategory ALARM, so that reading is dropped.
    ``fire alarm`` matches neither way. Two different pairs are left
    unresolved. Extra words keep the tag on the word-overlap path.
    """
    words = content_words(key)
    if len(words) < 2:
        return None
    found: list[int] = []
    for index, category_word in enumerate(words):
        category = catalog.category_alias.get(category_word)
        if category is None:
            continue
        remainder = words[:index] + words[index + 1 :]
        if not remainder:
            continue
        hits = [
            idx
            for idx in catalog.sub_index.get(" ".join(remainder), ())
            if catalog.entries[idx].category == category
        ]
        if not hits and len(remainder) > 1:
            remainder_words = set(remainder)
            hits = [
                idx
                for idx, entry in enumerate(catalog.entries)
                if entry.category == category
                and len(entry.sub_key.split()) == len(remainder)
                and set(entry.sub_key.split()) == remainder_words
            ]
        found.extend(hits)
    unique = list(dict.fromkeys(found))
    if len(unique) == 1:
        return unique[0]
    return None


def _name_hits(catalog: Catalog, word: str) -> list[int]:
    """Subcategories whose name is this word or its plural / -ing stem."""
    found: list[int] = []
    for form in word_forms(word):
        found.extend(catalog.sub_index.get(form, ()))
    return list(dict.fromkeys(found))


def _modified_pair(catalog: Catalog, key: str) -> int | None:
    """A category word choosing a shared subcategory name, plus a modifier.

    ``door wood knock``: ``knock`` is the name of DOORS/KNOCK and
    WINDOWS/KNOCK, and ``door`` picks the door. ``wood`` is itself a
    category word, so it is not a second sound. Two-word labels stay on
    the other paths (``pouring water`` still ties the two pours).
    """
    words = content_words(key)
    if len(words) < 3:
        return None
    category_words = [word for word in words if word in catalog.category_alias]
    sound_hits: list[int] = []
    sound_tokens = 0
    for word in words:
        if word in catalog.category_alias:
            continue
        hits = _name_hits(catalog, word)
        if not hits:
            continue
        sound_tokens += 1
        sound_hits = hits
    if sound_tokens != 1:
        return None
    chosen: list[int] = []
    for word in category_words:
        category = catalog.category_alias[word]
        chosen.extend(idx for idx in sound_hits if catalog.entries[idx].category == category)
    unique = list(dict.fromkeys(chosen))
    if len(unique) == 1:
        return unique[0]
    return None


def _contained_kinds(catalog: Catalog, key: str) -> dict[int, tuple[str, int]]:
    """Exact name or synonym of a token inside the label, including a stem.

    ``Burping, eructation`` contains the synonym ``burping``. ``sneezing``
    stems to the name ``sneeze``. The token has to name one subcategory;
    a shared word such as ``open`` or ``trickle`` stays a word hit.
    ``door wood knock`` is resolved separately.
    """
    words = content_words(key)
    # A one-word label can be the stem of the subcategory name ("sneezing").
    # Inside a longer label the name is not taken ("car" in "car alarm",
    # "pour" in "pouring water"). A synonym token still counts
    # ("burping" in "burping, eructation"). A shared name with a modifier
    # is handled by ``_modified_pair``.
    single = len(words) == 1
    # Only a token that names one subcategory. "Burping" and the stem
    # "sneeze" qualify. "Open" does not get to stack with "close", and
    # "trickle" stays a word hit so two such words still outrank one.
    hits: dict[int, int] = defaultdict(int)
    for word in words:
        if word in catalog.category_alias:
            continue
        forms = word_forms(word)
        synonyms: set[int] = set()
        for form in forms:
            synonyms.update(catalog.syn_index.get(form, ()))
        named = set(_name_hits(catalog, word)) if single else set()
        if len(named) != 1:
            named = set()
        if len(synonyms) > 1 or (not synonyms and not named):
            continue
        if len(synonyms) == 1 or len(named) == 1:
            for idx in synonyms | named:
                hits[idx] += 1
    return {idx: ("exact synonym", count) for idx, count in hits.items()}


def score_text(
    catalog: Catalog,
    keywords: str,
    *,
    category: str = "",
    pp_labels: str = "",
    uploader_tags: str = "",
    title: str = "",
    description: str = "",
    min_score: float | None = None,
    weights: Weights | None = None,
    on_tie: str = "blank",
    keep_ranked: int = 0,
) -> Prediction:
    if weights is None or min_score is None:
        builtin = default_config()
        if weights is None:
            weights = builtin.weights
        if min_score is None:
            min_score = builtin.min_score
    if on_tie not in ("blank", "first"):
        raise SystemExit(f"on_tie must be blank or first, got {on_tie!r}")
    scores: dict[int, float] = defaultdict(float)
    reasons: dict[int, list[tuple[float, str]]] = defaultdict(list)
    # Exact names and synonyms, excluding synonyms that only repeat a category
    # word ("Fire" listed under an alarm). A different tag such as surf still counts.
    solid: dict[int, float] = defaultdict(float)
    # Subcategory points from tags that do not name a category. "surf" beside
    # Wind still counts; the alarm synonyms of the single tag Fire do not.
    other_tag: dict[int, float] = defaultdict(float)
    category_scores: dict[str, float] = defaultdict(float)
    category_reasons: dict[str, list[tuple[float, str]]] = defaultdict(list)
    predominant = {norm_phrase(tag) for tag in split_labels(pp_labels)}
    # A PP label merged into a parent (Alarm_clock -> Alarm) is not in Keywords.
    # Score that label on its own so the specific name still counts, with +2.
    tags = split_labels(keywords)
    seen = {norm_phrase(tag) for tag in tags if norm_phrase(tag)}
    for raw in split_labels(pp_labels):
        key = norm_phrase(raw)
        if key and key not in seen:
            tags.append(raw)
            seen.add(key)

    for raw in tags:
        key = norm_phrase(raw)
        if not key:
            continue
        bonus = catalog.bonus_of(raw, weights.depth_step)
        pp = weights.pp_bonus if key in predominant else 0.0
        matched: dict[int, tuple[float, str]] = {}
        exact_name = catalog.sub_index.get(key, ())
        for idx in exact_name:
            matched[idx] = (weights.exact_sub, "exact subcategory")
        for idx in catalog.syn_index.get(key, ()):
            if idx in matched:
                continue
            # "Cat" is a synonym of CAT DOMESTIC and of MACHINES/MEDICAL (the scan).
            # When the subcategory name itself contains the word, and the tag is not
            # already an exact subcategory ("dog" is DOG, not DOG WILD), that hit
            # outranks a synonym that merely borrowed the word.
            name_words = catalog.entries[idx].sub_key.split()
            if not exact_name and " " not in key and key in name_words:
                matched[idx] = (weights.exact_sub, "subcategory name")
            else:
                matched[idx] = (weights.exact_syn, "exact synonym")

        paired = _paired_subcategory(catalog, key)
        if paired is not None and weights.exact_sub:
            previous = matched.get(paired)
            if previous is None or previous[0] < weights.exact_sub:
                matched[paired] = (weights.exact_sub, "category and subcategory")

        for idx, (kind, count) in _contained_kinds(catalog, key).items():
            each = weights.exact_sub if kind == "exact subcategory" else weights.exact_syn
            lexical = each * count
            if lexical <= 0:
                continue
            previous = matched.get(idx)
            if previous is None or previous[0] < lexical:
                label_kind = kind if count == 1 else f"{count} exact synonyms"
                matched[idx] = (lexical, label_kind)

        modified = _modified_pair(catalog, key)
        if modified is not None and weights.exact_sub:
            shared = catalog.entries[modified].sub_key
            for idx in list(matched):
                if idx != modified and catalog.entries[idx].sub_key == shared:
                    del matched[idx]
            matched[modified] = (weights.exact_sub, "category and subcategory")

        overlap: dict[int, int] = defaultdict(int)
        for word in content_words(key):
            hit: set[int] = set()
            for form in word_forms(word):
                for idx in catalog.word_index.get(form, ()):
                    if idx not in matched:
                        hit.add(idx)
            for idx in hit:
                overlap[idx] += 1
        for idx, count in overlap.items():
            matched[idx] = (weights.word * count, f"{count} word" + ("s" if count != 1 else ""))

        label = raw.replace("_", " ")
        names_category = _named_category(catalog, key) is not None
        for idx, (lexical, kind) in matched.items():
            points = lexical * bonus + pp
            if points <= 0:
                continue
            pp_note = f" +{weights.pp_bonus:g} PP" if pp else ""
            reasons[idx].append(
                (points, f"{label}: {kind} {lexical:g} x{bonus:.2f}{pp_note} = {points:.2f}")
            )
            scores[idx] += points
            if not names_category:
                other_tag[idx] += points
            # A category word plus its subcategory ("clock alarm", "clock tick")
            # is a real subcategory hit, so it outranks the bare category.
            synonym_of_category_word = names_category and kind not in (
                "exact subcategory",
                "category and subcategory",
            )
            if not synonym_of_category_word and any(
                name in kind
                for name in (
                    "exact subcategory",
                    "exact synonym",
                    "subcategory name",
                    "category and subcategory",
                )
            ):
                solid[idx] += points

        named = _named_category(catalog, key)
        if named and weights.exact_sub:
            category_name, form = named
            named_bonus = bonus if form == key else catalog.bonus_of(form, weights.depth_step)
            lexical = weights.exact_sub
            points = lexical * named_bonus + pp
            if points > 0:
                pp_note = f" +{weights.pp_bonus:g} PP" if pp else ""
                category_reasons[category_name].append(
                    (
                        points,
                        f"{label}: category {lexical:g} x{named_bonus:.2f}{pp_note} = {points:.2f}",
                    )
                )
                category_scores[category_name] += points

    for raw in split_labels(uploader_tags):
        key = norm_phrase(raw)
        if not key:
            continue
        matched = set(catalog.sub_index.get(key, ()))
        matched.update(catalog.syn_index.get(key, ()))
        if weights.uploader_tag == 0:
            continue
        for idx in matched:
            scores[idx] += weights.uploader_tag
            reasons[idx].append(
                (weights.uploader_tag, f"uploader tag {raw!r} +{weights.uploader_tag:g}")
            )

    if title.strip() and weights.title_match != 0:
        for idx in _ngram_hits(title, catalog):
            scores[idx] += weights.title_match
            reasons[idx].append((weights.title_match, f"title +{weights.title_match:g}"))
    if description.strip() and weights.description_match != 0:
        for idx in _ngram_hits(description, catalog):
            scores[idx] += weights.description_match
            reasons[idx].append(
                (weights.description_match, f"description +{weights.description_match:.2f}")
            )

    ranked_idx = sorted(
        scores,
        key=lambda idx: (-scores[idx], catalog.entries[idx].category, catalog.entries[idx].subcategory),
    )
    ranked = [
        (
            catalog.entries[idx].category,
            catalog.entries[idx].subcategory,
            scores[idx],
            _format_evidence(reasons[idx]),
        )
        for idx in ranked_idx[: max(keep_ranked, 1)]
    ]
    if keep_ranked:
        ranked = ranked[:keep_ranked]

    prediction = Prediction(ranked=ranked if keep_ranked else [])
    best = scores[ranked_idx[0]] if ranked_idx else 0.0
    leaders = [idx for idx in ranked_idx if scores[idx] == best] if ranked_idx else []
    row_category = (category or "").strip()
    if len(leaders) > 1 and row_category:
        narrowed = [idx for idx in leaders if catalog.entries[idx].category == row_category]
        if len(narrowed) == 1:
            leaders = narrowed

    prediction.ties = [
        (catalog.entries[idx].category, catalog.entries[idx].subcategory, scores[idx]) for idx in leaders
    ]
    named_best = max(category_scores.values()) if category_scores else 0.0
    named_leaders = [name for name, score in category_scores.items() if score == named_best and score > 0]
    # Rain and Water both clear the cutoff. Depth should not pick one of them.
    named_clear = [name for name, score in category_scores.items() if score >= min_score]
    other_best = max(other_tag.values()) if other_tag else 0.0

    def category_only(name: str, score: float, evidence: str) -> Prediction:
        prediction.category = name
        prediction.subcategory = ""
        prediction.score = score
        prediction.status = "category"
        prediction.evidence = evidence
        return prediction

    solid_best = max(solid.values()) if solid else 0.0
    solid_leaders = [idx for idx, score in solid.items() if score == solid_best and score > 0]
    if len(solid_leaders) > 1 and row_category:
        narrowed = [idx for idx in solid_leaders if catalog.entries[idx].category == row_category]
        if len(narrowed) == 1:
            solid_leaders = narrowed
    prediction.ties = [
        (catalog.entries[idx].category, catalog.entries[idx].subcategory, scores[idx]) for idx in leaders
    ]
    # An exact name or synonym on its own tag wins over a category word sitting
    # beside it ("surf" beside Wind). "Bell" stays ALARMS/BELL, not BELLS.
    if len(solid_leaders) == 1 and solid_best >= min_score:
        winner = catalog.entries[solid_leaders[0]]
        prediction.category = winner.category
        prediction.subcategory = winner.subcategory
        prediction.score = solid_best
        prediction.status = "assigned"
        prediction.evidence = _format_evidence(reasons[solid_leaders[0]])
        return prediction

    # "Alarm" ties SCIFI/ALARM with VEHICLES/ALARM at the same score as the
    # category name. "Fire" outscores the alarm synonyms that list it, because
    # those synonyms came from the word Fire itself. A second tag that already
    # matches some other subcategory ("surf" beside Wind) keeps that match.
    if (
        len(named_clear) == 1
        and len(named_leaders) == 1
        and named_best >= min_score
        and other_best <= 0
        and (
            named_best > solid_best
            or (named_best == solid_best and len(solid_leaders) != 1 and on_tie == "blank")
        )
    ):
        name = named_leaders[0]
        return category_only(name, named_best, _format_evidence(category_reasons[name]))

    if not leaders:
        prediction.evidence = "no overlapping tag"
        return prediction

    winner = catalog.entries[leaders[0]]
    prediction.score = best
    prediction.evidence = _format_evidence(reasons[leaders[0]])
    if best < min_score:
        prediction.status = "below"
        names = ", ".join(
            f"{catalog.entries[idx].category}/{catalog.entries[idx].subcategory}" for idx in leaders[:4]
        )
        prediction.evidence = f"below {min_score:g}: best {best:.2f} {names}; {prediction.evidence}"
        return prediction
    if len(leaders) > 1 and on_tie == "blank":
        names = ", ".join(
            f"{catalog.entries[idx].category}/{catalog.entries[idx].subcategory}" for idx in leaders[:8]
        )
        extra = "" if len(leaders) <= 8 else f" (+{len(leaders) - 8})"
        categories = {catalog.entries[idx].category for idx in leaders}
        if len(categories) == 1:
            name = next(iter(categories))
            # A one-word lead such as Rain,Water (WEATHER 1.50, WATER 1.25) is
            # not an obvious category. An exact synonym, or a lead of a full
            # word over every other category, is.
            runner_up = max(
                (scores[idx] for idx in scores if catalog.entries[idx].category != name),
                default=0.0,
            )
            if best >= weights.exact_syn or runner_up <= best - weights.word:
                return category_only(
                    name,
                    best,
                    f"category {name}; subcategory tied at {best:.2f} among {names}{extra}",
                )
        prediction.status = "tie"
        prediction.evidence = f"tie at {best:.2f} among {names}{extra}"
        return prediction

    prediction.category = winner.category
    prediction.subcategory = winner.subcategory
    prediction.status = "assigned"
    return prediction


def _optional(row: dict[str, str], *names: str) -> str:
    for name in names:
        if row.get(name):
            return row[name]
    return ""


def audioset_keywords(human_labels: str) -> str:
    """AudioSet separates labels with ';' and keeps commas inside a label."""
    return ",".join(part.strip() for part in (human_labels or "").split(";") if part.strip())


def join_tags(tags: list) -> str:
    """Comma-join tags so ``split_labels`` sees one tag per item."""
    parts: list[str] = []
    for tag in tags:
        text = str(tag).replace(",", " ").strip()
        if text:
            parts.append(text)
    return ",".join(parts)


def predominant_labels(ratings: dict, names: dict[str, str], label_order: list[str]) -> str:
    """Labels an annotator marked PP (rating 1.0), in ground-truth order."""
    wanted: list[str] = []
    seen: set[str] = set()
    for mid, values in ratings.items():
        if isinstance(values, (int, float)):
            values = [values]
        if not any(float(value) == 1.0 for value in values):
            continue
        name = names.get(str(mid))
        if not name or name in seen:
            continue
        seen.add(name)
        wanted.append(name)
    order = {name: pos for pos, name in enumerate(label_order)}
    wanted.sort(key=lambda name: (order.get(name, len(order)), name))
    return ",".join(wanted)


@dataclass
class AudioIndex:
    """Source tags and FSD50K metadata, keyed by (filename, source)."""

    clips: dict[tuple[str, str], dict[str, str]]

    def apply(self, row: dict[str, str]) -> str:
        """Copy dataset fields onto a row. Returns ``same``, ``refreshed``, or ``missing``."""
        found = self.clips.get(((row.get("filename") or ""), (row.get("source") or "")))
        if found is None:
            return "missing"
        previous = row.get("Keywords") or ""
        incoming = found.get("Keywords") or ""
        if incoming:
            row["Keywords"] = incoming
        for name in META_COLUMNS:
            row[name] = found.get(name, "")
        if previous and incoming and previous != incoming:
            return "refreshed"
        return "same"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _require(path: Path) -> Path:
    if not path.is_file():
        raise SystemExit(f"dataset file not found: {path}")
    return path


def _fsd_names(vocabulary: Path) -> dict[str, str]:
    names: dict[str, str] = {}
    for line in vocabulary.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("index,"):
            continue
        _index, rest = line.split(",", 1)
        name, mid = rest.rsplit(",", 1)
        names[mid.strip()] = name.strip()
    return names


def load_audio_index(audio_dir: Path) -> AudioIndex:
    """Read the label files and FSD50K metadata the UCS paper converts."""
    clips: dict[tuple[str, str], dict[str, str]] = {}

    audioset = audio_dir / "AudioSet" / "audios"
    for name in ("balanced_train_segments.csv", "eval_segments.csv"):
        for row in _read_csv(_require(audioset / name)):
            filename = (row.get("filename") or "").strip()
            if not filename:
                continue
            clips[(filename, "AudioSet")] = {"Keywords": audioset_keywords(row.get("human_labels") or "")}

    for row in _read_csv(_require(audio_dir / "ESC-50" / "meta" / "esc50.csv")):
        filename = (row.get("filename") or "").strip()
        if filename:
            clips[(filename, "ESC-50")] = {"Keywords": (row.get("category") or "").strip()}

    fsd_root = audio_dir / "FSD50K"
    # Collection names cover classes later merged into a parent (Alarm_clock -> Alarm).
    # The released 200-class vocabulary overwrites those mids when both exist.
    names: dict[str, str] = {}
    collection = fsd_root / "FSD50K.metadata" / "collection"
    for name in ("vocabulary_collection_dev.csv", "vocabulary_collection_eval.csv"):
        path = collection / name
        if path.is_file():
            names.update(_fsd_names(path))
    names.update(_fsd_names(_require(fsd_root / "FSD50K.ground_truth" / "vocabulary.csv")))
    ground: dict[str, tuple[list[str], dict[str, str]]] = {}
    for name in ("dev.csv", "eval.csv"):
        for row in _read_csv(_require(fsd_root / "FSD50K.ground_truth" / name)):
            fname = (row.get("fname") or "").strip()
            if not fname:
                continue
            labels = [part.strip() for part in (row.get("labels") or "").split(",") if part.strip()]
            mids = [part.strip() for part in (row.get("mids") or "").split(",") if part.strip()]
            by_mid = dict(names)
            by_mid.update(zip(mids, labels))
            ground[fname] = (labels, by_mid)

    info: dict[str, dict] = {}
    meta = fsd_root / "FSD50K.metadata"
    for name in ("dev_clips_info_FSD50K.json", "eval_clips_info_FSD50K.json"):
        info.update(json.loads(_require(meta / name).read_text(encoding="utf-8")))
    ratings = json.loads(_require(meta / "pp_pnp_ratings_FSD50K.json").read_text(encoding="utf-8"))

    for fname, (labels, by_mid) in ground.items():
        clip_info = info.get(fname) or {}
        tags = clip_info.get("tags") or []
        if isinstance(tags, str):
            tags = split_labels(tags)
        clips[(f"{fname}.wav", "FSD50K")] = {
            "Keywords": ",".join(labels),
            "pp_labels": predominant_labels(ratings.get(fname) or {}, by_mid, labels),
            "uploader_tags": join_tags(tags),
            "title": str(clip_info.get("title") or ""),
            "description": str(clip_info.get("description") or ""),
        }

    return AudioIndex(clips)


def apply_audio(rows: list[dict[str, str]], index: AudioIndex) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[index.apply(row)] += 1
    return counts


def matched_phrase(counts: dict[str, int]) -> str:
    found = counts["same"] + counts["refreshed"]
    total = found + counts["missing"]
    refreshed = f", {counts['refreshed']} keywords refreshed" if counts["refreshed"] else ""
    missing = f", {counts['missing']} missing" if counts["missing"] else ""
    return f"{found}/{total} clips{refreshed}{missing}"


def project_prediction(
    full: Prediction,
    allowed_pairs: set[tuple[str, str]],
) -> Prediction | None:
    """Keep a full-list hit whose category is allowed when the subcategory is not.

    ``pig`` matches ANIMALS/FARM, which the closed slice does not list. The
    category ANIMALS is still the obvious label, so SubCategory stays blank.
    """
    allowed_categories = {category for category, _subcategory in allowed_pairs}
    if full.status == "assigned":
        if (full.category, full.subcategory) in allowed_pairs:
            return full
        if full.category in allowed_categories:
            return Prediction(
                category=full.category,
                subcategory="",
                score=full.score,
                status="category",
                evidence=full.evidence,
                ranked=full.ranked,
                ties=full.ties,
            )
        return None
    if full.status == "category":
        return full if full.category in allowed_categories else None
    if full.status != "tie" or not full.ties:
        return None
    kept = [item for item in full.ties if item[0] in allowed_categories]
    if not kept:
        return None
    categories = {item[0] for item in kept}
    if len(categories) != 1:
        return None
    category = next(iter(categories))
    allowed_subs = [item for item in kept if (item[0], item[1]) in allowed_pairs]
    if len(kept) == 1 and allowed_subs:
        _category, subcategory, score = allowed_subs[0]
        return Prediction(
            category=category,
            subcategory=subcategory,
            score=score,
            status="assigned",
            evidence=full.evidence,
            ranked=full.ranked,
            ties=full.ties,
        )
    return Prediction(
        category=category,
        subcategory="",
        score=kept[0][2],
        status="category",
        evidence=full.evidence,
        ranked=full.ranked,
        ties=full.ties,
    )


def recover_category(
    primary: Prediction,
    full: Prediction | None,
    allowed_pairs: set[tuple[str, str]] | None,
) -> Prediction:
    """Fill a blank closed-slice row from the rest of the UCS list."""
    if primary.status in ("assigned", "category") or full is None or not allowed_pairs:
        return primary
    projected = project_prediction(full, allowed_pairs)
    return projected if projected is not None else primary


def score_manifest(
    catalog: Catalog,
    rows: list[dict[str, str]],
    *,
    min_score: float,
    weights: Weights | None = None,
    on_tie: str = "blank",
    background: Catalog | None = None,
    allowed_pairs: set[tuple[str, str]] | None = None,
) -> list[Prediction]:
    predictions: list[Prediction] = []
    for row in rows:
        keywords = row.get("Keywords") or ""
        shared = dict(
            category=row.get("Category") or "",
            pp_labels=_optional(row, "pp_labels", "pp"),
            uploader_tags=_optional(row, "uploader_tags", "tags"),
            title=_optional(row, "title"),
            description=_optional(row, "description"),
            min_score=min_score,
            weights=weights,
            on_tie=on_tie,
        )
        primary = score_text(catalog, keywords, **shared)
        full = None
        if background is not None and primary.status in ("tie", "below"):
            full = score_text(background, keywords, **shared)
        predictions.append(recover_category(primary, full, allowed_pairs))
    return predictions


def load_manifest(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def _identity(row: dict[str, str]) -> tuple[str, str, str]:
    key = (row.get("filename") or "", row.get("source") or "", row.get("path") or "")
    if not all(key):
        raise ValueError(f"row is missing filename, source, or path: {key}")
    return key


def manifest_fields(source_fields: list[str]) -> list[str]:
    missing = [name for name in MANIFEST_COLUMNS if name not in source_fields]
    if missing:
        raise ValueError(f"missing columns: {', '.join(missing)}")
    extra = [name for name in source_fields if name not in MANIFEST_COLUMNS]
    return list(MANIFEST_COLUMNS) + extra


def select_manifest_rows(
    split_rows: list[dict[str, str]],
    source_rows: list[dict[str, str]],
    source_fields: list[str],
) -> tuple[list[str], list[dict[str, str]]]:
    """Keep source rows named by a split, in split order.

    A split file only says which audio file belongs. Category, subcategory,
    keywords, and the rest come from the full manifest.
    """
    fields = manifest_fields(source_fields)
    index: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in source_rows:
        key = _identity(row)
        if key in index:
            filename, source, _path = key
            raise ValueError(f"duplicate row for {filename} ({source})")
        index[key] = row

    chosen: list[dict[str, str]] = []
    missing: list[tuple[str, str, str]] = []
    for row in split_rows:
        key = _identity(row)
        found = index.get(key)
        if found is None:
            missing.append(key)
            continue
        chosen.append({name: found.get(name, "") for name in fields})
    if missing:
        preview = ", ".join(f"{filename} ({source})" for filename, source, _path in missing[:8])
        extra = "" if len(missing) <= 8 else f" (+{len(missing) - 8})"
        raise ValueError(f"{len(missing)} split rows not in the full manifest: {preview}{extra}")
    return fields, chosen


def write_manifest(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _prior_index(rows: list[dict[str, str]]) -> tuple[dict[tuple[str, str], dict[str, str]], list[str]]:
    """Index rows by filename and source. Extra columns are kept in order."""
    index: dict[tuple[str, str], dict[str, str]] = {}
    extra: list[str] = []
    for row in rows:
        key = ((row.get("filename") or ""), (row.get("source") or ""))
        if not all(key):
            continue
        if key in index:
            filename, source = key
            raise ValueError(f"duplicate row for {filename} ({source})")
        index[key] = row
        for name in row:
            if name not in MANIFEST_COLUMNS and name not in META_COLUMNS and name not in extra:
                extra.append(name)
    return index, extra


def rows_from_audio(
    split_rows: list[dict[str, str]],
    prior_rows: list[dict[str, str]],
    index: AudioIndex,
    audio_dir: Path,
) -> tuple[list[str], list[dict[str, str]]]:
    """One manifest row per split file, labeled from the audio-folder datasets.

    Category and SubCategory come from ``prior_rows`` when that clip is
    there. Keywords, predominant labels, and clip text come from ``index``.
    """
    prior, extra = _prior_index(prior_rows)
    fields = list(MANIFEST_COLUMNS) + list(META_COLUMNS) + extra
    chosen: list[dict[str, str]] = []
    missing: list[tuple[str, str]] = []
    for row in split_rows:
        key = ((row.get("filename") or ""), (row.get("source") or ""))
        path = row.get("path") or ""
        if not all(key) or not path:
            raise ValueError(f"split row is missing filename, source, or path: {key}")
        clip = index.clips.get(key)
        if clip is None:
            missing.append(key)
            continue
        found = prior.get(key, {})
        chosen_row = {name: found.get(name, "") for name in fields}
        chosen_row["filename"] = key[0]
        chosen_row["source"] = key[1]
        chosen_row["path"] = path
        chosen_row["Category"] = found.get("Category", "")
        chosen_row["SubCategory"] = found.get("SubCategory", "")
        chosen_row["Keywords"] = clip.get("Keywords", "")
        chosen_row["exists"] = "True" if (audio_dir / path).is_file() else "False"
        for name in META_COLUMNS:
            chosen_row[name] = clip.get(name, "")
        chosen.append(chosen_row)
    if missing:
        preview = ", ".join(f"{filename} ({source})" for filename, source in missing[:8])
        extra_note = "" if len(missing) <= 8 else f" (+{len(missing) - 8})"
        raise ValueError(f"{len(missing)} split rows have no label file: {preview}{extra_note}")
    return fields, chosen


def make_manifests(
    splits_dir: Path,
    source_dir: Path | None,
    manifest_dir: Path,
    audio_dir: Path,
    splits: tuple[str, ...] = DEFAULT_WRITE_SPLITS,
) -> list[Path]:
    """Write manifests/manual/envsound_<split>.csv from splits/ and audio/.

    ``splits`` defaults to test. Train and val are not rewritten unless they
    are named here, so hand tags in those files stay put.
    """
    splits = parse_split_list(splits)
    index = load_audio_index(audio_dir)
    skipped = [name for name in SPLIT_NAMES if name not in splits]
    print(f"writing {', '.join(splits)}")
    if skipped:
        print(f"leaving {', '.join(skipped)} untouched")
    written: list[Path] = []
    for name in splits:
        split_path = splits_dir / f"{name}.csv"
        if not split_path.is_file():
            raise SystemExit(f"split not found: {split_path}")
        split_fields, split_rows = load_manifest(split_path)
        missing_split = [column for column in ("filename", "source", "path") if column not in split_fields]
        if missing_split:
            raise SystemExit(f"{split_path} is missing columns: {', '.join(missing_split)}")
        source_path = (source_dir / f"envsound_{name}.csv") if source_dir is not None else None
        existing = manifest_dir / f"envsound_{name}.csv"
        if source_path is not None and source_path.is_file():
            _fields, prior_rows = load_manifest(source_path)
            prior_from = source_path
        elif existing.is_file():
            _fields, prior_rows = load_manifest(existing)
            prior_from = existing
        else:
            prior_rows = []
            prior_from = None
        try:
            fields, rows = rows_from_audio(split_rows, prior_rows, index, audio_dir)
        except ValueError as exc:
            raise SystemExit(f"{name}: {exc}") from exc
        out = manifest_dir / f"envsound_{name}.csv"
        write_manifest(out, fields, rows)
        written.append(out)
        kept = "no prior category list" if prior_from is None else f"categories from {prior_from}"
        print(f"wrote {out} ({len(rows)} rows, {kept})")
    return written


def check_experiment_name(name: str) -> str:
    if name in (".", "..") or any(char in name for char in "\\/"):
        raise SystemExit(f"experiment name must be one folder name, not {name!r}")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
        raise SystemExit(
            f"experiment name must use letters, numbers, dots, dashes, or underscores: {name!r}"
        )
    return name


def parse_split_list(value: object, *, origin: str = "splits") -> tuple[str, ...]:
    """Return split names in train, val, test order. Default is test only."""
    if value is None:
        items: tuple[str, ...] | list[str] = DEFAULT_WRITE_SPLITS
    elif isinstance(value, str):
        items = tuple(part.strip() for part in value.split(",") if part.strip())
    elif isinstance(value, (list, tuple)):
        items = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise SystemExit(f"{origin} must be split names, got {item!r}")
            items.append(item.strip())
    else:
        raise SystemExit(f"{origin} must be a list of split names")
    if not items:
        raise SystemExit(f"{origin} is empty")
    unknown = [name for name in items if name not in SPLIT_NAMES]
    if unknown:
        raise SystemExit(f"unknown split {', '.join(unknown)}; expected {', '.join(SPLIT_NAMES)}")
    return tuple(name for name in SPLIT_NAMES if name in items)


def parse_pair(text: str) -> tuple[str, str]:
    raw = text.strip()
    if "/" not in raw:
        raise SystemExit(f"pair must be CATEGORY/SUBCATEGORY: {raw}")
    category, subcategory = raw.split("/", 1)
    category, subcategory = category.strip(), subcategory.strip()
    if not category or not subcategory:
        raise SystemExit(f"pair must be CATEGORY/SUBCATEGORY: {raw}")
    return category, subcategory


def pairs_from_text(text: str) -> list[str]:
    lines: list[str] = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            lines.append(line)
    return lines


def pairs_from_file(path: Path) -> frozenset[tuple[str, str]]:
    if not path.is_file():
        raise SystemExit(f"taxonomy file not found: {path}")
    if path.suffix.lower() == ".csv":
        found: list[tuple[str, str]] = []
        for row in _read_csv(path):
            category = (row.get("Category") or row.get("category") or "").strip()
            subcategory = (row.get("SubCategory") or row.get("subcategory") or "").strip()
            if category and subcategory:
                found.append((category, subcategory))
        if not found:
            raise SystemExit(f"{path} has no Category, SubCategory rows")
        return frozenset(found)
    return frozenset(parse_pair(line) for line in pairs_from_text(path.read_text(encoding="utf-8")))


def resolve_under_root(path: str | Path) -> Path:
    chosen = Path(path)
    if chosen.is_absolute():
        return chosen
    return ROOT / chosen


def parse_taxonomy(
    value: object, *, origin: str
) -> tuple[str, tuple[str, ...], frozenset[tuple[str, str]]]:
    if isinstance(value, str):
        mode = value.strip()
        if mode not in TAXONOMY_MODES:
            raise SystemExit(f"{origin}: unknown taxonomy {mode!r}")
        if mode in ("categories", "pairs"):
            raise SystemExit(f"{origin}: taxonomy {mode} needs a list")
        return mode, (), frozenset()
    if not isinstance(value, dict):
        raise SystemExit(f"{origin}: taxonomy must be a string or an object")
    unknown = sorted(set(value) - {"mode", "categories", "pairs", "file"})
    if unknown:
        raise SystemExit(f"{origin}: unknown taxonomy settings: {', '.join(unknown)}")
    mode = value.get("mode", "open")
    if not isinstance(mode, str) or mode not in TAXONOMY_MODES:
        raise SystemExit(f"{origin}: unknown taxonomy {mode!r}")
    extra = [key for key in ("categories", "pairs", "file") if value.get(key)]
    if mode in ("open", "closed") and extra:
        raise SystemExit(f"{origin}: taxonomy {mode} does not take {', '.join(extra)}")
    if mode == "categories" and (value.get("pairs") or value.get("file")):
        raise SystemExit(f"{origin}: taxonomy categories does not take a pair list")
    if mode == "pairs" and value.get("categories"):
        raise SystemExit(f"{origin}: taxonomy pairs does not take a category list")

    categories: tuple[str, ...] = ()
    if "categories" in value and value["categories"] is not None:
        raw_categories = value["categories"]
        if not isinstance(raw_categories, list) or not all(isinstance(item, str) for item in raw_categories):
            raise SystemExit(f"{origin}: categories must be a list of strings")
        categories = tuple(dict.fromkeys(item.strip() for item in raw_categories if item.strip()))
    pairs: set[tuple[str, str]] = set()
    if "pairs" in value and value["pairs"] is not None:
        raw_pairs = value["pairs"]
        if not isinstance(raw_pairs, list) or not all(isinstance(item, str) for item in raw_pairs):
            raise SystemExit(f"{origin}: pairs must be a list of CATEGORY/SUBCATEGORY strings")
        pairs.update(parse_pair(item) for item in raw_pairs)
    if value.get("file"):
        file_name = value["file"]
        if not isinstance(file_name, str):
            raise SystemExit(f"{origin}: taxonomy file must be a string")
        pairs.update(pairs_from_file(resolve_under_root(file_name)))
    if mode == "categories" and not categories:
        raise SystemExit(f"{origin}: taxonomy categories needs a category list")
    if mode == "pairs" and not pairs:
        raise SystemExit(f"{origin}: taxonomy pairs needs a pair list or a file")
    if mode != "categories":
        categories = ()
    if mode != "pairs":
        pairs = set()
    return mode, categories, frozenset(pairs)


def parse_closed_list(value: object, *, origin: str) -> frozenset[tuple[str, str]]:
    """Pairs a ``closed`` taxonomy may assign. Each item is CATEGORY/SUBCATEGORY."""
    if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
        raise SystemExit(f"{origin}: closed must be a non-empty list of CATEGORY/SUBCATEGORY strings")
    return frozenset(parse_pair(item) for item in value)


@dataclass(frozen=True)
class ExperimentConfig:
    """One tagging setup: weights, taxonomy, and which split files to emit."""

    name: str
    taxonomy: str
    categories: tuple[str, ...] = ()
    pairs: frozenset[tuple[str, str]] = frozenset()
    closed: frozenset[tuple[str, str]] = field(default_factory=frozenset)
    weights: Weights = field(default_factory=lambda: default_config().weights)
    min_score: float = field(default_factory=lambda: default_config().min_score)
    on_tie: str = field(default_factory=lambda: default_config().on_tie)
    splits: tuple[str, ...] = field(default_factory=lambda: default_config().splits)
    output_dir: Path | None = None
    note: str = ""


def parse_experiment(
    data: object,
    *,
    origin: str = "config",
    base: ExperimentConfig | None = None,
    inherit: bool = True,
) -> ExperimentConfig:
    if not isinstance(data, dict):
        raise SystemExit(f"{origin} must be a JSON object")
    unknown = sorted(set(data) - CONFIG_KEYS)
    if unknown:
        raise SystemExit(f"{origin}: unknown settings: {', '.join(unknown)}")
    name = data.get("name", "")
    if not isinstance(name, str) or not name.strip():
        raise SystemExit(f"{origin}: name is required")
    name = check_experiment_name(name.strip())
    note = data.get("note", "")
    if not isinstance(note, str):
        raise SystemExit(f"{origin}: note must be a string")
    if inherit and base is None:
        base = default_config()
    if "taxonomy" in data:
        taxonomy, categories, pairs = parse_taxonomy(data["taxonomy"], origin=origin)
    elif base is not None:
        taxonomy, categories, pairs = base.taxonomy, base.categories, base.pairs
    else:
        raise SystemExit(f"{origin}: taxonomy is required")
    if "weights" in data and data["weights"] is not None:
        raw_weights = data["weights"]
        if not isinstance(raw_weights, dict):
            raise SystemExit(f"{origin}: weights must be an object")
        unknown = sorted(set(raw_weights) - set(WEIGHT_NAMES))
        if unknown:
            raise SystemExit(f"{origin}: unknown weight: {', '.join(unknown)}")
        if base is None:
            missing = [key for key in WEIGHT_NAMES if key not in raw_weights]
            if missing:
                raise SystemExit(f"{origin}: weights missing {', '.join(missing)}")
            weights = Weights(**{key: as_finite(key, raw_weights[key]) for key in WEIGHT_NAMES})
        else:
            weights = base.weights.with_values(**raw_weights)
    elif base is not None:
        weights = base.weights
    else:
        raise SystemExit(f"{origin}: weights is required")
    if "min_score" in data:
        min_score = as_finite("min_score", data["min_score"])
    elif base is not None:
        min_score = base.min_score
    else:
        raise SystemExit(f"{origin}: min_score is required")
    if "on_tie" in data:
        on_tie = data["on_tie"]
    elif base is not None:
        on_tie = base.on_tie
    else:
        raise SystemExit(f"{origin}: on_tie is required")
    if on_tie not in ("blank", "first"):
        raise SystemExit(f"{origin}: on_tie must be blank or first")
    if "splits" in data:
        splits = parse_split_list(data["splits"], origin=f"{origin} splits")
    elif base is not None:
        splits = base.splits
    else:
        raise SystemExit(f"{origin}: splits is required")
    if "closed" in data:
        closed = parse_closed_list(data["closed"], origin=origin)
    elif base is not None:
        closed = base.closed
    else:
        raise SystemExit(f"{origin}: closed is required")
    output_dir = None
    if data.get("output_dir"):
        if not isinstance(data["output_dir"], str):
            raise SystemExit(f"{origin}: output_dir must be a string")
        output_dir = resolve_under_root(data["output_dir"])
    return ExperimentConfig(
        name=name,
        note=note,
        taxonomy=taxonomy,
        categories=categories,
        pairs=pairs,
        weights=weights,
        min_score=min_score,
        on_tie=on_tie,
        splits=splits,
        closed=closed,
        output_dir=output_dir,
    )


def load_config_file(path: Path) -> ExperimentConfig:
    if not path.is_file():
        raise SystemExit(f"config not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path} is not valid JSON: {exc}") from exc
    if isinstance(data, dict) and "name" not in data:
        data = {**data, "name": path.stem}
    own_defaults = path.resolve() == DEFAULT_CONFIG.resolve()
    return parse_experiment(data, origin=str(path), inherit=not own_defaults)


_DEFAULT_CONFIG: ExperimentConfig | None = None


def default_config() -> ExperimentConfig:
    """The scorer in ``configs/default.json``. Other configs overlay this."""
    global _DEFAULT_CONFIG
    if _DEFAULT_CONFIG is None:
        if not DEFAULT_CONFIG.is_file():
            raise SystemExit(f"default config not found: {DEFAULT_CONFIG}")
        _DEFAULT_CONFIG = load_config_file(DEFAULT_CONFIG)
    return _DEFAULT_CONFIG


def parse_sets(items: list[str]) -> tuple[dict[str, float], float | None]:
    changes: dict[str, float] = {}
    min_score: float | None = None
    for item in items:
        if "=" not in item:
            raise SystemExit(f"--set must be NAME=VALUE, got {item!r}")
        key, raw = item.split("=", 1)
        key = key.strip()
        try:
            number = float(raw.strip())
        except ValueError:
            raise SystemExit(f"{key} must be a number") from None
        if key == "min_score":
            min_score = as_finite("min_score", number)
            continue
        if key not in WEIGHT_NAMES:
            known = ", ".join((*WEIGHT_NAMES, "min_score"))
            raise SystemExit(f"unknown weight {key!r}; expected {known}")
        changes[key] = as_finite(key, number)
    return changes, min_score


def apply_cli(config: ExperimentConfig, args: argparse.Namespace) -> ExperimentConfig:
    """CLI flags override the same fields in a config. Unset flags leave the config alone."""
    weights = config.weights
    min_score = config.min_score
    if args.set:
        changes, set_min = parse_sets(args.set)
        if changes:
            weights = weights.with_values(**changes)
        if set_min is not None:
            min_score = set_min
    if args.min_score is not None:
        min_score = as_finite("min_score", args.min_score)

    if args.taxonomy and args.closed_slice and args.taxonomy != "closed":
        raise SystemExit("use either --taxonomy or --closed-slice")
    taxonomy = args.taxonomy or ("closed" if args.closed_slice else config.taxonomy)
    categories = config.categories
    pairs = set(config.pairs)
    if args.categories and args.pair_list:
        raise SystemExit("use either --categories or --pairs")
    if args.categories:
        if args.taxonomy not in (None, "categories"):
            raise SystemExit("--categories is only for --taxonomy categories")
        taxonomy = "categories"
        categories = tuple(dict.fromkeys(part.strip() for part in args.categories.split(",") if part.strip()))
        if not categories:
            raise SystemExit("--categories is empty")
    if args.pair_list:
        if args.taxonomy not in (None, "pairs"):
            raise SystemExit("--pairs is only for --taxonomy pairs")
        taxonomy = "pairs"
        listed = [part.strip() for part in args.pair_list.split(",") if part.strip()]
        if not listed:
            raise SystemExit("--pairs is empty")
        pairs = {parse_pair(part) for part in listed}
    if taxonomy == "categories" and not categories:
        raise SystemExit("taxonomy categories needs --categories or a category list in the config")
    if taxonomy == "pairs" and not pairs:
        raise SystemExit("taxonomy pairs needs --pairs or a pair list in the config")
    if taxonomy != "categories":
        categories = ()
    if taxonomy != "pairs":
        pairs = set()

    name = check_experiment_name(args.experiment_name) if args.experiment_name else config.name
    splits = parse_split_list(args.write_splits, origin="--write-splits") if args.write_splits is not None else config.splits
    on_tie = args.on_tie or config.on_tie
    return replace(
        config,
        name=name,
        taxonomy=taxonomy,
        categories=categories,
        pairs=frozenset(pairs),
        weights=weights,
        min_score=min_score,
        on_tie=on_tie,
        splits=splits,
    )


def allowlist_for(
    config: ExperimentConfig, records: list[tuple[str, str, str, str]]
) -> set[tuple[str, str]] | None:
    """Pairs the scorer may assign. None means the whole UCS list."""
    if config.taxonomy == "open":
        return None
    if config.taxonomy == "closed":
        if not config.closed:
            raise SystemExit("taxonomy closed needs a closed list; set \"closed\" in the config")
        return set(config.closed)
    if config.taxonomy == "categories":
        by_fold = {category.casefold(): category for category, _sub, _exp, _syn in records}
        resolved: list[str] = []
        missing: list[str] = []
        for name in config.categories:
            found = by_fold.get(name.casefold())
            if found is None:
                missing.append(name)
            elif found not in resolved:
                resolved.append(found)
        if missing:
            raise SystemExit(f"UCS has no category: {', '.join(missing)}")
        return {(category, subcategory) for category, subcategory, _exp, _syn in records if category in resolved}
    if config.taxonomy == "pairs":
        return set(config.pairs)
    raise SystemExit(f"unknown taxonomy: {config.taxonomy}")


def missing_pairs_message(missing: list[tuple[str, str]]) -> str:
    preview = ", ".join(f"{category}/{subcategory}" for category, subcategory in sorted(missing)[:8])
    extra = "" if len(missing) <= 8 else f" (+{len(missing) - 8})"
    noun = "pair" if len(missing) == 1 else "pairs"
    verb = "is" if len(missing) == 1 else "are"
    return f"{len(missing)} taxonomy {noun} {verb} not in the UCS list: {preview}{extra}"


def restrict_records(
    records: list[tuple[str, str, str, str]],
    allowed: set[tuple[str, str]] | None,
    *,
    on_missing: str = "error",
) -> tuple[list[tuple[str, str, str, str]], set[tuple[str, str]] | None, list[tuple[str, str]]]:
    """Keep records in ``allowed``. ``on_missing`` is ``error`` or ``skip``."""
    if allowed is None:
        return records, None, []
    if on_missing not in ("error", "skip"):
        raise SystemExit(f"on_missing must be error or skip, got {on_missing!r}")
    index = {
        (category.casefold(), subcategory.casefold()): (category, subcategory)
        for category, subcategory, _explanation, _synonyms in records
    }
    resolved: set[tuple[str, str]] = set()
    missing: list[tuple[str, str]] = []
    for category, subcategory in allowed:
        found = index.get((category.casefold(), subcategory.casefold()))
        if found is None:
            missing.append((category, subcategory))
        else:
            resolved.add(found)
    if missing and on_missing == "error":
        raise SystemExit(missing_pairs_message(missing))
    filtered = [record for record in records if (record[0], record[1]) in resolved]
    return filtered, resolved, missing


def assert_outside_manifests(out_dir: Path, manifest_dir: Path) -> None:
    out = out_dir.resolve()
    manual = manifest_dir.resolve()
    if out == manual or manual in out.parents:
        raise SystemExit(
            f"refusing to write {out} inside {manual}; train and val tags there are manual"
        )


def manual_splits_to_copy(scored: tuple[str, ...]) -> tuple[str, ...]:
    """Splits this config does not score. Those files are copied from the manual folder."""
    return tuple(name for name in SPLIT_NAMES if name not in scored)


def copy_manual_manifests(
    out_dir: Path,
    manifest_dir: Path,
    splits: tuple[str, ...],
) -> list[Path]:
    """Copy manual manifests for splits the config does not score."""
    written: list[Path] = []
    if not splits:
        return written
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in splits:
        source = manifest_dir / f"envsound_{name}.csv"
        if not source.is_file():
            raise SystemExit(
                f"missing {source}; this config does not score {name}, "
                "so that file is copied from the manual manifests"
            )
        destination = out_dir / source.name
        shutil.copy2(source, destination)
        written.append(destination)
        print(f"copied {destination} from {source}")
    return written


def labeled_rows(rows: list[dict[str, str]], predictions: list[Prediction]) -> list[dict[str, str]]:
    """Copy rows with Category and SubCategory set to the scorer's assignment."""
    labeled: list[dict[str, str]] = []
    for row, prediction in zip(rows, predictions):
        out = dict(row)
        out["Category"] = prediction.category
        out["SubCategory"] = prediction.subcategory
        labeled.append(out)
    return labeled


def extend_fields(fieldnames: list[str], rows: list[dict[str, str]]) -> list[str]:
    fields = list(fieldnames)
    for row in rows:
        for name in row:
            if name not in fields:
                fields.append(name)
    return fields


def format_scoring(config: ExperimentConfig, subcategory_count: int) -> str:
    weights = " ".join(f"{name}={getattr(config.weights, name):g}" for name in WEIGHT_NAMES)
    taxonomy = config.taxonomy
    if config.taxonomy == "categories":
        taxonomy += " (" + ", ".join(config.categories) + ")"
    span = "all UCS subcategories" if config.taxonomy == "open" else f"{subcategory_count} subcategories"
    return "\n".join(
        [
            f"taxonomy {taxonomy}, {span}",
            f"min_score {config.min_score:g}  on_tie {config.on_tie}",
            f"weights {weights}",
        ]
    )


def format_settings(config: ExperimentConfig, subcategory_count: int) -> str:
    lines = [f"experiment {config.name}", indent_block(format_scoring(config, subcategory_count))]
    lines.append(f"  splits {', '.join(config.splits)}")
    if config.note:
        lines.append(f"  note {config.note}")
    return "\n".join(lines)


def indent_block(text: str) -> str:
    return "\n".join(f"  {line}" for line in text.splitlines())


def config_snapshot(
    config: ExperimentConfig,
    *,
    subcategory_count: int,
    pairs: set[tuple[str, str]] | None,
    copied: tuple[str, ...] = (),
) -> dict[str, object]:
    present = tuple(name for name in SPLIT_NAMES if name in config.splits or name in copied)
    snapshot: dict[str, object] = {
        "name": config.name,
        "note": config.note,
        "taxonomy": config.taxonomy,
        "min_score": config.min_score,
        "on_tie": config.on_tie,
        "weights": {name: getattr(config.weights, name) for name in WEIGHT_NAMES},
        "splits": list(config.splits),
        "files": [f"envsound_{name}.csv" for name in present],
        "copied_from_manual": [f"envsound_{name}.csv" for name in copied],
        "subcategories": subcategory_count,
    }
    if config.taxonomy == "categories":
        snapshot["categories"] = list(config.categories)
    if pairs is not None:
        snapshot["pairs"] = [f"{category}/{subcategory}" for category, subcategory in sorted(pairs)]
    return snapshot


def output_directory(config: ExperimentConfig, output_dir: Path | None, *, multiple: bool) -> Path:
    if output_dir is not None:
        root = resolve_under_root(output_dir)
        return root / config.name if multiple else root
    if config.output_dir is not None:
        return config.output_dir
    return ROOT / "experiments" / config.name


def load_split_rows(
    name: str,
    *,
    manifest_dir: Path,
    splits_dir: Path,
    audio_dir: Path,
    index: AudioIndex | None,
) -> tuple[list[str], list[dict[str, str]], str]:
    """Rows to score. Prefer the manifest on disk; otherwise build from the split list."""
    manifest_path = manifest_dir / f"envsound_{name}.csv"
    if manifest_path.is_file():
        fieldnames, rows = load_manifest(manifest_path)
        return fieldnames, rows, str(manifest_path)
    if index is None:
        raise SystemExit(f"missing {manifest_path}; leave audio lookup on, or build the manifest first")
    split_path = splits_dir / f"{name}.csv"
    if not split_path.is_file():
        raise SystemExit(f"split not found: {split_path}")
    split_fields, split_rows = load_manifest(split_path)
    missing_split = [column for column in ("filename", "source", "path") if column not in split_fields]
    if missing_split:
        raise SystemExit(f"{split_path} is missing columns: {', '.join(missing_split)}")
    try:
        fieldnames, rows = rows_from_audio(split_rows, [], index, audio_dir)
    except ValueError as exc:
        raise SystemExit(f"{name}: {exc}") from exc
    return fieldnames, rows, f"{split_path} (no manifest yet)"


def borrow_missing_pairs(
    records: list[tuple[str, str, str, str]],
    allowed: set[tuple[str, str]] | None,
) -> tuple[list[tuple[str, str, str, str]], list[str]]:
    """Copy synonyms onto a closed pair the workbook files under another category.

    ``DOORS/DOORBELL`` is not a UCS row. ``BELLS/DOORBELL`` is. The slice still
    wants the door category, so the doorbell synonyms are scored there.
    """
    if not allowed:
        return records, []
    present = {(category.casefold(), subcategory.casefold()) for category, subcategory, _exp, _syn in records}
    by_sub: dict[str, tuple[str, str, str, str]] = {}
    for record in records:
        by_sub.setdefault(record[1].casefold(), record)
    extra: list[tuple[str, str, str, str]] = []
    notes: list[str] = []
    for category, subcategory in sorted(allowed):
        if (category.casefold(), subcategory.casefold()) in present:
            continue
        donor = by_sub.get(subcategory.casefold())
        if donor is None:
            continue
        # Keep Doorbell and Ding-Dong. Drop bare Chime, Door, and Ring, which
        # also name bells and doors that are not doorbells.
        sub_key = norm_phrase(subcategory)
        specific: list[str] = []
        for piece in donor[3].split(","):
            key = norm_phrase(piece)
            if not key:
                continue
            if key == sub_key or sub_key in key.split() or " " in key:
                specific.append(piece.strip())
        extra.append((category, subcategory, donor[2], ",".join(specific)))
        notes.append(f"{category}/{subcategory} uses synonyms from {donor[0]}/{donor[1]}")
    return records + extra, notes


def catalog_for(
    config: ExperimentConfig,
    records: list[tuple[str, str, str, str]],
    depths: dict[str, int],
    alias: dict[str, str],
) -> tuple[Catalog, set[tuple[str, str]] | None, list[tuple[str, str]], list[str]]:
    allowed = allowlist_for(config, records)
    # ``closed`` is the list in the config (configs/default.json unless a file
    # replaces it). A pair the workbook files under another category
    # (DOORS/DOORBELL is BELLS/DOORBELL) keeps that row's synonyms. An explicit
    # pairs list still fails on a typo.
    borrowed: list[str] = []
    if config.taxonomy == "closed":
        records, borrowed = borrow_missing_pairs(records, allowed)
    on_missing = "skip" if config.taxonomy == "closed" else "error"
    chosen, resolved, missing = restrict_records(records, allowed, on_missing=on_missing)
    catalog = build_catalog(chosen, depths, alias)
    if not catalog.entries:
        raise SystemExit(f"{config.name}: no UCS subcategories loaded")
    return catalog, resolved, missing, borrowed


def run_experiments(
    configs: list[ExperimentConfig],
    *,
    ucs_path: Path,
    ontology_path: Path,
    manifest_dir: Path,
    splits_dir: Path,
    audio_dir: Path,
    no_audio: bool,
    output_dir: Path | None,
) -> list[Path]:
    """Write scored manifests for each config. Never writes into ``manifest_dir``.

    Splits the config does not score are copied from ``manifest_dir`` into
    the experiment folder.
    """
    if not ucs_path.is_file():
        raise SystemExit(f"UCS list not found: {ucs_path}")
    if not ontology_path.is_file():
        raise SystemExit(f"AudioSet ontology not found: {ontology_path}")
    if not configs:
        raise SystemExit("no experiments to run")
    index = None
    if not no_audio:
        if not audio_dir.is_dir():
            raise SystemExit(f"audio folder not found: {audio_dir}")
        index = load_audio_index(audio_dir)
    records = load_ucs(ucs_path, None)
    depths, alias = load_ontology(ontology_path)
    full_catalog = build_catalog(records, depths, alias)
    multiple = len(configs) > 1
    written: list[Path] = []
    seen: dict[Path, str] = {}
    for config in configs:
        catalog, resolved, skipped, borrowed = catalog_for(config, records, depths, alias)
        out_dir = output_directory(config, output_dir, multiple=multiple).resolve()
        assert_outside_manifests(out_dir, manifest_dir)
        if out_dir in seen:
            raise SystemExit(f"{config.name} and {seen[out_dir]} would both write {out_dir}")
        seen[out_dir] = config.name
        print(format_settings(config, len(catalog.entries)))
        print(f"  output {out_dir}")
        sections = [format_settings(config, len(catalog.entries)), f"output {out_dir}"]
        if borrowed:
            note = "borrowed: " + "; ".join(borrowed)
            print(f"  {note}")
            sections.append(note)
        if skipped:
            warning = "warning: " + missing_pairs_message(skipped) + " (not scored)"
            print(f"  {warning}")
            sections.append(warning)
        background = None if config.taxonomy == "open" else full_catalog
        allowed_pairs = {(entry.category, entry.subcategory) for entry in catalog.entries}
        for name in config.splits:
            fieldnames, rows, source = load_split_rows(
                name,
                manifest_dir=manifest_dir,
                splits_dir=splits_dir,
                audio_dir=audio_dir,
                index=index,
            )
            if index is not None:
                counts = apply_audio(rows, index)
                print(f"  {name}: audio folder {matched_phrase(counts)}")
            predictions = score_manifest(
                catalog,
                rows,
                min_score=config.min_score,
                weights=config.weights,
                on_tie=config.on_tie,
                background=background,
                allowed_pairs=None if background is None else allowed_pairs,
            )
            summary = report(rows, predictions)
            print(summary)
            sections.append(f"[{name}] source {source}\n{summary}")
            destination = out_dir / f"envsound_{name}.csv"
            write_manifest(destination, extend_fields(fieldnames, rows), labeled_rows(rows, predictions))
            written.append(destination)
            print(f"wrote {destination} ({len(rows)} rows)")
        copied = manual_splits_to_copy(config.splits)
        written.extend(copy_manual_manifests(out_dir, manifest_dir, copied))
        if copied:
            sections.append("copied from manual: " + ", ".join(f"envsound_{name}.csv" for name in copied))
        snapshot = config_snapshot(
            config,
            subcategory_count=len(catalog.entries),
            pairs=resolved,
            copied=copied,
        )
        if skipped:
            snapshot["skipped_pairs"] = [
                f"{category}/{subcategory}" for category, subcategory in sorted(skipped)
            ]
        config_path = out_dir / "config.json"
        config_path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
        (out_dir / "report.txt").write_text("\n\n".join(sections) + "\n", encoding="utf-8")
        print(f"wrote {config_path}")
    return written


def collect_experiments(args: argparse.Namespace) -> list[ExperimentConfig]:
    if args.config and (args.experiment or args.experiment_dir):
        raise SystemExit("use --config or --experiment, not both")
    files: list[Path] = []
    if args.experiment_dir is not None:
        if args.experiment:
            raise SystemExit("use either --experiment or --experiment-dir")
        folder = args.experiment_dir
        if not folder.is_dir():
            raise SystemExit(f"experiment directory not found: {folder}")
        files = sorted(
            path
            for path in folder.glob("*.json")
            if path.is_file() and path.resolve() != DEFAULT_CONFIG.resolve()
        )
        if not files:
            raise SystemExit(f"no JSON configs in {folder}")
    elif args.experiment:
        files = list(args.experiment)
    if files:
        if args.experiment_name and len(files) != 1:
            raise SystemExit("--experiment-name applies to one experiment")
        loaded: list[ExperimentConfig] = []
        for path in files:
            if not path.is_file():
                raise SystemExit(f"experiment config not found: {path}")
            loaded.append(apply_cli(load_config_file(path), args))
        return loaded
    if args.experiment_name:
        base = load_config_file(args.config) if args.config else default_config()
        return [apply_cli(base, args)]
    raise SystemExit("no experiment config")


def write_scored(path: Path, fieldnames: list[str], rows: list[dict[str, str]], predictions: list[Prediction]) -> None:
    extra = ["pred_category", "pred_subcategory", "pred_score", "pred_status", "pred_evidence"]
    columns = list(fieldnames)
    for name in extra:
        if name not in columns:
            columns.append(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row, prediction in zip(rows, predictions):
            out = dict(row)
            out["pred_category"] = prediction.category
            out["pred_subcategory"] = prediction.subcategory
            out["pred_score"] = f"{prediction.score:.2f}"
            out["pred_status"] = prediction.status
            out["pred_evidence"] = prediction.evidence
            writer.writerow(out)


def report(rows: list[dict[str, str]], predictions: list[Prediction]) -> str:
    counts: dict[str, int] = defaultdict(int)
    gold_total = 0
    gold_pair = 0
    gold_sub = 0
    cat_total = 0
    cat_hit = 0
    empty_sub = 0
    empty_sub_hit = 0
    by_source: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    confusions: dict[tuple[str, str], int] = defaultdict(int)

    for row, prediction in zip(rows, predictions):
        counts[prediction.status] += 1
        gold_cat = (row.get("Category") or "").strip()
        gold = (row.get("SubCategory") or "").strip()
        if gold_cat:
            cat_total += 1
            if prediction.category == gold_cat:
                cat_hit += 1
            if not gold:
                empty_sub += 1
                if prediction.category == gold_cat:
                    empty_sub_hit += 1
        if not gold:
            continue
        gold_total += 1
        source = row.get("source") or ""
        by_source[source][1] += 1
        pair = f"{gold_cat}/{gold}"
        if prediction.subcategory:
            got = f"{prediction.category}/{prediction.subcategory}"
        elif prediction.category:
            got = f"{prediction.category}/(category only)"
        else:
            got = "(none)"
        if prediction.category == gold_cat and prediction.subcategory == gold:
            gold_pair += 1
            gold_sub += 1
            by_source[source][0] += 1
        else:
            if prediction.subcategory == gold:
                gold_sub += 1
            confusions[(pair, got)] += 1

    lines = [
        f"rows {len(rows)}",
        "  ".join(f"{name} {counts[name]}" for name in ("assigned", "category", "tie", "below")),
        f"gold category {cat_hit}/{cat_total} ({100 * cat_hit / cat_total:.1f}%)" if cat_total else "gold category 0",
        (
            f"category where subcategory was empty {empty_sub_hit}/{empty_sub} ({100 * empty_sub_hit / empty_sub:.1f}%)"
            if empty_sub
            else "category where subcategory was empty 0"
        ),
        f"gold subcategory rows {gold_total}",
    ]
    if gold_total:
        lines.append(f"exact category/subcategory {gold_pair}/{gold_total} ({100 * gold_pair / gold_total:.1f}%)")
        lines.append(f"subcategory only {gold_sub}/{gold_total} ({100 * gold_sub / gold_total:.1f}%)")
        for source in sorted(by_source):
            correct, total = by_source[source]
            lines.append(f"  {source}: {correct}/{total} ({100 * correct / total:.1f}%)")
        lines.append("top mismatches (gold -> predicted):")
        for (pair, got), count in sorted(confusions.items(), key=lambda item: item[1], reverse=True)[:12]:
            lines.append(f"  {count:4d}  {pair} -> {got}")
    return "\n".join(lines)


def explain(prediction: Prediction, top: int) -> str:
    lines = [
        f"{prediction.status}  {prediction.category} / {prediction.subcategory}  {prediction.score:.2f}".rstrip(),
        prediction.evidence,
        "",
    ]
    for category, subcategory, score, evidence in prediction.ranked[:top]:
        lines.append(f"{score:7.2f}  {category} / {subcategory}")
        if evidence:
            lines.append(f"         {evidence}")
    return "\n".join(lines)


def check_manifest_join() -> None:
    full = [
        {
            "filename": "a.wav",
            "Category": "ANIMALS",
            "SubCategory": "DOG",
            "Keywords": "Dog",
            "source": "ESC-50",
            "path": "ESC-50/a.wav",
            "exists": "True",
            "uploader_tags": "dog",
        },
        {
            "filename": "b.wav",
            "Category": "HUMAN",
            "SubCategory": "",
            "Keywords": "Cough",
            "source": "ESC-50",
            "path": "ESC-50/b.wav",
            "exists": "True",
            "uploader_tags": "",
        },
        {
            "filename": "c.wav",
            "Category": "WATER",
            "SubCategory": "POUR",
            "Keywords": "Pour",
            "source": "AudioSet",
            "path": "AudioSet/c.wav",
            "exists": "True",
            "uploader_tags": "",
        },
    ]
    fields = list(full[0])
    split = [
        {"filename": "b.wav", "source": "ESC-50", "path": "ESC-50/b.wav"},
        {"filename": "a.wav", "source": "ESC-50", "path": "ESC-50/a.wav"},
    ]
    out_fields, rows = select_manifest_rows(split, full, fields)
    assert out_fields[: len(MANIFEST_COLUMNS)] == MANIFEST_COLUMNS, out_fields
    assert out_fields[-1] == "uploader_tags"
    assert [row["filename"] for row in rows] == ["b.wav", "a.wav"]
    assert rows[0]["Keywords"] == "Cough" and rows[0]["SubCategory"] == ""
    assert rows[1]["uploader_tags"] == "dog"
    try:
        select_manifest_rows(
            [{"filename": "missing.wav", "source": "ESC-50", "path": "ESC-50/missing.wav"}],
            full,
            fields,
        )
    except ValueError as exc:
        assert "not in the full manifest" in str(exc)
    else:
        raise AssertionError("missing split row should fail")
    try:
        select_manifest_rows(split, full + [dict(full[0])], fields)
    except ValueError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("duplicate source row should fail")


def check_audio_helpers() -> None:
    assert audioset_keywords("Speech;Fire alarm") == "Speech,Fire alarm"
    assert audioset_keywords("Water tap, faucet;Speech") == "Water tap, faucet,Speech"
    assert join_tags(["air", "alarm", "door, bell"]) == "air,alarm,door  bell"
    labels = predominant_labels(
        {"/m/bell": [1.0, 1.0, -1], "/m/oven": [0.5, 0.5], "/m/alarm": [1.0]},
        {"/m/bell": "Bell", "/m/oven": "Microwave_oven", "/m/alarm": "Alarm"},
        ["Microwave_oven", "Bell", "Alarm"],
    )
    assert labels == "Bell,Alarm", labels
    index = AudioIndex({("a.wav", "FSD50K"): {"Keywords": "Bell", "pp_labels": "Bell", "uploader_tags": "bell"}})
    row = {"filename": "a.wav", "source": "FSD50K", "Keywords": "Alarm"}
    assert index.apply(row) == "refreshed"
    assert row["Keywords"] == "Bell" and row["pp_labels"] == "Bell" and row["title"] == ""


def check_rows_from_audio() -> None:
    index = AudioIndex(
        {
            ("a.wav", "ESC-50"): {
                "Keywords": "dog",
                "pp_labels": "",
                "uploader_tags": "",
                "title": "",
                "description": "",
            }
        }
    )
    prior = [
        {
            "filename": "a.wav",
            "Category": "ANIMALS",
            "SubCategory": "DOG",
            "Keywords": "Dog",
            "source": "ESC-50",
            "path": "old/a.wav",
            "exists": "False",
        }
    ]
    split = [{"filename": "a.wav", "source": "ESC-50", "path": "ESC-50/audio/a.wav"}]
    fields, rows = rows_from_audio(split, prior, index, ROOT / "audio")
    assert rows[0]["path"] == "ESC-50/audio/a.wav"
    assert (rows[0]["Category"], rows[0]["SubCategory"]) == ("ANIMALS", "DOG")
    assert rows[0]["Keywords"] == "dog"
    assert "pp_labels" in fields
    _fields, blank = rows_from_audio(split, [], index, ROOT / "audio")
    assert blank[0]["Category"] == "" and blank[0]["SubCategory"] == ""


def _cli(**overrides: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "set": None,
        "min_score": None,
        "taxonomy": None,
        "closed_slice": False,
        "categories": None,
        "pair_list": None,
        "experiment_name": None,
        "write_splits": None,
        "on_tie": None,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def _fails(call, text: str) -> None:
    try:
        call()
    except SystemExit as exc:
        assert text in str(exc.code), exc.code
    else:
        raise AssertionError(f"expected a failure containing {text!r}")


def check_experiments() -> None:
    assert DEFAULT_WRITE_SPLITS == ("test",)
    assert "train" not in DEFAULT_WRITE_SPLITS and "val" not in DEFAULT_WRITE_SPLITS
    assert parse_split_list("val,train") == ("train", "val")
    _fails(lambda: parse_split_list("holdout"), "unknown split")

    builtin = default_config()
    assert builtin.name == "default"
    assert builtin.splits == ("test",)
    assert builtin.taxonomy == "closed"
    assert default_config() is builtin
    plain = parse_experiment({"name": "plain"})
    assert plain.splits == builtin.splits
    assert plain.taxonomy == builtin.taxonomy
    assert plain.weights == builtin.weights
    closed = parse_experiment(
        {
            "name": "closed-strict",
            "taxonomy": "closed",
            "splits": ["val", "test"],
            "min_score": 4,
            "weights": {"exact_sub": 9, "word": 0.5},
            "on_tie": "blank",
        }
    )
    assert closed.splits == ("val", "test")
    assert closed.weights.exact_sub == 9 and closed.weights.word == 0.5
    assert closed.weights.pp_bonus == builtin.weights.pp_bonus
    assert closed.closed == builtin.closed
    assert ("ALARMS", "BELL") in builtin.closed and ("DOORS", "DOORBELL") in builtin.closed
    assert len(builtin.closed) == 21
    assert closed.min_score == 4
    _fails(lambda: parse_experiment({"name": "bad", "splits": ["train", "holdout"]}), "unknown split")
    _fails(lambda: parse_experiment({"name": "bad", "mystery": 1}), "unknown settings")

    overridden = apply_cli(plain, _cli(write_splits="train,val,test", set=["exact_sub=8", "min_score=1"]))
    assert overridden.splits == SPLIT_NAMES
    assert overridden.weights.exact_sub == 8 and overridden.min_score == 1

    records = [
        ("ANIMALS", "DOG", "a dog", "dog,puppy"),
        ("BELLS", "DOORBELL", "a doorbell", "doorbell"),
    ]
    categories = parse_experiment(
        {"name": "animals", "taxonomy": {"mode": "categories", "categories": ["animals"]}}
    )
    assert allowlist_for(categories, records) == {("ANIMALS", "DOG")}
    pairs = parse_experiment({"name": "dog", "taxonomy": {"mode": "pairs", "pairs": ["ANIMALS/DOG"]}})
    chosen, resolved, missing = restrict_records(records, allowlist_for(pairs, records))
    assert chosen == [records[0]] and resolved == {("ANIMALS", "DOG")} and missing == []
    kept, kept_pairs, skipped = restrict_records(
        records, {("ANIMALS", "DOG"), ("NOPE", "MISSING")}, on_missing="skip"
    )
    assert kept == [records[0]] and kept_pairs == {("ANIMALS", "DOG")} and skipped == [("NOPE", "MISSING")]
    _fails(lambda: restrict_records(records, {("NOPE", "MISSING")}), "not in the UCS list")

    row = {"Category": "ANIMALS", "SubCategory": "DOG", "Keywords": "dog"}
    prediction = Prediction(category="ALARMS", subcategory="BELL", status="assigned", score=3)
    [labeled] = labeled_rows([row], [prediction])
    assert (labeled["Category"], labeled["SubCategory"]) == ("ALARMS", "BELL")
    assert row["SubCategory"] == "DOG"

    manual = ROOT / "manifests" / "manual"
    _fails(lambda: assert_outside_manifests(manual, manual), "manual")
    _fails(lambda: assert_outside_manifests(manual / "nested", manual), "manual")
    assert_outside_manifests(ROOT / "experiments" / "demo", manual)
    assert manual_splits_to_copy(("test",)) == ("train", "val")
    assert manual_splits_to_copy(("val", "test")) == ("train",)
    assert manual_splits_to_copy(SPLIT_NAMES) == ()
    with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
        root = Path(tmp)
        source = root / "manual"
        source.mkdir()
        (source / "envsound_train.csv").write_text("filename\na.wav\n", encoding="utf-8")
        (source / "envsound_val.csv").write_text("filename\nb.wav\n", encoding="utf-8")
        out = root / "experiments" / "demo"
        copied = copy_manual_manifests(out, source, ("train", "val"))
        assert [path.name for path in copied] == ["envsound_train.csv", "envsound_val.csv"]
        assert (out / "envsound_train.csv").read_text(encoding="utf-8") == "filename\na.wav\n"
        assert copy_manual_manifests(out, source, ()) == []
        _fails(lambda: copy_manual_manifests(out, source, ("test",)), "missing")


def self_test(catalog: Catalog) -> None:
    check_experiments()
    check_manifest_join()
    check_audio_helpers()
    check_rows_from_audio()
    assert split_labels("Smoke detector, smoke alarm,Fire alarm") == [
        "Smoke detector, smoke alarm",
        "Fire alarm",
    ]
    assert split_labels("Waves, surf,Wind,Ocean") == ["Waves, surf", "Wind", "Ocean"]
    assert split_labels("Bark,Dog,Domestic_animals_and_pets,Animal") == [
        "Bark",
        "Dog",
        "Domestic_animals_and_pets",
        "Animal",
    ]
    assert split_labels("clock_alarm") == ["clock_alarm"]
    assert catalog.depth_of("Dog") == 2
    assert catalog.depth_of("Bark") == 3
    assert catalog.depth_of("Animal") == 0
    assert catalog.depth_of("Domestic_animals_and_pets") == 1
    assert catalog.depth_of("Dishes_and_pots_and_pans") == 2
    weights = default_config().weights
    dog_bonus = 1.0 + weights.depth_step * catalog.depth_of("Dog")
    assert catalog.bonus_of("Dog") == dog_bonus
    assert catalog.bonus_of("clock_alarm") == 1.0

    dog = score_text(catalog, "dog")
    assert (dog.category, dog.subcategory) == ("ANIMALS", "DOG"), dog
    assert dog.score == weights.exact_sub * dog_bonus, dog
    heavier = score_text(catalog, "dog", weights=weights.with_values(exact_sub=10))
    assert (heavier.category, heavier.subcategory) == ("ANIMALS", "DOG"), heavier
    assert heavier.score == 10 * dog_bonus, heavier

    meow = score_text(catalog, "Meow")
    assert (meow.category, meow.subcategory) == ("ANIMALS", "CAT DOMESTIC"), meow

    bell = score_text(catalog, "Bell")
    assert (bell.category, bell.subcategory) == ("ALARMS", "BELL"), bell
    assert bell.score == weights.exact_sub * catalog.bonus_of("Bell"), bell

    pp = score_text(catalog, "Bell", pp_labels="Bell")
    assert pp.score == bell.score + weights.pp_bonus, (bell.score, pp.score)
    assert (pp.category, pp.subcategory) == ("ALARMS", "BELL")
    pp_only = score_text(catalog, "", pp_labels="Bell")
    assert (pp_only.category, pp_only.subcategory, pp_only.score) == (
        "ALARMS",
        "BELL",
        bell.score + weights.pp_bonus,
    ), pp_only

    knock = score_text(catalog, "Knock")
    assert knock.status == "tie", knock
    opened = score_text(catalog, "Knock", on_tie="first")
    assert opened.status == "assigned" and opened.score == knock.score and opened.subcategory, opened
    knock_door = score_text(catalog, "Knock", category="DOORS")
    assert (knock_door.category, knock_door.subcategory) == ("DOORS", "KNOCK"), knock_door

    pour = score_text(catalog, "Pour", category="WATER")
    assert (pour.category, pour.subcategory) == ("WATER", "POUR"), pour

    uploader = score_text(catalog, "", uploader_tags="doorbell")
    assert (uploader.category, uploader.subcategory, uploader.score) == (
        "BELLS",
        "DOORBELL",
        weights.uploader_tag,
    ), uploader
    quiet = score_text(catalog, "", uploader_tags="doorbell", weights=weights.with_values(uploader_tag=0))
    assert quiet.status == "below" and quiet.score == 0, quiet

    title = score_text(catalog, "", title="doorbell in the hallway")
    assert title.status == "below", title
    assert title.score == weights.title_match

    description = score_text(catalog, "", description="someone rings the doorbell")
    assert description.status == "below", description
    assert description.score == weights.description_match

    sneeze = score_text(catalog, "sneezing")
    assert (sneeze.category, sneeze.subcategory) == ("HUMAN", "SNEEZE"), sneeze

    fire = score_text(catalog, "Fire")
    assert (fire.status, fire.category, fire.subcategory) == ("category", "FIRE", ""), fire
    alarm = score_text(catalog, "Alarm")
    assert (alarm.status, alarm.category, alarm.subcategory) == ("category", "ALARMS", ""), alarm
    clock_alarm = score_text(catalog, "clock_alarm")
    assert (clock_alarm.status, clock_alarm.category, clock_alarm.subcategory) == (
        "assigned",
        "ALARMS",
        "CLOCK",
    ), clock_alarm
    assert clock_alarm.score == weights.exact_sub * catalog.bonus_of("clock_alarm"), clock_alarm
    alarm_clock = score_text(catalog, "alarm clock")
    assert (alarm_clock.category, alarm_clock.subcategory) == ("ALARMS", "CLOCK"), alarm_clock
    clock_tick = score_text(catalog, "clock tick")
    assert (clock_tick.status, clock_tick.category, clock_tick.subcategory) == (
        "assigned",
        "CLOCKS",
        "TICK",
    ), clock_tick
    fire_alarm = score_text(catalog, "fire alarm")
    assert fire_alarm.status == "tie" and fire_alarm.subcategory == "", fire_alarm
    car_alarm = score_text(catalog, "car alarm")
    assert (car_alarm.status, car_alarm.category, car_alarm.subcategory) == ("category", "ALARMS", ""), car_alarm
    breathing = score_text(catalog, "breathing")
    assert (breathing.status, breathing.category, breathing.subcategory) == ("category", "HUMAN", ""), breathing
    assert {item[1] for item in breathing.ties} == {"BREATH", "SNORE"}, breathing
    burp = score_text(catalog, "Burping, eructation,Speech")
    assert burp.status == "tie" and burp.subcategory == "", burp
    tick = score_text(catalog, "Tick-tock,Clock")
    assert (tick.category, tick.subcategory) == ("ALARMS", "CLOCK"), tick
    snore = score_text(catalog, "Snoring,Animal")
    assert (snore.category, snore.subcategory) == ("HUMAN", "SNORE"), snore
    plumbing = score_text(catalog, "Toilet flush,Water")
    assert (plumbing.category, plumbing.subcategory) == ("WATER", "PLUMBING"), plumbing
    drip = score_text(catalog, "Trickle, dribble,Speech")
    assert (drip.category, drip.subcategory) == ("VOICES", "HISTORICAL"), drip
    cat = score_text(catalog, "Cat")
    assert (cat.status, cat.category, cat.subcategory) == ("category", "ANIMALS", ""), cat
    assert {item[1] for item in cat.ties} == {"CAT DOMESTIC", "CAT WILD"}, cat
    purr = score_text(catalog, "Purr")
    assert purr.status == "tie" and purr.subcategory == "", purr
    knock_door = score_text(catalog, "door_wood_knock")
    assert (knock_door.category, knock_door.subcategory) == ("DOORS", "KNOCK"), knock_door
    storm = score_text(catalog, "Thunder,Rain,Water,Thunderstorm")
    assert (storm.category, storm.subcategory) == ("WEATHER", "THUNDER"), storm
    wet_thunder = score_text(catalog, "Rain,Thunderstorm,Thunder")
    assert (wet_thunder.category, wet_thunder.subcategory) == ("WEATHER", "THUNDER"), wet_thunder
    dry = score_text(catalog, "Thunder,Thunderstorm")
    assert (dry.category, dry.subcategory) == ("WEATHER", "THUNDER"), dry
    mechanisms = score_text(catalog, "Tick-tock,Clock,Mechanisms")
    assert (mechanisms.category, mechanisms.subcategory) == ("ALARMS", "CLOCK"), mechanisms
    cowbell = score_text(catalog, "Cowbell,Bell")
    assert (cowbell.category, cowbell.subcategory) == ("ALARMS", "BELL"), cowbell
    clapping = score_text(catalog, "Clapping")
    assert clapping.status == "tie" and clapping.subcategory == "", clapping
    chime = score_text(catalog, "Chime,Bell")
    assert chime.status == "tie" and chime.subcategory == "", chime
    crackling = score_text(catalog, "crackling_fire")
    assert (crackling.status, crackling.category, crackling.subcategory) == ("category", "FIRE", ""), crackling
    pouring = score_text(catalog, "pouring_water")
    assert (pouring.status, pouring.category, pouring.subcategory) == ("category", "WATER", ""), pouring
    drops = score_text(catalog, "water_drops")
    assert (drops.status, drops.category, drops.subcategory) == ("category", "WATER", ""), drops
    thunder_only = score_text(catalog, "Thunderstorm")
    assert thunder_only.subcategory == "" and thunder_only.category == "WEATHER", thunder_only

    closed, _resolved, missing, borrowed = catalog_for(
        default_config(), load_ucs(DEFAULT_UCS, None), catalog.depths, catalog.alias
    )
    assert missing == [] and any("DOORBELL" in note for note in borrowed), (missing, borrowed)
    doorbell = score_text(closed, "Doorbell")
    assert (doorbell.category, doorbell.subcategory) == ("DOORS", "DOORBELL"), doorbell
    allowed = {(entry.category, entry.subcategory) for entry in closed.entries}
    pig = recover_category(score_text(closed, "pig"), score_text(catalog, "pig"), allowed)
    assert (pig.status, pig.category, pig.subcategory) == ("category", "ANIMALS", ""), pig
    creak = recover_category(
        score_text(closed, "door_wood_creaks"), score_text(catalog, "door_wood_creaks"), allowed
    )
    assert (creak.status, creak.category) == ("category", "DOORS") and creak.subcategory == "", creak


def _scoring_config(args: argparse.Namespace) -> ExperimentConfig:
    base = load_config_file(args.config) if args.config else default_config()
    return apply_cli(base, args)


def _settings_were_customized(args: argparse.Namespace) -> bool:
    return any(
        (
            args.config,
            args.set,
            args.taxonomy,
            args.closed_slice,
            args.on_tie,
            args.categories,
            args.pair_list,
            args.min_score is not None,
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score keywords against the UCS list.")
    parser.add_argument("manifest", nargs="?", type=Path, help="envsound CSV to score")
    parser.add_argument("-o", "--output", type=Path, help="CSV with pred_* columns added")
    parser.add_argument(
        "--make-manifests",
        action="store_true",
        help="write manifest CSVs from splits/ and the audio-folder label files. Test only, unless --write-splits or a config says otherwise",
    )
    parser.add_argument("--splits", type=Path, default=DEFAULT_SPLITS, help="directory of train.csv, val.csv, test.csv")
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=DEFAULT_SOURCE,
        help="optional directory of full envsound_*.csv lists; Category and SubCategory are copied from these when the file exists, otherwise kept from the manifest being rewritten",
    )
    parser.add_argument(
        "--audio",
        type=Path,
        default=DEFAULT_AUDIO,
        help="dataset root containing AudioSet, ESC-50, and FSD50K",
    )
    parser.add_argument(
        "--no-audio",
        action="store_true",
        help="score the CSV columns only, without the audio-folder label files",
    )
    parser.add_argument(
        "--manifest-dir",
        type=Path,
        default=DEFAULT_MANIFESTS,
        help="hand-tagged manifests (manifests/manual). Experiments never write here; splits they do not score are copied from here",
    )
    parser.add_argument("--ucs", type=Path, default=DEFAULT_UCS)
    parser.add_argument("--ontology", type=Path, default=DEFAULT_ONTOLOGY)
    parser.add_argument(
        "--min-score",
        type=float,
        default=None,
        help=f"minimum score to assign a subcategory (default: {default_config().min_score:g})",
    )
    parser.add_argument(
        "--closed-slice",
        action="store_true",
        help="score only the closed list in configs/default.json, or the config's own closed list (same as --taxonomy closed)",
    )
    parser.add_argument("--taxonomy", choices=TAXONOMY_MODES, help="open, closed, categories, or pairs")
    parser.add_argument("--categories", help="comma-separated UCS categories for --taxonomy categories")
    parser.add_argument(
        "--pairs",
        dest="pair_list",
        help="comma-separated CATEGORY/SUBCATEGORY pairs for --taxonomy pairs",
    )
    parser.add_argument("--on-tie", choices=("blank", "first"), help="blank leaves a tie empty; first keeps one of them")
    parser.add_argument(
        "--set",
        action="append",
        default=None,
        metavar="NAME=VALUE",
        help="override one weight or min_score, for example --set exact_sub=8 --set pp_bonus=1",
    )
    parser.add_argument("--config", type=Path, help="JSON scoring config for one manifest, --make-manifests, or --experiment-name")
    parser.add_argument(
        "--experiment",
        action="append",
        type=Path,
        default=None,
        help="JSON config for one tagging experiment. Repeat to run several. Writes experiments/<name>/ and does not touch manifests/manual/",
    )
    parser.add_argument(
        "--experiment-dir",
        type=Path,
        help="run every JSON config in this directory except configs/default.json",
    )
    parser.add_argument("--experiment-name", help="name for an experiment built from flags, or rename a single --experiment file")
    parser.add_argument("--output-dir", type=Path, help="folder for experiment manifests. A batch writes one subfolder per name")
    parser.add_argument(
        "--write-splits",
        help="splits to score or rebuild, comma-separated. Default is test. Train and val left off the list stay as the manual files, and an experiment copies them into its output folder. Example: train,val,test",
    )
    parser.add_argument("--keywords", help="score one keyword list and print the top candidates")
    parser.add_argument("--category", default="", help="existing Category, used only to break a tie")
    parser.add_argument("--pp", default="", help="predominant labels, comma-separated like Keywords")
    parser.add_argument("--uploader-tags", default="")
    parser.add_argument("--title", default="")
    parser.add_argument("--description", default="")
    parser.add_argument("--top", type=int, default=8)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    experiment_mode = bool(args.experiment or args.experiment_dir or args.experiment_name)
    if args.write_splits is not None and not (args.make_manifests or experiment_mode):
        raise SystemExit("--write-splits applies to --make-manifests and --experiment")
    if args.output_dir is not None and not experiment_mode:
        raise SystemExit("--output-dir applies to --experiment")

    configs: list[ExperimentConfig] | None = None
    if experiment_mode:
        if args.manifest is not None or args.keywords is not None:
            raise SystemExit("pass an experiment or a manifest to score, not both")
        configs = collect_experiments(args)

    if args.make_manifests:
        if configs is not None:
            if len(configs) != 1:
                raise SystemExit("pass one experiment config, or --write-splits, when also building manifests")
            split_choice = configs[0].splits
        else:
            split_choice = _scoring_config(args).splits
        make_manifests(args.splits, args.source_dir, args.manifest_dir, args.audio, split_choice)
        if not experiment_mode and args.manifest is None and args.keywords is None and not args.self_test:
            return 0

    if args.self_test:
        if not args.ucs.is_file():
            raise SystemExit(f"UCS list not found: {args.ucs}")
        if not args.ontology.is_file():
            raise SystemExit(f"AudioSet ontology not found: {args.ontology}")
        full_depths, full_alias = load_ontology(args.ontology)
        full_catalog = build_catalog(load_ucs(args.ucs, None), full_depths, full_alias)
        self_test(full_catalog)
        print(f"self-test ok ({len(full_catalog.entries)} subcategories)")
        if not experiment_mode and args.manifest is None and args.keywords is None:
            return 0

    if experiment_mode:
        assert configs is not None
        run_experiments(
            configs,
            ucs_path=args.ucs,
            ontology_path=args.ontology,
            manifest_dir=args.manifest_dir,
            splits_dir=args.splits,
            audio_dir=args.audio,
            no_audio=args.no_audio,
            output_dir=args.output_dir,
        )
        return 0

    if args.keywords is None and args.manifest is None:
        parser.print_help()
        return 2

    if not args.ucs.is_file():
        raise SystemExit(f"UCS list not found: {args.ucs}")
    if not args.ontology.is_file():
        raise SystemExit(f"AudioSet ontology not found: {args.ontology}")

    config = _scoring_config(args)
    score_depths, score_alias = load_ontology(args.ontology)
    score_records = load_ucs(args.ucs, None)
    catalog, _resolved, skipped, borrowed = catalog_for(config, score_records, score_depths, score_alias)
    full_catalog = build_catalog(score_records, score_depths, score_alias)
    background = None if config.taxonomy == "open" else full_catalog
    allowed_pairs = {(entry.category, entry.subcategory) for entry in catalog.entries}
    if _settings_were_customized(args):
        print(format_scoring(config, len(catalog.entries)))
    if borrowed:
        print("borrowed: " + "; ".join(borrowed))
    if skipped:
        print("warning: " + missing_pairs_message(skipped) + " (not scored)")

    if args.keywords is not None:
        prediction = score_text(
            catalog,
            args.keywords,
            category=args.category,
            pp_labels=args.pp,
            uploader_tags=args.uploader_tags,
            title=args.title,
            description=args.description,
            min_score=config.min_score,
            weights=config.weights,
            on_tie=config.on_tie,
            keep_ranked=args.top,
        )
        if background is not None and prediction.status in ("tie", "below"):
            full = score_text(
                background,
                args.keywords,
                category=args.category,
                pp_labels=args.pp,
                uploader_tags=args.uploader_tags,
                title=args.title,
                description=args.description,
                min_score=config.min_score,
                weights=config.weights,
                on_tie=config.on_tie,
                keep_ranked=args.top,
            )
            prediction = recover_category(prediction, full, allowed_pairs)
        print(explain(prediction, args.top))
        return 0

    fieldnames, rows = load_manifest(args.manifest)
    is_split = "Keywords" not in fieldnames and {"filename", "source", "path"} <= set(fieldnames)
    if is_split and args.no_audio:
        raise SystemExit(
            f"{args.manifest} is a split list, not a manifest. "
            "Run with --make-manifests to build manifests/manual/ from splits/."
        )
    if not args.no_audio:
        if not args.audio.is_dir():
            raise SystemExit(f"audio folder not found: {args.audio}")
        counts = apply_audio(rows, load_audio_index(args.audio))
        if is_split and counts["missing"]:
            raise SystemExit(
                f"{counts['missing']} split rows have no label file under {args.audio}"
            )
        for name in META_COLUMNS:
            if name not in fieldnames:
                fieldnames.append(name)
        fsd = sum(1 for row in rows if row.get("source") == "FSD50K" and row.get("pp_labels"))
        print(
            f"audio folder {matched_phrase(counts)} "
            f"({fsd} FSD50K clips with a predominant label)"
        )
    predictions = score_manifest(
        catalog,
        rows,
        min_score=config.min_score,
        weights=config.weights,
        on_tie=config.on_tie,
        background=background,
        allowed_pairs=None if background is None else allowed_pairs,
    )
    print(report(rows, predictions))
    if args.output:
        write_scored(args.output, fieldnames, rows, predictions)
        print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
