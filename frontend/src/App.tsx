import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import {
  Activity,
  ArrowDown,
  ArrowRight,
  BookOpen,
  Check,
  CircleHelp,
  Code2,
  ExternalLink,
  Flag,
  Gauge,
  GitBranch,
  Layers3,
  ListFilter,
  Pause,
  Play,
  Plus,
  RotateCcw,
  Search,
  ShieldCheck,
  Square,
  X,
} from 'lucide-react';
import { docsUrl } from './api/client';
import type { Item, Label } from './api/client';
import { DEFAULT_CONFIG, DemoController, GUIDED_CONFIG } from './demo';
import type { RunConfig } from './demo';
import { DetailPanel } from './components/DetailPanel';
import { ManualForm } from './components/ManualForm';
import { eventTime, locationName, money, shortId, title } from './format';

function useMobile() {
  const [mobile, setMobile] = useState(() => window.matchMedia('(max-width: 900px)').matches);
  useEffect(() => {
    const query = window.matchMedia('(max-width: 900px)');
    const listener = () => setMobile(query.matches);
    query.addEventListener('change', listener);
    return () => query.removeEventListener('change', listener);
  }, []);
  return mobile;
}
function wasTutorialSeen() {
  try {
    return localStorage.getItem('fraud-lab-tutorial') === 'complete';
  } catch {
    return false;
  }
}

