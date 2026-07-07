'use client';

import { useMemo, useState } from 'react';
import { UserFacingError, getApiClient } from '@/lib/api';
import type { NotionExportPreviewVM, NotionExportVM } from '@/lib/api/apiClient';
import styles from './NotionExportPanel.module.css';

type Phase = 'idle' | 'connect' | 'preview' | 'submitting' | 'done';

interface Props {
  jobId: string;
}

// US-NV8(#258) — 내부 저장 후 Notion export: 미리보기 → 명시 승인 → 내보내기.
// 자동 export 없음. 토큰은 서버에서 암호화 저장되고 응답으로 되돌아오지 않는다(SEC-8/12).
export function NotionExportPanel({ jobId }: Props) {
  const api = useMemo(() => getApiClient(), []);
  const [phase, setPhase] = useState<Phase>('idle');
  const [token, setToken] = useState('');
  const [parentPageId, setParentPageId] = useState('');
  const [preview, setPreview] = useState<NotionExportPreviewVM | null>(null);
  const [result, setResult] = useState<NotionExportVM | null>(null);
  const [error, setError] = useState<string | null>(null);
  const parentPageMissing = phase === 'connect' && parentPageId.trim().length < 32;

  function fail(err: unknown) {
    setError(err instanceof UserFacingError ? err.message : 'Notion 내보내기에 실패했습니다.');
  }

  async function loadPreview() {
    const loaded = await api.previewNotionExport(jobId);
    setPreview(loaded);
    setPhase('preview');
  }

  async function open() {
    setError(null);
    try {
      const connection = await api.getNotionConnection();
      if (connection.connected) await loadPreview();
      else setPhase('connect');
    } catch (err) {
      fail(err);
    }
  }

  async function saveConnection() {
    setError(null);
    try {
      await api.saveNotionConnection(token.trim(), parentPageId.trim());
      setToken('');
      await loadPreview();
    } catch (err) {
      fail(err);
    }
  }

  function cancelConnection() {
    setError(null);
    setToken('');
    setParentPageId('');
    setPhase('idle');
  }

  async function approve() {
    setError(null);
    setPhase('submitting');
    try {
      const exported = await api.approveNotionExport(jobId, true);
      setResult(exported);
      setPhase('done');
      if (exported.status !== 'exported') {
        setError(exported.errorMessage ?? 'Notion 내보내기에 실패했습니다.');
      }
    } catch (err) {
      setPhase('preview');
      fail(err);
    }
  }

  return (
    <section
      className={styles.panel}
      aria-label="Notion 내보내기"
      data-testid="notion-export-panel"
    >
      {phase === 'idle' ? (
        <button
          type="button"
          className={styles.openButton}
          onClick={open}
          data-testid="notion-export-open"
        >
          Notion으로 내보내기
        </button>
      ) : null}

      {phase === 'connect' ? (
        <div className={styles.form}>
          <p className={styles.hint}>
            Notion 내부 연동 토큰과 상위 페이지 ID를 등록하세요. 토큰은 암호화되어 저장됩니다.
          </p>
          <input
            type="password"
            className={styles.field}
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="Notion 연동 토큰"
            aria-label="Notion 연동 토큰"
            data-testid="notion-token-input"
          />
          <input
            className={styles.field}
            value={parentPageId}
            onChange={(e) => setParentPageId(e.target.value)}
            placeholder="상위 페이지 ID (32자)"
            aria-label="Notion 상위 페이지 ID"
            data-testid="notion-parent-input"
          />
          {parentPageMissing ? (
            <p className={styles.error} role="alert" data-testid="notion-parent-warning">
              상위 페이지 ID를 등록해야 Notion에 페이지를 만들 수 있습니다.
            </p>
          ) : null}
          <button
            type="button"
            className={styles.primaryButton}
            onClick={saveConnection}
            disabled={token.trim().length < 16 || parentPageId.trim().length < 32}
            data-testid="notion-connect-save"
          >
            연결 저장
          </button>
          <button
            type="button"
            className={styles.ghostButton}
            onClick={cancelConnection}
            data-testid="notion-connect-cancel"
          >
            취소
          </button>
        </div>
      ) : null}

      {phase === 'preview' && preview ? (
        <div className={styles.preview} data-testid="notion-export-preview">
          <p className={styles.title}>{preview.preview.title}</p>
          <ul className={styles.artifactList}>
            {preview.preview.artifacts.map((artifact) => (
              <li key={artifact.kind}>{artifact.title}</li>
            ))}
          </ul>
          <div className={styles.actions}>
            <button
              type="button"
              className={styles.primaryButton}
              onClick={approve}
              data-testid="notion-export-approve"
            >
              승인하고 내보내기
            </button>
            <button type="button" className={styles.ghostButton} onClick={() => setPhase('idle')}>
              닫기
            </button>
          </div>
        </div>
      ) : null}

      {phase === 'submitting' ? (
        <p className={styles.hint} role="status">
          Notion으로 내보내는 중…
        </p>
      ) : null}

      {phase === 'done' && result?.status === 'exported' && result.notionPageId ? (
        <p role="status" data-testid="notion-export-done">
          Notion 저장 완료 —{' '}
          <a
            className={styles.pageLink}
            href={`https://www.notion.so/${result.notionPageId.replace(/-/g, '')}`}
            target="_blank"
            rel="noopener noreferrer"
            data-testid="notion-export-link"
          >
            저장된 페이지 열기
          </a>
        </p>
      ) : null}
      {phase === 'done' && result && result.status !== 'exported' ? (
        <button
          type="button"
          className={styles.ghostButton}
          onClick={() => setPhase('preview')}
          data-testid="notion-export-retry"
        >
          다시 시도
        </button>
      ) : null}

      {error ? (
        <p className={styles.error} role="alert" data-testid="notion-export-error">
          {error}
        </p>
      ) : null}
    </section>
  );
}
