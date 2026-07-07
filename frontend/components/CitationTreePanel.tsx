'use client';

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { getApiClient } from '@/lib/api';
import type { CitationNode, CitationTreeResponse } from '@/types/citationGraph';
import styles from './CitationTreePanel.module.css';

interface CitationTreePanelProps {
  paperId: string;
  onClose?: () => void;
}

type LoadState =
  | { kind: 'loading' }
  | { kind: 'done'; tree: CitationTreeResponse }
  | { kind: 'error'; message: string };

interface GraphNode {
  node: CitationNode;
  parentId: string;
  x: number;
  y: number;
  depth: number;
}

interface GraphLayout {
  width: number;
  height: number;
  rootX: number;
  rootY: number;
  nodes: GraphNode[];
}

const MIN_GRAPH_WIDTH = 1100;
const GRAPH_PADDING_X = 160;
const ROOT_Y = 90;
const DEPTH_1_Y = 300;
const DEPTH_2_Y = 620;
const GRAPH_PADDING_BOTTOM = 160;
const COLUMN_GAP = 260;

export function CitationTreePanel({ paperId, onClose }: CitationTreePanelProps) {
  const [state, setState] = useState<LoadState>({ kind: 'loading' });
  const [expanded, setExpanded] = useState<Record<string, CitationTreeResponse>>({});
  const [expanding, setExpanding] = useState<string | null>(null);
  const [saved, setSaved] = useState<Set<string>>(() => new Set());
  const [saving, setSaving] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const panelRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  const load = useCallback(
    async (refresh = false) => {
      setState({ kind: 'loading' });
      setActionError(null);
      try {
        const tree = await getApiClient().getCitationTree(paperId, { refresh });
        setState({ kind: 'done', tree });
        if (refresh) setExpanded({});
      } catch {
        setState({ kind: 'error', message: '인용 트리를 불러오지 못했습니다.' });
      }
    },
    [paperId],
  );

  useEffect(() => {
    void load(false);
  }, [load]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCloseRef.current?.();
    };
    document.addEventListener('keydown', onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    panelRef.current?.focus();
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, []);

  async function toggleExpand(nodeId: string) {
    if (expanded[nodeId]) {
      setExpanded((prev) => {
        const next = { ...prev };
        delete next[nodeId];
        return next;
      });
      return;
    }

    setExpanding(nodeId);
    setActionError(null);
    try {
      const tree = await getApiClient().getCitationTree(paperId, { expandNodeId: nodeId });
      // Keep one branch open at a time so dense citation graphs stay readable.
      setExpanded({ [nodeId]: tree });
    } catch {
      setActionError('선택한 인용의 하위 트리를 불러오지 못했습니다.');
    } finally {
      setExpanding(null);
    }
  }

  async function save(node: CitationNode) {
    setSaving(node.nodeId);
    setActionError(null);
    try {
      await getApiClient().saveCitationNode(paperId, node);
      setSaved((prev) => new Set(prev).add(node.nodeId));
    } catch {
      setActionError('라이브러리에 저장하지 못했습니다.');
    } finally {
      setSaving(null);
    }
  }

  return (
    <div className={styles.backdrop} onClick={onClose} data-testid="citation-tree-backdrop">
      <section
        ref={panelRef}
        className={styles.panel}
        role="dialog"
        aria-modal="true"
        aria-label="각주 트리"
        tabIndex={-1}
        onClick={(event) => event.stopPropagation()}
        data-testid="citation-tree-panel"
      >
      <div className={styles.header}>
        <div>
          <h2 className={styles.title}>각주 트리</h2>
        </div>
        <div className={styles.tools}>
          <button
            type="button"
            className={styles.secondary}
            onClick={() => void load(true)}
            disabled={state.kind === 'loading'}
          >
            새로고침
          </button>
          {onClose ? (
            <button
              type="button"
              className={styles.close}
              onClick={onClose}
              aria-label="닫기"
              data-testid="citation-tree-close"
            >
              ✕
            </button>
          ) : null}
        </div>
      </div>

      {state.kind === 'loading' ? (
        <p className={styles.message}>인용 관계를 불러오는 중...</p>
      ) : state.kind === 'error' ? (
        <p className={styles.error} role="alert">
          {state.message}
        </p>
      ) : (
        <>
          {state.tree.status === 'RateLimited' || state.tree.status === 'Unavailable' ? (
            <p className={styles.error} role="status">
              현재 제공자가 응답하지 않아 일부 인용 정보를 표시할 수 없습니다.
            </p>
          ) : null}
          {actionError ? (
            <p className={styles.error} role="alert">
              {actionError}
            </p>
          ) : null}
          <CitationGraph
            tree={state.tree}
            expandedById={expanded}
            expandingId={expanding}
            savedIds={saved}
            savingId={saving}
            onExpand={toggleExpand}
            onSave={save}
          />
        </>
      )}
      </section>
    </div>
  );
}

