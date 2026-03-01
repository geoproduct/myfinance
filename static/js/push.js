/**
 * MyFinance – Web Push 등록 / 해제
 * base.html에서 vapidPublicKey 변수가 주입된 후 로드됩니다.
 */

(function () {
  'use strict';

  // ── VAPID 공개키: base.html의 <script> 블록에서 window.vapidPublicKey 주입 ──
  const VAPID_KEY = window.vapidPublicKey || '';

  if (!VAPID_KEY) {
    console.warn('[Push] VAPID_PUBLIC_KEY not set – push disabled');
    return;
  }

  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
    console.warn('[Push] Push API not supported in this browser');
    return;
  }

  // ── 유틸 ─────────────────────────────────────────────────────────────────
  function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - base64String.length % 4) % 4);
    const base64  = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    const raw     = atob(base64);
    return Uint8Array.from([...raw].map(c => c.charCodeAt(0)));
  }

  // ── 서비스 워커 등록 ─────────────────────────────────────────────────────
  async function registerSW() {
    try {
      const reg = await navigator.serviceWorker.register('/static/sw.js', { scope: '/' });
      console.log('[Push] SW registered:', reg.scope);
      return reg;
    } catch (e) {
      console.error('[Push] SW registration failed:', e);
      return null;
    }
  }

  // ── 구독 저장 (서버 전송) ─────────────────────────────────────────────────
  async function saveSubscription(sub) {
    const json = sub.toJSON();
    const resp = await fetch('/push/subscribe', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({
        endpoint: json.endpoint,
        keys:     json.keys,
      }),
    });
    return resp.ok;
  }

  // ── 구독 해제 (서버에서 삭제) ─────────────────────────────────────────────
  async function deleteSubscription(sub) {
    await fetch('/push/unsubscribe', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ endpoint: sub.endpoint }),
    });
    await sub.unsubscribe();
  }

  // ── 구독 초기화 (페이지 로드 시) ─────────────────────────────────────────
  async function initPush() {
    const reg = await registerSW();
    if (!reg) return;

    // 알림 권한 상태 확인
    if (Notification.permission === 'denied') {
      updatePushUI(false, true);
      return;
    }

    // 기존 구독 확인
    const existing = await reg.pushManager.getSubscription();
    if (existing) {
      // 이미 구독 중 → 서버에 재확인 등록
      await saveSubscription(existing);
      updatePushUI(true);
    } else {
      updatePushUI(false);
    }
  }

  // ── 구독 요청 ─────────────────────────────────────────────────────────────
  window.requestPushSubscription = async function () {
    const permission = await Notification.requestPermission();
    if (permission !== 'granted') {
      alert('알림 권한이 거부되었습니다. 브라우저 설정에서 허용해 주세요.');
      updatePushUI(false, true);
      return;
    }

    const reg = await navigator.serviceWorker.ready;
    try {
      const sub = await reg.pushManager.subscribe({
        userVisibleOnly:      true,
        applicationServerKey: urlBase64ToUint8Array(VAPID_KEY),
      });
      const ok = await saveSubscription(sub);
      if (ok) {
        updatePushUI(true);
        showToast('🔔 푸시 알림이 활성화되었습니다!', 'success');
      }
    } catch (e) {
      console.error('[Push] Subscribe failed:', e);
      showToast('푸시 알림 등록에 실패했습니다.', 'danger');
    }
  };

  // ── 구독 취소 ─────────────────────────────────────────────────────────────
  window.cancelPushSubscription = async function () {
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    if (sub) {
      await deleteSubscription(sub);
      showToast('푸시 알림이 비활성화되었습니다.', 'info');
    }
    updatePushUI(false);
  };

  // ── UI 업데이트 ───────────────────────────────────────────────────────────
  function updatePushUI(subscribed, denied) {
    const btn = document.getElementById('pushToggleBtn');
    if (!btn) return;
    if (denied) {
      btn.innerHTML = '<i class="fa-solid fa-bell-slash me-1"></i>알림 차단됨';
      btn.className = 'btn btn-sm btn-outline-secondary disabled';
      return;
    }
    if (subscribed) {
      btn.innerHTML = '<i class="fa-solid fa-bell me-1"></i>알림 켜짐';
      btn.className = 'btn btn-sm btn-success';
      btn.onclick   = window.cancelPushSubscription;
    } else {
      btn.innerHTML = '<i class="fa-regular fa-bell me-1"></i>알림 받기';
      btn.className = 'btn btn-sm btn-outline-primary';
      btn.onclick   = window.requestPushSubscription;
    }
  }

  // ── 토스트 메시지 ─────────────────────────────────────────────────────────
  function showToast(msg, type) {
    const toastHtml = `
      <div class="toast align-items-center text-white bg-${type === 'success' ? 'success' : type === 'danger' ? 'danger' : 'info'} border-0 show"
           role="alert" style="position:fixed;bottom:1.5rem;right:1.5rem;z-index:9999;min-width:240px">
        <div class="d-flex">
          <div class="toast-body">${msg}</div>
          <button type="button" class="btn-close btn-close-white me-2 m-auto" onclick="this.closest('.toast').remove()"></button>
        </div>
      </div>`;
    document.body.insertAdjacentHTML('beforeend', toastHtml);
    setTimeout(() => {
      const t = document.body.querySelector('.toast:last-of-type');
      if (t) t.remove();
    }, 4000);
  }

  // ── 초기화 ───────────────────────────────────────────────────────────────
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initPush);
  } else {
    initPush();
  }
})();
