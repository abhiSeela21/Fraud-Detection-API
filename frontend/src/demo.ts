import { ApiFailure, delay, HttpApi } from './api/client';
import type { DemoApi, Item, Label, Transaction } from './api/client';

export interface RunConfig {
  profile: 'commuter' | 'traveler' | 'business';
  scenario: 'normal' | 'burst' | 'travel' | 'amount' | 'category_channel' | 'mixed';
  seed: number;
  count: number;
  paceMs: number;
}
export const DEFAULT_CONFIG: RunConfig = {
  profile: 'commuter',
  scenario: 'mixed',
  seed: 42,
  count: 40,
  paceMs: 1000,
};
export const GUIDED_CONFIG: RunConfig = { ...DEFAULT_CONFIG, count: 20, paceMs: 500 };
export interface DemoState {
  connection: 'idle' | 'waking' | 'ready' | 'offline';
  run: 'idle' | 'running' | 'paused' | 'stopped' | 'complete';
  items: Item[];
  progress: number;
  total: number;
  runId: string | null;
  error: string | null;
  notice: string | null;
  expired: boolean;
  retryAt: number;
  wakingSince: number;
  lastLatency: number | null;
  manualBusy: boolean;
  savingAlert: string | null;
}

export class DemoController {
  private state: DemoState = {
    connection: 'idle',
    run: 'idle',
    items: [],
    progress: 0,
    total: 0,
    runId: null,
    error: null,
    notice: null,
    expired: false,
    retryAt: 0,
    wakingSince: 0,
    lastLatency: null,
    manualBusy: false,
    savingAlert: null,
  };
  private listeners = new Set<() => void>();
  private revision = 0;
  private operation = new AbortController();
  private feedbackOperation = new AbortController();
  private hasSession = false;
  private pending: { config: RunConfig; id: string; index: number; queue: Transaction[] } | null =
    null;

