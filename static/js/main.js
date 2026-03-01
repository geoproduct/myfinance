// ── 사이드바 토글 ──────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  const toggle = document.getElementById('sbToggle');
  const sb     = document.getElementById('sidebar');
  if (toggle && sb) {
    toggle.addEventListener('click', () => sb.classList.toggle('open'));
    document.addEventListener('click', e => {
      if (!sb.contains(e.target) && !toggle.contains(e.target))
        sb.classList.remove('open');
    });
  }
  // alert 자동 닫기
  document.querySelectorAll('.alert').forEach(el => {
    setTimeout(() => bootstrap.Alert.getOrCreateInstance(el)?.close(), 4000);
  });
});

// ── 숫자 콤마 포맷 ────────────────────────────
function fmtNum(input) {
  const v = input.value.replace(/[^0-9]/g, '');
  input.value = v ? parseInt(v).toLocaleString() : '';
}

// ── 알림 전체 읽음 ────────────────────────────
function readAllNotif() {
  fetch('/api/notif/read-all', {method:'POST'}).then(() => location.reload());
}
