import { describe, expect, it } from 'vitest';
import {
  abstainReasonLabel,
  examinedRangeMessage,
  parseAgentContent,
} from '@/lib/agentChat/evidenceResult';

describe('parseAgentContent', () => {
  it('parses a successful EvidenceResult JSON payload', () => {
    const content = JSON.stringify({
      state: 'ok',
      claims: [
        {
          statement: 'Cottention achieves native linear memory complexity.',
          supporting: [
            {
              paperId: '2409.18747v1',
              recordRef: '2409.18747v1',
              anchor: null,
              quote: 'Cottention achieves native linear memory complexity.',
            },
          ],
          conflicting: [],
        },
      ],
      coverage: { paperCount: 3, queryUsed: 'transformer attention' },
    });

    const parsed = parseAgentContent(content);
    expect(parsed.kind).toBe('evidence');
    if (parsed.kind === 'evidence') {
      expect(parsed.result.claims).toHaveLength(1);
      expect(parsed.result.claims[0].supporting[0].paperId).toBe('2409.18747v1');
      expect(parsed.result.coverage.paperCount).toBe(3);
    }
  });

  it('passes through the optional answer narrative field', () => {
    const content = JSON.stringify({
      state: 'ok',
      claims: [],
      coverage: { paperCount: 0 },
      answer: "'self-attention reduces computation' 문장이 포함된 논문을 총 1편 찾았습니다.",
    });

    const parsed = parseAgentContent(content);
    expect(parsed.kind).toBe('evidence');
    if (parsed.kind === 'evidence') {
      expect(parsed.result.answer).toContain('1편');
    }
  });

  it('parses an abstain response and maps it to a human-readable label', () => {
    const parsed = parseAgentContent('[abstain] insufficient_evidence');
    expect(parsed.kind).toBe('abstain');
    if (parsed.kind === 'abstain') {
      expect(parsed.reason).toBe('insufficient_evidence');
      expect(abstainReasonLabel(parsed.reason)).toBe('근거가 충분하지 않아 답변을 보류했습니다.');
    }
  });

  it('falls back to a generic label for an unknown abstain reason', () => {
    expect(abstainReasonLabel('some_new_reason')).toBe('답변을 생성하지 못했습니다.');
  });

  it('keeps a label for llm_unavailable — the assembler still emits it', () => {
    // 백엔드가 이 사유를 **지어내는** 것을 막았을 뿐 생산자가 사라진 게 아니다
    // (`assembler`가 치명 오류에서 낸다). 항목을 지우면 진짜 LLM 실패가 일반
    // 폴백 문구로 떨어져 사유가 화면에서 사라진다.
    const label = abstainReasonLabel('llm_unavailable');
    expect(label).not.toBe(abstainReasonLabel('some_code_nobody_emits'));
    expect(label).toContain('분석을 끝내지 못했어요');
  });

  it('parses an error response', () => {
    const parsed = parseAgentContent('[error] evidence_unavailable');
    expect(parsed.kind).toBe('error');
  });

  it('treats plain text (e.g. user messages, novelty mode) as text', () => {
    const parsed = parseAgentContent('transformer 모델의 attention 메커니즘에 대한 최근 연구 동향은?');
    expect(parsed.kind).toBe('text');
    if (parsed.kind === 'text') {
      expect(parsed.text).toContain('transformer');
    }
  });

  it('does not choke on JSON-looking text that is not an EvidenceResult', () => {
    const parsed = parseAgentContent('{"foo": "bar"}');
    expect(parsed.kind).toBe('text');
  });

  it('labels a cancelled turn as cancelled, not as missing evidence (v3 §2.8)', () => {
    expect(abstainReasonLabel('cancelled')).toBe(
      '취소했어요. 확인한 논문에서는 아직 근거를 찾기 전이었어요.',
    );
    expect(
      examinedRangeMessage({ paperCount: 2, examined: 2, candidates: 16, stoppedReason: 'cancelled' }),
    ).toBe('취소됨 · 후보 16편 중 2편 확인');
  });
});
