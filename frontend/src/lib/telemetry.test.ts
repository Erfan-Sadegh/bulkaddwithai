import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@sentry/react', () => ({
  init: vi.fn(),
  setTag: vi.fn(),
  addBreadcrumb: vi.fn(),
  captureMessage: vi.fn(),
  withScope: (callback: (scope: { setTag: ReturnType<typeof vi.fn> }) => void) => callback({ setTag: vi.fn() }),
}));

import * as Sentry from '@sentry/react';
import { captureApiFailure, getRequestId, trackEvent } from './telemetry';

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
});
