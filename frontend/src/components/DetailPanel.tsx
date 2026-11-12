import { ArrowUpRight, Check, Flag, ShieldCheck, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import type { Item, Label } from '../api/client';
import { eventTime, locationName, money, shortId, title } from '../format';

interface Props {
  item: Item | null;
  saving: boolean;
  expired: boolean;
  onClose: () => void;
  onLabel: (item: Item, label: Label) => Promise<boolean>;
}

export function DetailPanel({ item, saving, expired, onClose, onLabel }: Props) {
  const heading = useRef<HTMLHeadingElement>(null);
  const reviewHeading = useRef<HTMLHeadingElement>(null);
  const [failed, setFailed] = useState(false);
  const transactionId = item?.score.transaction_id;
  useEffect(() => {
    if (!transactionId || !heading.current) return;
    const panel = heading.current.closest('aside');
    if (panel && !panel.closest('dialog')) panel.scrollIntoView({ block: 'start' });
    heading.current.focus({ preventScroll: true });
  }, [transactionId]);
  if (!item)
    return (
      <aside className="detail-panel detail-empty" aria-label="Transaction details">
        <div className="empty-symbol">
          <ArrowUpRight size={22} />
        </div>
        <h2>Follow a transaction</h2>
        <p>Select a row to see its score, historical context, and review signals.</p>
        <div className="detail-empty-note">
          <span className="small-dot" /> Every score comes from the API
        </div>
      </aside>
    );
  const { score, transaction } = item;
  async function save(label: Label) {
    setFailed(false);
    const ok = await onLabel(item!, label);
    setFailed(!ok);
  }
  return (
    <aside className="detail-panel" aria-label="Transaction details">
      <div className="panel-top">
        <span className="eyebrow">TRANSACTION DETAILS</span>
        <button className="icon-button" aria-label="Close transaction details" onClick={onClose}>
          <X size={18} />
        </button>
      </div>
      <h2 ref={heading} tabIndex={-1}>
        Transaction <span className="mono">{shortId(item)}</span>
      </h2>
      <p className="muted detail-subtitle">
        {eventTime(transaction.timestamp)} UTC · {title(transaction.channel)}
      </p>
      <div className={`risk-summary ${score.recommendation}`}>
        <div>
          <span className="eyebrow">RISK INDEX</span>
          <div className="risk-number">
            {score.risk_score}
            <span>/ 100</span>
          </div>
        </div>
        <span className={`badge ${score.recommendation}`}>
          {score.recommendation === 'review' ? <Flag size={13} /> : <ShieldCheck size={13} />}
          {title(score.recommendation)}
        </span>
      </div>
      {score.alert_id && (
        <button
          className="text-button review-shortcut"
          onClick={() => {
            const review = reviewHeading.current;
            review?.closest('section')?.scrollIntoView({ block: 'nearest' });
            review?.focus({ preventScroll: true });
          }}
        >
          Jump to review <ArrowUpRight size={14} />
        </button>
      )}
      <dl className="transaction-facts">
        <div>
          <dt>Amount</dt>
          <dd>{money(transaction.amount)}</dd>
        </div>
        <div>
          <dt>Account</dt>
          <dd className="mono">{transaction.account_id}</dd>
        </div>
        <div>
          <dt>Category</dt>
          <dd>{title(transaction.merchant_category)}</dd>
        </div>
        <div>
          <dt>Location</dt>
          <dd>{locationName(transaction)}</dd>
        </div>
      </dl>
      <section className="detail-section">
        <h3>How the score is assembled</h3>
        <div className="score-components">
          <div>
            <span>Model probability</span>
            <strong>{(score.model_probability * 100).toFixed(1)}%</strong>
          </div>
          <div>
            <span>Rules adjustment</span>
            <strong>+{score.rule_adjustment} points</strong>
          </div>
          <div>
            <span>Review threshold</span>
            <strong>{score.review_threshold} / 100</strong>
          </div>
        </div>
        <p className="helper">
          Rounded model contribution + rules adjustment, capped at 100. The risk index is not a
          probability.
        </p>
      </section>
      <section className="detail-section">
        <h3>
          Rule signals <span className="count-tag">{score.rule_signals.length}</span>
        </h3>
        {score.rule_signals.length ? (
          <ul className="signals">
            {score.rule_signals.map((signal) => (
              <li key={signal.code}>
                <div>
                  <span className={`signal-dot ${signal.adjustment ? 'warning' : ''}`} />
                  <strong>{title(signal.code.toLowerCase())}</strong>
                  <span className="signal-points">
                    {signal.adjustment ? `+${signal.adjustment}` : 'Info'}
                  </span>
                </div>
                <p>{signal.message}</p>
              </li>
            ))}
          </ul>
        ) : (
          <p className="quiet-box">
            <Check size={15} /> No rules triggered for this event.
          </p>
        )}
        <p className="helper">
          Rule adjustments are capped at 40 points in total. These signals describe the rules, not
          the classifier’s reasoning.
        </p>
      </section>
      <section className="detail-section">
        <h3>Earlier account activity</h3>
        <dl className="context-grid">
          <div>
            <dt>Prior transactions</dt>
            <dd>{score.features.history_count}</dd>
          </div>
          <div>
            <dt>Amount vs. average</dt>
            <dd>
              {score.features.history_count
                ? `${score.features.amount_ratio.toFixed(1)}×`
                : 'No baseline'}
            </dd>
          </div>
          <div>
            <dt>Events in prior 5 min</dt>
            <dd>{score.features.transactions_last_5m}</dd>
          </div>
          <div>
            <dt>Physical distance</dt>
            <dd>{Math.round(score.features.distance_from_previous_km).toLocaleString()} km</dd>
          </div>
        </dl>
        <p className="helper">
          History excludes this event and all later events. Model probabilities are learned and
          calibrated on synthetic data.
        </p>
      </section>
      {score.alert_id && (
        <section className="detail-section feedback-section">
          <h3 ref={reviewHeading} tabIndex={-1}>
            Make a simulated review
          </h3>
          <p>How would you label this alert?</p>
          <div className="feedback-actions">
            <button
              className="button"
              aria-pressed={item.feedback === 'fraud'}
              disabled={saving || expired}
              onClick={() => void save('fraud')}
            >
              <Flag size={15} /> Fraud
            </button>
            <button
              className="button"
              aria-pressed={item.feedback === 'legitimate'}
              disabled={saving || expired}
              onClick={() => void save('legitimate')}
            >
              <ShieldCheck size={15} /> Legitimate
            </button>
          </div>
          <p className="feedback-state" role="status">
            {saving ? (
              'Saving reviewer label…'
            ) : item.feedback ? (
              <>
                <Check size={14} /> Saved: {item.feedback}
              </>
            ) : (
              'Not labeled yet'
            )}
          </p>
          {failed && (
            <p className="field-error" role="alert">
              Label was not saved.{' '}
              {expired ? 'Start a fresh session to continue.' : 'Please try again.'}
            </p>
          )}
          <p className="helper">
            Your label is simulated feedback. It does not retrain the model or change its score.
          </p>
        </section>
      )}
      <details className="version-details">
        <summary>Scoring versions</summary>
        <dl>
          {[
            ['Model', score.model_version],
            ['Features', score.feature_version],
            ['Rules', score.rule_version],
            ['Formula', score.scoring_version],
          ].map(([name, value]) => (
            <div key={name}>
              <dt>{name}</dt>
              <dd className="mono">{value}</dd>
            </div>
          ))}
        </dl>
      </details>
    </aside>
  );
}
