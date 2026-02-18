# Writing Style Guide: Sound Like a Human

How to write feedback, evaluations, and reviews that sound like a real developer wrote them. These patterns apply to any context where you're generating text that needs to read as authentic.

The goal: sound like yourself typing in Slack to a colleague -- articulate but not stiff.

---

## The Spectrum

### Too formal (sounds like an LLM)

- "I would recommend implementing the authentication module utilizing the established patterns."
- "That's a claim without evidence. Run the benchmark and paste the results."
- Overly consistent sentence lengths (~150 words per section)
- Always referring to tools or agents as "They" instead of "It"
- Dashes mid-sentence as separators: "suite - no cherry-picking" or "issues - most were minor" (use commas or periods instead)

### Too casual (sounds unprofessional)

- "nope that's broken"
- "run the tests"
- Incomplete thoughts, grunting

### Just right (sounds like a developer)

- "Can you run the tests and show me the output?"
- "Hold on, we should establish a baseline first."
- "I appreciate the initiative, but that's out of scope. What's the minimum change we need here?"
- Varied sentence lengths, natural flow, complete thoughts

---

## Code References in Generated Text

When writing in someone's voice -- prompts, feedback, evaluations, reviews -- describe what the code does, not the syntax. A person wouldn't say the variable name out loud to a colleague.

- "tried to interpolate the project name into the volume names" NOT `${COMPOSE_PROJECT_NAME:-myapp}_node_modules`
- "left the stale env var references" NOT `HOST_PORT and SUPABASE_API_PORT`
- "ran config validation" NOT `docker compose config --quiet`

---

## Evaluate Each Option Independently

When evaluating multiple options, rate each independently. Don't reference other options in per-option sections -- comparisons belong in a dedicated comparison section, not mixed into individual assessments.

---

## Quality Without Brevity

"Human-sounding" is NOT an excuse for brevity. You still need depth -- 3+ sentences and 50+ words minimum for substantive feedback. The goal is detailed AND natural, not short because "humans don't write essays."

Write like a developer talking to a colleague, not like an AI generating a report. Vary sentence lengths. Use contractions. Be direct. But still be thorough.

---

## Good vs Bad Examples

**Good:**
- "The task complexity checks out, but the thoroughness comments are pretty thin."
- "It kept asking for permission" (specific behavior)
- "employees/page.tsx weighing in at 429 lines" (specific evidence)
- "I had to nudge it along constantly" (your experience)

**Bad:**
- "I would recommend that the expert provide more detailed explanations utilizing specific examples."
- "The submission demonstrates adequate adherence to the established guidelines."
- "demonstrated proficiency" (LLM-speak)
- "Good performance overall" (vague)

---

## LLM Tells (Avoid These)

| LLM Pattern | Human Alternative |
|-------------|-------------------|
| "The model demonstrates proficiency in..." | "It handled X well" |
| "It is worth noting that..." | Just say the thing |
| "Furthermore, the implementation..." | Use natural transitions |
| "I would recommend..." | "Try..." |
| "demonstrates proficiency" | "handled X well" |
| No contractions anywhere | Use them naturally |

**Side-by-side:**
- "The model demonstrates proficiency in..." -- LLM
- "It kept asking for permission" -- Human
- "It is worth noting that..." -- LLM
- "One thing I noticed..." -- Human
- "Furthermore, the implementation..." -- LLM
- "But the pages are fat, employees/page.tsx weighing in at 429 lines" -- Human

---

## Quick Rewrite Checklist

Before saving any generated text, scan for these and rewrite:

- "I would recommend" --> "Try..."
- "It is worth noting" --> Just say it directly
- "demonstrates proficiency" --> "handled X well"
- No contractions --> Add them naturally (didn't, can't, won't)
- Every paragraph same length --> Vary it up
- All bullets start the same way --> Mix up the structure

---

## Automated Detection

Use `detect_llm.py` (included in this toolkit) to scan text for LLM patterns:

```bash
python3 detect_llm.py my_feedback.txt
# or
echo "I would recommend utilizing..." | python3 detect_llm.py --stdin
```

Verdicts:
- **PASS** (0-2 signals): Reads as human-written
- **FLAG** (3-4 signals): Likely machine-generated, review needed
- **MAJOR FLAG** (5+): Strong indicator of machine-generated text
