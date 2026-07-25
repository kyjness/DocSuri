// Headless corpus MathJax render sweep (u5 render-verification, Part 1).
//
// The doc-model mirror carries ~1.23M display formulas across 9 parser generations. This runs each
// one through the SAME MathJax config the browser uses — importing `lib/mathEngine.ts` (Node 24
// type-stripping) so the packages / macros / preprocess rules are the SSOT, never a drifting copy —
// and reports which LaTeX constructs COLLAPSE a formula (the `\vspace`-class failures that render as
// the fallback "수식" chip). A fix then lands in mathEngine and both paths get it.
//
// It verifies RENDERER RESILIENCE (parser-version-independent), not parser@10 output fidelity.
//
// Usage (from frontend/):
//   node scripts/audit-math-render.mjs --sample 2000        # fast taxonomy over a random sample
//   node scripts/audit-math-render.mjs                       # full corpus (slow; dedup keeps it sane)
//   node scripts/audit-math-render.mjs --limit 500 --out /tmp/report.json
//
// Failures are split into SYSTEMIC (offending command defined by NO paper's author macros → a real
// gap to fix in mathEngine) vs AUTHOR-RESOLVABLE (the command is some paper's `\newcommand`, so the
// runtime render — which merges that paper's meta.macros — would resolve it; noise for our purposes).

