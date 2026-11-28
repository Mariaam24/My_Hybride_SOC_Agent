"""lab1_ingest.py - TP1: ingestion pipeline + knowledge graph (standard library only).

Run from the project root:
    python3 lab1_ingest.py                       # build the graph, run the queries
    python3 lab1_ingest.py --no-normalize        # see the silent join bug
    python3 lab1_ingest.py --twice               # idempotence + ontology check
    python3 lab1_ingest.py --contact ransomware  # who do I contact?
    python3 lab1_ingest.py --impact db-01        # what depends on db-01?
"""
import argparse
import csv
from pathlib import Path

DATA = Path("data")
NOTES = DATA / "notes"
CSV_FILES = ["topics.csv", "contacts.csv", "assets.csv"]
HEADER_KEYS = ("topic", "role", "updated", "author")      # author is optional (RETEX notes)

# The ontology: which relation may link which kinds of node.
ONTOLOGY = {
    "ABOUT":      ("note", "topic"),
    "OWNED_BY":   ("topic", "team"),
    "MEMBER_OF":  ("person", "team"),
    "DEPENDS_ON": ("asset", "asset"),
}


# ---------------------------------------------------------------- 1. COLLECT
def collect():
    """Which sources exist? Notes (unstructured) and CSV files (structured)."""
    return sorted(NOTES.glob("*.md")), [DATA / name for name in CSV_FILES]


# ---------------------------------------------------------------- 2. EXTRACT
def read_note(path):
    """A note = a 3-line header (topic, role, updated), then one sentence per line."""
    lines = path.read_text(encoding="utf-8").splitlines()
    head, i = {}, 0
    while i < len(lines) and lines[i].split(":", 1)[0].strip() in HEADER_KEYS:
        name, value = lines[i].split(":", 1)
        head[name.strip()] = value.strip()
        i += 1
    sentences = [line.strip() for line in lines[i:] if line.strip()]
    return {"id": path.stem, "topic": head["topic"], "role": head["role"],
            "updated": head["updated"], "author": head.get("author"), "sentences": sentences}


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def extract(note_paths, csv_paths):
    notes = [read_note(p) for p in note_paths]
    topics, contacts, assets = [read_csv(p) for p in csv_paths]
    return notes, topics, contacts, assets


# -------------------------------------------------------------- 3. NORMALIZE
def key(text):
    """The join key: same thing, same spelling. ' IR ' and 'ir' become 'ir'."""
    return text.strip().lower()


def clean(row):
    """Strip the spaces around every value; e-mail addresses get one spelling."""
    row = {name.strip(): (value or "").strip() for name, value in row.items()}
    if "email" in row:
        row["email"] = row["email"].lower()
    return row


def raw(row):
    """What happens WITHOUT normalize: values are kept as they are."""
    return {name: (value or "") for name, value in row.items()}


# ---------------------------------------------------------------- 4. ENRICH
def enrich(notes, topics, k):
    """Add what no note says by itself: the team that owns it (from topics.csv)."""
    team_of = {k(r["topic"]): r["team"] for r in topics}
    for note in notes:
        note["team"] = team_of.get(k(note["topic"]))      # None = orphan note
    return notes


# ------------------------------------------------------------------ 5. LOAD
def new_graph():
    return {"nodes": {}, "edges": set()}


def add_node(g, node_id, kind, **props):
    """Idempotent: a node that already exists is left as it is (like MERGE)."""
    g["nodes"].setdefault(node_id, {"kind": kind, **props})


def add_edge(g, src, rel, dst):
    """Idempotent, and the ontology refuses a relation between the wrong kinds."""
    kinds = (g["nodes"][src]["kind"], g["nodes"][dst]["kind"])
    assert kinds == ONTOLOGY[rel], f"{rel} cannot link {kinds[0]} -> {kinds[1]}"
    g["edges"].add((src, rel, dst))


