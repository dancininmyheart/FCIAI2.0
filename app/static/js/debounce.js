/**
 * 防抖动工具函数
 * 用于防止用户短时间内多次点击按钮导致重复提交请求
 */

/**
 * 防抖函数 - 确保函数在一定时间间隔内只执行一次
 * @param {Function} func - 要执行的函数
 * @param {number} wait - 等待时间(毫秒)
 * @returns {Function} - 返回防抖后的函数
 */
function debounce(func, wait) {
    let timeout;
    return function(...args) {
        const context = this;
        clearTimeout(timeout);
        timeout = setTimeout(() => {
            func.apply(context, args);
        }, wait);
    };
}

/**
 * 初始化带有防抖功能的按钮
 * 查找所有带有 data-debounce 属性的按钮并应用防抖
 */
function initDebouncedButtons() {
    if (document.documentElement.dataset.debounceReady === 'true') return;
    document.documentElement.dataset.debounceReady = 'true';

    document.addEventListener('click', function(event) {
        const button = event.target.closest('[data-debounce]');
        if (!button) return;

        const wait = parseInt(button.getAttribute('data-debounce'), 10) || 500;
        const now = Date.now();
        const lastClick = Number(button.dataset.lastDebouncedClick || 0);
        if (now - lastClick < wait) {
            event.preventDefault();
            event.stopImmediatePropagation();
            return;
        }
        button.dataset.lastDebouncedClick = String(now);

        const loadingText = button.getAttribute('data-loading-text');
        if (!loadingText) return;
        const originalHtml = button.innerHTML;
        setTimeout(() => {
            if (!button.isConnected) return;
            button.classList.add('btn-loading');
            button.setAttribute('aria-busy', 'true');
            if (button instanceof HTMLButtonElement) button.disabled = true;
            button.innerHTML = loadingText;
        }, 0);
        setTimeout(() => {
            if (!button.isConnected) return;
            button.classList.remove('btn-loading');
            button.removeAttribute('aria-busy');
            if (button instanceof HTMLButtonElement) button.disabled = false;
            button.innerHTML = originalHtml;
        }, Math.max(wait, 1000));
    }, true);
}

/**
 * 辅助函数：获取元素上的事件监听器
 * 注意：这是一个简化版本，无法获取使用addEventListener添加的匿名函数
 * 在实际使用中，我们可以使用jQuery的data存储或其他方法
 */
function getEventListeners(element, eventType) {
    // 在真实环境中，这个函数实现可能更复杂
    // 这里只是一个简化版本
    if (!element || !eventType) return [];
    
    // 这个函数在实际浏览器环境中无法正确工作
    // 仅作为示例
    return [];
}

/**
 * 为按钮添加防抖动功能
 * @param {HTMLElement} button - 按钮元素
 * @param {Function} clickHandler - 点击处理函数
 * @param {number} debounceTime - 防抖时间（毫秒）
 * @param {string} loadingText - 加载状态文本
 */
function addButtonDebounce(button, clickHandler, debounceTime = 1000, loadingText = null) {
    if (!button || !clickHandler) return;
    
    // 保存原始HTML
    const originalHTML = button.innerHTML;
    
    // 创建防抖动的点击处理函数
    const debouncedClickHandler = debounce(function(event) {
        // 禁用按钮
        button.disabled = true;
        button.classList.add('btn-disabled');
        
        // 如果有加载文本，显示加载状态
        if (loadingText) {
            button.classList.add('btn-loading');
            button.innerHTML = loadingText;
        }
        
        // 调用原始点击处理函数
        clickHandler.call(button, event);
        
        // 延迟后恢复按钮状态
        setTimeout(() => {
            button.disabled = false;
            button.classList.remove('btn-disabled');
            
            // 恢复原始文本
            if (loadingText) {
                button.classList.remove('btn-loading');
                button.innerHTML = originalHTML;
            }
        }, debounceTime);
    }, debounceTime);
    
    // 为按钮添加点击事件
    button.addEventListener('click', debouncedClickHandler);
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initDebouncedButtons);
} else {
    initDebouncedButtons();
}
