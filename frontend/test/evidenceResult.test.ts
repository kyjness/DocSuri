import { describe, expect, it } from 'vitest';
import { abstainReasonLabel, parseAgentContent } from '@/lib/agentChat/evidenceResult';

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
});
