// ===================== 全局状态 =====================
let currentSearch = {
  keyword: '',
  dataSource: 'all',
  currentPage: 1,
  totalPages: 1,
  totalResults: 0
};

// ===================== 工具函数 =====================

// 统一把 \ -> /，并去掉开头的 "./"
// 仅用于构造 URL（展示图片/拼预览链接等），不修改原始数据
function normalizeRelPathForUrl(p) {
  if (!p) return p;
  let s = String(p).replace(/\\/g, '/');
  while (s.startsWith('./')) s = s.slice(2);
  return s;
}

// 构造下载 URL（使用“查询参数版”下载接口）
function buildDownloadUrl(rawPath) {
  const params = new URLSearchParams({
    path: rawPath,
    download: '1'
  });
  return `/ingredient/api/ingredient/download?${params.toString()}`;
}

// 安全设置属性值（用于把路径放进 data-attribute）
function escapeAttr(val) {
  return String(val).replace(/"/g, '&quot;');
}

// ===================== 事件绑定：回车触发搜索 =====================
document.getElementById('searchInput').addEventListener('keypress', function (e) {
  if (e.key === 'Enter') {
    currentSearch.currentPage = 1;
    searchIngredient();
  }
});

// ===================== 搜索主流程 =====================
function searchIngredient() {
  const searchInput = document.getElementById('searchInput');
  const dataSourceFilter = document.getElementById('dataSourceFilter');
  const resultsContainer = document.getElementById('searchResults');

  const searchTerm = (searchInput.value || '').trim();
  const dataSource = dataSourceFilter.value;

  if (!searchTerm) {
    resultsContainer.innerHTML = '<p class="no-results">请输入要搜索的成分名称</p>';
    return;
  }

  // 显示加载状态
  resultsContainer.innerHTML = '<p class="loading">正在搜索...</p>';

  // 更新当前搜索状态
  currentSearch.keyword = searchTerm;
  currentSearch.dataSource = dataSource;

  // 构造查询参数
  const params = new URLSearchParams({
    keyword: searchTerm,
    data_source: dataSource,
    page: String(currentSearch.currentPage),
    per_page: '12'
  });

  // 调用搜索 API
  fetch(`/ingredient/api/ingredient/search?${params.toString()}`, { method: 'GET' })
    .then(res => res.json())
    .then(data => {
      if (!data.success) {
        resultsContainer.innerHTML = `<p class="error">${data.message || '搜索失败'}</p>`;
        return;
      }
      displayResults(data.data, data.pagination);
    })
    .catch(err => {
      console.error('搜索出错:', err);
      resultsContainer.innerHTML = '<p class="error">搜索时发生错误，请稍后重试</p>';
    });
}

// ===================== 渲染结果与分页 =====================
function displayResults(data, pagination) {
  const resultsContainer = document.getElementById('searchResults');

  if (!Array.isArray(data) || data.length === 0) {
    resultsContainer.innerHTML = '<p class="no-results">未找到相关成分</p>';
    return;
  }

  // 更新状态
  if (pagination) {
    currentSearch.currentPage = pagination.current_page;
    currentSearch.totalPages = pagination.total_pages;
    currentSearch.totalResults = pagination.total;
  }

  let html = `
    <div class="results-header">
      <p>找到 ${currentSearch.totalResults} 个结果</p>
    </div>
    <div class="results-grid">
  `;

  data.forEach(item => {
    const productName = item.产品名称 || '';
    const mainIngredients = item.主要成分 || '';
    const dataSource = item.数据源 || '';
    const detailUrl = item.detail_url || '';
    const rawPath = item.截图路径 || '';

    // 数据源标签
    let dataSourceTag = '';
    if (dataSource) {
      const tagClass = dataSource === '注册'
        ? 'registration-tag'
        : (dataSource === '备案' ? 'filing-tag' : 'unknown-tag');
      dataSourceTag = `<span class="data-source-tag ${tagClass}">${dataSource}</span>`;
    }

    html += `
      <div class="result-card">
        <h3>${productName} ${dataSourceTag}</h3>
        <p><strong>主要成分：</strong>${mainIngredients}</p>

        ${rawPath ? `
          <div class="btn-row">
            <button class="download-btn" data-path="${escapeAttr(rawPath)}">
              <i class="bi bi-download"></i> 下载文件
            </button>
          </div>
        ` : ''}

        ${detailUrl ? `
          <div class="btn-row">
            <button class="download-btn" onclick="window.location.href='${detailUrl}'">
              <i class="bi bi-link"></i> 跳转原页面
            </button>
          </div>
        ` : ''}
      </div>
    `;
  });

  html += `</div>`; // 结束 .results-grid

  // 分页
  if (currentSearch.totalPages > 1) {
    html += `
      <div class="pagination">
        <button class="pagination-btn" ${currentSearch.currentPage <= 1 ? 'disabled' : ''} 
                onclick="goToPage(${currentSearch.currentPage - 1})">
          <i class="bi bi-chevron-left"></i> 上一页
        </button>
        <span class="pagination-info">
          第 ${currentSearch.currentPage} 页，共 ${currentSearch.totalPages} 页
        </span>
        <button class="pagination-btn" ${currentSearch.currentPage >= currentSearch.totalPages ? 'disabled' : ''} 
                onclick="goToPage(${currentSearch.currentPage + 1})">
          下一页 <i class="bi bi-chevron-right"></i>
        </button>
      </div>
    `;
  }

  resultsContainer.innerHTML = html;

  // 事件委托：绑定下载按钮
  resultsContainer.removeEventListener('click', onResultsClick);
  resultsContainer.addEventListener('click', onResultsClick);
}

// 处理点击事件（下载）
function onResultsClick(e) {
  const btn = e.target.closest('.download-btn');
  if (!btn) return;
  const rawPath = btn.getAttribute('data-path') || '';
  if (rawPath) {
    downloadFile(rawPath);
  }
}

// ===================== 分页跳转 =====================
function goToPage(page) {
  if (page < 1 || page > currentSearch.totalPages || page === currentSearch.currentPage) return;
  currentSearch.currentPage = page;
  searchIngredient();
}

// ===================== 下载核心 =====================
function downloadFile(filePath) {
  const url = buildDownloadUrl(filePath);

  fetch(url, { method: 'GET' })
    .then(response => {
      if (response.ok) return response.blob();
      return response.json().then(err => {
        throw new Error(err && err.error ? err.error : '文件下载失败');
      }).catch(() => { throw new Error('文件下载失败'); });
    })
    .then(blob => {
      const a = document.createElement('a');
      const objUrl = window.URL.createObjectURL(blob);
      a.href = objUrl;
      const fileName = String(filePath).split(/[\\/]/).pop() || 'download';
      a.download = fileName;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(objUrl);
    })
    .catch(err => {
      console.error('下载出错:', err);
      alert(err.message || '文件下载失败，请稍后重试');
    });
}
