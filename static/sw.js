/**
 * MyFinance Service Worker
 * - Web Push 알림 수신 처리
 * - 오프라인 캐시 (선택적)
 */

const CACHE_NAME = 'myfinance-v1';
const STATIC_ASSETS = [
  '/',
  '/static/css/style.css',
  '/static/js/main.js',
];

// ── Install: 정적 에셋 프리캐시 ─────────────────────────
self.addEventListener('install', event => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(STATIC_ASSETS).catch(() => {/* 실패 무시 */});
    })
  );
});

// ── Activate: 이전 캐시 정리 ────────────────────────────
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

// ── Push 수신 ───────────────────────────────────────────
self.addEventListener('push', event => {
  let data = { title: 'MyFinance', body: '새 알림이 있습니다.', url: '/' };

  if (event.data) {
    try {
      data = Object.assign(data, JSON.parse(event.data.text()));
    } catch (e) {
      data.body = event.data.text();
    }
  }

  const options = {
    body:    data.body,
    icon:    '/static/img/icon-192.png',  // 없으면 브라우저 기본 아이콘
    badge:   '/static/img/badge-72.png',
    vibrate: [100, 50, 100],
    data:    { url: data.url || '/' },
    actions: [
      { action: 'open',    title: '열기' },
      { action: 'dismiss', title: '닫기' },
    ],
    tag:     'myfinance-notification',
    renotify: true,
  };

  event.waitUntil(
    self.registration.showNotification(data.title, options)
  );
});

// ── 알림 클릭 ───────────────────────────────────────────
self.addEventListener('notificationclick', event => {
  event.notification.close();

  if (event.action === 'dismiss') return;

  const targetUrl = (event.notification.data && event.notification.data.url) || '/';

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(windowClients => {
      // 이미 열린 탭이 있으면 포커스
      for (const client of windowClients) {
        if (client.url.includes(self.location.origin) && 'focus' in client) {
          client.navigate(targetUrl);
          return client.focus();
        }
      }
      // 없으면 새 탭 열기
      if (clients.openWindow) {
        return clients.openWindow(targetUrl);
      }
    })
  );
});

// ── Push 구독 변경 (브라우저가 갱신 시 서버에 재등록) ──
self.addEventListener('pushsubscriptionchange', event => {
  event.waitUntil(
    self.registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: event.oldSubscription
        ? event.oldSubscription.options.applicationServerKey
        : null,
    }).then(sub => {
      return fetch('/push/subscribe', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(sub.toJSON()),
      });
    })
  );
});
