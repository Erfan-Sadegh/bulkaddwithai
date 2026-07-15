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
  | 'start_new_products'
  | 'category_picker'
  | 'fill_missing_fields'
  | 'apply_preparation_days';

export type ObservedFailureField =
  | 'title'
  | 'price_toman'
  | 'stock'
  | 'preparation_days'
  | 'weight_grams'
  | 'package_weight_grams'
  | 'unit_quantity'
  | 'category'
  | 'shop_name'
  | 'contact_mobile';

type RageClickEvent = { event: 'ui_rage_click'; control: ObservedControl; click_count: number };
type DeadClickEvent = { event: 'ui_dead_click'; control: ObservedControl };
type InteractionEvent = RageClickEvent | DeadClickEvent;
export type ObservedActionEvent = {
  event: 'ui_action_started' | 'ui_action_accepted' | 'ui_action_blocked' | 'ui_action_failed';
  control: ObservedControl;
  attempt_id: string;
  outcome?: 'validation' | 'state' | 'network' | 'server' | 'unknown';
  failure_field?: ObservedFailureField;
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
    beforeSend: scrubSentryEvent,
    beforeSendTransaction: scrubSentryEvent,
  });
}

function scrubSentryEvent<T>(event: T): T {
  const envelope = event as {
    user?: unknown;
    request?: { cookies?: unknown; data?: unknown; url?: string; headers?: Record<string, string> };
  };
  delete envelope.user;
  if (envelope.request) {
    delete envelope.request.cookies;
    delete envelope.request.data;
    if (envelope.request.url) envelope.request.url = stripQuery(envelope.request.url);
    envelope.request.headers = Object.fromEntries(
      Object.entries(envelope.request.headers ?? {}).filter(
        ([key]) => !['authorization', 'cookie', 'x-admin-password', 'x-request-id'].includes(key.toLowerCase()),
      ),
    );
  }
  scrubSessionFields(event);
  return event;
}

