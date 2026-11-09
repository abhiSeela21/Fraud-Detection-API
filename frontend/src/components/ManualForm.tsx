import { useEffect, useRef, useState } from 'react';
import { X } from 'lucide-react';
import type { Transaction } from '../api/client';

interface Props {
  busy: boolean;
  onSubmit: (transaction: Transaction) => Promise<boolean>;
  onClose: () => void;
}
const locations = {
  Chicago: { country: 'US', latitude: 41.8781, longitude: -87.6298 },
  'New York': { country: 'US', latitude: 40.7128, longitude: -74.006 },
  London: { country: 'GB', latitude: 51.5074, longitude: -0.1278 },
};

export function ManualForm({ busy, onSubmit, onClose }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const attempt = useRef<{ fingerprint: string; transaction: Transaction } | null>(null);
  const [draft, setDraft] = useState({
    amount: '85.00',
    account: 'syn_manual_1',
    category: 'groceries',
    channel: 'in_person',
    city: 'Chicago',
    time: '2026-01-01T12:00',
  });
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  function change(key: keyof typeof draft, value: string) {
    setDraft((previous) => ({ ...previous, [key]: value }));
    attempt.current = null;
    setFailed(false);
  }
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const fingerprint = JSON.stringify(draft);
    if (attempt.current?.fingerprint !== fingerprint) {
      attempt.current = {
        fingerprint,
        transaction: {
          client_transaction_id: crypto.randomUUID(),
          account_id: draft.account,
          run_id: null,
          amount: draft.amount,
          currency: 'USD',
          timestamp: new Date(`${draft.time}Z`).toISOString(),
          merchant_category: draft.category as Transaction['merchant_category'],
          channel: draft.channel as Transaction['channel'],
          location: locations[draft.city as keyof typeof locations],
        },
      };
    }
    const ok = await onSubmit(attempt.current.transaction);
    if (ok) onClose();
    else setFailed(true);
  }
  return (
    <dialog
      ref={dialog}
      className="modal manual-modal"
      aria-labelledby="manual-title"
      onCancel={(event) => {
        if (busy) event.preventDefault();
      }}
      onClose={onClose}
    >
      <div className="panel-top">
        <span className="eyebrow">TRY THE SCORING API</span>
        <button
          className="icon-button"
          disabled={busy}
          aria-label="Close manual transaction"
          onClick={onClose}
        >
          <X size={19} />
        </button>
      </div>
      <h2 id="manual-title">Submit a synthetic transaction</h2>
      <p className="muted">
        Use the same scoring flow as the live feed. No payment credentials are collected.
      </p>
      <form onSubmit={(event) => void submit(event)}>
        <fieldset disabled={busy}>
          <div className="form-grid">
            <label>
              Amount (USD)
              <input
                type="number"
                min="0.01"
                max="100000"
                step="0.01"
                required
                value={draft.amount}
                onChange={(event) => change('amount', event.target.value)}
              />
            </label>
            <label>
              Synthetic account
              <select
                value={draft.account}
                onChange={(event) => change('account', event.target.value)}
              >
                {[1, 2, 3].map((number) => (
                  <option value={`syn_manual_${number}`} key={number}>
                    Manual account 0{number}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Merchant category
              <select
                value={draft.category}
                onChange={(event) => change('category', event.target.value)}
              >
                {[
                  'groceries',
                  'dining',
                  'transport',
                  'hotel',
                  'airfare',
                  'software',
                  'equipment',
                  'entertainment',
                ].map((value) => (
                  <option key={value} value={value}>
                    {value[0].toUpperCase() + value.slice(1)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Channel
              <select
                value={draft.channel}
                onChange={(event) => change('channel', event.target.value)}
              >
                <option value="in_person">In person</option>
                <option value="online">Online</option>
              </select>
            </label>
            <label>
              Location
              <select value={draft.city} onChange={(event) => change('city', event.target.value)}>
                {Object.keys(locations).map((value) => (
                  <option key={value}>{value}</option>
                ))}
              </select>
            </label>
            <label>
              Event time (UTC)
              <input
                type="datetime-local"
                required
                min="2020-01-01T00:00"
                max="2100-12-31T23:59"
                value={draft.time}
                onChange={(event) => change('time', event.target.value)}
              />
            </label>
          </div>
        </fieldset>
        {failed && (
          <p className="field-error" role="alert">
            Transaction was not confirmed. Retry unchanged to reuse its transaction ID, or close
            this form to check the workspace error.
          </p>
        )}
        <div className="modal-footer">
          <span className="helper">Submitting pauses an active feed.</span>
          <button className="button primary" disabled={busy} type="submit">
            {busy ? 'Scoring…' : failed ? 'Retry transaction' : 'Score transaction'}
          </button>
        </div>
      </form>
    </dialog>
  );
}
