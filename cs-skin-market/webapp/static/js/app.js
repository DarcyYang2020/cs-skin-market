// CS-Market Web App - Frontend Scripts

// ---- Mobile sidebar ----
function toggleSidebar(open) {
  var body = document.body;
  var btn = document.getElementById('sidebar-toggle');
  var scrim = document.getElementById('sidebar-scrim');
  var want = (typeof open === 'boolean') ? open : !body.classList.contains('sidebar-open');
  body.classList.toggle('sidebar-open', want);
  if (btn) btn.setAttribute('aria-expanded', want ? 'true' : 'false');
  if (scrim) scrim.style.display = want ? 'block' : 'none';
  if (want && btn) btn.focus();
}
document.addEventListener('DOMContentLoaded', function() {
  var toggle = document.getElementById('sidebar-toggle');
  var scrim = document.getElementById('sidebar-scrim');
  if (toggle) toggle.addEventListener('click', function() { toggleSidebar(); });
  if (scrim) scrim.addEventListener('click', function() { toggleSidebar(false); });
  document.querySelectorAll('.sidebar-nav a').forEach(function(a) {
    a.addEventListener('click', function() { toggleSidebar(false); });
  });
});

// ---- Modal Helper ----
var __lastFocused = null;
function openModal(id) {
  var el = document.getElementById(id);
  if (!el) return;
  __lastFocused = document.activeElement;
  el.style.display = 'flex';
  var closeBtn = el.querySelector('.modal-close-btn');
  if (closeBtn) closeBtn.focus();
}
function closeModal(id) {
  var el = document.getElementById(id);
  if (!el) return;
  // 允许随时关闭弹窗：分析继续在后台进行，完成后结果保存至报告/分析结果
  el.style.display = 'none';
  if (__lastFocused && __lastFocused.focus && __lastFocused.isConnected) {
    __lastFocused.focus();
    __lastFocused = null;
  }
}

// ---- Close modal on overlay click ----
document.addEventListener('click', function(e) {
  if (e.target.classList.contains('modal-overlay')) {
    closeModal(e.target.id);
  }
});

// ---- Esc closes top-most modal / mobile sidebar ----
document.addEventListener('keydown', function(e) {
  if (e.key !== 'Escape') return;
  var overlays = document.querySelectorAll('.modal-overlay');
  for (var i = overlays.length - 1; i >= 0; i--) {
    if (overlays[i].style.display !== 'none') {
      closeModal(overlays[i].id);
      return;
    }
  }
  if (document.body.classList.contains('sidebar-open')) toggleSidebar(false);
});

// ---- Toast Helper ----
function showToast(message, type) {
  type = type || 'success';
  var container = document.getElementById('toast-container');
  if (!container) return;
  var toast = document.createElement('div');
  toast.className = 'toast toast-' + type;
  toast.setAttribute('role', 'status');
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(function() {
    toast.style.opacity = '0'; toast.style.transition = 'opacity 0.3s';
    setTimeout(function() { toast.remove(); }, 300);
  }, 2500);
}

// ---- Hide analysis overlays on htmx complete ----
document.addEventListener('htmx:afterRequest', function(evt) {
  var overlay = document.getElementById('analysis-overlay-full');
  if (overlay) overlay.style.display = 'none';
  var wlOverlay = document.getElementById('wl-analysis-indicator');
  if (wlOverlay) wlOverlay.style.display = 'none';
});

// ---- Checkbox Select All ----
function toggleAllCheckboxes(source) {
  document.querySelectorAll('.wl-checkbox').forEach(function(cb) { cb.checked = source.checked; });
}

// ---- Auto-close flash messages ----
document.addEventListener('DOMContentLoaded', function() {
  setTimeout(function() {
    document.querySelectorAll('.flash-msg').forEach(function(f) {
      f.style.opacity = '0'; f.style.transition = 'opacity 0.5s';
      setTimeout(function() { f.remove(); }, 500);
    });
  }, 3000);
});

// ---- Keyboard support for tab elements (Enter / Space) ----
document.addEventListener('keydown', function(e) {
  var t = e.target;
  if (!t || !t.classList || !t.classList.contains('tab')) return;
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault();
    t.click();
  }
});

// ===== UX: 全局确认弹窗（替换 hx-confirm 原生弹窗） =====
var __confirmCb = null;
function showConfirmModal(message, onConfirm) {
  __confirmCb = onConfirm;
  var el = document.getElementById('confirm-modal');
  if (!el) return;
  __lastFocused = document.activeElement;
  document.getElementById('confirm-message').textContent = message;
  el.style.display = 'flex';
  var cancelBtn = el.querySelector('.btn-outline');
  if (cancelBtn) cancelBtn.focus();
}
function closeConfirmModal(ok) {
  var el = document.getElementById('confirm-modal');
  if (el) el.style.display = 'none';
  if (ok && __confirmCb) { var cb = __confirmCb; __confirmCb = null; cb(); }
  else __confirmCb = null;
  if (__lastFocused && __lastFocused.focus && __lastFocused.isConnected) {
    __lastFocused.focus();
    __lastFocused = null;
  }
}
document.addEventListener('htmx:confirm', function(evt) {
  var msg = evt.detail.question;
  if (!msg) return;
  evt.preventDefault();
  showConfirmModal(msg, function() { evt.detail.issueRequest(true); });
});
