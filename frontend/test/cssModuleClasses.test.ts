/**
 * CSS 모듈 클래스 대조 — 소비자가 읽는 이름에 규칙이 실재하는가.
 *
 * 근거표를 목록으로 바꾸며 CSS에서 `.evidenceLabel`을 지웠는데, **novelty의 실험 계획 뷰가
 * 아직 쓰고 있었다**(2026-08-25). `styles.<없는 이름>`은 `undefined`이고
 * `className={undefined}`는 class 속성을 아예 안 만든다 — 예외도 경고도 없고, CSS 모듈 타입이
 * `Record<string, string>`이라 tsc도 안 잡는다. vitest는 클래스명을 아이덴티티로 목하므로
 * 렌더 테스트도 전부 초록으로 지나간다. 화면을 열어야만 보이는 종류라 여기서 기계로 고정한다.
 *
 * **별칭은 파일 단위로 묶는다.** 한 파일이 스타일시트를 둘 이상 import 하고(`styles`와
 * `screen`), 같은 스타일시트를 여러 파일이 다른 이름으로 import 한다. 별칭을 파일 밖에서
 * 합치면 `screen.foo`를 엉뚱한 시트에 대고 검사하게 된다. 그리고 import 줄 자체를 먼저
 * 걷어내야 한다 — 안 걷으면 `'../page.module.css'` 경로 문자열이 `page.module`로 매칭된다.
 *
 * **반대 방향(규칙은 있는데 아무도 안 읽는다)은 여기서 안 본다.** 죽은 CSS는 화면을 깨뜨리지
 * 않고, 그 검사를 처음 붙였을 때 잘못된 목록을 만들어 **살아 있는 규칙 38줄을 지우게 했다**
 * (`app/page.module.css`는 라우트 17개가, `GlossaryTermBadge.module.css`는 배지와 에디터
 * 둘이 함께 쓴다). 검사가 틀리면 코드를 지우게 만든다 — 못 잡는 것보다 나쁘다.
 */
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const ROOT = join(__dirname, '..');
const SOURCE_DIRS = ['app', 'components', 'lib'];

/** `.foo {`·`.foo,`·`.foo:hover` — 선택자 맨 앞의 클래스. 들여쓰기는 `@media` 안이다. */
const DEFINITION = /^[ \t]*\.([A-Za-z][\w-]*)(?=[\s,{:.])/gm;
/** `import x from './y.module.css'` — 소비자↔스타일시트를 잇는 유일한 근거다. */
const CSS_IMPORT = /^import\s+(\w+)\s+from\s+['"]([^'"]+\.module\.css)['"];?$/gm;

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) walk(path, out);
    else if (/\.tsx?$/.test(entry.name)) out.push(path);
  }
  return out;
}

/** 주석 속 산문이 클래스를 언급하면(`.screen fills the frame …`) 정의로 잡힌다. */
function definedClasses(cssPath: string): Set<string> {
  const css = readFileSync(cssPath, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
  return new Set([...css.matchAll(DEFINITION)].map((m) => m[1]));
}

/** `@/`는 tsconfig paths 별칭(프로젝트 루트)이다. */
function resolveSheet(fromFile: string, spec: string): string {
  return spec.startsWith('@/') ? join(ROOT, spec.slice(2)) : resolve(dirname(fromFile), spec);
}

/** (소비자 파일, 별칭 → 스타일시트) 하나하나가 검사 단위다. */
function bindings(): Array<{ name: string; file: string; alias: string; sheet: string }> {
  const found = [];
  for (const dir of SOURCE_DIRS) {
    for (const file of walk(join(ROOT, dir))) {
      const text = readFileSync(file, 'utf8');
      for (const [, alias, spec] of text.matchAll(CSS_IMPORT)) {
        found.push({
          name: `${relative(ROOT, file)} (${alias})`,
          file,
          alias,
          sheet: resolveSheet(file, spec),
        });
      }
    }
  }
  return found;
}

describe('CSS module classes exist for every consumer that reads them', () => {
  const all = bindings();

  it('finds the consumer/stylesheet bindings to check', () => {
    // 하나도 못 찾으면 아래 검사가 **공집합을 통과**한다 — 초록이 무의미해진다.
    expect(all.length).toBeGreaterThan(20);
    expect(all.map((b) => b.name)).toContain(
      'components/agent/AgentChatScreen.tsx (styles)',
    );
  });

  it.each(all)('$name', ({ file, alias, sheet }) => {
    const defined = definedClasses(sheet);
    // import 줄을 먼저 걷어낸다 — 경로 문자열(`'../page.module.css'`)이 `page.module`로 잡힌다.
    const body = readFileSync(file, 'utf8').replace(CSS_IMPORT, '');
    const read = new RegExp(`\\b${alias}\\.([A-Za-z][\\w]*)\\b`, 'g');
    const missing = [...new Set([...body.matchAll(read)].map((m) => m[1]))].filter(
      (name) => !defined.has(name),
    );

    expect(missing).toEqual([]);
  });
});
