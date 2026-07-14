import * as Sentry from '@sentry/react';

type SafeTagValue = string | number | boolean | null | undefined;
type ClarityCommand = 'event' | 'set';

declare global {
  interface Window {
    clarity?: (command: ClarityCommand, key: string, value?: string | string[]) => void;
  }
}

const SENSITIVE_TAG = /(token|secret|password|authorization|mobile|phone|name|title|description|transcript|voice|payload)/i;
const EVENT_NAME = /^[a-z][a-z0-9_]{1,63}$/;
const REQUEST_ID_KEY = 'bulkadd_request_id';

export function initializeTelemetry(): void {
  const dsn = import.meta.env.VITE_SENTRY_DSN;
  if (!dsn) return;
  Sentry.init({
    dsn,
    environment: import.meta.env.VITE_APP_ENVIRONMENT || 'production',
    release: import.meta.env.VITE_APP_RELEASE || undefined,
    sendDefaultPii: false,
    tracesSampleRate: 0,
    beforeSend(event) {
      delete event.user;
      if (event.request) {
        delete event.request.cookies;
        delete event.request.data;
        if (event.request.url) event.request.url = stripQuery(event.request.url);
        event.request.headers = Object.fromEntries(
          Object.entries(event.request.headers ?? {}).filter(
            ([key]) => !['authorization', 'cookie', 'x-admin-password'].includes(key.toLowerCase()),
          ),
        );
      }
      return event;
    },
  });
  Sentry.setTag('request_id', getRequestId());
}

export function getRequestId(): string {
  const existing = window.sessionStorage.getItem(REQUEST_ID_KEY);
  if (existing && /^[A-Za-z0-9._:-]{1,64}$/.test(existing)) return existing;
  const generated = globalThis.crypto?.randomUUID?.().replace(/-/g, '') ?? `${Date.now()}${Math.random()}`.replace(/\D/g, '');
  window.sessionStorage.setItem(REQUEST_ID_KEY, generated);
  return generated;
}

export function trackEvent(name: string, tags: Record<string, SafeTagValue> = {}): void {
  if (!EVENT_NAME.test(name)) return;
  const safeTags = sanitizeTags(tags);
  window.clarity?.('event', name);
  Object.entries(safeTags).forEach(([key, value]) => window.clarity?.('set', key, value));
  Sentry.addBreadcrumb({ category: 'product', message: name, level: 'info', data: safeTags });
}

export function captureApiFailure(path: string, status: number | null, requestId?: string | null): void {
  const safePath = stripQuery(path);
  const tags = { path: safePath, status: status ?? 'network', request_id: requestId ?? getRequestId() };
  trackEvent('http_request_failed', tags);
  Sentry.withScope((scope) => {
    Object.entries(tags).forEach(([key, value]) => scope.setTag(key, value));
    Sentry.captureMessage('frontend_http_request_failed', 'warning');
  });
}

function sanitizeTags(tags: Record<string, SafeTagValue>): Record<string, string> {
  return Object.fromEntries(
    Object.entries(tags)
      .filter(([key, value]) => !SENSITIVE_TAG.test(key) && value !== undefined && value !== null)
      .map(([key, value]) => [key, String(value).slice(0, 120)]),
  );
}

function stripQuery(value: string): string {
  return value.split(/[?#]/, 1)[0];
}
