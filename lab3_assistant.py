"""lab3_assistant.py - TP3: the retrieval-generation chain (standard library only).

The chain:  question -> by_meaning + by_keywords -> fuse (RRF) -> rerank -> FLOOR
            -> generate -> "answer [source: id]"   or   "I don't know".

Run from the project root:
    python3 lab3_assistant.py                          # gold questions at FLOOR 0.6 + the try_floors table
    python3 lab3_assistant.py --gold data/gold_extended.jsonl
    python3 lab3_assistant.py --floor 0                # abstention off: watch the trap questions
    python3 lab3_assistant.py --ask "Which AD FS event IDs mean bad credentials?"
    python3 lab3_assistant.py --ask "..." --prompt     # also print the grounded prompt
    python3 lab3_assistant.py --rewrite                # query rewriting (the table is filled in chapter 5)
"""
import argparse
import math
import re
from collections import Counter

from lab2_index import GOLD, build_index, chunks_sentences, cosine, load_gold, load_notes, stem, stem_vector, tokens

FLOOR = 0.6                                   # minimum relevance to answer (FR-04)
ABSTAIN = "I don't know - that isn't in my notes."
RRF_K = 60                                    # reciprocal rank fusion constant
TOP = 3                                       # chunks kept after reranking
#SYNONYMS = {}                                 # query rewriting table: filled in from DIAGNOSED failures (chapter 5)
SYNONYMS = {
    # --- A. vocabulaire : le mot de la question -> le mot de la note (27)
    "email": "message", "received": "recipients", "deceptive": "suspicious",
    "federation": "ad fs", "recording": "auditing", "tier": "priority",
    "breach": "compromise", "misuse": "abuse", "elevated": "privileged",
    "established": "confirmed", "readiness": "preparation", "repository": "bitbucket",
    "alert": "alert rule", "trigger": "matches", "weakness": "cwe", "invalidated": "revoke",
    "cleanup": "remediation", "legitimate": "existing", "examination": "forensic",
    "copies": "copy", "preserved": "preserve", "remains": "remaining",
    "collected": "collector", "artifacts": "evidence", "chain-of-custody": "evidence",
    "identifier": "technique", "result": "resulttype",

    # --- B. mots de cadrage sans sens métier : ignorés (25)
    "check": "", "determine": "", "everyone": "", "set": "", "before": "",
    "associated": "", "using": "", "get": "", "stay": "", "applies": "", "appears": "",
    "follow": "", "advance": "", "stage": "", "accompany": "", "place": "", "later": "",
    "possible": "", "so": "", "end": "", "currently": "", "enabled": "", "listed": "",
    "look": "", "reported": "",

    # --- C. entrées supplémentaires (24), à n'ajouter qu'en dernier
    "detail": "verbose", "response": "handling", "lessons-review": "post-incident",
    "sign-in": "credentials", "audit": "cloudtrail", "cloud": "aws",
    "destructive": "ransomware", "sources": "events", "first": "start",
    "account-to-account": "", "activity": "", "att&ck": "", "category": "", "class": "",
    "code": "", "details": "", "investigate": "", "label": "", "platform": "",
    "responders": "", "sequence": "", "service": "", "sigma": "", "technical": "",
}


# ---------------------------------------------------------------- FUSION
def fuse(*rankings, k=RRF_K):
    """Reciprocal Rank Fusion: score(chunk) = sum over retrievers of 1 / (k + rank).
    It adds RANKS, not scores: cosine is in 0-1, BM25 is unbounded."""
    score = Counter()
    for ranking in rankings:
        for rank, cid in enumerate(ranking, start=1):
            score[cid] += 1 / (k + rank)
    return [cid for cid, _ in score.most_common()]


# ------------------------------------------------------- CITATION CHECKS
def cited_ids(answer):
    return set(re.findall(r"\[(?:source: )?([\w-]+#\d+)\]", answer))


def citations_ok(answer, sent_ids):
    """Every cited id must be one we sent to the model. Unknown id = invented citation."""
    ids = cited_ids(answer)
    return bool(ids) and ids <= set(sent_ids)


def supported(answer, by_id):
    """Faithfulness for an extractive answer: the text IS the cited chunk, word for word."""
    text, _, cid = answer.rpartition(" [source: ")
    chunk = by_id.get(cid.rstrip("]"))
    return chunk is not None and text == chunk["text"]


