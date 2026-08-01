// CS-Market Web App - Frontend Scripts

// ---- Modal Helper ----
function openModal(id) {
  var el = document.getElementById(id);
  if (el) el.style.display = 'flex';
}
function closeModal(id) {
  var el = document.getElementById(id);
  if (!el) return;
  // 允许随时关闭弹窗：分析继续在后台进行，完成后结果保存至报告/分析结果
  el.style.display = 'none';
}

// ---- Close modal on overlay click ----
document.addEventListener('click', function(e) {
  if (e.target.classList.contains('modal-overlay')) {
    closeModal(e.target.id);
  }
});

// ---- Toast Helper ----
function showToast(message, type) {
  type = type || 'success';
  var container = document.getElementById('toast-container');
  if (!container) return;
  var toast = document.createElement('div');
  toast.className = 'toast toast-' + type;
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


// ===== UX: 全局确认弹窗（替换 hx-confirm 原生弹窗） =====
var __confirmCb = null;
function showConfirmModal(message, onConfirm) {
  __confirmCb = onConfirm;
  var el = document.getElementById('confirm-modal');
  if (!el) return;
  document.getElementById('confirm-message').textContent = message;
  el.style.display = 'flex';
}
function closeConfirmModal(ok) {
  var el = document.getElementById('confirm-modal');
  if (el) el.style.display = 'none';
  if (ok && __confirmCb) { var cb = __confirmCb; __confirmCb = null; cb(); }
  else __confirmCb = null;
}
document.addEventListener('htmx:confirm', function(evt) {
  var msg = evt.detail.question;
  if (!msg) return;
  evt.preventDefault();
  showConfirmModal(msg, function() { evt.detail.issueRequest(true); });
});
