# ar5iv HTML fixtures

Real ar5iv (LaTeXML) renderings, stored gzipped and byte-unmodified as fetched from
`https://ar5iv.labs.arxiv.org/html/<id>`. They exist because every other parser test in this unit
feeds the parser hand-written markup: synthetic input cannot reproduce the depth, subfigure
nesting, or MathML volume that real LaTeX conversion produces, so a regression on real papers
would otherwise only surface in deployment.

Every included paper is **CC BY 4.0**, which permits redistribution with attribution. This is not
incidental — the unit gates ingestion on an open licence, and papers under arXiv's default
`nonexclusive-distrib` licence (which does **not** grant redistribution) must not be vendored here
even though the parser handles them identically.

| arXiv ID | Title | Authors | Licence |
|---|---|---|---|
| [2210.12090](https://arxiv.org/abs/2210.12090) | AutoPrognosis 2.0: Democratizing Diagnostic and Prognostic Modeling in Healthcare with Automated Machine Learning | Imrie, Cebere, McKinney, van der Schaar | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| [2112.01799](https://arxiv.org/abs/2112.01799) | Global Context with Discrete Diffusion in Vector Quantised Modelling for Image Generation | Hu, Wang, Cham, Yang, Suganthan | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| [2305.02531](https://arxiv.org/abs/2305.02531) | Can LLMs Capture Human Preferences? | Goli, Singh | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |

## What each one covers

- **2210.12090** — 5 top-level sections over 19 with nesting, 6 data tables, 5 figures, no display
  maths. The table-heavy path.
- **2112.01799** — 24 sections, 24 display formulas, 18 source figures that collapse to 12 blocks
  (LaTeXML nests subfigures inside a parent `ltx_figure`). The maths + subfigure path.
- **2305.02531** — *not* the paper: ar5iv serves an `HTTP 200` "No content available" page for it,
  the truncated-conversion case `_MIN_HTML_FULLTEXT_CHARS` exists to reject. Kept so that guard is
  tested against the real page rather than a mock of it. Re-fetching may return a real rendering
  if ar5iv later converts the paper — see the note in `test_real_paper_fixtures.py`.

## Refreshing

Fixtures are pinned deliberately: ar5iv re-renders papers as LaTeXML improves, so a re-fetch can
legitimately change the expected digests. Only refresh on purpose:

```bash
curl -sL "https://ar5iv.labs.arxiv.org/html/<id>" | gzip -9 > tests/fixtures/ar5iv/<id>.html.gz
DOCSURI_UPDATE_FIXTURES=1 uv run pytest tests/test_real_paper_fixtures.py
git diff tests/fixtures/ar5iv/   # review what moved before committing
```
