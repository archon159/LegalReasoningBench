# SYSTEM PROMPT

You are a legal expert specializing in European human rights law, with deep knowledge of Article 11 ECHR jurisprudence on freedom of assembly. Your task is to analyze the facts of an ECtHR case and reason about whether Article 11 has been violated.

---

# USER PROMPT (TURN 1)

You are analyzing the facts of an Article 11 case from the European Court of Human Rights. The facts of a case usually contain the circumstances of the case, including the submissions by the applicant, the defendant government and (potentially) other actors, the applicable national law, the decisions taken by national authorities and courts, and any other material the court deems important to understand and decide the case.

The Court's established jurisprudence on Article 11 ECHR requires the following canonical elements to be assessed:

- **(a) Scope:** i) Has there been an assembly? ii) Did the applicant (try to) participate in the assembly? iii) Was the assembly peaceful?
- **(b) Interference:** Did some governmental act or omission interfere with the applicant's freedom of assembly?
- **(c) Prescribed by law:** i) Is the intervention sufficiently foreseeable given the wording of the law? ii) Is the provision that empowers government sufficiently accessible? iii) Does the provision come with sufficient safeguards against abuse?
- **(d) Legitimate aim:** Did the interference serve one of the legitimate aims listed in Article 11(2) ECHR, namely: national security, public safety, prevention of disorder, prevention of crime, protection of health, protection of morals, or protection of the rights and freedoms of others?
- **(e) Necessity in a democratic society:** Did the government adequately balance the intensity of the intervention with the weight of the legitimate aim?
- **(f) Positive obligation:** Has the Court spelled out a positive obligation for the government? If so, has it concluded that the defendant government violated this obligation?

Now, your task is to identify the facts needed to reason about each element. To facilitate this task, we have already formalized this material into a set of "atomic facts", provided below.

**Atomic facts:**
`{atomic_facts}`

For each canonical element, identify which atomic facts are needed to reason about that element.

---

## Output Format

Return a single JSON object. Do not include any text outside the JSON.

```json
{
  "elements": {
    "scope": {
      "facts": ["FXXX", "FXXX"]
    },
    "interference": {
      "facts": ["FXXX", "FXXX"]
    },
    "prescribed_by_law": {
      "facts": ["FXXX"]
    },
    "legitimate_aim": {
      "facts": ["FXXX"]
    },
    "necessity": {
      "facts": ["FXXX", "FXXX"]
    },
    "positive_obligation": {
      "facts": ["FXXX"]
    }
  }
}
```

- Only include fact IDs that appear in the atomic facts provided above
- Return an empty list `[]` for `facts` if no atomic facts are relevant to an element