function scrubSessionFields(value: unknown): void {
  if (Array.isArray(value)) {
    value.forEach(scrubSessionFields);
    return;
  }
  if (!value || typeof value !== 'object') return;
  const record = value as Record<string, unknown>;
  Object.entries(record).forEach(([key, item]) => {
    if (['request_id', 'session_key'].includes(key.toLowerCase())) {
      delete record[key];
      return;
    }
    if (typeof item === 'string') {
      record[key] = item.replace(/\b(request_id|session_key)=([^\s&]+)/gi, '$1=[REDACTED]');
      return;
    }
    scrubSessionFields(item);
  });
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

export function captureApiFailure(path: string, status: number | null, _requestId?: string | null): void {
  const safePath = stripQuery(path);
  const tags = { path: safePath, status: status ?? 'network' };
  trackEvent('http_request_failed', tags);
  Sentry.withScope((scope) => {
    Object.entries(tags).forEach(([key, value]) => scope.setTag(key, value));
    Sentry.captureMessage('frontend_http_request_failed', 'warning');
  });
}

type PendingControlAttempt = {
  timeoutId: number | null;
  pointerId: number;
  report: (event: InteractionEvent) => void;
};
const pendingControlAttempts = new Map<ObservedControl, PendingControlAttempt[]>();

export function installInteractionObserver(report: (event: InteractionEvent) => void): () => void {
  const clicks = new Map<ObservedControl, number[]>();
  const lastReported = new Map<ObservedControl, number>();
  const observedControl = (event: PointerEvent): ObservedControl | undefined => {
    const target = event.target instanceof Element ? event.target.closest<HTMLElement>('[data-observe-control]') : null;
    return target?.dataset.observeControl as ObservedControl | undefined;
  };
  const pendingForPointer = (event: PointerEvent): [ObservedControl, PendingControlAttempt] | null => {
    const pointerId = Number.isFinite(event.pointerId) ? event.pointerId : 0;
    for (const [control, attempts] of pendingControlAttempts.entries()) {
      const pending = [...attempts].reverse().find(
        (attempt) => attempt.report === report && attempt.pointerId === pointerId && attempt.timeoutId === null,
      );
      if (pending) return [control, pending];
    }
    return null;
  };
  const discardUnsettledPointer = (pointerId: number) => {
    pendingControlAttempts.forEach((attempts, control) => {
      const remaining = attempts.filter(
        (attempt) => !(attempt.report === report && attempt.pointerId === pointerId && attempt.timeoutId === null),
      );
      if (remaining.length > 0) pendingControlAttempts.set(control, remaining);
      else pendingControlAttempts.delete(control);
    });
  };
  const onPointerDown = (event: PointerEvent) => {
    if (event.button !== 0 || event.isPrimary === false) return;
    const pointerId = Number.isFinite(event.pointerId) ? event.pointerId : 0;
    discardUnsettledPointer(pointerId);
    const control = observedControl(event);
    if (!control) return;
    const now = Date.now();
    if (!['photo_drop_zone', 'add_photo_button'].includes(control)) {
      const pending: PendingControlAttempt = {
        timeoutId: null,
        pointerId,
        report,
      };
      pendingControlAttempts.set(control, [...(pendingControlAttempts.get(control) ?? []), pending]);
    }
    const recent = [...(clicks.get(control) ?? []), now].filter((timestamp) => now - timestamp <= 1500);
    clicks.set(control, recent);
    if (recent.length < 3 || now - (lastReported.get(control) ?? 0) < 5000) return;
    lastReported.set(control, now);
    const payload: RageClickEvent = { event: 'ui_rage_click', control, click_count: Math.min(recent.length, 12) };
    trackEvent(payload.event, { control: payload.control, click_count: payload.click_count });
    report(payload);
  };
  const onPointerUp = (event: PointerEvent) => {
    if (event.button !== 0 || event.isPrimary === false) return;
    const match = pendingForPointer(event);
    if (!match) return;
    const [control, pending] = match;
    pending.timeoutId = window.setTimeout(() => {
      const current = pendingControlAttempts.get(control) ?? [];
      const remaining = current.filter((item) => item !== pending);
      if (remaining.length > 0) pendingControlAttempts.set(control, remaining);
      else pendingControlAttempts.delete(control);
      const payload: DeadClickEvent = { event: 'ui_dead_click', control };
      trackEvent(payload.event, { control });
      report(payload);
    }, 1500);
  };
  const onPointerCancel = (event: PointerEvent) => {
    const match = pendingForPointer(event);
    if (!match) return;
    const [control, pending] = match;
    const attempts = pendingControlAttempts.get(control) ?? [];
    const index = attempts.indexOf(pending);
    if (index < 0) return;
    attempts.splice(index, 1);
    if (attempts.length > 0) pendingControlAttempts.set(control, attempts);
    else pendingControlAttempts.delete(control);
  };
  document.addEventListener('pointerdown', onPointerDown, true);
  document.addEventListener('pointerup', onPointerUp, true);
  document.addEventListener('pointercancel', onPointerCancel, true);
  return () => {
    document.removeEventListener('pointerdown', onPointerDown, true);
    document.removeEventListener('pointerup', onPointerUp, true);
    document.removeEventListener('pointercancel', onPointerCancel, true);
    pendingControlAttempts.forEach((attempts, control) => {
      const remaining = attempts.filter((attempt) => {
        if (attempt.report !== report) return true;
        if (attempt.timeoutId !== null) window.clearTimeout(attempt.timeoutId);
        return false;
      });
      if (remaining.length > 0) pendingControlAttempts.set(control, remaining);
      else pendingControlAttempts.delete(control);
    });
  };
}

export function beginObservedAction(
  control: ObservedControl,
  report: (event: ObservedActionEvent) => void,
): {
  accepted: () => void;
  blocked: (outcome: 'validation' | 'state', failureField?: ObservedFailureField) => void;
  failed: (outcome: 'network' | 'server' | 'unknown') => void;
} {
  consumePendingControlAttempt(control);
  const attemptId = createUuid();
  let terminal = false;
  const emit = (event: ObservedActionEvent) => {
    trackEvent(event.event, {
      control: event.control,
      attempt_id: event.attempt_id,
      outcome: event.outcome,
      failure_field: event.failure_field,
    });
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
    blocked: (outcome, failureField) => finish({
      event: 'ui_action_blocked',
      control,
      attempt_id: attemptId,
      outcome,
      failure_field: outcome === 'validation' ? failureField : undefined,
    }),
    failed: (outcome) => finish({ event: 'ui_action_failed', control, attempt_id: attemptId, outcome }),
  };
}

function consumePendingControlAttempt(control: ObservedControl): void {
  const attempts = pendingControlAttempts.get(control) ?? [];
  const pending = attempts.pop();
  if (!pending) return;
  if (pending.timeoutId !== null) window.clearTimeout(pending.timeoutId);
  if (attempts.length > 0) pendingControlAttempts.set(control, attempts);
  else pendingControlAttempts.delete(control);
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
