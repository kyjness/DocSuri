// TypeGen / drift-review pipeline (LC-7, BR-U5-19).
//
// The curated DTO types in types/generated/*.ts mirror the EXPOSED contract of
// shared/dtos/*.schema.json (the SSOT). The shared schemas are doc-oriented and
// partly root-less ($defs only), so a raw codegen is kept under
// types/.schema-raw/ for DRIFT REVIEW: regenerate, diff against the curated
// types, and reconcile on any schema change. The committed, build-consumed types
// remain types/generated/*.ts.
import { compileFromFile } from 'json-schema-to-typescript';
import { writeFile, mkdir } from 'node:fs/promises';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const sharedDtos = resolve(here, '../../shared/dtos');
const rawDir = resolve(here, '../types/.schema-raw');

const SCHEMAS = [
  'search.schema.json',
  'accounts.schema.json',
  'library.schema.json',
  'docmodel.schema.json',
];

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
    ? `gen:types finished with ${failures} schema(s) skipped (root-less $defs). Curated types in types/generated/ are authoritative.`
    : 'gen:types finished. Diff types/.schema-raw/ against types/generated/ to review drift.',
);
