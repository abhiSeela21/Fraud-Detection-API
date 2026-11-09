import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { DetailPanel } from './DetailPanel';
import { scoreFor, transaction } from '../testing';

it('distinguishes model output from rule signals and reports feedback failure', async () => {
  const tx = transaction();
  const item = { transaction: tx, score: scoreFor(tx), feedback: null };
  const save = vi.fn().mockResolvedValue(false);
  render(
    <DetailPanel item={item} saving={false} expired={false} onClose={() => {}} onLabel={save} />,
  );
  expect(screen.getByText('Model probability')).toBeInTheDocument();
  expect(screen.getByText(/not the classifier/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: /^Fraud$/ }));
  expect(screen.getByRole('alert')).toHaveTextContent('Label was not saved');
  expect(screen.getByRole('button', { name: /^Fraud$/ })).toHaveAttribute('aria-pressed', 'false');
});
