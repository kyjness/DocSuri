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
function readCss(cssPath: string): string {
  return readFileSync(cssPath, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
}

function definedClasses(cssPath: string): Set<string> {
  return new Set([...readCss(cssPath).matchAll(DEFINITION)].map((m) => m[1]));
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

// 모듈 스코프에 한 번 — `describe` 둘이 나눠 쓴다(안 그러면 `app`·`components`·`lib`
// 전체 walk가 두 번 돈다).
const all = bindings();

describe('CSS module classes exist for every consumer that reads them', () => {
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

/**
 * `hidden` 속성으로 접는 요소는 **`display`를 세우면 안 되거나, 세웠으면 가드를 함께 둬야
 * 한다.** UA 시트의 `[hidden] { display: none }`은 author 규칙에 무조건 진다 — 특이도가
 * 아니라 캐스케이드 원점 문제라 클래스 하나로 통째로 무력해진다.
 *
 * 실제로 그랬다(2026-08-26): 근거 줄을 논문 단위로 묶으며 `.evidenceRow`에 `display: grid`를
 * 줬더니 접힌 근거가 전부 보였다. 종전 `.evidenceClaim`이 display를 안 세워서 접기가 **우연히**
 * 동작하고 있었을 뿐이다. jsdom은 CSS 모듈을 아이덴티티로 목하므로 렌더 테스트가 계산된
 * 스타일을 못 보고, 그래서 이 결함은 화면을 열어야만 보인다.
 */
describe('classes rendered with the hidden attribute', () => {
  // `\b`를 쓰면 `aria-hidden=`도 잡힌다(`-`와 `h` 사이가 단어 경계다) — 그쪽은 접기가
  // 아니라 접근성 표시라 무관하다. 앞이 공백이거나 `{`인 것만 본다.
  const HIDDEN_PROP = /className=\{styles\.(\w+)\}[^>]*?[\s{]hidden=/gs;

  it.each(all)('$name', ({ file, sheet }) => {
    const body = readFileSync(file, 'utf8');
    const css = readCss(sheet);
    for (const [, name] of body.matchAll(HIDDEN_PROP)) {
      // **`display`를 세웠는지 따지지 않는다.** `composes:`로 물려받으면 자기 블록에 그
      // 선언이 없어 검사가 그냥 넘어간다 — 실제로 `.evidenceRow`를 `composes: evidenceRef`로
      // 정리하면서 이 검사가 조용히 무력해졌다(가드를 지워도 초록이었다). 가드는 공짜이므로
      // `hidden`으로 접는 클래스면 **무조건** 요구한다.
      expect(css, `\`${name}\` needs a [hidden] guard`).toMatch(
        new RegExp(`\\.${name}\\[hidden\\]`),
      );
    }
  });
});

/**
 * `composes:` 대상은 **쓰이는 자리보다 먼저** 정의돼야 한다 — css-loader가 소스 순서로
 * 해석해서, 뒤에 있으면 `referenced class name … not found`로 빌드가 깨진다.
 *
 * **vitest도 tsc도 CSS 모듈을 컴파일하지 않는다.** 그래서 로컬에서 테스트·타입·린트가 전부
 * 초록인 채 CI의 `next build`에서만 터졌다(2026-08-26, 중복 규칙을 `composes`로 정리하다가
 * 셋이 한꺼번에). 빌드보다 훨씬 싼 검사로 같은 것을 여기서 막는다.
 */
describe('composes targets are declared before use', () => {
  const COMPOSES_AT = /^[ \t]*composes:\s*([^;]+);/gm;

  it.each([...new Set(all.map((b) => b.sheet))].map((sheet) => ({ sheet })))(
    '$sheet',
    ({ sheet }) => {
      const css = readCss(sheet);
      const late: string[] = [];
      for (const match of css.matchAll(COMPOSES_AT)) {
        // `composes: a b from "./x.css"` — 다른 파일에서 가져오는 것은 순서와 무관하다.
        if (/\sfrom\s/.test(match[1])) continue;
        for (const name of match[1].trim().split(/\s+/)) {
          const declared = css.search(new RegExp(`^[ \\t]*\\.${name}(?=[\\s,{:.])`, 'm'));
          if (declared < 0 || declared > match.index!) late.push(name);
        }
      }
      expect([...new Set(late)]).toEqual([]);
    },
  );
});
