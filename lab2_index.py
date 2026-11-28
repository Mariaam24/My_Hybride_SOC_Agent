"""lab2_index.py - TP2: chunking, vectors and a searchable index (standard library only).

Run from the project root:
    python3 lab2_index.py                         # the grid: vectors x chunking (7 gold questions)
    python3 lab2_index.py --gold data/gold_extended.jsonl
    python3 lab2_index.py --prefix                # lever 3: put the note's topic in front of every chunk
    python3 lab2_index.py --ask "What is the first step in a phishing investigation?"
    python3 lab2_index.py --scores                # best score of every question (the trap too)
    python3 lab2_index.py --roles                 # how many chunks each role may search
    python3 lab2_index.py --roles --ask "How do I recover from ransomware?"
"""
import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path

from lab1_ingest import NOTES, read_note

GOLD = Path("data/gold.jsonl")
STOPWORDS = set("""a an the of to in on at for and or is are was were be by with as it its this
that what when how who where which why do does i my me we you can from if into than then there
their they them have has had will should""".split())

# Who may see which note level (chapter 7 will build on this).
VISIBLE = {
    "auditor":   {"public"},
    "analyst":   {"public", "internal"},
    "responder": {"public", "internal", "restricted"},
}


# ---------------------------------------------------------------- VECTORS
def tokens(text):
    """Lowercase words and numbers, without the small words that carry no meaning."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [w for w in words if len(w) > 1 and w not in STOPWORDS]


def tf_vector(text):
    """Sparse vector: {word: how many times it appears}. One dimension per word."""
    return Counter(tokens(text))


def stem(word):
    """The crudest stemmer: drop a final 's' (opens -> open, logs -> log)."""
    return word[:-1] if len(word) > 2 and word.endswith("s") and not word.endswith("ss") else word


def stem_vector(text):
    """tf_vector after stemming, so 'events' and 'event' count as the same word."""
    return Counter(stem(w) for w in tokens(text))


def cosine(a, b):
    """cos(a, b) = (a . b) / (|a| x |b|). Ignores the length of the texts."""
    dot = sum(count * b[word] for word, count in a.items() if word in b)
    norm = math.sqrt(sum(c * c for c in a.values())) * math.sqrt(sum(c * c for c in b.values()))
    return dot / norm if norm else 0.0


# --------------------------------------------------------------- CHUNKING
def load_notes():
    return [read_note(p) for p in sorted(NOTES.glob("*.md"))]


def make_chunk(note, chunk_id, text):
    """Every chunk keeps its id, its parent note and its access level (for citing, filtering, purging)."""
    return {"id": chunk_id, "note": note["id"], "role": note["role"],
            "updated": note["updated"], "context": note["topic"], "text": text}


def chunks_whole(notes):
    """One chunk per note. Complete context, but the vector is diluted."""
    return [make_chunk(n, n["id"], " ".join(n["sentences"])) for n in notes]


def chunks_sentences(notes):
    """One chunk per sentence: ids like 'phishing#2'. Focused vectors, precise citations."""
    return [make_chunk(n, f"{n['id']}#{i}", s) for n in notes for i, s in enumerate(n["sentences"])]


def chunks_window(notes, size=2):
    """Sliding window of `size` consecutive sentences, one step at a time (id = first sentence)."""
    chunks = []
    for n in notes:
        last = max(1, len(n["sentences"]) - size + 1)
        for i in range(last):
            chunks.append(make_chunk(n, f"{n['id']}#{i}", " ".join(n["sentences"][i:i + size])))
    return chunks


CHUNKERS = {"whole": chunks_whole, "sentence": chunks_sentences, "window": chunks_window}


# ------------------------------------------------------------------ INDEX
def build_index(chunks, vectorize, prefix=False):
    """The index = every chunk next to its vector. Built once.

    prefix=True puts the note's topic in front of the text that is vectorized
    (the chunk keeps its own text for display): a sentence such as 'Start by confirming
    the suspicious message' then also carries the word 'phishing'."""
    return [(chunk, vectorize((chunk["context"] + " " if prefix else "") + chunk["text"]))
            for chunk in chunks]


def visible_to(role, index):
    """Keep only the chunks this role may see. Applied BEFORE scoring, never after."""
    allowed = VISIBLE[role]
    return [(chunk, vec) for chunk, vec in index if chunk["role"] in allowed]


def search(index, question, vectorize, k=3, role=None):
    """Top-k chunks. The question MUST use the same vectorize() as the chunks."""
    if role:
        index = visible_to(role, index)
    q = vectorize(question)
    scored = [(cosine(q, vec), chunk) for chunk, vec in index]
    scored.sort(key=lambda pair: (-pair[0], pair[1]["id"]))
    return scored[:k]


