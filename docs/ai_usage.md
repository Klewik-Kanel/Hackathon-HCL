# AI-usage disclosure

The brief allows AI coding assistants and asks us to say how we used them
and how we verified the output. This is that statement.

## What AI assistants were used for

| Part | Assistant used | How we verified it |
| --- | --- | --- |
| Design document, architecture and flowcharts | Claude | Reviewed by all four members against the brief, section by section |
| First draft of the application code (all modules) | Claude | 55 automated tests (`pytest`), the 31-question evaluation, running the app on our own laptop, and each owner reading and explaining their own module (see `docs/CONTRIBUTIONS.md`) |
| Test cases and the evaluation set | Claude, edited by us | Expected answers checked by hand against the clause text in the PDFs |
| Synthetic student data | Generator script written with Claude. It can call the local LLM (`qwen2.5:7b-instruct`); the CSVs currently in `data/students/` came from its offline mode (no LLM calls, see `generation_log.json`) | `scripts/validate_data.py` (0 errors); boundary students S1001-S1011 written by code and checked by hand |
| Document text in `data/docs/*.txt` | Extracted from the official NSUT PDFs with Claude's help, page by page | Spot-checked clause numbers and page numbers against the PDFs (e.g. 11.2 on p.18, 12.3 on p.19) |
| Rule registry values | Drafted with Claude from the PDFs | Each row cites its clause; to be checked against the page by the owner before the demo |
| Student login (passwords, tokens) | Claude, at our request | 10 tests in `tests/test_auth.py`; tried in the UI on our laptop |

## Where human judgement was applied

- Choosing the use case, the documents and the simplest architecture.
- Deciding which decisions are code and which are LLM (precedence, eligibility and citations are code).
- Choosing NSUT's real rule ("no supplementary examinations", clause 12.3) over the brief's assumption.
- Reviewing every rule value against the source PDF.
- Fixing behaviour found by the evaluation (for example, the not-found guard for unrelated questions).
- Running the app ourselves and reporting what broke (an old Docker container still answering on port 8000).
- Asking for student password login, and for plain text labels instead of emoji in the UI.

Each member must be able to explain any line in the modules they own;
we rehearse this before judging.
