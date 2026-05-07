# SYSTEM PROMPT

You are a legal expert specializing in European human rights law, with deep knowledge of Article 11 ECHR jurisprudence on freedom of assembly. Your task is to analyze the facts of an ECtHR case and reason about whether Article 11 has been violated.

---

# USER PROMPT

You are analyzing the facts of an Article 11 case from the European Court of Human Rights. The facts of a case usually contain the circumstances of the case, including the submissions by the applicant, the defendant government and (potentially) other actors, the applicable national law, the decisions taken by national authorities and courts, and any other material the court deems important to understand and decide the case.

The Court's established jurisprudence on Article 11 ECHR requires the following canonical elements to be assessed:

- **(a) Scope**
- **(b) Interference**
- **(c) Prescribed by law**
- **(d) Legitimate aim**
- **(e) Necessity in a democratic society**
- **(f) Positive obligation**

Now, your task is to identify the facts needed to reason about the case. To facilitate this task, we have already formalized this material into a set of "atomic facts", provided below.

**Atomic facts:**
`{atomic_facts}`

For each canonical element, identify which atomic facts are needed to answer its question, and provide a conclusion. Then provide a final conclusion on whether Article 11 has been violated.

---

## Output Format

Return a single JSON object. Do not include any text outside the JSON.

```json
{
  "elements": {
    "scope": {
      "conclusion": "yes/no",
      "facts": ["FXXX", "FXXX"]
    },
    "interference": {
      "conclusion": "yes/no",
      "facts": ["FXXX", "FXXX"]
    },
    "prescribed_by_law": {
      "conclusion": "yes/no",
      "facts": ["FXXX"]
    },
    "legitimate_aim": {
      "conclusion": "yes/no",
      "facts": ["FXXX"]
    },
    "necessity": {
      "conclusion": "yes/no",
      "facts": ["FXXX", "FXXX"]
    },
    "positive_obligation": {
      "conclusion": "yes/no",
      "facts": ["FXXX"]
    }
  },
  "violated": true/false
}
```

- For each element, `conclusion` should be `yes` if the element is satisfied or established, and `no` otherwise.
- `violated` is a boolean — `true` if Article 11 has been violated, `false` otherwise
- Only include fact IDs that appear in the atomic facts provided above
- Return an empty list `[]` for `facts` if no atomic facts are relevant to an element