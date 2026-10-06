# AI-usage disclosure

The brief allows AI coding assistants and asks us to say how we used them
and how we verified the output. This is that statement.

## What AI assistants were used for

| Part | Assistant used | How we verified it |
| --- | --- | --- |
| Design document, architecture and flowcharts | Claude | Reviewed by all four members against the brief, section by section |
| First draft of the application code (all modules) | Claude | 45 automated tests (`pytest`), the 31-question evaluation, and each owner reading and explaining their own module line by line (see `docs/CONTRIBUTIONS.md`) |
| Test cases and the evaluation set | Claude, edited by us | Expected answers checked by hand against the clause text in the PDFs |
| Synthetic student data | Local LLM (`qwen2.5:7b-instruct`) via our generator | `scripts/validate_data.py`; errors the model made are logged and fixed by code |
| Rule registry values | Typed by us from the PDFs | Each row cites its clause; checked against the page before the demo |

## Where human judgement was applied

- Choosing the use case, the documents and the simplest architecture.
- Deciding which decisions are code and which are LLM (precedence, eligibility and citations are code).
- Choosing NSUT's real rule ("no supplementary examinations", clause 12.3) over the brief's assumption.
- Reviewing every rule value against the source PDF.
- Fixing behaviour found by the evaluation (for example, the not-found guard for unrelated questions).

Each member must be able to explain any line in the modules they own;
we rehearsed this before judging.
