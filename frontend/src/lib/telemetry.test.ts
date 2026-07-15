import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@sentry/react', () => ({
  init: vi.fn(),
  setTag: vi.fn(),
  addBreadcrumb: vi.fn(),
  captureMessage: vi.fn(),
  withScope: (callback: (scope: { setTag: ReturnType<typeof vi.fn> }) => void) => callback({ setTag: vi.fn() }),
}));

import * as Sentry from '@sentry/react';
import {
  beginObservedAction,
  captureApiFailure,
  getRequestId,
  installInteractionObserver,
  installRuntimeFailureObserver,
  initializeTelemetry,
  trackEvent,
} from './telemetry';

describe('telemetry', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    window.clarity = vi.fn();
    vi.clearAllMocks();
  });

  it('creates one safe request id for the browser session', () => {
    const first = getRequestId();
    const second = getRequestId();

    expect(first).toBe(second);
    expect(first).toMatch(/^[A-Za-z0-9._:-]{1,64}$/);
  });

  it('never sends the browser session request id to Sentry', () => {
    vi.stubEnv('VITE_SENTRY_DSN', 'https://public@example.ingest.sentry.io/1');

    initializeTelemetry();

    expect(Sentry.init).toHaveBeenCalled();
    expect(Sentry.setTag).not.toHaveBeenCalledWith('request_id', expect.anything());
    const options = vi.mocked(Sentry.init).mock.calls[0][0];
    const event = options.beforeSend?.(
      {
        type: undefined,
        request: { headers: { 'X-Request-ID': 'raw-session-id' } },
        tags: { request_id: 'raw-session-id' },
        contexts: { correlation: { session_key: 'hashed-session-key' } },
      },
      {},
    );
    expect(JSON.stringify(event)).not.toContain('raw-session-id');
    expect(JSON.stringify(event)).not.toContain('hashed-session-key');
    const transaction = options.beforeSendTransaction?.(
      {
        type: 'transaction',
        transaction: 'catalog',
        request: { headers: { 'X-Request-ID': 'raw-transaction-session' } },
        tags: { session_key: 'hashed-transaction-session' },
      },
      {},
    );
    expect(JSON.stringify(transaction)).not.toContain('raw-transaction-session');
    expect(JSON.stringify(transaction)).not.toContain('hashed-transaction-session');
    vi.unstubAllEnvs();
  });

  it('does not forward sensitive custom tags to Clarity', () => {
    trackEvent('processing_job_failed', { stage: 'vision', mobile: '09120000000', access_token: 'secret' });

    expect(window.clarity).toHaveBeenCalledWith('event', 'processing_job_failed');
    expect(window.clarity).toHaveBeenCalledWith('set', 'stage', 'vision');
    expect(window.clarity).not.toHaveBeenCalledWith('set', 'mobile', expect.anything());
    expect(window.clarity).not.toHaveBeenCalledWith('set', 'access_token', expect.anything());
  });

  it('strips query strings from captured API failures', () => {
    captureApiFailure('/integrations/basalam/callback?code=secret', 500, 'request-1');

    expect(Sentry.captureMessage).toHaveBeenCalledWith('frontend_http_request_failed', 'warning');
    expect(window.clarity).toHaveBeenCalledWith('set', 'path', '/integrations/basalam/callback');
  });

  it('reports repeated clicks with the exact allowlisted product control', () => {
    vi.useFakeTimers();
    const report = vi.fn();
    const stop = installInteractionObserver(report);
    const button = document.createElement('button');
    button.dataset.observeControl = 'build_product_list';
    document.body.append(button);

    button.click();
    vi.advanceTimersByTime(100);
    button.click();
    vi.advanceTimersByTime(100);
    button.click();

    expect(report).toHaveBeenCalledWith({ event: 'ui_rage_click', control: 'build_product_list', click_count: 3 });
    expect(window.clarity).toHaveBeenCalledWith('event', 'ui_rage_click');
    stop();
    vi.useRealTimers();
  });

  it('ignores repeated clicks on uninstrumented elements', () => {
    const report = vi.fn();
    const stop = installInteractionObserver(report);
    const button = document.createElement('button');
    button.textContent = 'private user-facing text';
    document.body.append(button);

    button.click();
    button.click();
    button.click();

    expect(report).not.toHaveBeenCalled();
    stop();
  });

  it('correlates a product action start and terminal outcome without user text', () => {
    const report = vi.fn();
    const action = beginObservedAction('publish_basalam', report);

    action.failed('server');
    action.accepted();

    expect(report).toHaveBeenCalledTimes(2);
    const started = report.mock.calls[0][0];
    const failed = report.mock.calls[1][0];
    expect(started).toMatchObject({ event: 'ui_action_started', control: 'publish_basalam' });
    expect(failed).toEqual({
      event: 'ui_action_failed',
      control: 'publish_basalam',
      attempt_id: started.attempt_id,
      outcome: 'server',
    });
  });

  it('reports browser runtime failures without message, stack, or URL', () => {
    const report = vi.fn();
    const stop = installRuntimeFailureObserver(report, 'catalog');

    window.dispatchEvent(new ErrorEvent('error', { message: 'private product title and token', filename: 'https://example.test/?token=secret' }));

    expect(report).toHaveBeenCalledWith({
      event: 'frontend_runtime_failed',
      code: 'script_error',
      surface: 'catalog',
    });
    expect(JSON.stringify(report.mock.calls)).not.toContain('private');
    expect(JSON.stringify(report.mock.calls)).not.toContain('token');
    stop();
  });
});
