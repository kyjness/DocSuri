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
const generatedDir = resolve(here, '../types/generated');

// 기계 생성분을 **추적되는 경로**에 쓰는 스키마. CI가 `git diff --exit-code types/`로
// 검사하므로 이쪽만 드리프트가 자동으로 잡힌다.
//
// 나머지 스키마는 types/generated/*.ts가 손으로 큐레이션된 것이라 여기 못 넣는다 —
// 덮어쓰면 큐레이션이 사라진다. 그쪽은 예전처럼 .schema-raw/ 덤프를 놓고 **사람이**
// 비교한다. 즉 이 목록에 없는 스키마는 기계 검사가 없다.
const MACHINE_GENERATED = {
  'evidence.schema.json': 'evidence.ts',
};

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
await mkdir(generatedDir, { recursive: true });

const compile = (schema, bannerComment) =>
  compileFromFile(resolve(sharedDtos, schema), {
    bannerComment,
    additionalProperties: false,
    unreachableDefinitions: true,
    declareExternallyReferenced: true,
    $refOptions: { resolve: { localDtos } },
  });

let failures = 0;
for (const schema of SCHEMAS) {
  const out = schema.replace('.schema.json', '.raw.ts');
  try {
    const ts = await compile(
      schema,
      '/* RAW codegen — drift reference only. Build uses types/generated/. */',
    );
    await writeFile(resolve(rawDir, out), ts, 'utf8');
    console.log(`drift-dump ${out}`);
  } catch (err) {
    failures += 1;
    console.warn(`skip ${schema}: ${err instanceof Error ? err.message : String(err)}`);
  }

  const machine = MACHINE_GENERATED[schema];
  if (!machine) continue;
  try {
    const ts = await compile(
      schema,
      `/* GENERATED from shared/dtos/${schema} by \`pnpm gen:types\` — do not edit by hand.
 * This file is committed so CI's \`git diff --exit-code types/\` fails when the schema
 * moves and this does not. Consumers import from here; nothing re-declares these shapes. */`,
    );
    await writeFile(resolve(generatedDir, machine), ts, 'utf8');
    console.log(`generated ${machine}`);
  } catch (err) {
    failures += 1;
    // 여기서 exit 0으로 나가면 추적되는 파일이 낡은 채로 남고 diff는 비어 CI가 초록이다 —
    // 가드가 무는 것처럼 보이는 바로 그 순간에 안 문다.
    process.exitCode = 1;
    console.error(`FAILED ${schema} -> ${machine}: ${err instanceof Error ? err.message : String(err)}`);
  }
}

const guarded = Object.keys(MACHINE_GENERATED).length;
console.log(
  failures
    ? `gen:types finished with ${failures} schema(s) skipped — see the reason above; a skipped schema has NO drift reference.`
    : `gen:types finished. ${guarded}/${SCHEMAS.length} schema(s) are machine-checked by ` +
      `\`git diff --exit-code types/\`; the rest need a human to diff types/.schema-raw/ ` +
      'against the curated types/generated/*.ts.',
);