function CitationGraph({
  tree,
  expandedById,
  expandingId,
  savedIds,
  savingId,
  onExpand,
  onSave,
}: {
  tree: CitationTreeResponse;
  expandedById: Record<string, CitationTreeResponse>;
  expandingId: string | null;
  savedIds: Set<string>;
  savingId: string | null;
  onExpand: (nodeId: string) => void;
  onSave: (node: CitationNode) => void;
}) {
  const [zoom, setZoom] = useState(1);
  const [horizontalScroll, setHorizontalScroll] = useState({ left: 0, max: 0 });
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const pendingScrollCenterRef = useRef<{ x: number; y: number } | null>(null);
  const didFitInitialGraphRef = useRef(false);
  const graph = layoutGraph(tree, expandedById);
  const byId = new Map(graph.nodes.map((item) => [item.node.nodeId, item]));

  const centerOffset = useCallback(
    (viewport: HTMLDivElement, value: number) => ({
      x: Math.max(0, (viewport.clientWidth - graph.width * value) / 2),
      y: Math.max(0, (viewport.clientHeight - graph.height * value) / 2),
    }),
    [graph.height, graph.width],
  );

  const syncHorizontalScroll = useCallback(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    setHorizontalScroll({
      left: viewport.scrollLeft,
      max: Math.max(0, viewport.scrollWidth - viewport.clientWidth),
    });
  }, []);

  useLayoutEffect(() => {
    const target = pendingScrollCenterRef.current;
    const viewport = viewportRef.current;
    if (!target || !viewport) return;
    pendingScrollCenterRef.current = null;
    const offset = centerOffset(viewport, zoom);
    viewport.scrollLeft = target.x * zoom + offset.x - viewport.clientWidth / 2;
    viewport.scrollTop = target.y * zoom + offset.y - viewport.clientHeight / 2;
    syncHorizontalScroll();
  }, [centerOffset, syncHorizontalScroll, zoom]);

  useEffect(() => {
    if (didFitInitialGraphRef.current) return;
    const frame = window.requestAnimationFrame(() => {
      const viewport = viewportRef.current;
      if (!viewport) return;
      didFitInitialGraphRef.current = true;
      const fit = Math.min(viewport.clientWidth / graph.width, viewport.clientHeight / graph.height);
      setZoom(Math.min(1, Math.max(0.25, fit)));
      viewport.scrollLeft = 0;
      viewport.scrollTop = 0;
      syncHorizontalScroll();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [graph.height, graph.width, syncHorizontalScroll]);

  useEffect(() => {
    syncHorizontalScroll();
    window.addEventListener('resize', syncHorizontalScroll);
    return () => window.removeEventListener('resize', syncHorizontalScroll);
  }, [graph.width, graph.height, syncHorizontalScroll, zoom]);

  function changeZoom(nextZoom: number) {
    const viewport = viewportRef.current;
    if (nextZoom === zoom) return;
    const currentZoom = zoom;
    const offset = viewport ? centerOffset(viewport, currentZoom) : { x: 0, y: 0 };
    pendingScrollCenterRef.current = {
      x: viewport
        ? (viewport.scrollLeft + viewport.clientWidth / 2 - offset.x) / currentZoom
        : graph.rootX,
      y: viewport
        ? (viewport.scrollTop + viewport.clientHeight / 2 - offset.y) / currentZoom
        : graph.rootY,
    };
    setZoom(nextZoom);
  }

  function moveHorizontal(nextLeft: number) {
    const viewport = viewportRef.current;
    if (!viewport) return;
    viewport.scrollLeft = nextLeft;
    setHorizontalScroll((prev) => ({ ...prev, left: nextLeft }));
  }

  const horizontalMax = Math.max(1, horizontalScroll.max);

  return (
    <div className={styles.graph} data-testid="citation-graph">
      <div className={styles.zoomControls} aria-label="그래프 확대/축소">
        <button
          type="button"
          className={styles.secondary}
          onClick={() => changeZoom(Math.max(0.25, zoom - 0.25))}
          disabled={zoom <= 0.25}
        >
          축소
        </button>
        <span className={styles.zoomValue}>{Math.round(zoom * 100)}%</span>
        <button
          type="button"
          className={styles.secondary}
          onClick={() => changeZoom(Math.min(1.5, zoom + 0.25))}
          disabled={zoom >= 1.5}
        >
          확대
        </button>
      </div>

      <div className={styles.graphViewport} ref={viewportRef} onScroll={syncHorizontalScroll}>
        <div
          className={styles.graphWorld}
          style={{ width: graph.width * zoom, height: graph.height * zoom }}
        >
          <div className={styles.graphFrame} style={{ width: graph.width * zoom, height: graph.height * zoom }}>
            <div
              className={styles.graphCanvas}
              style={{
                width: graph.width,
                height: graph.height,
                transform: `scale(${zoom})`,
              }}
            >
              <svg
                className={styles.graphSvg}
                viewBox={`0 0 ${graph.width} ${graph.height}`}
                aria-hidden="true"
              >
                {graph.nodes.map((item) => {
                  const parent = item.parentId === tree.rootPaperId ? null : byId.get(item.parentId);
                  const x1 = parent?.x ?? graph.rootX;
                  const y1 = parent?.y ?? graph.rootY;
                  return (
                    <line
                      key={`${item.parentId}-${item.node.nodeId}`}
                      x1={x1}
                      y1={y1}
                      x2={item.x}
                      y2={item.y}
                      className={styles.edge}
                    />
                  );
                })}
              </svg>

              <div
                className={styles.rootNode}
                style={{
                  left: graph.rootX,
                  top: graph.rootY,
                  transform: 'translate(-50%, -50%)',
                }}
                aria-label={`현재 논문 ${tree.rootPaperId}`}
              >
                <span className={styles.rootBadge}>현재 논문</span>
                <strong>{tree.rootPaperId}</strong>
              </div>

              {graph.nodes.map((item) => (
                <GraphNodeCard
                  key={item.node.nodeId}
                  node={item.node}
                  x={item.x}
                  y={item.y}
                  depth={item.depth}
                  expanded={Boolean(expandedById[item.node.nodeId])}
                  expanding={expandingId === item.node.nodeId}
                  saved={savedIds.has(item.node.nodeId)}
                  saving={savingId === item.node.nodeId}
                  onExpand={onExpand}
                  onSave={onSave}
                />
              ))}
            </div>
          </div>
        </div>
      </div>
      <label className={styles.horizontalScroller}>
        <span>좌우 이동</span>
        <input
          aria-label="그래프 좌우 이동"
          type="range"
          min={0}
          max={horizontalMax}
          value={Math.min(horizontalScroll.left, horizontalMax)}
          disabled={horizontalScroll.max <= 0}
          onChange={(event) => moveHorizontal(Number(event.currentTarget.value))}
        />
      </label>
    </div>
  );
}

function layoutGraph(
  tree: CitationTreeResponse,
  expandedById: Record<string, CitationTreeResponse>,
): GraphLayout {
  const depth1 = tree.nodes;
  const depth2 = depth1.flatMap((parent) =>
    (expandedById[parent.nodeId]?.nodes ?? []).map((node) => ({ node, parentId: parent.nodeId })),
  );
  const rowCount = Math.max(depth1.length, depth2.length, 1);
  const width = Math.max(MIN_GRAPH_WIDTH, GRAPH_PADDING_X * 2 + (rowCount - 1) * COLUMN_GAP);
  const rootX = width / 2;

  const spread = <T,>(items: T[], y: number, toNode: (item: T) => CitationNode, toParent: (item: T) => string) =>
    items.map((item, index) => ({
      node: toNode(item),
      parentId: toParent(item),
      x: items.length === 1 ? rootX : GRAPH_PADDING_X + index * ((width - GRAPH_PADDING_X * 2) / (items.length - 1)),
      y,
      depth: y === DEPTH_1_Y ? 1 : 2,
    }));

  return {
    width,
    height: (depth2.length > 0 ? DEPTH_2_Y : depth1.length > 0 ? DEPTH_1_Y : ROOT_Y) + GRAPH_PADDING_BOTTOM,
    rootX,
    rootY: ROOT_Y,
    nodes: [
      ...spread(depth1, DEPTH_1_Y, (node) => node, () => tree.rootPaperId),
      ...spread(depth2, DEPTH_2_Y, (item) => item.node, (item) => item.parentId),
    ],
  };
}

function GraphNodeCard({
  node,
  x,
  y,
  depth,
  expanded,
  expanding,
  saved,
  saving,
  onExpand,
  onSave,
}: {
  node: CitationNode;
  x: number;
  y: number;
  depth: number;
  expanded: boolean;
  expanding: boolean;
  saved: boolean;
  saving: boolean;
  onExpand: (nodeId: string) => void;
  onSave: (node: CitationNode) => void;
}) {
  const year = node.year ? String(node.year) : '연도 미상';
  const citations = typeof node.citationCount === 'number' ? `${node.citationCount.toLocaleString()}회 인용` : '인용수 미상';
  const canExpand = depth < 2;
  const link = citationLink(node);

  return (
    <article
      className={styles.graphNode}
      aria-label={node.title}
      style={{
        left: x,
        top: y,
        transform: 'translate(-50%, -50%)',
      }}
    >
      <p className={styles.nodeTitle}>{node.title}</p>
      <div className={styles.nodeMeta}>
        <span>{year}</span>
        <span>{citations}</span>
        {node.alreadyShown ? <span>이미 표시됨</span> : null}
      </div>
      <div className={styles.nodeActions}>
        {canExpand ? (
          <button
            type="button"
            className={styles.button}
            onClick={() => onExpand(node.nodeId)}
            disabled={expanding}
            data-testid={`citation-expand-${node.nodeId}`}
          >
            {expanding ? '확장 중' : expanded ? '축소' : '확장'}
          </button>
        ) : null}
        {link ? (
          <a
            className={`${styles.button} ${styles.nodeLink}`}
            href={link.href}
            target={link.external ? '_blank' : undefined}
            rel={link.external ? 'noopener noreferrer' : undefined}
          >
            열기
          </a>
        ) : null}
        <button
          type="button"
          className={styles.button}
          onClick={() => onSave(node)}
          disabled={!node.saveable || saving || saved}
          data-testid={`citation-save-${node.nodeId}`}
        >
          {saved ? '저장됨' : saving ? '저장 중' : node.saveable ? '저장' : '저장 불가'}
        </button>
      </div>
    </article>
  );
}

function citationLink(node: CitationNode): { href: string; external: boolean } | null {
  const href = node.arxivId ? `https://arxiv.org/abs/${encodeURIComponent(node.arxivId)}` : node.url;
  if (!href || !/^https?:\/\//i.test(href)) return null;
  return { href, external: true };
}
