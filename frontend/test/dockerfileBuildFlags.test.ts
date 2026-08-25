/**
 * 이미지가 세우는 `NEXT_PUBLIC_*`와 코드가 읽는 것이 같은지.
 *
 * `NEXT_PUBLIC_*`는 **빌드 시점에 번들로 박힌다.** 그래서 Dockerfile이 세우는 이름과 코드가
 * 읽는 이름이 갈리면 그 플래그는 아무 일도 하지 않는데, **빌드는 성공하고 테스트는 목
 * 전송이라 초록이며** 화면을 열기 전까지 아무 데도 안 보인다.
 *
 * 실제로 갈려 있었다(2026-08-25 발견): Dockerfile이 `..._RESEARCH_AGENT_ENABLED`를 세우는데
 * 읽는 쪽은 `..._EVIDENCE_AGENT_ENABLED`라, real API 이미지가 **Research 비활성**으로
 * 빌드되고 있었다 — 모드 선택 버튼이 disabled로 뜨는 상태다.
 */
import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

const ROOT = join(__dirname, '..');
const SKIP = new Set(['node_modules', '.next', 'test', 'e2e', 'types']);

function sources(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (SKIP.has(name) || name.startsWith('.')) continue;
    const path = join(dir, name);
    if (statSync(path).isDirectory()) sources(path, out);
    else if (/\.(ts|tsx)$/.test(name)) out.push(path);
  }
  return out;
}

function flagsIn(text: string): Set<string> {
  return new Set(text.match(/NEXT_PUBLIC_[A-Z0-9_]+/g) ?? []);
}

describe('Dockerfile build flags', () => {
  it('declares an ARG for every NEXT_PUBLIC_ flag the app reads', () => {
    const dockerfile = readFileSync(join(ROOT, 'Dockerfile'), 'utf8');
    const declared = new Set(
      [...dockerfile.matchAll(/^ARG (NEXT_PUBLIC_[A-Z0-9_]+)/gm)].map((m) => m[1]),
    );

    const read = new Set<string>();
    for (const file of sources(ROOT)) {
      for (const flag of flagsIn(readFileSync(file, 'utf8'))) read.add(flag);
    }

    const missing = [...read].filter((flag) => !declared.has(flag)).sort();
    expect(missing, `이미지가 안 세우는 플래그 — 번들에 빈 값으로 박힌다: ${missing}`).toEqual(
      [],
    );
  });

  it('does not declare an ARG nothing reads', () => {
    const dockerfile = readFileSync(join(ROOT, 'Dockerfile'), 'utf8');
    // 주석에 든 이름은 세는 대상이 아니다 — 갈렸던 경위를 거기에 적어 뒀다.
    const declared = [...dockerfile.matchAll(/^ARG (NEXT_PUBLIC_[A-Z0-9_]+)/gm)].map((m) => m[1]);

    const read = new Set<string>();
    for (const file of sources(ROOT)) {
      for (const flag of flagsIn(readFileSync(file, 'utf8'))) read.add(flag);
    }

    const dead = declared.filter((flag) => !read.has(flag)).sort();
    expect(dead, `아무도 안 읽는 ARG — 세운다고 믿게 만든다: ${dead}`).toEqual([]);
  });
});
