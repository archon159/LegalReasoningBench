# SYSTEM PROMPT

You are a legal expert specializing in European human rights law, with deep knowledge of Article 11 ECHR jurisprudence on freedom of assembly. Your task is to analyze ECtHR judgments to build a structured understanding of how courts reason about Article 11 cases. You will work through a judgment in stages, building on your prior analysis at each step. Your analysis should be thorough, precise, and faithful to what the Court actually said.

---

# USER PROMPT

In the previous steps, we gave you only the reasoning section of the judgment and asked you to identify the Court's conclusions and the factual grounding for each element. We now ask you to relate your analysis to the earlier part of the judgment in which the Court reports the circumstances of the case — the submissions of the parties, the applicable national law, the decisions of national authorities and courts, and any other material the Court considered relevant. We have formalized this material into a set of atomic facts, provided below.

**Atomic facts:**
`{atomic_facts}`

We ask you to write three lists.

**List 1:** For every individual fact that you listed as "factual grounding" (in the legal reasoning part of the decision), find all possible "atomic facts" that the Court was pointing to. Make sure that these atomic facts actually correspond to the exact factual grounding quote.

**List 2:** In the next step, focus on each element of law that you have found is discussed by the Court: which "atomic facts" are strictly necessary to support this part of the reasoning of the court, grounded in the facts mentioned by the Court. Where multiple atomic facts establish the same point, include only the most critical or representative facts.

**List 3:** In the final step, focus on the final conclusion (Art. 11 ECHR has been violated, or not): which "atomic facts" are strictly necessary for the Court to come to this conclusion, assuming that the Court will apply the doctrinal structure of Art. 11 ECHR. Focus on what the case actually turned on.

This procedure implies that any fact in List 3 must feature in List 2, and any fact listed in List 2 must feature in List 1. Put differently, what we want you to do is to narrow down on the atomic facts that are absolutely necessary to back up the legal reasoning of the Court, as grounded in its assessment of the facts (List 2). By contrast, in List 3, we do not want you to replicate the Court's reasoning. Rather in the light of the facts of the case: which atomic facts are essential for reaching the conclusion (Art. 11 violated or not) that the Court reached. 

---

## Output Format

Return a JSON object with two keys. In `analysis`, write the three lists in full as described above. In `results`, extract the structured conclusions.

```json
{
  "analysis": "Your three lists here...",
  "results": {
    "list1": {
      "scope":                ["FXXX", "FXXX"],
      "interference":         ["FXXX"],
      "prescribed_by_law":    ["FXXX"],
      "legitimate_aim":       ["FXXX"],
      "necessity":            ["FXXX"],
      "positive_obligation":  ["FXXX"]
    },
    "list2": {
      "scope":                ["FXXX"],
      "interference":         ["FXXX"],
      "prescribed_by_law":    ["FXXX"],
      "legitimate_aim":       ["FXXX"],
      "necessity":            ["FXXX"],
      "positive_obligation":  ["FXXX"]
    },
    "list3": ["FXXX", "FXXX"]
  }
}
```

- `analysis`: Remember to escape any quotes with \
- `list1` and `list2` are keyed by the six canonical elements; include only fact IDs that appear in the atomic facts provided
- `list3` is a flat list of fact IDs representing the irreducible factual core for the final conclusion
- Any fact ID in `list2` must appear in `list1` for the same element; any fact ID in `list3` must appear in `list2` for at least one element
- An element's list may be empty `[]` if no atomic facts correspond to it