/************* Toast（可选） *************/
function showToast(message, type = 'success') {
  const container = document.getElementById('toastContainer');
  if (!container) return;
  const normalizedType = type === 'danger' ? 'error' : type;
  const toast = document.createElement('div');
  toast.className = `toast ${normalizedType}`;
  toast.setAttribute('role', normalizedType === 'error' ? 'alert' : 'status');
  toast.setAttribute('aria-atomic', 'true');
  const icon = document.createElement('i');
  icon.className =
    normalizedType === 'success' ? 'bi bi-check-circle-fill'
    : normalizedType === 'warning' ? 'bi bi-exclamation-triangle-fill'
    : normalizedType === 'error'   ? 'bi bi-x-circle-fill'
    : 'bi bi-info-circle-fill';
  icon.setAttribute('aria-hidden', 'true');
  const text = document.createElement('span');
  text.className = 'toast-message';
  text.textContent = message;
  const closeButton = document.createElement('button');
  closeButton.type = 'button';
  closeButton.className = 'toast-close';
  closeButton.setAttribute('aria-label', document.documentElement.lang === 'en' ? 'Dismiss notification' : '关闭通知');
  closeButton.innerHTML = '<i class="bi bi-x-lg" aria-hidden="true"></i>';
  closeButton.addEventListener('click', () => toast.remove());
  toast.appendChild(icon);
  toast.appendChild(text);
  toast.appendChild(closeButton);
  container.appendChild(toast);
  setTimeout(() => toast.remove(), normalizedType === 'error' ? 6000 : 4000);
}

function escapeHtml(value) {
  const element = document.createElement('div');
  element.textContent = String(value ?? '');
  return element.innerHTML;
}

/************* 安全存储工具 *************/
const SafeStore = (() => {
  let available = true;
  try {
    const k = '__ls_probe__';
    localStorage.setItem(k, '1');
    localStorage.removeItem(k);
  } catch (e) {
    available = false;
    console.warn('[completion-popup] localStorage unavailable, fallback to memory only:', e);
  }
  const mem = new Map();
  return {
    get(key) {
      if (available) {
        try { return localStorage.getItem(key); } catch (e) { console.warn('[get] ls err:', e); }
      }
      return mem.get(key) ?? null;
    },
    set(key, val) {
      if (available) {
        try { localStorage.setItem(key, val); return; } catch (e) { console.warn('[set] ls err:', e); }
      }
      mem.set(key, val);
    },
    remove(key) {
      if (available) {
        try { localStorage.removeItem(key); return; } catch (e) { console.warn('[remove] ls err:', e); }
      }
      mem.delete(key);
    },
    hasLS: available
  };
})();

/************* 任务级弹窗状态 *************/
let completionPopupCreating = false; // 本页去抖

const storageKeyOf = (taskKey = 'GLOBAL') => `completionPopupAlreadyShown:${taskKey}`;

/** 在“开始新任务”时调用（用同一个 taskKey） */
function resetCompletionPopupState(taskKey = 'GLOBAL') {
  completionPopupCreating = false;
  SafeStore.remove(storageKeyOf(taskKey));
  console.log('[completion-popup] reset state for', taskKey);
}

/**
 * 显示“任务完成”弹窗（每个 taskKey 仅弹一次）
 * @param {string} message - 文案
 * @param {string} taskKey - 任务唯一标识（强烈建议传：队列id/文件名+时间戳）
 */
function showCompletionPopup(message, taskKey = 'GLOBAL') {
  const key = storageKeyOf(taskKey);

  // 注意：每次调用现读存储，避免陈旧缓存
  const already = SafeStore.get(key) === 'true';
  console.log('[completion-popup] try show; task=', taskKey, 'already=', already, 'creating=', completionPopupCreating);

  if (completionPopupCreating || already) return;

  try {
    completionPopupCreating = true;
    SafeStore.set(key, 'true'); // 先写入，避免并发触发

    // 移除已存在的
    const existed = document.getElementById('completionModal');
    if (existed && existed.parentNode) existed.parentNode.removeChild(existed);

    // 背景
    const modal = document.createElement('div');
    modal.id = 'completionModal';
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-modal', 'true');
    modal.setAttribute('aria-labelledby', 'completionMessage');

    // 内容
    const modalContent = document.createElement('div');
    const messageElement = document.createElement('p');
    messageElement.id = 'completionMessage';
    messageElement.textContent = message;

    const confirmButton = document.createElement('button');
    try {
      const lang =
        (typeof currentLanguage !== 'undefined' && currentLanguage) ||
        document.documentElement.lang || 'zh';
      confirmButton.textContent = (lang === 'en') ? 'Noted' : '确定';
    } catch { confirmButton.textContent = '确定'; }

    confirmButton.onclick = function () {
      try { if (modal && modal.parentNode) modal.parentNode.removeChild(modal); }
      catch (e) { console.error('Error removing modal:', e); }
      finally {
        completionPopupCreating = false;
        if (typeof loadHistory === 'function') loadHistory();
      }
    };

    modalContent.appendChild(messageElement);
    modalContent.appendChild(confirmButton);
    modal.appendChild(modalContent);

    // 确保 body 存在
    const ensureAppend = () => {
      if (document.body) {
        document.body.appendChild(modal);
        requestAnimationFrame(() => confirmButton.focus());
      } else {
        // 极端情况：还没解析到 <body>，推迟一帧
        requestAnimationFrame(ensureAppend);
      }
    };
    ensureAppend();

    // 样式
    modal.style.cssText =
      'position:fixed;inset:0;background-color:rgba(0,0,0,0.5);display:flex;justify-content:center;align-items:center;z-index:99999';
    modalContent.style.cssText =
      'background-color:white;padding:30px;border-radius:10px;text-align:center;box-shadow:0 10px 30px rgba(0,0,0,0.25);max-width:420px;width:90%';
    messageElement.style.cssText =
      'margin-bottom:20px;font-size:16px;color:#343a40';
    confirmButton.style.cssText =
      'background-color:#0094d9;color:white;border:none;padding:10px 20px;border-radius:8px;cursor:pointer;font-size:14px;font-weight:600';

    console.log('[completion-popup] shown for', taskKey);
  } catch (e) {
    console.error('[completion-popup] create error:', e);
    completionPopupCreating = false;
    SafeStore.remove(key);

    // 兜底：如果创建失败，别让页面卡住
    const progressContainer = document.getElementById('progressContainer');
    const queueStatus = document.getElementById('queue-status');
    if (progressContainer) progressContainer.style.display = 'none';
    if (queueStatus) queueStatus.style.display = 'none';
    if (typeof loadHistory === 'function') loadHistory();
  }
}

/************* 其它 *************/
function toggleUserInfo() {
  const body = document.querySelector('.user-info-body');
  const toggle = document.querySelector('.user-info-toggle i');
  if (!body || !toggle) return;
  if (body.classList.contains('expanded')) {
    body.classList.remove('expanded');
    toggle.className = 'bi bi-chevron-up';
  } else {
    body.classList.add('expanded');
    toggle.className = 'bi bi-chevron-down';
  }
}

function processFlashMessages() {}

/** 如需：页面加载时做一些绑定 */
document.addEventListener('DOMContentLoaded', () => {
  // 示例：开始任务时重置（用同一个 taskKey）
  // document.getElementById('startTranslate')?.addEventListener('click', () => {
  //   const jobId = crypto.randomUUID();
  //   resetCompletionPopupState(jobId);
  //   startTranslate(jobId);
  // });
});
