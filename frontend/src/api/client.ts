import type { components } from './schema';

export type Transaction = components['schemas']['Transaction-Output'];
export type Score = components['schemas']['ScoreResult'];
export type Item = Pick<
  components['schemas']['TransactionItem'],
  'transaction' | 'score' | 'feedback'
>;
export type Label = 'fraud' | 'legitimate';
export type Batch = components['schemas']['BatchRequest'];
export type Page = components['schemas']['Page'];

export class ApiFailure extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public retryAfter = 0,
  ) {
    super(message);
  }
}

export const apiBase = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '');
export const docsUrl = `${apiBase}/docs`;

export function delay(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new DOMException('Cancelled', 'AbortError'));
      return;
    }
    const finish = () => {
      signal.removeEventListener('abort', cancel);
      resolve();
    };
    const timer = setTimeout(finish, ms);
    const cancel = () => {
      clearTimeout(timer);
      signal.removeEventListener('abort', cancel);
      reject(new DOMException('Cancelled', 'AbortError'));
    };
    signal.addEventListener('abort', cancel, { once: true });
  });
}

export interface DemoApi {
  ready(signal: AbortSignal): Promise<void>;
  session(signal: AbortSignal): Promise<void>;
  history(cursor: string | null, signal: AbortSignal): Promise<Page>;
  batch(body: Batch, signal: AbortSignal): Promise<Transaction[]>;
  score(body: Transaction, signal: AbortSignal): Promise<Score>;
  feedback(id: string, label: Label, signal: AbortSignal): Promise<void>;
}

export class HttpApi implements DemoApi {
  async request<T>(
    path: string,
    signal: AbortSignal,
    body?: unknown,
    method = body === undefined ? 'GET' : 'POST',
    timeout = 8000,
  ): Promise<T> {
    const controller = new AbortController();
    const abort = () => controller.abort();
    if (signal.aborted) throw new DOMException('Cancelled', 'AbortError');
    signal.addEventListener('abort', abort, { once: true });
    const timer = setTimeout(abort, timeout);
    try {
      const response = await fetch(`${apiBase}${path}`, {
        method,
        credentials: 'include',
        cache: 'no-store',
        signal: controller.signal,
        headers:
          body === undefined
            ? { Accept: 'application/json' }
            : { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        throw new ApiFailure(
          response.status,
          data?.error?.code ?? 'API_ERROR',
          data?.error?.message ?? 'The API could not complete that request.',
          Number(response.headers.get('Retry-After')) || 0,
        );
      }
      if (data === null)
        throw new ApiFailure(0, 'INVALID_RESPONSE', 'The API returned an unreadable response.');
      return data as T;
    } catch (error) {
      if (signal.aborted) throw new DOMException('Cancelled', 'AbortError');
      if (error instanceof ApiFailure) throw error;
      throw new ApiFailure(
        0,
        'NETWORK_ERROR',
        'The API could not be reached. Check your connection and retry.',
      );
    } finally {
      clearTimeout(timer);
      signal.removeEventListener('abort', abort);
    }
  }

  async ready(signal: AbortSignal): Promise<void> {
    const deadline = Date.now() + 60000;
    while (Date.now() < deadline) {
      try {
        await this.request(
          '/health',
          signal,
          undefined,
          'GET',
          Math.min(8000, deadline - Date.now()),
        );
        return;
      } catch (error) {
        if (signal.aborted) throw error;
        if (
          error instanceof ApiFailure &&
          error.status !== 0 &&
          error.status !== 503 &&
          error.status !== 502 &&
          error.status !== 504
        )
          throw error;
      }
      await delay(Math.max(0, Math.min(1500, deadline - Date.now())), signal);
    }
    throw new ApiFailure(
      503,
      'API_ASLEEP',
      'The API is still unavailable. Free hosting can take a moment to wake up. Please retry.',
    );
  }

  async session(signal: AbortSignal): Promise<void> {
    await this.request('/v1/sessions', signal, { mode: 'browser' });
  }
  history(cursor: string | null, signal: AbortSignal): Promise<Page> {
    return this.request(
      `/v1/transactions?limit=100${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`,
      signal,
    );
  }
  async batch(body: Batch, signal: AbortSignal): Promise<Transaction[]> {
    const response = await this.request<components['schemas']['BatchResponse']>(
      '/v1/simulations/batch',
      signal,
      body,
    );
    return response.transactions;
  }
  score(body: Transaction, signal: AbortSignal): Promise<Score> {
    return this.request('/v1/transactions/score', signal, body);
  }
  async feedback(id: string, label: Label, signal: AbortSignal): Promise<void> {
    await this.request(`/v1/alerts/${encodeURIComponent(id)}/feedback`, signal, { label }, 'PATCH');
  }
}
