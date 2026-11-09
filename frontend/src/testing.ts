import { ApiFailure, delay } from './api/client';
import type { Batch, DemoApi, Item, Label, Page, Score, Transaction } from './api/client';

export function transaction(index = 0, runId = 'test-run'): Transaction {
  return {
    client_transaction_id: `${runId}-${index}`,
    account_id: 'syn_test',
    run_id: runId,
    amount: '85.00',
    currency: 'USD',
    timestamp: '2026-01-01T12:00:00Z',
    merchant_category: 'groceries',
    channel: 'in_person',
    location: { country: 'US', latitude: 41.8781, longitude: -87.6298 },
  };
}
export function scoreFor(tx: Transaction, review = true): Score {
  return {
    transaction_id: `result-${tx.client_transaction_id}`,
    client_transaction_id: tx.client_transaction_id,
    risk_score: review ? 65 : 10,
    recommendation: review ? 'review' : 'clear',
    rule_signals: [{ code: 'LIMITED_HISTORY', message: 'Limited prior activity.', adjustment: 0 }],
    rule_score: 0,
    rule_adjustment: 0,
    model_probability: review ? 0.65 : 0.1,
    review_threshold: 38,
    model_version: 'test-model',
    feature_version: 'features-v2',
    rule_version: 'rules-v1',
    scoring_version: 'combined-v1',
    alert_id: review ? `alert-${tx.client_transaction_id}` : null,
    features: {
      history_count: 0,
      amount_ratio: 1,
      transactions_last_5m: 0,
      distance_from_previous_km: 0,
      travel_speed_kmh: 0,
      unusual_category: false,
      unusual_channel: false,
      amount_to_median: 1,
      category_frequency: 0,
      channel_frequency: 0,
      seconds_since_previous: 0,
    },
  };
}

export class FakeApi implements DemoApi {
  sessions = 0;
  scoreCalls: Transaction[] = [];
  stored = new Map<string, Item>();
  lostResponse = false;
  failFeedback = false;
  scoreDelay = 0;
  async ready(): Promise<void> {}
  async session(): Promise<void> {
    this.sessions++;
  }
  async history(): Promise<Page> {
    if (!this.sessions) throw new ApiFailure(401, 'SESSION_REQUIRED', 'No session');
    return {
      items: [...this.stored.values()]
        .reverse()
        .map((item) => ({ ...item, received_at: '2026-01-01T12:00:00Z' })),
      next_cursor: null,
    };
  }
  async batch(body: Batch): Promise<Transaction[]> {
    return Array.from({ length: body.count }, (_, index) =>
      transaction(body.offset + index, body.run_id),
    );
  }
  async score(tx: Transaction, signal: AbortSignal): Promise<Score> {
    this.scoreCalls.push(tx);
    if (this.scoreDelay) await delay(this.scoreDelay, signal);
    if (!this.stored.has(tx.client_transaction_id))
      this.stored.set(tx.client_transaction_id, {
        transaction: tx,
        score: scoreFor(tx),
        feedback: null,
      });
    if (this.lostResponse) {
      this.lostResponse = false;
      throw new ApiFailure(0, 'NETWORK_ERROR', 'Response lost');
    }
    return this.stored.get(tx.client_transaction_id)!.score;
  }
  async feedback(id: string, label: Label): Promise<void> {
    if (this.failFeedback) throw new ApiFailure(503, 'UNAVAILABLE', 'Feedback could not be saved');
    for (const item of this.stored.values()) if (item.score.alert_id === id) item.feedback = label;
  }
}
