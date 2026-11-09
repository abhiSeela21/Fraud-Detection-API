import { afterEach, expect, it, vi } from 'vitest';
import { ApiFailure, HttpApi } from './client';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
it('uses browser cookies without returning a bearer token to application state', async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValue(
      new Response(JSON.stringify({ expires_at: '2026-01-02T00:00:00Z' }), { status: 201 }),
    );
  vi.stubGlobal('fetch', fetcher);
  expect(await new HttpApi().session(new AbortController().signal)).toBeUndefined();
  expect(fetcher.mock.calls[0][1].credentials).toBe('include');
  expect(fetcher.mock.calls[0][1].headers.Authorization).toBeUndefined();
  expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({ mode: 'browser' });
});
it('retains rate-limit details for visible retry handling', async () => {
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValue(
        new Response(
          JSON.stringify({ error: { code: 'RATE_LIMITED', message: 'Wait before retrying' } }),
          { status: 429, headers: { 'Retry-After': '15' } },
        ),
      ),
  );
  await expect(
    new HttpApi().request('/v1/transactions', new AbortController().signal),
  ).rejects.toMatchObject({ status: 429, code: 'RATE_LIMITED', retryAfter: 15 });
});
it('retries waking health checks and cancels waiting when the page leaves', async () => {
  vi.useFakeTimers();
  const fetcher = vi.fn().mockResolvedValue(new Response('{}', { status: 503 }));
  vi.stubGlobal('fetch', fetcher);
  const abort = new AbortController();
  const ready = new HttpApi().ready(abort.signal);
  const rejection = expect(ready).rejects.toMatchObject({ name: 'AbortError' });
  await vi.advanceTimersByTimeAsync(0);
  abort.abort();
  await rejection;
  await vi.advanceTimersByTimeAsync(10000);
  expect(fetcher).toHaveBeenCalledTimes(1);
});
it('does not show gateway HTML as a user error message', async () => {
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValue(new Response('<html>internal gateway details</html>', { status: 502 })),
  );
  try {
    await new HttpApi().request('/health', new AbortController().signal);
  } catch (error) {
    expect(error).toBeInstanceOf(ApiFailure);
    expect((error as Error).message).not.toContain('internal gateway details');
  }
});
