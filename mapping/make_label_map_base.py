"""Build mapping/label_map_base.csv from the labels in audio/.

Each row is one ``(source, label)`` pair that ``make_master_manifest`` writes
into ``manifests/master.csv``. Category and subcategory are copied from
``label_map_llm.csv`` when that pair is already mapped. A label the map does
not list keeps those two fields empty.

Role is not copied. It comes from the source metadata:

- FoleySet's ``category`` column is a ``group``. Its ``sub-category`` is ``primary``.
- ESC-50 has one class per clip and no parent, so every label is ``primary``.
- AudioSet and FSD50K use the AudioSet ontology in
  ``references/audioset_hierarchy.json``. A class with children is ``parent``.
  A class with none is ``primary``.   ``Music``, ``Speech``, and classes that sit
  only under a style, mood, room, noise, recording, or sourceless branch are ``context``.
  Children of ``Vocal music`` stay sound events (``A capella``, ``Beatboxing``,
  ``Chant``). A class that also sits under a physical source stays ``parent``
  or ``primary``.

The original conversion scripts are in ``references/beck_lerch_tools/``.

Usage:
  python mapping/make_label_map_base.py
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from make_master_manifest import (
    AUDIO_DIR,
    MAP_COLUMNS,
    ROOT,
    load_label_map,
    resolve_under_root,
    rows_from_audio,
    split_labels,
    write_manifest,
)

DEFAULT_PRIOR_MAP = ROOT / "mapping" / "label_map_llm.csv"
HIERARCHY = ROOT / "references" / "audioset_hierarchy.json"
FOLEY_METADATA = AUDIO_DIR / "FoleySet" / "metadata" / "foleyset_metadata.csv"
OUT = ROOT / "mapping" / "label_map_base.csv"
SOURCE_ORDER = ("AudioSet", "ESC-50", "FSD50K", "FoleySet")

# Ontology branches that describe style, mood, setting, or a channel, not a sound source.
CONTEXT_BRANCHES = frozenset(
    {
        "Music genre",
        "Music role",
        "Music mood",
        "Acoustic environment",
        "Noise",
        "Background noise",
        "Other sourceless",
        "Silence",
        "Recording",
    }
)
# A class that also belongs to one of these is a sound, even if a second parent is a context branch.
SOURCE_BRANCHES = frozenset(
    {
        "Musical instrument",
        "Human sounds",
        "Animal",
        "Sounds of things",
        "Natural sounds",
    }
)
EXACT_CONTEXT = frozenset({"Music", "Speech"})


class Hierarchy:
    """AudioSet ontology: name to node, and each id's parent ids."""

    def __init__(self, nodes: list[dict[str, object]]) -> None:
        self.by_name = {str(node["name"]): node for node in nodes}
        self.parents: dict[str, list[str]] = {str(node["id"]): [] for node in nodes}
        for node in nodes:
            parent_id = str(node["id"])
            for child_id in node.get("child_ids") or []:
                child = str(child_id)
                if child in self.parents:
                    self.parents[child].append(parent_id)

    def ancestor_names(self, node_id: str) -> set[str]:
        """Names of this node and every node above it."""
        names: set[str] = set()
        seen: set[str] = set()
        stack = [node_id]
        by_id = {str(node["id"]): node for node in self.by_name.values()}
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            node = by_id.get(current)
            if node is not None:
                names.add(str(node["name"]))
            stack.extend(self.parents.get(current, []))
        return names

    def role(self, name: str) -> str:
        """``context``, ``parent``, or ``primary`` for one ontology display name."""
        node = self.by_name.get(name)
        if node is None:
            return "primary"
        ancestors = self.ancestor_names(str(node["id"]))
        if name in EXACT_CONTEXT:
            return "context"
        in_context = bool(ancestors & CONTEXT_BRANCHES)
        # Vocal music is filed under Music genre. The node itself is a style.
        # Its children are performances: A capella, Beatboxing, Chant.
        if "Vocal music" in ancestors and name != "Vocal music":
            in_context = False
        if in_context and not (ancestors & SOURCE_BRANCHES):
            return "context"
        if node.get("child_ids"):
            return "parent"
        return "primary"


