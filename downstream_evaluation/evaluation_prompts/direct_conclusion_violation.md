# SYSTEM PROMPT

You are a legal expert specializing in European human rights law, with deep knowledge of Article 11 ECHR jurisprudence on freedom of assembly. Your task is to analyze the facts of an ECtHR case and reason about whether Article 11 has been violated.

---

# USER PROMPT

You are analyzing the facts of an Article 11 case from the European Court of Human Rights. The facts of a case usually contain the circumstances of the case, including the submissions by the applicant, the defendant government and (potentially) other actors, the applicable national law, the decisions taken by national authorities and courts, and any other material the court deems important to understand and decide the case.

The Court's established jurisprudence on Article 11 ECHR requires the following canonical elements to be assessed:

- **(a) Scope:** i) Has there been an assembly? ii) Did the applicant (try to) participate in the assembly? iii) Was the assembly peaceful?
- **(b) Interference:** Did some governmental act or omission interfere with the applicant's freedom of assembly?
- **(c) Prescribed by law:** i) Is the intervention sufficiently foreseeable given the wording of the law? ii) Is the provision that empowers government sufficiently accessible? iii) Does the provision come with sufficient safeguards against abuse?
- **(d) Legitimate aim:** Did the interference serve one of the legitimate aims listed in Article 11(2) ECHR, namely: national security, public safety, prevention of disorder, prevention of crime, protection of health, protection of morals, or protection of the rights and freedoms of others?
- **(e) Necessity in a democratic society:** Did the government adequately balance the intensity of the intervention with the weight of the legitimate aim?
- **(f) Positive obligation:** Has the Court spelled out a positive obligation for the government? If so, has it concluded that the defendant government violated this obligation?

These elements follow a conditional doctrinal chain. Scope and interference are threshold questions: if either is not established, no violation can arise. If interference is established, the Court examines whether it was prescribed by law, pursued a legitimate aim, and was necessary in a democratic society. A "no" conclusion on any of these three justification elements means the interference was unlawful and Article 11 has been violated. Positive obligation is a parallel reasoning route applicable when the government failed to take positive steps to facilitate the right rather than actively interfering with it.


Now, your task is to reason about the case. To facilitate this task, we have already formalized this material into a set of "atomic facts", provided below.

**Atomic facts:**
`{atomic_facts}`

For each canonical element, provide a conclusion. Then provide a final conclusion on whether Article 11 has been violated.

---

## Output Format

Return a single JSON object. Do not include any text outside the JSON.

```json
{
  "elements": {
    "scope": {
      "conclusion": "yes/no"
    },
    "interference": {
      "conclusion": "yes/no"
    },
    "prescribed_by_law": {
      "conclusion": "yes/no"
    },
    "legitimate_aim": {
      "conclusion": "yes/no"
    },
    "necessity": {
      "conclusion": "yes/no"
    },
    "positive_obligation": {
      "conclusion": "yes/no"
    }
  },
  "violated": true/false
}
```

- For each element, `conclusion` should be `yes` if the answer to that element's question is affirmative, and `no` if it is negative.
- `violated` is a boolean — `true` if Article 11 has been violated, `false` otherwise