# -------------------------------------------------------------- ASSISTANT
class Assistant:
    """The chain, built over ANY list of chunks. Chapter 7 builds one per role."""

    def __init__(self, chunks, floor=FLOOR, use_rewrite=False):
        self.chunks = chunks
        self.by_id = {c["id"]: c for c in chunks}
        self.floor = floor
        self.use_rewrite = use_rewrite
        self.index = build_index(chunks, stem_vector)                    # for by_meaning
        self.docs = {c["id"]: stem_vector(c["text"]) for c in chunks}    # for by_keywords
        self.df = Counter(w for doc in self.docs.values() for w in doc)
        self.avg_len = sum(sum(d.values()) for d in self.docs.values()) / max(1, len(chunks))

    # ---- stage 1: two retrievers, two kinds of evidence
    def by_meaning(self, question):
        """Cosine between the question vector and every chunk vector."""
        q = stem_vector(question)
        scored = sorted(((cosine(q, vec), c["id"]) for c, vec in self.index), key=lambda p: (-p[0], p[1]))
        return [cid for score, cid in scored if score > 0]

    def by_keywords(self, question, k1=1.5, b=0.75):
        """BM25: rare words weigh more, repeats saturate, long chunks are normalized."""
        n_docs = len(self.docs)
        scored = []
        for cid, doc in self.docs.items():
            length, score = sum(doc.values()), 0.0
            for word in stem_vector(question):
                if word in doc:
                    idf = math.log(1 + (n_docs - self.df[word] + 0.5) / (self.df[word] + 0.5))
                    tf = doc[word]
                    score += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * length / self.avg_len))
            if score > 0:
                scored.append((score, cid))
        return [cid for score, cid in sorted(scored, key=lambda p: (-p[0], p[1]))]

    # ---- stage 2: judge narrow (question and chunk read together)
    def relevance(self, question, chunk):
        """Share of the question's important words that the chunk (plus its note's topic) covers."""
        q = set(stem_vector(question))
        if not q:
            return 0.0
        covered = set(stem_vector(chunk["context"] + " " + chunk["text"]))
        return len(q & covered) / len(q)

    def rerank(self, question, candidate_ids):
        """Stable sort: on a tie in relevance, the better fused rank stays first."""
        scored = [(self.relevance(question, self.by_id[cid]), cid) for cid in candidate_ids]
        return sorted(scored, key=lambda p: -p[0])[:TOP]

    # ---- stage 3: prompt and generation
    def build_prompt(self, question, reranked):
        sources = "\n".join(f"[{cid}] {self.by_id[cid]['text']}" for _, cid in reranked)
        return (f"Answer ONLY from the sources below. Cite the source id in brackets.\n"
                f"If the sources do not contain the answer, reply exactly: {ABSTAIN}\n"
                f"Sources:\n{sources}\n"
                f"Question: {question}\nAnswer:")

    def generate(self, reranked):
        """Extractive 'generator': quote the best passage. Swap in an LLM call here."""
        _, cid = reranked[0]
        return f"{self.by_id[cid]['text']} [source: {cid}]"

    # ---- the whole chain
    def answer(self, question, explain=False, show_prompt=False):
        q = rewrite(question) if self.use_rewrite else question
        meaning, keywords = self.by_meaning(q), self.by_keywords(q)
        fused = fuse(meaning, keywords)
        reranked = self.rerank(q, fused)
        best = reranked[0][0] if reranked else 0.0
        abstained = not reranked or best < self.floor

        text = ABSTAIN if abstained else self.generate(reranked)
        sent = [cid for _, cid in reranked]
        result = {"text": text, "source": None if abstained else reranked[0][1],
                  "note": None if abstained else self.by_id[reranked[0][1]]["note"],
                  "score": best, "abstained": abstained, "sent": sent,
                  "retrieved": [(round(s, 2), cid) for s, cid in reranked]}
        if explain:
            print(f"Q: {question}")
            if q != question:
                print(f"rewrite    : {q}")
            print(f"by_meaning : {meaning[:5]}")
            print(f"by_keywords: {keywords[:5]}")
            print(f"fuse (RRF) : {fused[:5]}")
            print(f"rerank     : {result['retrieved']}")
            print(f"best relevance {best:.2f} vs FLOOR {self.floor}")
            if show_prompt and reranked:
                print("--- prompt ---\n" + self.build_prompt(q, reranked) + "\n--------------")
            print(f"A: {text}")
        return result


