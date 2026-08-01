// CS-Market Web App - Frontend Scripts

// ---- Modal Helper ----
function openModal(id) {
  var el = document.getElementById(id);
  if (el) el.style.display = 'flex';
}
function closeModal(id) {
  var el = document.getElementById(id);
  if (!el) return;
  // Don't close analysis modal while an analysis is running (spinner visible).
  // The modal content will update when htmx completes; user can dismiss after.
  if (id === 'analysis-modal') {
    var body = document.getElementById('modal-body');
    if (body && body.querySelector('.spinner')) return;
  }
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
  var toast = document.createElement('div');
  toast.className = 'toast toast-' + type;
  toast.textContent = message;
  document.body.appendChild(toast);
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


// ===== UX: 分析加载（骨架屏 + 阶段轮换） =====
var ANALYSIS_STEPS = [
  '正在采集行情数据...',
  '正在合并成交量...',
  '正在计算评分与决策...',
  '正在生成报告...'
];
function showAnalysisLoading(extraText) {
  var body = document.getElementById('modal-body');
  if (!body) return;
  var stepsHtml = ANALYSIS_STEPS.map(function(s, i) {
    return '<div class="load-step" id="load-step-' + i + '" style="opacity:0.3;">' + s + '</div>';
  }).join('');
  body.innerHTML =
    '<div style="padding:30px;">' +
      '<div style="display:flex;align-items:center;gap:14px;margin-bottom:22px;">' +
        '<div class="spinner" style="width:30px;height:30px;flex-shrink:0;"></div>' +
        '<div style="font-size:15px;font-weight:600;">' + (extraText || '正在分析，请耐心等待...') + '</div>' +
      '</div>' +
      '<div class="skeleton" style="height:16px;width:82%;margin-bottom:10px;"></div>' +
      '<div class="skeleton" style="height:16px;width:56%;margin-bottom:20px;"></div>' +
      stepsHtml +
    '</div>';
  openModal('analysis-modal');
  var i = 0;
  if (window.__analysisStepTimer) clearInterval(window.__analysisStepTimer);
  window.__analysisStepTimer = setInterval(function() {
    var cur = document.getElementById('load-step-' + i);
    if (cur) cur.style.opacity = '1';
    var prev = document.getElementById('load-step-' + (i === 0 ? ANALYSIS_STEPS.length - 1 : i - 1));
    if (prev) prev.style.opacity = '0.3';
    i = (i + 1) % ANALYSIS_STEPS.length;
  }, 6000);
}
// pages may call showLoadingAndOpen(); route to the shared loader
window.showLoadingAndOpen = window.showLoadingAndOpen || function() { showAnalysisLoading(); };

// ===== UX: 复制摘要 =====
function copySummary(btn) {
  var root = btn.closest('#analysis-report') || document;
  var parts = [];
  var label = root.querySelector('.fusion-label');
  if (label) parts.push(label.textContent.replace(/\s+/g,' ').trim());
  root.querySelectorAll('.key-card').forEach(function(el) {
    var t = el.textContent.replace(/\s+/g,' ').trim();
    if (t) parts.push(t);
  });
  var zones = root.querySelectorAll('.price-zone');
  zones.forEach(function(el) { var t = el.textContent.replace(/\s+/g,' ').trim(); if (t) parts.push(t); });
  var detail = root.querySelector('.fusion-detail');
  if (detail) parts.push(detail.textContent.replace(/\s+/g,' ').trim());
  var text = parts.join('\n');
  function done() { var t = document.getElementById('toast'); if (t) { t.textContent = '✅ 已复制摘要'; t.style.display='block'; setTimeout(function(){t.style.display='none';},2000); } }
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(done, function() { fallbackCopy(text, done); });
  } else { fallbackCopy(text, done); }
}
function fallbackCopy(text, cb) {
  var ta = document.createElement('textarea');
  ta.value = text; ta.style.position='fixed'; ta.style.opacity='0';
  document.body.appendChild(ta); ta.select();
  try { document.execCommand('copy'); } catch(e) {}
  document.body.removeChild(ta); cb();
}

// ===== UX: 主题切换 =====
function toggleTheme() {
  var d = document.body.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
  document.body.setAttribute('data-theme', d);
  try { localStorage.setItem('cs-theme', d); } catch(e) {}
}
(function() {
  var t = null;
  try { t = localStorage.getItem('cs-theme'); } catch(e) {}
  if (t) document.body.setAttribute('data-theme', t);
})();
