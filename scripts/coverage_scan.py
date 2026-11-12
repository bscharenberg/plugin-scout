"""How much of the plugin catalog can Plugin Scout ever suggest?

A maintainer tool, not part of the plugin. Run it after the catalog grows:

    python3 -I scripts/coverage_scan.py                  # download the live catalog
    python3 -I scripts/coverage_scan.py --file cat.json  # or read a saved copy
    python3 -I scripts/coverage_scan.py --topic games    # which plugins a topic reaches, and the word that matched

It prints the share of plugins that match at least one topic, how many each topic reaches, and the plugins
no topic reaches, so new kinds of plugins are easy to spot. It reads only; nothing is installed or changed.
"""

import argparse
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import catalog  # noqa: E402
import sanitize  # noqa: E402
import usage  # noqa: E402


def load(path):
    if path:
        return catalog.validate(json.loads(Path(path).read_text(encoding="utf-8-sig")))["entries"]
    return catalog.validate(catalog.fetch_catalog())["entries"]


def trigger(topic, entry):
    """The word that matched, or "(catalog category)" when only the category did."""
    pattern = usage._CATALOG[topic]
    for text in (f"{entry.get('name', '')} {entry.get('title') or ''}", (entry.get("description") or "")[:300]):
        m = pattern.search(text)
        if m:
            return m.group(0).lower()
    return "(catalog category)"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", help="a saved copy of plugin-catalog.json")
    ap.add_argument("--topic", help="list what one topic reaches")
    ap.add_argument("--show", type=int, default=40, help="how many unreached plugins to list (default 40)")
    args = ap.parse_args(argv)
    entries = load(args.file)

    if args.topic:
        if args.topic not in usage.TOPICS:
            sys.exit(f"unknown topic; choose from: {', '.join(sorted(usage.TOPICS))}")
        hits = [(trigger(args.topic, e), e) for e in entries if usage._match_strength(args.topic, e)]
        words = collections.Counter(w for w, _ in hits)
        print(f"{args.topic}: {len(hits)} plugins. Matched on: "
              + ", ".join(f"{w} ({n})" for w, n in words.most_common(15)))
        for w, e in hits[:args.show]:
            print(f"  [{w}] {e['name']}: {sanitize.clean(e.get('description'), 90)}")
        return

    per_topic = collections.Counter()
    unreached = []
    for e in entries:
        topics = [t for t in usage.TOPICS if usage._match_strength(t, e)]
        per_topic.update(topics)
        if not topics:
            unreached.append(e)
    reached = len(entries) - len(unreached)
    print(f"Reachable: {reached} of {len(entries)} plugins ({100 * reached / max(len(entries), 1):.1f}%)")
    print("\nPlugins per topic:")
    for t, n in per_topic.most_common():
        print(f"  {n:5}  {usage.label(t)}")
    print(f"\nNot reached by any topic ({len(unreached)}), first {min(args.show, len(unreached))}:")
    for e in unreached[:args.show]:
        print(f"  {e['name']} [{e.get('category')}]: {sanitize.clean(e.get('description'), 90)}")


if __name__ == "__main__":
    main()