def rewrite(question):
    """Query rewriting with a synonym table (empty until chapter 5 fills it from diagnosed failures)."""
    return " ".join(SYNONYMS.get(w.lower().strip("?"), w) for w in question.split())


# -------------------------------------------- DEFAULT ASSISTANT (all notes)
_cache = {}


def default_assistant(floor=FLOOR, use_rewrite=False):
    key = (floor, use_rewrite)
    if key not in _cache:
        _cache[key] = Assistant(chunks_sentences(load_notes()), floor, use_rewrite)
    return _cache[key]


def answer(question, explain=False, floor=FLOOR, use_rewrite=False, show_prompt=False):
    """The function chapter 4's evaluator calls, exactly as a user would."""
    return default_assistant(floor, use_rewrite).answer(question, explain, show_prompt)


# ---------------------------------------------------------------- REPORTS
def run_gold(assistant, gold):
    rows = []
    for g in gold:
        r = assistant.answer(g["question"])
        expected = g["answer_note"]
        ok = r["abstained"] if expected is None else (not r["abstained"] and r["note"] == expected)
        rows.append({**r, "question": g["question"], "expected": expected, "ok": ok, "kind": g.get("kind", "")})
    return rows


def report(assistant, gold):
    rows = run_gold(assistant, gold)
    print(f"FLOOR {assistant.floor}\n")
    for r in rows:
        mark = "ok" if r["ok"] else "XX"
        print(f"{mark}  {r['score']:.2f}  {r['kind']:<17} {r['question'][:70]}")
        print(f"            -> {r['text'][:90]}")
    answerable = [r for r in rows if r["expected"] is not None]
    refusals = [r for r in rows if r["expected"] is None]
    given = [r for r in answerable if not r["abstained"]]
    print(f"\nanswered correctly (right note): {sum(r['ok'] for r in answerable)}/{len(answerable)}")
    print(f"abstained correctly            : {sum(r['ok'] for r in refusals)}/{len(refusals)}")
    print(f"citations valid / supported    : "
          f"{sum(citations_ok(r['text'], r['sent']) for r in given)}/{len(given)} / "
          f"{sum(supported(r['text'], assistant.by_id) for r in given)}/{len(given)}"
          f"   (abstentions have no citation to check)")


def try_floors(gold, use_rewrite=False):
    """Sweep the FLOOR and find the band that works, from measurements (not taste)."""
    print(f"{'FLOOR':>6} {'right note':>12} {'trap refused':>14}")
    answerable = [g for g in gold if g["answer_note"] is not None]
    refusals = [g for g in gold if g["answer_note"] is None]
    for floor in (0.0, 0.3, 0.5, 0.6, 0.7, 0.8, 1.0):
        rows = run_gold(default_assistant(floor, use_rewrite), gold)
        right = sum(r["ok"] for r in rows if r["expected"] is not None)
        refused = sum(r["ok"] for r in rows if r["expected"] is None)
        print(f"{floor:>6} {right:>8}/{len(answerable)} {refused:>10}/{len(refusals)}")

    rows = run_gold(default_assistant(0.0, use_rewrite), gold)             # scores without any abstention
    good = [r["score"] for r in rows if r["expected"] is not None and r["note"] == r["expected"]]
    traps = [r["score"] for r in rows if r["expected"] is None]
    if good and traps:
        low, high = min(good), max(traps)
        print(f"\nlowest relevance of a question answered from the right note : {low:.2f}")
        print(f"highest relevance of a question that must be refused        : {high:.2f}")
        if high < low:
            print(f"-> working band: {high:.2f} < FLOOR <= {low:.2f}   (margin {low - high:.2f})")
        else:
            print("-> NO FLOOR separates them: a refusal scores at least as high as a good answer.")
            print("   Moving the FLOOR only moves questions between the columns (chapter 5).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default=str(GOLD))
    ap.add_argument("--floor", type=float, default=FLOOR)
    ap.add_argument("--ask")
    ap.add_argument("--prompt", action="store_true", help="print the grounded prompt too")
    ap.add_argument("--rewrite", action="store_true", help="apply the synonym table before retrieval")
    args = ap.parse_args()

    if args.ask:
        answer(args.ask, explain=True, floor=args.floor, use_rewrite=args.rewrite, show_prompt=args.prompt)
        return
    gold = load_gold(args.gold)
    report(default_assistant(args.floor, args.rewrite), gold)
    print()
    try_floors(gold, args.rewrite)


if __name__ == "__main__":
    main()