def build_graph(verbose=False, normalize=True, graph=None):
    k = key if normalize else (lambda s: s)
    prep = clean if normalize else raw

    note_paths, csv_paths = collect()
    notes, topics, contacts, assets = extract(note_paths, csv_paths)
    topics, contacts, assets = ([prep(r) for r in rows] for rows in (topics, contacts, assets))
    notes = enrich(notes, topics, k)

    g = graph if graph is not None else new_graph()
    rejected = 0

    for r in topics:                                   # topic -OWNED_BY-> team
        if not (r["topic"].strip() and r["team"].strip()):
            rejected += 1
            continue
        add_node(g, "topic:" + k(r["topic"]), "topic", name=r["topic"])
        add_node(g, "team:" + k(r["team"]), "team", name=r["team"])
        add_edge(g, "topic:" + k(r["topic"]), "OWNED_BY", "team:" + k(r["team"]))

    for n in notes:                                    # note -ABOUT-> topic
        add_node(g, "note:" + n["id"], "note", name=n["id"], role=n["role"],
                 updated=n["updated"], team=n["team"], author=n["author"])
        add_node(g, "topic:" + k(n["topic"]), "topic", name=n["topic"])
        add_edge(g, "note:" + n["id"], "ABOUT", "topic:" + k(n["topic"]))

    for r in contacts:                                 # person -MEMBER_OF-> team
        if not (r["person"].strip() and r["team"].strip()):
            rejected += 1
            continue
        add_node(g, "person:" + k(r["person"]), "person", name=r["person"],
                 team=r["team"], email=r["email"], shift=r["shift"])
        add_node(g, "team:" + k(r["team"]), "team", name=r["team"])
        add_edge(g, "person:" + k(r["person"]), "MEMBER_OF", "team:" + k(r["team"]))

    for r in assets:                                   # asset -DEPENDS_ON-> asset
        if not r["asset"].strip():
            rejected += 1
            continue
        role = r.get("role") or "restricted"
        add_node(g, "asset:" + k(r["asset"]), "asset", name=r["asset"], role=role)
        if r["depends_on"].strip():
            add_node(g, "asset:" + k(r["depends_on"]), "asset", name=r["depends_on"], role=role)
            add_edge(g, "asset:" + k(r["asset"]), "DEPENDS_ON", "asset:" + k(r["depends_on"]))

    if verbose:
        orphans = [n["id"] for n in notes if n["team"] is None]
        print(f"collect : {len(note_paths)} notes + {len(csv_paths)} CSV files")
        print(f"extract : {len(notes)} notes, {len(topics)} topic rows, "
              f"{len(contacts)} contact rows, {len(assets)} asset rows")
        print(f"load    : {len(g['nodes'])} nodes, {len(g['edges'])} edges")
        print(f"quality : orphan notes (no owning team) = {', '.join(orphans) or 'none'}"
              f" | rejected rows = {rejected}")
    return g


# ------------------------------------------------------------------ QUERIES
def out(g, node, rel):
    """Follow a relation forward: node -rel-> ?"""
    return sorted(d for s, r, d in g["edges"] if s == node and r == rel)


def into(g, node, rel):
    """Follow a relation backward: ? -rel-> node"""
    return sorted(s for s, r, d in g["edges"] if d == node and r == rel)


def contact_for(g, topic):
    """2 hops: topic -OWNED_BY-> team <-MEMBER_OF- person. Empty list = no answer."""
    teams = out(g, "topic:" + key(topic), "OWNED_BY")
    return [g["nodes"][p] for t in teams for p in into(g, t, "MEMBER_OF")]


def topics_of(g, person):
    """The reverse of contact_for: which topics does this person cover?"""
    teams = out(g, "person:" + key(person), "MEMBER_OF")
    return [g["nodes"][t]["name"] for team in teams for t in into(g, team, "OWNED_BY")]


def impact_of(g, asset):
    """Everything that depends on this asset, at ANY depth (the graph's strength)."""
    found, todo = [], ["asset:" + key(asset)]
    while todo:
        for a in into(g, todo.pop(), "DEPENDS_ON"):
            if a not in found:
                found.append(a)
                todo.append(a)
    return [g["nodes"][a]["name"] for a in found]


# --------------------------------------------------------------------- MAIN
def show_contact(g, topic):
    people = contact_for(g, topic)
    if not people:
        print(f"Who do I contact about {topic}?  I don't know - no team owns '{topic}'.")
        return
    who = "; ".join(f"{p['name']} ({p['team']}) <{p['email']}>, {p['shift']} shift" for p in people)
    print(f"Who do I contact about {topic}?  {who}  [source: graph topics.csv > contacts.csv]")


def show_impact(g, asset):
    found = impact_of(g, asset)
    if not found:
        print(f"What depends on {asset}?  Nothing found.")
    else:
        print(f"What depends on {asset}?  {', '.join(found)}  [source: graph assets.csv]")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-normalize", action="store_true", help="skip normalize(): see the bug")
    ap.add_argument("--twice", action="store_true", help="load twice + ontology check")
    ap.add_argument("--contact", help="who do I contact about this topic?")
    ap.add_argument("--impact", help="what depends on this asset?")
    args = ap.parse_args()

    g = build_graph(verbose=True, normalize=not args.no_normalize)
    print()

    if args.twice:
        before = (len(g["nodes"]), len(g["edges"]))
        build_graph(graph=g)
        after = (len(g["nodes"]), len(g["edges"]))
        print(f"idempotence: first load {before}, second load {after} -> "
              f"{'same counts, safe' if before == after else 'DIFFERENT: not idempotent'}")
        try:
            add_edge(g, "note:phishing", "MEMBER_OF", "team:l1")
        except AssertionError as err:
            print(f"ontology   : refused -> {err}")
        return

    if args.contact:
        show_contact(g, args.contact)
    elif args.impact:
        show_impact(g, args.impact)
    else:
        for topic in ("phishing", "ransomware", "parking"):
            show_contact(g, topic)
        show_impact(g, "db-01")
        print(f"Which topics does Sara cover?  {', '.join(topics_of(g, 'Sara'))}")


if __name__ == "__main__":
    main()