def load_hierarchy(path: Path) -> Hierarchy:
    if not path.is_file():
        raise SystemExit(f"ontology hierarchy not found: {path}")
    nodes = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(nodes, list):
        raise SystemExit(f"{path.name} must be a list of ontology nodes")
    return Hierarchy(nodes)


def foley_group_labels(path: Path) -> set[str]:
    """FoleySet ``category`` values. Those names are groups, not sound classes."""
    if not path.is_file():
        raise SystemExit(f"FoleySet metadata not found: {path}")
    groups: set[str] = set()
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            name = (row.get("category") or "").strip()
            if name:
                groups.add(name)
    return groups


def display_name(label: str) -> str:
    """FSD50K ``Electric_guitar`` and ``Boat_and_Water_vehicle`` use the ontology's display name."""
    if "_" not in label:
        return label
    return label.replace("_and_", ", ").replace("_", " ")


def role_for_label(source: str, label: str, groups: set[str], hierarchy: Hierarchy) -> str:
    """The role of one source label."""
    if source == "FoleySet":
        if label in groups:
            return "group"
        return "primary"
    if source == "ESC-50":
        return "primary"
    return hierarchy.role(display_name(label))


def unique_label_rows(
    audio_rows: list[dict[str, str]],
    label_map: dict[tuple[str, str], tuple[str, str, str]],
    groups: set[str] | None = None,
    hierarchy: Hierarchy | None = None,
) -> list[dict[str, str]]:
    """One map row per label that appears in the audio metadata."""
    if groups is None:
        groups = foley_group_labels(FOLEY_METADATA)
    if hierarchy is None:
        hierarchy = load_hierarchy(HIERARCHY)
    found: set[tuple[str, str]] = set()
    for row in audio_rows:
        source = (row.get("source") or "").strip()
        for label in split_labels(row.get("Keywords") or ""):
            found.add((source, label))
    order = {name: index for index, name in enumerate(SOURCE_ORDER)}
    rows: list[dict[str, str]] = []
    for source, label in sorted(found, key=lambda pair: (order.get(pair[0], len(order)), pair[1].casefold())):
        mapped = label_map.get((source, label))
        category = ""
        subcategory = ""
        if mapped is not None:
            _prior_role, category, subcategory = mapped
        rows.append(
            {
                "source": source,
                "label": label,
                "role": role_for_label(source, label, groups, hierarchy),
                "category": category,
                "subcategory": subcategory,
            }
        )
    return rows


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Build a label map of the unique keywords in audio/, assigning each label a role."
    )
    parser.add_argument(
        "--prior",
        type=Path,
        default=DEFAULT_PRIOR_MAP,
        metavar="MAP",
        help=f"label map to copy category and subcategory from (default {DEFAULT_PRIOR_MAP.relative_to(ROOT)})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUT,
        metavar="CSV",
        help=f"where to write the base map (default {OUT.relative_to(ROOT)})",
    )
    args = parser.parse_args(argv)
    prior_path = resolve_under_root(args.prior)
    output_path = resolve_under_root(args.output)
    audio_rows, _stats = rows_from_audio(AUDIO_DIR)
    rows = unique_label_rows(audio_rows, load_label_map(prior_path))
    write_manifest(output_path, list(MAP_COLUMNS), rows)
    copied = sum(1 for row in rows if row["category"] or row["subcategory"])
    by_source: dict[str, int] = {}
    by_role: dict[str, int] = {}
    for row in rows:
        by_source[row["source"]] = by_source.get(row["source"], 0) + 1
        by_role[row["role"]] = by_role.get(row["role"], 0) + 1
    sources = ", ".join(f"{name} {by_source[name]}" for name in SOURCE_ORDER if name in by_source)
    roles = ", ".join(f"{name} {by_role[name]}" for name in ("primary", "parent", "context", "group") if name in by_role)
    print(
        f"wrote {output_path} ({len(rows)} rows: {sources}; roles {roles}; "
        f"{copied} categories kept from {prior_path.name}; {len(rows) - copied} without a category)"
    )


if __name__ == "__main__":
    main()
