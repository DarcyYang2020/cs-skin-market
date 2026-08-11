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

// ---- Add to watchlist (F-3.16, 2026-08-09)：全站共享，仅用户主动点击加入 ----
// 服务端渲染按钮（discover top10）直接 onclick="addToWatchlist('name', this)"；
// 分析报告页用 data-name + getAttribute 传入（避免名称内引号转义问题）。
function addToWatchlist(name, btn) {
  name = String(name || "").trim();
  if (!name) { showToast("缺少饰品名称", "error"); return; }
  if (btn) btn.disabled = true;
  var fd = new FormData();
  fd.append("name", name);
  fd.append("holding", "0");
  fd.append("avg_cost", "0");
  fd.append("quantity", "0");
  fetch("/api/watchlist/add", {method:"POST", body: fd})
    .then(function(r) { return r.text(); })
    .then(function(t) {
      if (String(t).trim() === "OK") {
        if (btn) { btn.disabled = true; btn.innerHTML = "\u2713 \u5df2\u81ea\u9009"; btn.title = "\u5df2\u5728\u81ea\u9009"; }
        showToast("\u2705 \u5df2\u6dfb\u52a0\u5230\u81ea\u9009: " + name);
      } else {
        if (btn) btn.disabled = false;
        showToast("\u6dfb\u52a0\u5931\u8d25: " + (t || "\u672a\u77e5\u9519\u8bef"), "error");
      }
    })
    .catch(function() { if (btn) btn.disabled = false; showToast("\u8bf7\u6c42\u5931\u8d25", "error"); });
}

// ---- Hide analysis overlays on htmx complete ----
document.addEventListener('htmx:afterRequest', function(evt) {
  var overlay = document.getElementById('analysis-overlay-full');
  if (overlay) overlay.style.display = 'none';
  var wlOverlay = document.getElementById('wl-analysis-indicator');
  if (wlOverlay) wlOverlay.style.display = 'none';
});

// ---- Checkbox Select All ----
// 2026-08-10：加入行过滤（跳过隐藏行）+ 联动持仓管理批量操作条；防御性调用避免无批量条页面报错
function toggleAllCheckboxes(source) {
  document.querySelectorAll('.wl-checkbox').forEach(function(cb) {
    var r = cb.closest ? cb.closest('.wl-row') : null;
    if (r && r.style && r.style.display !== 'none') cb.checked = source.checked;
    else if (!r) cb.checked = source.checked;
  });
  if (typeof window.updateWlBatchBar === 'function') window.updateWlBatchBar();
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
