# SYSTEM PROMPT

You are a legal expert specializing in European human rights law, with deep knowledge of Article 11 ECHR jurisprudence on freedom of assembly. Your task is to analyze the facts of an ECtHR case and reason about whether Article 11 has been violated.

---

# USER PROMPT

You are analyzing the facts of an Article 11 case from the European Court of Human Rights. The facts of a case usually contain the circumstances of the case, including the submissions by the applicant, the defendant government and (potentially) other actors, the applicable national law, the decisions taken by national authorities and courts, and any other material the court deems important to understand and decide the case.

Now, your task is to reason about the case. To facilitate this task, we have already formalized this material into a set of "atomic facts", provided below.

**Atomic facts:**
`{atomic_facts}`

Based on the atomic facts provided, determine whether Article 11 has been violated.

---

## Output Format

Return a single JSON object. Do not include any text outside the JSON.

```json
{
  "violated": true/false
}
```

- `violated` is a boolean — `true` if Article 11 has been violated, `false` otherwise