import { readFileSync, readdirSync, writeFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { homedir } from 'node:os';

import { mathjax } from 'mathjax-full/js/mathjax.js';
import { TeX } from 'mathjax-full/js/input/tex.js';
import { SVG } from 'mathjax-full/js/output/svg.js';
import { liteAdaptor } from 'mathjax-full/js/adaptors/liteAdaptor.js';
import { RegisterHTMLHandler } from 'mathjax-full/js/handlers/html.js';
// Package Configuration side-effect imports — MUST mirror PACKAGES in mathEngine (the bundler needs
// these static in the browser path; Node needs them here). `physics` is not in AllPackages, so every
// one is registered explicitly.
import 'mathjax-full/js/input/tex/base/BaseConfiguration.js';
import 'mathjax-full/js/input/tex/ams/AmsConfiguration.js';
import 'mathjax-full/js/input/tex/amscd/AmsCdConfiguration.js';
import 'mathjax-full/js/input/tex/boldsymbol/BoldsymbolConfiguration.js';
import 'mathjax-full/js/input/tex/braket/BraketConfiguration.js';
import 'mathjax-full/js/input/tex/cancel/CancelConfiguration.js';
import 'mathjax-full/js/input/tex/cases/CasesConfiguration.js';
import 'mathjax-full/js/input/tex/centernot/CenternotConfiguration.js';
import 'mathjax-full/js/input/tex/color/ColorConfiguration.js';
import 'mathjax-full/js/input/tex/configmacros/ConfigMacrosConfiguration.js';
import 'mathjax-full/js/input/tex/enclose/EncloseConfiguration.js';
import 'mathjax-full/js/input/tex/extpfeil/ExtpfeilConfiguration.js';
import 'mathjax-full/js/input/tex/gensymb/GensymbConfiguration.js';
import 'mathjax-full/js/input/tex/mathtools/MathtoolsConfiguration.js';
import 'mathjax-full/js/input/tex/newcommand/NewcommandConfiguration.js';
import 'mathjax-full/js/input/tex/physics/PhysicsConfiguration.js';
import 'mathjax-full/js/input/tex/textcomp/TextcompConfiguration.js';
import 'mathjax-full/js/input/tex/textmacros/TextMacrosConfiguration.js';
import 'mathjax-full/js/input/tex/unicode/UnicodeConfiguration.js';
import 'mathjax-full/js/input/tex/upgreek/UpgreekConfiguration.js';

import { DEFAULT_MACROS, PACKAGES, preprocessLatex } from '../lib/mathEngine.ts';

// ---- args ----------------------------------------------------------------
function parseArgs(argv) {
  const a = { mirror: join(homedir(), 'data/docsuri-data/s3'), sample: null, limit: null, out: null };
  for (let i = 0; i < argv.length; i += 1) {
    const k = argv[i];
    if (k === '--mirror') a.mirror = argv[++i];
    else if (k === '--sample') a.sample = Number(argv[++i]);
    else if (k === '--limit') a.limit = Number(argv[++i]);
    else if (k === '--out') a.out = argv[++i];
  }
  return a;
}

// ---- MathJax harness -----------------------------------------------------
const adaptor = liteAdaptor();
RegisterHTMLHandler(adaptor);
// One document reused across formulas (author macros are NOT merged here — this is the systemic
// pass). A macro-DEFINING expression persists in the TeX jax, so those get a throwaway document,
// mirroring renderMath's isolation rule.
const DEFINES_RE = /\\(?:x?def|gdef|edef|let|(?:re|provide)?newcommand|DeclareMathOperator)\b/;
function makeDoc() {
  const tex = new TeX({
    packages: PACKAGES,
    macros: { ...DEFAULT_MACROS },
    formatError: (_jax, err) => {
      throw err;
    },
  });
  const svg = new SVG({ fontCache: 'none' });
  return mathjax.document('', { InputJax: tex, OutputJax: svg });
}
let sharedDoc = makeDoc();
let sinceRecycle = 0;
// MathJax's document accumulates every converted expression in an internal math list, so reusing one
// document across tens of thousands of convert() calls leaks until the heap dies (OOM at ~60k). Drop
// and rebuild it every RECYCLE_EVERY formulas to release that state — cheap next to the converts.
const RECYCLE_EVERY = 1000;
function renderFails(latex) {
  if (++sinceRecycle >= RECYCLE_EVERY) {
    sharedDoc = makeDoc();
    sinceRecycle = 0;
  }
  // A macro-defining expression persists in the TeX jax, so isolate it in a throwaway document.
  const doc = DEFINES_RE.test(latex) ? makeDoc() : sharedDoc;
  try {
    // convert() runs the TeX compile where an undefined command / bad construct throws (formatError).
    // No need to serialize the SVG (outerHTML) — the parse failure is what we're detecting, and
    // skipping it keeps the sweep lighter.
    doc.convert(preprocessLatex(latex), { display: true });
    return null;
  } catch (err) {
    // MathJax throws its own `TeXError`, which is NOT a JS `Error` subclass — but it does carry a
    // `.message` ("Undefined control sequence \vspace"). Read that first; only fall back to String().
    return err && typeof err.message === 'string' ? err.message : String(err);
  }
}

// Normalize an error message into a bucket key + the offending control sequence (if any).
function classify(message) {
  const undef = message.match(/Undefined control sequence (\\[a-zA-Z@]+|\\.)/);
  if (undef) return { key: `undefined ${undef[1]}`, cmd: undef[1].replace(/^\\/, '') };
  // Collapse variable bits (positions, tokens) so like errors bucket together.
  const key = message
    .replace(/\s+/g, ' ')
    .replace(/'[^']*'/g, "'…'")
    .slice(0, 80);
  return { key, cmd: null };
}

// ---- doc-model walk ------------------------------------------------------
function* walk(node) {
  if (Array.isArray(node)) {
    for (const x of node) yield* walk(x);
  } else if (node && typeof node === 'object') {
    yield node;
    for (const v of Object.values(node)) yield* walk(v);
  }
}

function latestVersionFile(paperDir) {
  let best = null;
  let bestN = -1;
  for (const f of readdirSync(paperDir)) {
    const m = f.match(/^v(\d+)\.json$/);
    if (m && Number(m[1]) > bestN) {
      bestN = Number(m[1]);
      best = join(paperDir, f);
    }
  }
  return best;
}

// ---- main ----------------------------------------------------------------
function main() {
  const args = parseArgs(process.argv.slice(2));
  const dmDir = join(args.mirror, 'doc-model');
  let paperDirs = readdirSync(dmDir)
    .map((n) => join(dmDir, n))
    .filter((p) => {
      try {
        return statSync(p).isDirectory();
      } catch {
        return false;
      }
    });
  if (args.sample && args.sample < paperDirs.length) {
    // Deterministic stride sample across the (sorted) corpus — spreads over parser generations.
    const stride = Math.floor(paperDirs.length / args.sample);
    paperDirs = paperDirs.filter((_, i) => i % stride === 0).slice(0, args.sample);
  }
  if (args.limit) paperDirs = paperDirs.slice(0, args.limit);

  console.log(`[plan] ${paperDirs.length} papers (mirror: ${args.mirror})`);

  const authorMacroNames = new Set(); // union of all papers' meta.macros keys (backslash-stripped)
  const uniqueLatex = new Map(); // latex -> example paperId (dedup)
  let totalFormulas = 0;
  let papersRead = 0;

  const started = Date.now();
  for (let i = 0; i < paperDirs.length; i += 1) {
    const dir = paperDirs[i];
    const file = latestVersionFile(dir);
    if (!file) continue;
    let doc;
    try {
      doc = JSON.parse(readFileSync(file, 'utf8'));
    } catch {
      continue;
    }
    papersRead += 1;
    const pid = dir.split('/').pop();
    const macros = doc?.meta?.macros;
    if (macros && typeof macros === 'object') {
      for (const k of Object.keys(macros)) authorMacroNames.add(k.replace(/^\\/, ''));
    }
    for (const n of walk(doc)) {
      if (n && n.type === 'formula' && typeof n.latex === 'string' && n.latex) {
        totalFormulas += 1;
        if (!uniqueLatex.has(n.latex)) uniqueLatex.set(n.latex, pid);
      }
    }
    if ((i + 1) % 2000 === 0) {
      console.log(`  …scanned ${i + 1}/${paperDirs.length} papers, ${uniqueLatex.size} unique formulas`);
    }
  }

  console.log(
    `[scan] ${papersRead} papers read, ${totalFormulas} formulas, ${uniqueLatex.size} unique; ` +
      `${authorMacroNames.size} distinct author-macro names`,
  );
  console.log('[render] rendering unique formulas with DEFAULT_MACROS…');

  const buckets = new Map(); // key -> { count, cmd, examples:Set, authorResolvable }
  let rendered = 0;
  let failed = 0;
  for (const [latex, pid] of uniqueLatex) {
    const message = renderFails(latex);
    rendered += 1;
    if (message) {
      failed += 1;
      const { key, cmd } = classify(message);
      let b = buckets.get(key);
      if (!b) {
        b = { count: 0, cmd, examples: new Set(), authorResolvable: cmd ? authorMacroNames.has(cmd) : false };
        buckets.set(key, b);
      }
      b.count += 1;
      if (b.examples.size < 5) b.examples.add(`${pid}: ${latex.slice(0, 90)}`);
    }
    if (rendered % 20000 === 0) console.log(`  …rendered ${rendered}/${uniqueLatex.size}`);
  }

  const rows = [...buckets.entries()]
    .map(([key, b]) => ({ key, count: b.count, cmd: b.cmd, authorResolvable: b.authorResolvable, examples: [...b.examples] }))
    .sort((x, y) => y.count - x.count);
  const systemic = rows.filter((r) => !r.authorResolvable);
  const author = rows.filter((r) => r.authorResolvable);
  const systemicFails = systemic.reduce((s, r) => s + r.count, 0);
  const authorFails = author.reduce((s, r) => s + r.count, 0);

  const elapsed = ((Date.now() - started) / 1000).toFixed(1);
  console.log(`\n===== MATH RENDER SWEEP (${elapsed}s) =====`);
  console.log(`unique formulas: ${uniqueLatex.size} | failed: ${failed} ` +
    `(systemic ${systemicFails}, author-resolvable ${authorFails})`);
  console.log(`\n--- SYSTEMIC failure buckets (actionable — fix in mathEngine) ---`);
  for (const r of systemic.slice(0, 40)) {
    console.log(`  ${String(r.count).padStart(6)}  ${r.key}`);
    if (r.examples[0]) console.log(`          e.g. ${r.examples[0]}`);
  }
  if (systemic.length === 0) console.log('  (none) 🎉');
  console.log(`\n--- top AUTHOR-RESOLVABLE (noise — resolved by each paper's meta.macros at runtime) ---`);
  for (const r of author.slice(0, 12)) console.log(`  ${String(r.count).padStart(6)}  ${r.key}`);

  const outPath = args.out || join(process.env.TMPDIR || '/tmp', `math-render-sweep-${Date.now()}.json`);
  writeFileSync(
    outPath,
    JSON.stringify(
      {
        mirror: args.mirror,
        papersRead,
        totalFormulas,
        uniqueFormulas: uniqueLatex.size,
        failed,
        systemicFails,
        authorFails,
        systemic,
        author,
      },
      null,
      2,
    ),
  );
  console.log(`\n[report] written: ${outPath}`);
}

main();
