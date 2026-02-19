# Feedback Quality Checklist

Quality gates for written evaluations and reviews. Use this to catch misalignment between numeric ratings and written comments before submission.

---

## Minimum Comment Requirements

Each rating comment should have:

- At least **3 sentences** (not 1-2 sentence summaries)
- At least **50 words** total
- At least **one specific citation** (turn number, quote, file reference, or concrete example)

### Too short (will get flagged)

> "Got there eventually but needed pushing. Docker isolation worked."

### Good length

> "Got docker isolation working after about an hour of debugging shm_size and network issues. However, it tried to wrap up early twice -- first at 87 minutes with 30 tests still failing, then again after skipping 6 tests I explicitly said not to skip. The final result came only after significant pushback."

---

## Rating / Comment Alignment

Your written comment must match your numeric rating. This is the most common quality rejection.

| If your comment says... | Then your rating should... |
|-------------------------|---------------------------|
| Option A was better | Favor A (lower end of scale) |
| Option B was better | Favor B (higher end of scale) |
| They were equal | Land at the midpoint with explicit justification |

### Aligned Example

> **Rating:** Leans toward A
> **Comment:** "Option A completed the Docker setup faster and with fewer errors. Option B struggled with the port configuration for about 20 minutes. A had a cleaner solution overall."
>
> Rating favors A, comment favors A. Aligned.

### Misaligned Example (will be rejected)

> **Rating:** Neutral
> **Comment:** "Option A completed the Docker setup faster and with fewer errors. Option B struggled with the port configuration for about 20 minutes."
>
> Comment clearly favors A, but rating says "tie." Misaligned.

---

## Contradiction Detection

### High Rating + Negative Language

| Comment contains... | But rating is high | Issue |
|--------------------|--------------------|-------|
| "struggled" | 4-5 out of 5 | Contradiction |
| "failed" | 4-5 out of 5 | Major contradiction |
| "broken" | 4-5 out of 5 | Contradiction |
| "couldn't" | 4-5 out of 5 | Contradiction |
| "poor" | 4-5 out of 5 | Major contradiction |

### Low Rating + Positive Language

| Comment contains... | But rating is low | Issue |
|--------------------|--------------------|-------|
| "excellent" | 1-2 out of 5 | Major contradiction |
| "perfect" | 1-2 out of 5 | Major contradiction |
| "great" | 1-2 out of 5 | Contradiction |
| "well done" | 1-2 out of 5 | Contradiction |

### Neutral Rating Sanity Check

A middle-of-the-road rating should:
- Describe tradeoffs or "adequate but..."
- Pure praise + neutral rating --> Why not higher?
- Pure criticism + neutral rating --> Why not lower?

---

## Cross-Field Consistency

When you have multiple rating dimensions, they should tell a coherent story:

- Code Quality 5/5 + "fat files, no tests" --> Contradiction
- Thoroughness 5/5 + "skipped E2E tests" --> Needs justification
- Interaction Quality 5/5 + "had to coax it along constantly" --> Contradiction

---

## Common Pitfalls

### The "All Midpoints" Problem

If all ratings land at the midpoint for both options:
- The task might be too easy (both succeeded without challenge)
- Or the feedback isn't distinguishing between options
- Check: Do your comments explain why both deserve the same score?

### Neutral Rating with Clear Winner

If your comments clearly favor one option but the rating says "tie":
- Either adjust the rating to match your comments
- Or balance the comments to show real tradeoffs that justify neutral

### High Ratings + Many Issues

If you logged 3+ behavioral issues but still gave top scores:
- Issues should impact ratings
- Either the issues were truly minor, or the ratings are too generous

---

## Self-Check Before Submitting

For each rating field, verify:

```
Comment favors:  [A / B / Neither]
Rating given:    [value]
Match check:     [aligned / misaligned]
Word count:      [X] (must be 50+)
Sentences:       [X] (must be 3+)
Has citation:    [yes / no]
```