  constructor(private api: DemoApi = new HttpApi()) {}
  snapshot = (): DemoState => this.state;
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };
  private write(patch: Partial<DemoState>) {
    this.state = { ...this.state, ...patch };
    this.listeners.forEach((listener) => listener());
  }
  private begin(): number {
    this.operation.abort();
    this.operation = new AbortController();
    return ++this.revision;
  }
  private current(ticket: number) {
    return ticket === this.revision && !this.operation.signal.aborted;
  }

  private async connect(signal: AbortSignal) {
    if (this.state.connection !== 'ready') {
      this.write({ connection: 'waking', wakingSince: Date.now(), error: null });
      await this.api.ready(signal);
      if (signal.aborted) throw new DOMException('Cancelled', 'AbortError');
      this.write({ connection: 'ready' });
    }
    if (!this.hasSession) {
      await this.api.session(signal);
      this.hasSession = true;
    }
  }

  async hydrate(): Promise<void> {
    const ticket = this.begin();
    const signal = this.operation.signal;
    this.write({ connection: 'waking', wakingSince: Date.now(), error: null });
    try {
      await this.api.ready(signal);
      if (!this.current(ticket)) return;
      this.write({ connection: 'ready' });
      const items: Item[] = [];
      let cursor: string | null = null;
      do {
        const page = await this.api.history(cursor, signal);
        items.push(...page.items);
        cursor = page.next_cursor ?? null;
      } while (cursor && items.length < 500);
      if (!this.current(ticket)) return;
      this.hasSession = true;
      this.write({
        items: items.reverse(),
        notice: items.length
          ? 'Your temporary session was restored. Start a new run to keep exploring.'
          : null,
      });
    } catch (error) {
      if (!this.current(ticket)) return;
      if (error instanceof ApiFailure && error.status === 401) {
        const hadSession = this.hasSession || this.state.items.length > 0;
        this.hasSession = false;
        if (hadSession) this.fail(error);
        return;
      }
      this.fail(error);
    }
  }

  async start(config: RunConfig): Promise<void> {
    if (
      this.state.run === 'running' ||
      this.state.run === 'paused' ||
      this.state.manualBusy ||
      this.state.expired
    )
      return;
    if (
      !Number.isInteger(config.seed) ||
      config.seed < 0 ||
      config.seed > 4294967295 ||
      !Number.isInteger(config.count) ||
      config.count < 1 ||
      config.count > 200 ||
      config.paceMs < 0
    ) {
      this.write({ error: 'Choose a valid seed and a run of 1–200 transactions.' });
      return;
    }
    if (this.state.items.length + config.count > 500) {
      this.write({
        error:
          'This run would exceed the 500-transaction demo session limit. Start a fresh session first.',
      });
      return;
    }
    const id = crypto.randomUUID();
    this.pending = { config: { ...config }, id, index: 0, queue: [] };
    this.write({
      run: 'running',
      runId: id,
      progress: 0,
      total: config.count,
      error: null,
      notice: null,
    });
    await this.feed();
  }

  private async feed(): Promise<void> {
    const ticket = this.begin();
    const signal = this.operation.signal;
    try {
      await this.connect(signal);
      while (this.pending && this.current(ticket)) {
        const run = this.pending;
        if (run.index >= run.config.count) {
          this.write({
            run: 'complete',
            notice: 'Run complete. Inspect a transaction or try a new scenario.',
          });
          return;
        }
        if (!run.queue.length) {
          run.queue = await this.api.batch(
            {
              run_id: run.id,
              seed: run.config.seed,
              profile: run.config.profile,
              scenario: run.config.scenario,
              start_time: '2026-01-01T00:00:00Z',
              offset: run.index,
              count: Math.min(10, run.config.count - run.index),
            },
            signal,
          );
          if (!run.queue.length)
            throw new ApiFailure(
              0,
              'EMPTY_BATCH',
              'The API returned an empty simulation batch. Retry this run.',
            );
        }
        if (!this.current(ticket)) return;
        const transaction = run.queue[0];
        const started = performance.now();
        const score = await this.api.score(transaction, signal);
        if (!this.current(ticket)) return;
        run.queue.shift();
        run.index++;
        const item: Item = { transaction, score, feedback: null };
        this.write({
          items: [
            ...this.state.items.filter((row) => row.score.transaction_id !== score.transaction_id),
            item,
          ],
          progress: run.index,
          lastLatency: performance.now() - started,
        });
        if (run.index < run.config.count) await delay(run.config.paceMs, signal);
      }
    } catch (error) {
      if (this.current(ticket)) this.fail(error);
    }
  }

  pause(reason = 'Feed paused. Your run is ready to resume.'): void {
    if (this.state.run !== 'running') return;
    this.begin();
    this.write({
      run: 'paused',
      notice: reason,
      connection: this.state.connection === 'waking' ? 'idle' : this.state.connection,
    });
  }
  async resume(): Promise<void> {
    if (
      !this.pending ||
      this.state.run !== 'paused' ||
      Date.now() < this.state.retryAt ||
      this.state.manualBusy ||
      this.state.expired
    )
      return;
    this.write({ run: 'running', error: null, notice: null });
    await this.feed();
  }
  stop(): void {
    this.begin();
    this.pending = null;
    this.write({
      run: 'stopped',
      manualBusy: false,
      connection: this.state.connection === 'waking' ? 'idle' : this.state.connection,
      notice: 'Run stopped. Its transactions are still available for review.',
    });
  }
  resetSession(): void {
    this.begin();
    this.feedbackOperation.abort();
    this.feedbackOperation = new AbortController();
    this.pending = null;
    this.hasSession = false;
    this.write({
      run: 'idle',
      connection: this.state.connection === 'waking' ? 'idle' : this.state.connection,
      items: [],
      progress: 0,
      total: 0,
      runId: null,
      expired: false,
      retryAt: 0,
      error: null,
      notice: 'A fresh session will be created with your next request.',
      manualBusy: false,
      savingAlert: null,
    });
  }
  clearError(): void {
    this.write({ error: null });
  }

  async scoreManual(transaction: Transaction): Promise<boolean> {
    if (this.state.manualBusy || this.state.expired || Date.now() < this.state.retryAt)
      return false;
    this.pause('Feed paused for a manual transaction.');
    const ticket = this.begin();
    const signal = this.operation.signal;
    this.write({ manualBusy: true, error: null });
    try {
      await this.connect(signal);
      const started = performance.now();
      const score = await this.api.score(transaction, signal);
      if (!this.current(ticket)) return false;
      this.write({
        items: [
          ...this.state.items.filter((row) => row.score.transaction_id !== score.transaction_id),
          { transaction, score, feedback: null },
        ],
        lastLatency: performance.now() - started,
        manualBusy: false,
        notice: 'Manual transaction scored by the API.',
      });
      return true;
    } catch (error) {
      if (this.current(ticket)) this.fail(error);
      return false;
    }
  }

  async label(item: Item, label: Label): Promise<boolean> {
    const id = item.score.alert_id;
    if (!id || this.state.savingAlert) return false;
    this.feedbackOperation = new AbortController();
    this.write({ savingAlert: id, error: null });
    const signal = this.feedbackOperation.signal;
    try {
      await this.api.feedback(id, label, signal);
      if (signal.aborted) return false;
      this.write({
        savingAlert: null,
        items: this.state.items.map((row) =>
          row.score.alert_id === id ? { ...row, feedback: label } : row,
        ),
        notice: `Reviewer label saved: ${label}. You can change it anytime during this session.`,
      });
      return true;
    } catch (error) {
      if (!signal.aborted) {
        this.write({ savingAlert: null });
        this.fail(error, false);
      }
      return false;
    }
  }

  private fail(error: unknown, pause = true): void {
    if (error instanceof DOMException && error.name === 'AbortError') return;
    const failure =
      error instanceof ApiFailure
        ? error
        : new ApiFailure(0, 'UNKNOWN', 'Something went wrong. Please retry.');
    const expired = failure.status === 401;
    if (expired) this.hasSession = false;
    this.write({
      error: expired
        ? 'Your temporary session expired. Start a fresh session to continue.'
        : failure.message,
      expired,
      retryAt:
        failure.status === 429 ? Date.now() + Math.max(1, failure.retryAfter || 60) * 1000 : 0,
      run: pause && this.state.run === 'running' ? 'paused' : this.state.run,
      connection: this.state.connection === 'waking' ? 'offline' : this.state.connection,
      manualBusy: false,
    });
  }
  dispose(): void {
    this.begin();
    this.feedbackOperation.abort();
    this.listeners.clear();
    this.state = {
      ...this.state,
      savingAlert: null,
      manualBusy: false,
      run: this.state.run === 'running' ? 'paused' : this.state.run,
      connection: this.state.connection === 'waking' ? 'idle' : this.state.connection,
    };
  }
}
