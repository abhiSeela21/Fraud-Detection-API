import { afterEach, describe, expect, it, vi } from 'vitest';
import { DEFAULT_CONFIG, DemoController } from './demo';
import { FakeApi } from './testing';
import { ApiFailure } from './api/client';

afterEach(() => vi.useRealTimers());
describe('simulation lifecycle', () => {
  it('can restore and save feedback after an effect cleanup/remount', async () => {
    const api = new FakeApi();
    const demo = new DemoController(api);
    await demo.start({ ...DEFAULT_CONFIG, count: 1, paceMs: 0 });
    demo.dispose();
    await demo.hydrate();
    expect(await demo.label(demo.snapshot().items[0], 'fraud')).toBe(true);
    expect(demo.snapshot().savingAlert).toBeNull();
    expect(demo.snapshot().items[0].feedback).toBe('fraud');
    demo.dispose();
  });
  it('waits for Retry-After before retrying the same transaction', async () => {
    vi.useFakeTimers();
    const api = new FakeApi();
    const demo = new DemoController(api);
    const spy = vi
      .spyOn(api, 'score')
      .mockRejectedValueOnce(new ApiFailure(429, 'RATE_LIMITED', 'Wait', 15));
    await demo.start({ ...DEFAULT_CONFIG, count: 1, paceMs: 0 });
    await demo.resume();
    expect(spy).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(15000);
    await demo.resume();
    expect(spy).toHaveBeenCalledTimes(2);
    expect(spy.mock.calls[0][0]).toEqual(spy.mock.calls[1][0]);
    expect(demo.snapshot().run).toBe('complete');
    demo.dispose();
  });

  it('requires an explicit fresh session after expiry', async () => {
    const api = new FakeApi();
    const demo = new DemoController(api);
    const spy = vi
      .spyOn(api, 'score')
      .mockRejectedValueOnce(new ApiFailure(401, 'SESSION_EXPIRED', 'Expired'));
    await demo.start({ ...DEFAULT_CONFIG, count: 1, paceMs: 0 });
    expect(demo.snapshot().expired).toBe(true);
    await demo.resume();
    expect(spy).toHaveBeenCalledTimes(1);
    demo.resetSession();
    await demo.start({ ...DEFAULT_CONFIG, count: 1, paceMs: 0 });
    expect(api.sessions).toBe(2);
    expect(demo.snapshot().run).toBe('complete');
    demo.dispose();
  });
  it('reuses an unconfirmed transaction after a lost response', async () => {
    const api = new FakeApi();
    api.lostResponse = true;
    const demo = new DemoController(api);
    await demo.start({ ...DEFAULT_CONFIG, count: 3, paceMs: 0 });
    expect(demo.snapshot().run).toBe('paused');
    expect(demo.snapshot().items).toHaveLength(0);
    await demo.resume();
    expect(demo.snapshot().run).toBe('complete');
    expect(demo.snapshot().items).toHaveLength(3);
    expect(api.scoreCalls[0]).toEqual(api.scoreCalls[1]);
    expect(api.stored.size).toBe(3);
    demo.dispose();
  });

  it('pauses playback without background requests and resumes the same run', async () => {
    vi.useFakeTimers();
    const api = new FakeApi();
    const demo = new DemoController(api);
    const first = demo.start({ ...DEFAULT_CONFIG, count: 3, paceMs: 1000 });
    await vi.advanceTimersByTimeAsync(0);
    expect(demo.snapshot().progress).toBe(1);
    const runId = demo.snapshot().runId;
    demo.pause();
    await first;
    await vi.advanceTimersByTimeAsync(5000);
    expect(api.scoreCalls).toHaveLength(1);
    const resumed = demo.resume();
    await vi.advanceTimersByTimeAsync(2000);
    await resumed;
    expect(demo.snapshot().runId).toBe(runId);
    expect(demo.snapshot().progress).toBe(3);
    demo.dispose();
  });

  it('aborts an in-flight score on pause and retries its original ID', async () => {
    vi.useFakeTimers();
    const api = new FakeApi();
    api.scoreDelay = 1000;
    const demo = new DemoController(api);
    const start = demo.start({ ...DEFAULT_CONFIG, count: 1, paceMs: 0 });
    await vi.advanceTimersByTimeAsync(0);
    demo.pause();
    await start;
    const resumed = demo.resume();
    await vi.advanceTimersByTimeAsync(1000);
    await resumed;
    expect(api.scoreCalls[0].client_transaction_id).toBe(api.scoreCalls[1].client_transaction_id);
    expect(demo.snapshot().items).toHaveLength(1);
    demo.dispose();
  });

  it('gives deliberate reruns new IDs while retaining earlier results', async () => {
    const api = new FakeApi();
    const demo = new DemoController(api);
    await demo.start({ ...DEFAULT_CONFIG, count: 1, paceMs: 0 });
    const firstId = demo.snapshot().runId;
    await demo.start({ ...DEFAULT_CONFIG, count: 1, paceMs: 0 });
    expect(demo.snapshot().runId).not.toBe(firstId);
    expect(demo.snapshot().items).toHaveLength(2);
    expect(api.sessions).toBe(1);
    demo.dispose();
  });

  it('only changes feedback after the API confirms it', async () => {
    const api = new FakeApi();
    const demo = new DemoController(api);
    await demo.start({ ...DEFAULT_CONFIG, count: 1, paceMs: 0 });
    const item = demo.snapshot().items[0];
    api.failFeedback = true;
    expect(await demo.label(item, 'fraud')).toBe(false);
    expect(demo.snapshot().items[0].feedback).toBeNull();
    api.failFeedback = false;
    expect(await demo.label(item, 'legitimate')).toBe(true);
    expect(demo.snapshot().items[0].feedback).toBe('legitimate');
    demo.dispose();
  });
});
