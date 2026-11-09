"""Theory-of-Mind probe (research extension): what agents say others know, against grounds and truth.

For each seeded topic and each ordered pair (A, B), A is interviewed on a snapshot clone with
"Does B know about <topic>?" The answer is labeled by the ``awareness`` classifier (does A
claim that B knows) and compared with two things that A's prompt never sees:

* A's **grounds** from the belief ledger: A told B, or A heard B mention it;
* B's **truth**: whether B's own memory holds a supported exposure.

Cells of the resulting table (FANToM-style, Kim et al. 2023, adapted to a running simulation):

| A claims B knows | A has grounds | B knows | label |
| yes | yes | yes | grounded_correct |
| yes | no  | yes | ungrounded_correct (a guess that happens to be right) |
| yes | any | no  | over_attribution (B does not know) |
| no  | yes | yes | under_attribution (A had grounds but denies) |
| no  | no  | yes | unaware_of_other (nothing A experienced showed it) |
| no  | any | no  | correct_negative |

Mock runs exercise the pipeline only; with a real model the labels describe that model's
behavior in this town, not human theory of mind.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from ..cognition.beliefs import BeliefLedger
from .diffusion import classify
from .evidence import Topic
from .interview import InterviewSession

QUESTION = "Does {name} know about {topic}?"


def label(claims: bool | None, grounded: bool, truth: bool) -> str:
    if claims is None:
        return "label_failed"
    if claims and truth and grounded:
        return "grounded_correct"
    if claims and truth:
        return "ungrounded_correct"
    if claims:
        return "over_attribution"
    if truth and grounded:
        return "under_attribution"
    if truth:
        return "unaware_of_other"
    return "correct_negative"


def probe_tom(session: InterviewSession, topic: Topic, agents: list[str], ledger: BeliefLedger) -> list[dict[str, Any]]:
    names = {a: session.identities[a].name for a in agents}
    truth = ledger.truth(topic.key)
    rows = []
    topic_pattern = "|".join(topic.require_all) if topic.require_all else "|".join(re.escape(k) for k in topic.keywords) or re.escape(topic.label)
    for a in agents:
        for b in agents:
            if a == b:
                continue
            q = QUESTION.format(name=names[b], topic=topic.label)
            ans = session.ask(a, q)
            first, last = names[b].split()[0], names[b].split()[-1]
            lab = classify(
                session,
                a,
                q,
                ans.answer,
                f"whether {names[b]} knows about {topic.label}",
                [first, last, *topic.keywords],
                {},
                require_all=[rf"\b({re.escape(first)}|{re.escape(last)}|(he|she|they)\b)", f"({topic_pattern})"],
            )
            g = ledger.beliefs[topic.key][a].grounds.get(b)
            rows.append(
                {
                    "event": topic.key,
                    "agent_id": a,
                    "about": b,
                    "question": q,
                    "answer": ans.answer,
                    "claims_other_knows": lab["claims_knowledge"],
                    "grounds": g.basis if g else None,
                    "grounds_at": g.first_at if g else None,
                    "other_holds": truth[b],
                    "label": label(lab["claims_knowledge"], g is not None, truth[b]),
                    "reference_time": session.now.isoformat(),
                    "call_ids": ans.call_ids,
                }
            )
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    counts = Counter(r["label"] for r in rows)
    truthful = [r for r in rows if r["other_holds"]]
    claimed = [r for r in rows if r["claims_other_knows"]]
    return {
        "pairs": n,
        "labels": dict(sorted(counts.items())),
        # precision of attribution: when A says B knows, how often B does
        "attribution_precision": round(len([r for r in claimed if r["other_holds"]]) / len(claimed), 3) if claimed else None,
        # recall: of the pairs where B knows, how often A says so
        "attribution_recall": round(len([r for r in truthful if r["claims_other_knows"]]) / len(truthful), 3) if truthful else None,
        "grounded_share_of_claims": round(len([r for r in claimed if r["grounds"]]) / len(claimed), 3) if claimed else None,
    }
