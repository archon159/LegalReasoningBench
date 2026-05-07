# SYSTEM PROMPT

You are a legal expert specializing in European human rights law, with deep knowledge of Article 11 ECHR jurisprudence on freedom of assembly. Your task is to analyze ECtHR judgments to build a structured understanding of how courts reason about Article 11 cases. You will work through a judgment in stages, building on your prior analysis at each step. Your analysis should be thorough, precise, and faithful to what the Court actually said.

---

# USER PROMPT

Read the following reasoning section from a decision by the European Court of Human Rights, and then analyze the questions below.

**Reasoning text:**
`{reasoning_text}`

**1.** Does the Court come to the conclusion that Article 11 ECHR has been violated? If yes, from which paragraph(s) do you take this information? Quote the paragraph number and the wording.

**2.** Please also give us the decisions of the Court regarding the elements of the canonical doctrine of Article 11 ECHR. In the Court's established jurisprudence, Article 11 ECHR requires the following tests:

- **(a) Scope:** i) has there been an assembly? ii) did the applicant (try to) participate in the assembly? iii) was the assembly peaceful?
- **(b) Interference:** did some governmental act or omission interfere with the applicant's freedom of assembly?
- **(c) Prescribed by law:** i) is the intervention sufficiently foreseeable, given the wording of the law? ii) is the provision that empowers government sufficiently accessible? iii) does the provision come with sufficient safeguards against abuse?
- **(d) Legitimate aim:** did it serve one of the legitimate aims listed in Article 11 ECHR, namely: national security, public safety, the prevention of disorder, prevention of crime, the protection of health, the protection of morals, protection of the rights and freedoms of others?
- **(e) Necessity in a democratic society:** did government adequately balance the intensity of the intervention with the weight of the legitimate aim?
- **(f) Positive obligation:** has the Court spelled out a positive obligation for government? If so, has it come to the conclusion that the defendant government has violated this obligation?

Which of these canonical elements of the doctrine of Article 11 ECHR are explicitly discussed in the decision? Are elements of doctrine implied (e.g. by the fact that the Court explicitly discusses an element that logically requires an earlier element to be given)? Again, quote the paragraph number and the wording for each canonical element that the Court has explicitly discussed.

---

## Output

Return a JSON object with two keys. In `analysis`, answer the questions above as fully as you would in a standalone response — for the final violation conclusion as well as each element and sub-element, quote the specific passages that ground each finding, treating each sub-element as a separate question requiring its own answer. In `results`, extract the structured conclusions as shown below.

```json
{
  "analysis": "Your full analysis here...",
  "results": {
    "violated": "true/false/null",
    "elements": {
      "scope":                         {"conclusion": "yes/no/null", "discussed": "explicit/implied/not_discussed"},
      "scope_assembly_exists":         {"conclusion": "yes/no/null", "discussed": "explicit/implied/not_discussed"},
      "scope_participation":           {"conclusion": "yes/no/null", "discussed": "explicit/implied/not_discussed"},
      "scope_peaceful":                {"conclusion": "yes/no/null", "discussed": "explicit/implied/not_discussed"},
      "interference":                  {"conclusion": "yes/no/null", "discussed": "explicit/implied/not_discussed"},
      "prescribed_by_law":             {"conclusion": "yes/no/null", "discussed": "explicit/implied/not_discussed"},
      "prescribed_by_law_foreseeable": {"conclusion": "yes/no/null", "discussed": "explicit/implied/not_discussed"},
      "prescribed_by_law_accessible":  {"conclusion": "yes/no/null", "discussed": "explicit/implied/not_discussed"},
      "prescribed_by_law_safeguards":  {"conclusion": "yes/no/null", "discussed": "explicit/implied/not_discussed"},
      "legitimate_aim":                {"conclusion": "yes/no/null", "discussed": "explicit/implied/not_discussed", "aims_found": []},
      "necessity":                     {"conclusion": "yes/no/null", "discussed": "explicit/implied/not_discussed"},
      "positive_obligation":           {"conclusion": "yes/no/null", "discussed": "explicit/implied/not_discussed"}
    }
  }
}
```
- `analysis`: Remember to escape any quotes with \
- `violated`: `"true"` if Article 11 has been violated, `"false"` if not, `"null"` if unclear
- `conclusion`: `"yes"` if the Court answers the element's question affirmatively, `"no"` if negatively, `"null"` if not discussed or unresolved
- `discussed`: `"explicit"` if directly addressed, `"implied"` if follows from other elements, `"not_discussed"` if absent entirely
- `aims_found`: list of applicable aims from: `"national_security"`, `"public_safety"`, `"prevention_of_disorder"`, `"prevention_of_crime"`, `"protection_of_health"`, `"protection_of_morals"`, `"rights_of_others"` — empty list `[]` if legitimate aim not discussed