export default function App({ controller: supplied }: { controller?: DemoController }) {
  const [controller] = useState(() => supplied ?? new DemoController());
  const state = useSyncExternalStore(controller.subscribe, controller.snapshot);
  const [config, setConfig] = useState<RunConfig>(DEFAULT_CONFIG);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [manual, setManual] = useState(false);
  const [info, setInfo] = useState(false);
  const [filter, setFilter] = useState<'all' | 'review' | 'unlabeled' | 'clear'>('all');
  const [query, setQuery] = useState('');
  const [runOnly, setRunOnly] = useState(false);
  const [guide, setGuide] = useState<'offer' | 'watch' | 'label' | 'done' | 'hidden'>(() =>
    wasTutorialSeen() ? 'hidden' : 'offer',
  );
  const [now, setNow] = useState(Date.now());
  const mobile = useMobile();
  const detailDialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    void controller.hydrate();
    const hidden = () => {
      if (document.hidden)
        controller.pause('Feed paused because this tab is hidden. Resume when you are ready.');
    };
    document.addEventListener('visibilitychange', hidden);
    return () => {
      document.removeEventListener('visibilitychange', hidden);
      controller.dispose();
    };
  }, [controller]);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    if (mobile && selectedId) detailDialog.current?.showModal();
  }, [mobile, selectedId]);

  const selected = state.items.find((item) => item.score.transaction_id === selectedId) ?? null;
  const reviews = state.items.filter((item) => item.score.recommendation === 'review');
  const pendingReviews = reviews.filter((item) => !item.feedback);
  const blocked = state.retryAt > now;
  const active = state.run === 'running' || state.run === 'paused';
  const unavailable =
    state.connection === 'waking' || state.connection === 'offline' || state.expired || blocked;
  const visible = state.items
    .filter((item) => {
      const matchesFilter =
        filter === 'all' ||
        (filter === 'review' && item.score.recommendation === 'review') ||
        (filter === 'clear' && item.score.recommendation === 'clear') ||
        (filter === 'unlabeled' && item.score.recommendation === 'review' && !item.feedback);
      const text =
        `${item.transaction.account_id} ${item.transaction.merchant_category} ${locationName(item.transaction)} ${shortId(item)}`.toLowerCase();
      return (
        matchesFilter &&
        (!runOnly || item.transaction.run_id === state.runId) &&
        text.includes(query.toLowerCase())
      );
    })
    .slice()
    .reverse();
  const guideStep = guide === 'watch' && state.run === 'complete' ? 'inspect' : guide;
  function inspect(item: Item) {
    controller.pause('Feed paused for investigation. Resume when you are ready.');
    setSelectedId(item.score.transaction_id);
    if (guide !== 'hidden' && item.score.alert_id) setGuide('label');
  }
  async function label(item: Item, value: Label) {
    const ok = await controller.label(item, value);
    if (ok && guide !== 'hidden') setGuide('done');
    return ok;
  }
  function dismissGuide() {
    setGuide('hidden');
    try {
      localStorage.setItem('fraud-lab-tutorial', 'complete');
    } catch {
      /* Preference storage is optional. */
    }
  }
  function newSession() {
    controller.resetSession();
    setSelectedId(null);
    setRunOnly(false);
    if (guide !== 'hidden') setGuide('offer');
  }
  function closeDetails() {
    const id = selectedId;
    if (detailDialog.current?.open) detailDialog.current.close();
    setSelectedId(null);
    queueMicrotask(() => {
      const trigger = document.querySelector<HTMLButtonElement>(
        `button[data-transaction-id="${id}"]`,
      );
      (trigger ?? document.getElementById('transactions-title'))?.focus();
    });
  }
  const detail = (
    <DetailPanel
      key={selected?.score.transaction_id ?? 'empty'}
      item={selected}
      saving={!!state.savingAlert}
      expired={state.expired}
      onClose={closeDetails}
      onLabel={label}
    />
  );

  return (
    <>
      <a className="skip-link" href="#workspace">
        Skip to transaction workspace
      </a>
      <header className="site-header">
        <div className="header-inner">
          <a className="brand" href="/" aria-label="Fraud Lab home">
            <span className="brand-mark">
              <Activity size={20} strokeWidth={2.5} />
            </span>
            <span>
              fraud<span className="brand-light">lab</span>
            </span>
            <span className="demo-tag">API DEMO</span>
          </a>
          <nav aria-label="Main navigation">
            <button
              className="nav-link active"
              onClick={() =>
                document.getElementById('workspace')?.scrollIntoView({ behavior: 'auto' })
              }
            >
              Workspace
            </button>
            <button className="nav-link" onClick={() => setInfo(true)}>
              How it works
            </button>
            <a className="nav-link docs-link" href={docsUrl} target="_blank" rel="noreferrer">
              API docs <ExternalLink size={13} />
            </a>
          </nav>
          <div className={`connection ${state.connection}`} role="status">
            <span className="status-dot" />
            {state.connection === 'ready'
              ? 'API connected'
              : state.connection === 'waking'
                ? 'Connecting to API'
                : state.connection === 'offline'
                  ? 'API unavailable'
                  : 'Checking API'}
          </div>
        </div>
      </header>
      <main className="page-shell">
        <section className="page-heading">
          <div>
            <div className="eyebrow heading-eyebrow">
              <span className="small-dot" /> SYNTHETIC PAYMENT MONITOR
            </div>
            <h1>Transaction review</h1>
            <p>Run a simulation. Follow the signals. Make the review.</p>
          </div>
          <button
            className="button"
            onClick={() => setManual(true)}
            disabled={unavailable || state.manualBusy}
          >
            <Plus size={16} /> Manual transaction
          </button>
        </section>

        {state.connection === 'waking' && (
          <div className="service-banner" role="status">
            <Activity size={19} />
            <div>
              <strong>Waking up the scoring API</strong>
              <p>
                Free hosting may need a moment to start. Your workspace is waiting for a real API
                response.
              </p>
            </div>
            <span className="mono">
              {Math.max(0, Math.floor((now - state.wakingSince) / 1000))}s
            </span>
          </div>
        )}
        {state.error && (
          <div className="error-banner" role="alert">
            <CircleHelp size={19} />
            <div>
              <strong>
                {state.expired
                  ? 'Session expired'
                  : blocked
                    ? 'Request limit reached'
                    : 'A request needs attention'}
              </strong>
              <p>
                {state.error}
                {blocked ? ` Try again in ${Math.ceil((state.retryAt - now) / 1000)} seconds.` : ''}
              </p>
              <span className="helper">
                Unconfirmed simulation transactions keep their IDs when you resume.
              </span>
            </div>
            {state.expired ? (
              <button className="button" onClick={newSession}>
                Fresh session
              </button>
            ) : state.connection === 'offline' ? (
              <button className="button" onClick={() => void controller.hydrate()}>
                Retry connection
              </button>
            ) : (
              <button
                className="icon-button"
                aria-label="Dismiss error"
                onClick={() => controller.clearError()}
              >
                <X size={17} />
              </button>
            )}
          </div>
        )}

        {guide !== 'hidden' && (
          <section
            className={`tutorial-card ${guideStep === 'done' ? 'finished' : ''}`}
            aria-label="Guided demo"
          >
            <div className="tutorial-icon">
              {guideStep === 'done' ? <Check size={22} /> : <BookOpen size={22} />}
            </div>
            <div className="tutorial-copy">
              <div className="eyebrow">
                {guideStep === 'offer'
                  ? 'YOUR FIRST INVESTIGATION'
                  : guideStep === 'done'
                    ? 'INVESTIGATION COMPLETE'
                    : 'GUIDED DEMO'}
              </div>
              <h2>
                {guideStep === 'offer'
                  ? 'Get to know the signals.'
                  : guideStep === 'watch'
                    ? '1. Watch the transactions arrive.'
                    : guideStep === 'inspect'
                      ? '2. Open a review alert.'
                      : guideStep === 'label'
                        ? '3. Make your simulated review.'
                        : 'You’ve completed the review loop.'}
              </h2>
              <p>
                {guideStep === 'offer'
                  ? 'A short, seeded simulation takes you from the first payment to a review decision.'
                  : guideStep === 'watch'
                    ? 'Twenty synthetic events are being scored through the API. Review alerts will appear as the scenario develops.'
                    : guideStep === 'inspect'
                      ? 'Choose an alert to explore its score components and the account activity behind its rule signals.'
                      : guideStep === 'label'
                        ? 'Inspect the details, then label the alert fraud or legitimate. Your feedback is saved to this session.'
                        : 'Now change the profile, scenario, or seed to run your own experiment.'}
              </p>
            </div>
            <div className="tutorial-actions">
              {guideStep === 'offer' ? (
                <>
                  <button
                    className="button primary"
                    disabled={unavailable || active}
                    onClick={() => {
                      setConfig(GUIDED_CONFIG);
                      setGuide('watch');
                      setFilter('all');
                      setRunOnly(false);
                      void controller.start(GUIDED_CONFIG);
                    }}
                  >
                    Start guided demo <ArrowRight size={15} />
                  </button>
                  <button className="text-button" onClick={dismissGuide}>
                    Explore on my own
                  </button>
                </>
              ) : guideStep === 'inspect' && reviews.length ? (
                <button className="button primary" onClick={() => inspect(reviews[0])}>
                  Inspect an alert <ArrowRight size={15} />
                </button>
              ) : guideStep === 'done' ? (
                <button className="button" onClick={dismissGuide}>
                  Explore simulations <ArrowRight size={15} />
                </button>
              ) : (
                <button className="text-button" onClick={dismissGuide}>
                  Dismiss tutorial
                </button>
              )}
            </div>
          </section>
        )}

        <section className="simulation-card" aria-labelledby="simulation-title">
          <div className="section-heading">
            <div className="inline-heading">
              <Layers3 size={17} />
              <h2 id="simulation-title">Simulation controls</h2>
            </div>
            <span className="helper simulation-explainer">
              Seeded events · runs only while this page is active
            </span>
          </div>
          <div className="simulation-controls">
            <fieldset className="config-fields" disabled={active || state.manualBusy}>
              <label>
                Spending profile
                <select
                  value={config.profile}
                  onChange={(event) =>
                    setConfig({ ...config, profile: event.target.value as RunConfig['profile'] })
                  }
                >
                  <option value="commuter">Routine commuter</option>
                  <option value="traveler">Frequent traveler</option>
                  <option value="business">Business spender</option>
                </select>
              </label>
              <label>
                Scenario
                <select
                  value={config.scenario}
                  onChange={(event) =>
                    setConfig({ ...config, scenario: event.target.value as RunConfig['scenario'] })
                  }
                >
                  <option value="mixed">Mixed risk signals</option>
                  <option value="normal">Normal spending</option>
                  <option value="amount">Amount spikes</option>
                  <option value="burst">Rapid activity</option>
                  <option value="travel">Impossible travel</option>
                  <option value="category_channel">Category & channel shift</option>
                </select>
              </label>
              <label className="seed-field">
                Seed
                <input
                  type="number"
                  min="0"
                  max="4294967295"
                  step="1"
                  value={config.seed}
                  onChange={(event) => setConfig({ ...config, seed: Number(event.target.value) })}
                />
              </label>
              <label>
                Events
                <select
                  value={config.count}
                  onChange={(event) => setConfig({ ...config, count: Number(event.target.value) })}
                >
                  {[20, 40, 100, 200].map((value) => (
                    <option key={value}>{value}</option>
                  ))}
                </select>
              </label>
              <label>
                Playback
                <select
                  value={config.paceMs}
                  onChange={(event) => setConfig({ ...config, paceMs: Number(event.target.value) })}
                >
                  <option value="1500">Relaxed</option>
                  <option value="1000">Standard</option>
                  <option value="500">Fast</option>
                </select>
              </label>
            </fieldset>
            <div className="run-actions">
              {active ? (
                <>
                  <button
                    className="button primary"
                    disabled={unavailable || state.manualBusy}
                    onClick={() =>
                      state.run === 'running' ? controller.pause() : void controller.resume()
                    }
                  >
                    {state.run === 'running' ? <Pause size={15} /> : <Play size={15} />}
                    {state.run === 'running' ? 'Pause feed' : 'Resume feed'}
                  </button>
                  <button
                    className="icon-button stop-button"
                    aria-label="Stop simulation"
                    onClick={() => controller.stop()}
                  >
                    <Square size={16} />
                  </button>
                </>
              ) : (
                <button
                  className="button primary"
                  disabled={unavailable || state.manualBusy}
                  onClick={() => {
                    if (guide === 'offer') dismissGuide();
                    void controller.start(config);
                  }}
                >
                  <Play size={15} />
                  {state.run === 'complete' || state.run === 'stopped'
                    ? 'Start new run'
                    : 'Start simulation'}
                </button>
              )}
            </div>
          </div>
          <div className="simulation-footer">
            <p className="helper">
              {config.profile === 'commuter'
                ? 'Predictable local purchases with modest amounts.'
                : config.profile === 'traveler'
                  ? 'Travel, hotels, and purchases across several locations.'
                  : 'Larger routine purchases for software, equipment, and travel.'}{' '}
              Event time is simulated; playback only changes arrival speed.
            </p>
            <button className="text-button" disabled={active} onClick={() => setGuide('offer')}>
              <RotateCcw size={12} /> Replay tutorial
            </button>
          </div>
          {state.total > 0 && (
            <div
              className="progress-track"
              aria-label="Simulation progress"
              role="progressbar"
              aria-valuenow={state.progress}
              aria-valuemin={0}
              aria-valuemax={state.total}
            >
              <span style={{ width: `${(state.progress / state.total) * 100}%` }} />
            </div>
          )}
        </section>

        <section className="metrics" aria-label="Session overview">
          <div className="metric">
            <span className="metric-label">
              <Activity size={15} /> Transactions scored
            </span>
            <strong>{state.items.length.toLocaleString()}</strong>
            <span>This temporary session</span>
          </div>
          <div className="metric">
            <span className="metric-label">
              <Flag size={15} /> Sent for review
            </span>
            <strong>
              {reviews.length}
              <span className="metric-inline">{pendingReviews.length} unlabeled</span>
            </strong>
            <span>
              {state.items.length
                ? `${((reviews.length / state.items.length) * 100).toFixed(1)}% of session transactions`
                : 'Waiting for scored transactions'}
            </span>
          </div>
          <div className="metric">
            <span className="metric-label">
              <Gauge size={15} /> Last API response
            </span>
            <strong>
              {state.lastLatency === null ? '—' : Math.round(state.lastLatency)}
              {state.lastLatency !== null && <span className="metric-unit">ms</span>}
            </strong>
            <span>Browser round trip · not a benchmark</span>
          </div>
        </section>

        <div className="workspace-grid" id="workspace">
          <section className="transactions-panel" aria-labelledby="transactions-title">
            <div className="workspace-heading">
              <div>
                <div className="inline-heading">
                  <h2 id="transactions-title" tabIndex={-1}>
                    Transaction feed
                  </h2>
                  <span className="count-tag">{visible.length}</span>
                </div>
                <p className="helper">
                  {state.run === 'running'
                    ? 'New events are arriving.'
                    : (state.notice ?? 'Scored events will appear here.')}
                </p>
              </div>
              <span className={`feed-state ${state.run}`}>
                <span className="status-dot" />
                {state.run === 'running'
                  ? 'Live'
                  : state.run === 'complete'
                    ? 'Complete'
                    : state.run === 'paused'
                      ? 'Paused'
                      : state.run === 'stopped'
                        ? 'Stopped'
                        : 'Ready'}
              </span>
            </div>
            <div className="filters">
              <div className="filter-tabs" role="group" aria-label="Filter transactions">
                {(
                  [
                    ['all', 'All events'],
                    ['review', 'Review'],
                    ['unlabeled', 'Unlabeled'],
                    ['clear', 'Clear'],
                  ] as const
                ).map(([value, text]) => (
                  <button
                    key={value}
                    aria-pressed={filter === value}
                    className={filter === value ? 'selected' : ''}
                    onClick={() => setFilter(value)}
                  >
                    {value === 'review' && <Flag size={12} />}
                    {text}
                  </button>
                ))}
              </div>
              <label className="search-field">
                <Search size={15} />
                <input
                  aria-label="Search transactions"
                  placeholder="Search account, category, city…"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                />
              </label>
            </div>
            {state.runId && (
              <div className="run-filter">
                <ListFilter size={13} />
                <label>
                  <input
                    type="checkbox"
                    checked={runOnly}
                    onChange={(event) => setRunOnly(event.target.checked)}
                  />{' '}
                  Current run only
                </label>
                <span className="mono">
                  {state.progress} / {state.total} events in run
                </span>
              </div>
            )}
            {visible.length ? (
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th scope="col">
                        Transaction <ArrowDown size={11} />
                      </th>
                      <th scope="col">Amount</th>
                      <th scope="col">Risk</th>
                      <th scope="col">Decision</th>
                      <th scope="col">
                        <span className="sr-only">Inspect</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {visible.map((item) => (
                      <tr
                        key={item.score.transaction_id}
                        className={item.score.transaction_id === selectedId ? 'selected-row' : ''}
                      >
                        <td>
                          <div className="row-primary">
                            <span className={`transaction-icon ${item.score.recommendation}`}>
                              {item.score.recommendation === 'review' ? (
                                <Flag size={14} />
                              ) : (
                                <ShieldCheck size={14} />
                              )}
                            </span>
                            <div>
                              <strong>{title(item.transaction.merchant_category)}</strong>
                              <span className="row-secondary">
                                <span className="mono">{shortId(item)}</span> ·{' '}
                                {eventTime(item.transaction.timestamp)} UTC
                              </span>
                              <span className="row-tertiary">
                                {item.transaction.account_id} · {locationName(item.transaction)}
                              </span>
                            </div>
                          </div>
                        </td>
                        <td className="amount-cell">
                          {money(item.transaction.amount)}
                          <span className="row-secondary">
                            USD · {title(item.transaction.channel)}
                          </span>
                        </td>
                        <td>
                          <div className={`score-cell ${item.score.recommendation}`}>
                            <strong>{item.score.risk_score}</strong>
                            <span className="score-track">
                              <span style={{ width: `${item.score.risk_score}%` }} />
                            </span>
                          </div>
                        </td>
                        <td>
                          <span className={`badge ${item.score.recommendation}`}>
                            {title(item.score.recommendation)}
                          </span>
                          {item.feedback && (
                            <span className="row-secondary feedback-label">
                              <Check size={11} />
                              {title(item.feedback)}
                            </span>
                          )}
                        </td>
                        <td>
                          <button
                            className="icon-button inspect-button"
                            aria-label={`Inspect transaction ${shortId(item)}`}
                            data-transaction-id={item.score.transaction_id}
                            onClick={() => inspect(item)}
                          >
                            <ArrowRight size={16} />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="feed-empty">
                <div className="empty-symbol">
                  {state.items.length ? <Search size={25} /> : <Activity size={27} />}
                </div>
                <h3>
                  {state.items.length
                    ? 'No matching transactions'
                    : 'Your investigation starts here'}
                </h3>
                <p>
                  {state.items.length
                    ? 'Try another filter or clear your search.'
                    : 'Start the guided demo or choose a scenario above to see the scoring API in action.'}
                </p>
                {state.items.length > 0 && (
                  <button
                    className="button"
                    onClick={() => {
                      setFilter('all');
                      setQuery('');
                      setRunOnly(false);
                    }}
                  >
                    Clear filters
                  </button>
                )}
              </div>
            )}
            <div className="table-footer">
              <span>
                {visible.length} of {state.items.length} session events · newest first
              </span>
              <span>Event times shown in UTC</span>
            </div>
          </section>
          {!mobile && detail}
        </div>
        <div className="session-tools">
          <span>Temporary, isolated session · up to 500 transactions</span>
          <button
            className="text-button"
            disabled={active || state.manualBusy || !!state.savingAlert}
            onClick={newSession}
          >
            <RotateCcw size={13} /> Fresh session
          </button>
        </div>
        <footer className="site-footer">
          <div>
            <ShieldCheck size={15} />
            <span>Synthetic data only. No real payments are processed or declined.</span>
          </div>
          <a
            href="https://github.com/abhiSeela21/Fraud-Detection-API"
            target="_blank"
            rel="noreferrer"
          >
            <GitBranch size={13} /> Source code <ExternalLink size={11} />
          </a>
        </footer>
        <div className="sr-only" role="status" aria-live="polite" aria-atomic="true">
          {state.run === 'paused'
            ? 'Simulation paused.'
            : state.run === 'complete'
              ? `Simulation complete. ${state.progress} transactions scored.`
              : ''}
        </div>
      </main>
      {mobile && selected && (
        <dialog
          ref={detailDialog}
          className="detail-dialog"
          aria-label="Transaction investigation"
          onClose={closeDetails}
        >
          {detail}
        </dialog>
      )}
      {manual && (
        <ManualForm
          busy={state.manualBusy}
          onClose={() => setManual(false)}
          onSubmit={(transaction) => controller.scoreManual(transaction)}
        />
      )}
      {info && <InfoDialog onClose={() => setInfo(false)} />}
    </>
  );
}

function InfoDialog({ onClose }: { onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  return (
    <dialog
      ref={dialog}
      className="modal info-modal"
      aria-labelledby="info-title"
      onClose={onClose}
    >
      <div className="panel-top">
        <span className="eyebrow">BEHIND THE WORKSPACE</span>
        <button className="icon-button" aria-label="Close how it works" onClick={onClose}>
          <X size={19} />
        </button>
      </div>
      <h2 id="info-title">A scoring API, made tangible.</h2>
      <p className="muted">
        This workspace is a client of the documented fraud detection API. Every displayed score is
        returned by that service.
      </p>
      <ol className="how-steps">
        <li>
          <span>01</span>
          <div>
            <h3>Generate synthetic events</h3>
            <p>
              Choose an invented spending profile and a seeded scenario. Playback stops when you
              pause or leave the tab.
            </p>
          </div>
        </li>
        <li>
          <span>02</span>
          <div>
            <h3>Build earlier-event context</h3>
            <p>
              The API uses only prior account activity within the same run. Future events never
              become historical features.
            </p>
          </div>
        </li>
        <li>
          <span>03</span>
          <div>
            <h3>Score and recommend</h3>
            <p>
              A calibrated model probability and capped rule adjustments produce a risk index and a
              clear or review recommendation.
            </p>
          </div>
        </li>
        <li>
          <span>04</span>
          <div>
            <h3>Investigate and label</h3>
            <p>
              Inspect separate rule signals and model output. Reviewer labels are feedback, not
              verified ground truth or automatic retraining.
            </p>
          </div>
        </li>
      </ol>
      <div className="info-disclosure">
        All detection results come from synthetic data. They do not establish real-world fraud
        detection performance.
      </div>
      <div className="info-links">
        <a className="button primary" href={docsUrl} target="_blank" rel="noreferrer">
          <Code2 size={15} /> Try the API docs <ExternalLink size={13} />
        </a>
        <a
          className="button"
          href="https://github.com/abhiSeela21/Fraud-Detection-API/blob/main/docs/evaluation/recall-policy/report.md"
          target="_blank"
          rel="noreferrer"
        >
          Read the evaluation <ExternalLink size={13} />
        </a>
      </div>
    </dialog>
  );
}
