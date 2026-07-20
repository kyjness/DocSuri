# Real-paper fixtures

Real inputs for the three parse paths, stored byte-unmodified as fetched (HTML and TEI gzipped).
They exist because every other parser test in this unit feeds hand-written markup: synthetic input
cannot reproduce the nesting depth, subfigure grouping, MathML volume, or GROBID's noisier section
segmentation that real documents produce, so a regression on real papers would otherwise only
surface in deployment — which is retired.

Consumed by `tests/test_real_paper_fixtures.py`.

## Licence

Every included paper is **CC BY 4.0**, which permits redistribution with attribution. This is not
incidental — the unit gates ingestion on an open licence, and papers under arXiv's default
`nonexclusive-distrib` licence (which does **not** grant redistribution) must not be vendored here
even though the parsers handle them identically. The well-known transformer/ResNet/BERT papers were
all checked and all carry that default licence; none of them can live in this directory.

| arXiv ID | Title | Authors | Licence |
|---|---|---|---|
| [2210.12090](https://arxiv.org/abs/2210.12090) | AutoPrognosis 2.0: Democratizing Diagnostic and Prognostic Modeling in Healthcare with Automated Machine Learning | Imrie, Cebere, McKinney, van der Schaar | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| [2112.01799](https://arxiv.org/abs/2112.01799) | Global Context with Discrete Diffusion in Vector Quantised Modelling for Image Generation | Hu, Wang, Cham, Yang, Suganthan | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| [2305.02531](https://arxiv.org/abs/2305.02531) | Can LLMs Capture Human Preferences? | Goli, Singh | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |

## Layout

### `ar5iv/` — LaTeXML HTML, the arXiv doc-model source

- **2210.12090** (35 KB gz) — 19 sections with nesting, 6 data tables, 5 figures, no display
  maths. The table-heavy path.
- **2112.01799** (86 KB gz) — 24 sections, 24 display formulas, 18 source figures that collapse to
  12 blocks (LaTeXML nests subfigures inside a parent `ltx_figure`). The maths + subfigure path.
- **2305.02531** (2 KB gz) — *not* the paper: ar5iv serves an `HTTP 200` "No content available"
  page for it, the truncated-conversion case `_MIN_HTML_FULLTEXT_CHARS` exists to reject. Kept so
  that guard is tested against the real page rather than a mock of it. Re-fetching may return a
  real rendering if ar5iv later converts the paper — the test says so when it fails.

### `grobid/` — TEI, the only doc-model path for non-arXiv sources

- **2210.12090** (23 KB gz) — produced by GROBID 0.8.0 from `pdf/2210.12090.pdf`. Parses to 23
  sections / 54 blocks with 6 figures, 5 tables and 11 crop specs. GROBID segments far more
  aggressively than LaTeXML (each numbered "Challenge N." subheading becomes its own div, and the
  leading div has an empty head), which is exactly the real-world shape worth pinning.

Requested with the same parameters `GrobidHttpClient` uses in production — `teiCoordinates` for
`figure` and `formula` only, no consolidation — so the fixture matches what the adapter really
receives:

```bash
docker run -d --name grobid -p 8070:8070 lfoppiano/grobid:0.8.0
curl -F "input=@tests/fixtures/pdf/2210.12090.pdf" \
     -F "teiCoordinates=figure" -F "teiCoordinates=formula" \
     http://localhost:8070/api/processFulltextDocument | gzip -9 \
     > tests/fixtures/grobid/2210.12090.tei.xml.gz
```

### `pdf/` — the source PDF

- **2210.12090** (930 KB) — the only uncompressed fixture, and the only paper carried in all three
  forms. It backs PDF text extraction and the bbox page-crop render, which cannot be exercised
  without real page geometry. Kept to one paper deliberately: `2112.01799`'s PDF is 42 MB, far too
  heavy to vendor for the marginal coverage it would add.

## Refreshing

Fixtures are pinned deliberately: ar5iv re-renders papers as LaTeXML improves and GROBID's
segmentation shifts between releases, so a re-fetch can legitimately change the expected digests.
Only refresh on purpose:

```bash
curl -sL "https://ar5iv.labs.arxiv.org/html/<id>" | gzip -9 > tests/fixtures/ar5iv/<id>.html.gz
DOCSURI_UPDATE_FIXTURES=1 uv run pytest tests/test_real_paper_fixtures.py
git diff tests/fixtures/   # review what moved before committing
```

The digests record structure and content hashes, not the full DocModel, so the diff stays readable.
Each path also carries assertions that do **not** consult the digest (text volume, nesting, block
kinds, reading order, crop bbox sanity) — a regression cannot pass merely by being re-recorded.