# ------------------------------------------------------------- EVALUATION
def load_gold(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def evaluate(index, gold, vectorize, k=3):
    """Recall@1, Recall@3 (right NOTE among the top chunks) and words of context."""
    answerable = [row for row in gold if row["answer_note"] is not None]
    hit1 = hit3 = words = 0
    missed = []
    for row in answerable:
        top = search(index, row["question"], vectorize, k)
        notes = [chunk["note"] for _, chunk in top]
        hit1 += notes[:1] == [row["answer_note"]]
        hit3 += row["answer_note"] in notes
        words += sum(len(chunk["text"].split()) for _, chunk in top)
        if notes[:1] != [row["answer_note"]]:
            missed.append((row["question"], row["answer_note"], notes[0] if notes else None))
    n = len(answerable)
    return {"n": n, "hit1": hit1, "hit3": hit3, "words": words / n if n else 0, "missed": missed}


def grid(gold, prefix=False):
    notes = load_notes()
    print(f"{len([r for r in gold if r['answer_note']])} answerable questions "
          f"(the trap questions are not counted here) | topic prefix: {'ON' if prefix else 'off'}\n")
    print(f"{'vectors':<9}{'chunking':<14}{'chunks':>6}{'R@1':>12}{'R@3':>12}{'words':>8}")
    details = []
    for vname, vec in (("tf", tf_vector), ("tf+stem", stem_vector)):
        for cname, chunker in (("whole note", chunks_whole), ("sentence", chunks_sentences),
                               ("window of 2", chunks_window)):
            index = build_index(chunker(notes), vec, prefix)
            r = evaluate(index, gold, vec)
            print(f"{vname:<9}{cname:<14}{len(index):>6}"
                  f"{r['hit1']:>6}/{r['n']} {r['hit1'] / r['n']:.2f}"
                  f"{r['hit3']:>4}/{r['n']} {r['hit3'] / r['n']:.2f}{r['words']:>8.0f}")
            details += [(vname, cname, m) for m in r["missed"]]
    print("\nMissed at k=1 (right note not first):")
    for vname, cname, (question, expected, got) in details:
        print(f"  [{vname} | {cname}] {question}  expected={expected}  got={got}")
    if not details:
        print("  none")


def show_scores(gold, prefix=False):
    """Best cosine of every question, the trap questions included (E4: is there a threshold?)."""
    index = build_index(chunks_sentences(load_notes()), stem_vector, prefix)
    rows = []
    for row in gold:
        score, chunk = search(index, row["question"], stem_vector, 1)[0]
        ok = "-" if row["answer_note"] is None else ("ok" if chunk["note"] == row["answer_note"] else "WRONG")
        rows.append((score, chunk["id"], row["answer_note"], ok, row.get("kind", ""), row["question"]))
    rows.sort(key=lambda r: (-r[0], r[1]))
    print(f"{'score':>6}  {'best chunk':<24}{'expected':<20}{'top1':<6}{'kind':<18}question")
    for score, cid, expected, ok, kind, q in rows:
        print(f"{score:>6.2f}  {cid:<24}{str(expected):<20}{ok:<6}{kind:<18}{q}")
    answer = [r for r in rows if r[2] is not None]
    refuse = [r for r in rows if r[2] is None]
    if answer and refuse:
        low = min(answer, key=lambda r: r[0])
        high = max(refuse, key=lambda r: r[0])
        print(f"\nlowest answerable best-score : {low[0]:.2f}  ({low[5]})")
        print(f"highest refusal best-score   : {high[0]:.2f}  ({high[5]})")
        print("-> a cosine threshold " + ("CAN" if low[0] > high[0] else "CANNOT")
              + " separate them. A retriever never says 'I don't know' by itself.")


def show_roles(question=None, prefix=False):
    """E3 preview of access control: filter BEFORE scoring, then compare the roles."""
    index = build_index(chunks_sentences(load_notes()), stem_vector, prefix)
    print(f"{'role':<11}{'sees':<34}{'chunks searched':>16}")
    for role, levels in VISIBLE.items():
        print(f"{role:<11}{', '.join(sorted(levels)):<34}{len(visible_to(role, index)):>16}")
    if question:
        print(f"\nQuestion: {question}")
        for role in VISIBLE:
            top = search(index, question, stem_vector, 1, role=role)
            score, chunk = top[0] if top else (0.0, {"id": "-", "text": ""})
            print(f"  {role:<10} {score:.2f}  [{chunk['id']}] {chunk['text']}")


def ask(question, vectorize, chunker, role=None, prefix=False):
    index = build_index(chunker(load_notes()), vectorize, prefix)
    print(f"{len(index)} chunks in the index" + (f", filtered for role '{role}'" if role else ""))
    for score, chunk in search(index, question, vectorize, 3, role):
        print(f"{score:.2f}  [{chunk['id']}] ({chunk['role']}) {chunk['text']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default=str(GOLD))
    ap.add_argument("--ask")
    ap.add_argument("--role", choices=sorted(VISIBLE))
    ap.add_argument("--chunking", choices=sorted(CHUNKERS), default="sentence")
    ap.add_argument("--tf", action="store_true", help="plain tf vectors, no stemming")
    ap.add_argument("--scores", action="store_true")
    ap.add_argument("--roles", action="store_true")
    ap.add_argument("--prefix", action="store_true", help="put the note's topic in front of every chunk")
    args = ap.parse_args()

    if args.roles:
        show_roles(args.ask, args.prefix)
    elif args.scores:
        show_scores(load_gold(args.gold), args.prefix)
    elif args.ask:
        ask(args.ask, tf_vector if args.tf else stem_vector, CHUNKERS[args.chunking], args.role, args.prefix)
    else:
        grid(load_gold(args.gold), args.prefix)


if __name__ == "__main__":
    main()