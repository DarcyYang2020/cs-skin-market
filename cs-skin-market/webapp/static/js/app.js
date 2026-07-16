
// CS-Market Web App - Frontend Scripts

// ---- Modal Helper ----
function openModal(id) {
  var el = document.getElementById(id);
  if (el) el.style.display = 'flex';
}
function closeModal(id) {
  var el = document.getElementById(id);
  if (el) el.style.display = 'none';
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

// ---- Auto-open modal when content loads into #modal-body ----
document.addEventListener('htmx:afterSettle', function(evt) {
  if (evt.detail.target && evt.detail.target.id === 'modal-body') {
    openModal('analysis-modal');
  }
});

