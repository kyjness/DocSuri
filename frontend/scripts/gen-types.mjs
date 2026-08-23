// TypeGen / drift-review pipeline (LC-7, BR-U5-19).
//
// The curated DTO types in types/generated/*.ts mirror the EXPOSED contract of
// shared/dtos/*.schema.json (the SSOT). The shared schemas are doc-oriented and
// partly root-less ($defs only), so a raw codegen is kept under
// types/.schema-raw/ for DRIFT REVIEW: regenerate, diff against the curated
// types, and reconcile on any schema change. The committed, build-consumed types
// remain types/generated/*.ts.
import { compileFromFile } from 'json-schema-to-typescript';
import { writeFile, mkdir, readFile } from 'node:fs/promises';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const sharedDtos = resolve(here, '../../shared/dtos');
const rawDir = resolve(here, '../types/.schema-raw');

// Every shared DTO schema the frontend carries a curated type for. Missing one costs nothing
// visible and removes the only mechanical check there is: summarization was absent here, so when
// its AssetRef.type enum grew a `formula` member the Python DTO picked it up through codegen and
// the hand-curated TS stopped at the boundary, with nothing anywhere to notice.
const SCHEMAS = [
  'search.schema.json',
  'accounts.schema.json',
  'library.schema.json',
  'docmodel.schema.json',
  'mypage.schema.json',
  'summarization.schema.json',
  'evidence.schema.json',
];

// A schema's $id is its canonical https://docsuri.dev/ URL, and cross-schema $refs use it —
// summarization refs docmodel, library refs search. Left alone the resolver tries to FETCH those
// over the network, which fails offline and in CI, so exactly the two schemas that share types
// were the two that never produced a drift dump. Serve them from the checkout instead: the local
// file is what we are auditing anyway, and a published copy would be the wrong answer.
const localDtos = {
  order: 1,
  canRead: /^https:\/\/docsuri\.dev\/shared\/dtos\//,
  read: (file) => readFile(resolve(sharedDtos, file.url.split('/').pop()), 'utf8'),
};

await mkdir(rawDir, { recursive: true });

let failures = 0;
for (const schema of SCHEMAS) {
  const out = schema.replace('.schema.json', '.raw.ts');
  try {
    const ts = await compileFromFile(resolve(sharedDtos, schema), {
      bannerComment: '/* RAW codegen — drift reference only. Build uses types/generated/. */',
      additionalProperties: false,
      unreachableDefinitions: true,
      declareExternallyReferenced: true,
      $refOptions: { resolve: { localDtos } },
    });
    await writeFile(resolve(rawDir, out), ts, 'utf8');
    console.log(`drift-dump ${out}`);
  } catch (err) {
    failures += 1;
    console.warn(`skip ${schema}: ${err instanceof Error ? err.message : String(err)}`);
  }
}

console.log(
  failures
    ? `gen:types finished with ${failures} schema(s) skipped — see the reason above; a skipped schema has NO drift reference. Curated types in types/generated/ are authoritative.`
    : 'gen:types finished. Diff types/.schema-raw/ against types/generated/ to review drift.',
);
