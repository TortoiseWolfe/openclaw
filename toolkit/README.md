# Human-Sounding Writing Toolkit

Tools and checklists for writing text that sounds like a real person wrote it -- not an LLM. Works for cover letters, feedback, reviews, or anything where authenticity matters.

## What's Here

| File | What It Does |
|------|-------------|
| `writing-style-guide.md` | The full style guide: tone spectrum, LLM tells, rewrite checklist |
| `detect_llm.py` | Python script: detects LLM-generated text patterns (formal phrases, hedging, missing contractions, generic praise). Returns PASS / FLAG / MAJOR FLAG |
| `prompt-complexity-checklist.md` | Signals and examples for gauging prompt difficulty |
| `feedback-quality-checklist.md` | Contradiction detection, rating alignment, comment quality minimums |
| `utils.py` | Shared utility: `count_words()` excluding punctuation-only tokens |
| `test_detect_llm.py` | Unit tests for `detect_llm.py` |
| `test_utils.py` | Unit tests for `utils.py` |

## Quick Start

**Check if text sounds human:**

```bash
python3 detect_llm.py my_cover_letter.txt
# or
echo "I would recommend utilizing this comprehensive approach" | python3 detect_llm.py --stdin
```

**Before writing:** Read `writing-style-guide.md`

**After writing:** Run `detect_llm.py` on it, then check `feedback-quality-checklist.md`

## Running Tests

```bash
cd toolkit
python3 -m pytest test_detect_llm.py test_utils.py -v
```

Or with unittest:

```bash
python3 -m unittest test_detect_llm test_utils -v
```
