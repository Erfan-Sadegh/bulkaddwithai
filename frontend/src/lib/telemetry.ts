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
export type ObservedControl =
  | 'photo_drop_zone'
  | 'add_photo_button'
  | 'build_product_list'
  | 'publish_basalam'
  | 'submit_torob'
  | 'connect_basalam'
  | 'record_voice'
  | 'change_platform'
  | 'delete_photo'
  | 'split_photo'
  | 'start_new_products';

type RageClickEvent = { event: 'ui_rage_click'; control: ObservedControl; click_count: number };
export type ObservedActionEvent = {
  event: 'ui_action_started' | 'ui_action_accepted' | 'ui_action_blocked' | 'ui_action_failed';
  control: ObservedControl;
  attempt_id: string;
  outcome?: 'validation' | 'state' | 'network' | 'server' | 'unknown';
};
export type RuntimeFailureEvent = {
  event: 'frontend_runtime_failed';
  code: 'script_error' | 'unhandled_rejection';
  surface: 'catalog' | 'admin';
};

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

export function installInteractionObserver(report: (event: RageClickEvent) => void): () => void {
  const clicks = new Map<ObservedControl, number[]>();
  const lastReported = new Map<ObservedControl, number>();
  const handler = (event: MouseEvent) => {
    const target = event.target instanceof Element ? event.target.closest<HTMLElement>('[data-observe-control]') : null;
    const control = target?.dataset.observeControl as ObservedControl | undefined;
    if (!control) return;
    const now = Date.now();
    const recent = [...(clicks.get(control) ?? []), now].filter((timestamp) => now - timestamp <= 1500);
    clicks.set(control, recent);
    if (recent.length < 3 || now - (lastReported.get(control) ?? 0) < 5000) return;
    lastReported.set(control, now);
    const payload: RageClickEvent = { event: 'ui_rage_click', control, click_count: Math.min(recent.length, 12) };
    trackEvent(payload.event, { control: payload.control, click_count: payload.click_count });
    report(payload);
  };
  document.addEventListener('click', handler, true);
  return () => document.removeEventListener('click', handler, true);
}

export function beginObservedAction(
  control: ObservedControl,
  report: (event: ObservedActionEvent) => void,
): {
  accepted: () => void;
  blocked: (outcome: 'validation' | 'state') => void;
  failed: (outcome: 'network' | 'server' | 'unknown') => void;
} {
  const attemptId = createUuid();
  let terminal = false;
  const emit = (event: ObservedActionEvent) => {
    trackEvent(event.event, { control: event.control, attempt_id: event.attempt_id, outcome: event.outcome });
    report(event);
  };
  const finish = (event: ObservedActionEvent) => {
    if (terminal) return;
    terminal = true;
    emit(event);
  };
  emit({ event: 'ui_action_started', control, attempt_id: attemptId });
  return {
    accepted: () => finish({ event: 'ui_action_accepted', control, attempt_id: attemptId }),
    blocked: (outcome) => finish({ event: 'ui_action_blocked', control, attempt_id: attemptId, outcome }),
    failed: (outcome) => finish({ event: 'ui_action_failed', control, attempt_id: attemptId, outcome }),
  };
}

export function installRuntimeFailureObserver(
  report: (event: RuntimeFailureEvent) => void,
  surface: RuntimeFailureEvent['surface'],
): () => void {
  const lastReported = new Map<RuntimeFailureEvent['code'], number>();
  const emit = (code: RuntimeFailureEvent['code']) => {
    const now = Date.now();
    if (now - (lastReported.get(code) ?? 0) < 10_000) return;
    lastReported.set(code, now);
    const payload: RuntimeFailureEvent = { event: 'frontend_runtime_failed', code, surface };
    trackEvent(payload.event, { code, surface });
    report(payload);
  };
  const onError = () => emit('script_error');
  const onUnhandledRejection = () => emit('unhandled_rejection');
  window.addEventListener('error', onError);
  window.addEventListener('unhandledrejection', onUnhandledRejection);
  return () => {
    window.removeEventListener('error', onError);
    window.removeEventListener('unhandledrejection', onUnhandledRejection);
  };
}

function createUuid(): string {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (character) => {
    const random = Math.floor(Math.random() * 16);
    const value = character === 'x' ? random : (random & 0x3) | 0x8;
    return value.toString(16);
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
