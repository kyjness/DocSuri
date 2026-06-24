import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CitationTreePanel } from '@/components/CitationTreePanel';

describe('CitationTreePanel', () => {
  it('loads the citation tree, expands a node, and saves a saveable citation', async () => {
    const user = userEvent.setup();
    render(<CitationTreePanel paperId="2101.00001" />);

    expect(await screen.findByTestId('citation-tree-panel')).toBeInTheDocument();
    expect(screen.getByRole('dialog', { name: '각주 트리' })).toBeInTheDocument();
    expect(await screen.findByText('Attention Is All You Need')).toBeInTheDocument();
    expect(screen.getByTestId('citation-graph')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '확대' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '축소' })).toBeInTheDocument();
    expect(screen.getByLabelText('그래프 좌우 이동')).toBeInTheDocument();
    expect(screen.getByText(/OpenReview workshop record/)).toBeInTheDocument();

    const links = screen.getAllByRole('link', { name: '열기' });
    expect(links[0]).toHaveAttribute('href', 'https://arxiv.org/abs/1706.03762');
    expect(links[0]).toHaveAttribute('target', '_blank');
    expect(links[0]).toHaveAttribute('rel', 'noopener noreferrer');
    expect(links[1]).toHaveAttribute('href', 'https://doi.org/10.5555/3295222.3295349');
    expect(links[1]).toHaveAttribute('target', '_blank');
    expect(links[1]).toHaveAttribute('rel', 'noopener noreferrer');

    const zoomOut = screen.getByRole('button', { name: '축소' });
    await user.click(zoomOut);
    await user.click(zoomOut);
    await user.click(zoomOut);
    expect(screen.getByText('25%')).toBeInTheDocument();
    expect(zoomOut).toBeDisabled();

    const parentExpand = screen.getByTestId('citation-expand-1706.03762');
    await user.click(parentExpand);
    expect(
      await screen.findByText(
        'Neural Machine Translation by Jointly Learning to Align and Translate',
      ),
    ).toBeInTheDocument();
    expect(screen.queryByTestId('citation-expand-1409.0473')).not.toBeInTheDocument();
    expect(parentExpand).toHaveTextContent('축소');

    await user.click(parentExpand);
    expect(
      screen.queryByText('Neural Machine Translation by Jointly Learning to Align and Translate'),
    ).not.toBeInTheDocument();
    expect(parentExpand).toHaveTextContent('확장');

    await user.click(parentExpand);
    expect(
      await screen.findByText(
        'Neural Machine Translation by Jointly Learning to Align and Translate',
      ),
    ).toBeInTheDocument();

    await user.click(screen.getByTestId('citation-expand-doi:10.5555/3295222.3295349'));
    expect(
      await screen.findByText('Batch Normalization: Accelerating Deep Network Training'),
    ).toBeInTheDocument();
    expect(
      screen.queryByText('Neural Machine Translation by Jointly Learning to Align and Translate'),
    ).not.toBeInTheDocument();

    await user.click(screen.getByTestId('citation-save-1706.03762'));
    expect(await screen.findByText('저장됨')).toBeInTheDocument();
  });

  it('uses the latest onClose handler for Escape without remounting the modal effect', async () => {
    const user = userEvent.setup();
    const firstClose = vi.fn();
    const secondClose = vi.fn();
    const { rerender } = render(<CitationTreePanel paperId="2101.00001" onClose={firstClose} />);

    expect(await screen.findByTestId('citation-tree-panel')).toBeInTheDocument();
    await waitFor(() => expect(document.body.style.overflow).toBe('hidden'));

    rerender(<CitationTreePanel paperId="2101.00001" onClose={secondClose} />);
    await user.keyboard('{Escape}');

    expect(firstClose).not.toHaveBeenCalled();
    expect(secondClose).toHaveBeenCalledTimes(1);
  });
});
