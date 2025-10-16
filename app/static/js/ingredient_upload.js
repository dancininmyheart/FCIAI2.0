(function () {
  const fileInput = document.getElementById('ingredientFileInput');
  const selectButton = document.getElementById('selectIngredientFile');
  const uploadButton = document.getElementById('uploadIngredientBtn');
  const selectedInfo = document.getElementById('selectedFileInfo');
  const dropzone = document.getElementById('uploadDropzone');
  const fileListContainer = document.getElementById('fileListContainer');

  if (!fileInput || !selectButton || !uploadButton || !selectedInfo || !dropzone || !fileListContainer) {
    return;
  }

  const allowedExtensions = ['.json', '.csv', '.xls', '.xlsx', '.zip', '.rar', '.7z'];
  const originalButtonHtml = uploadButton.innerHTML;

  selectButton.addEventListener('click', () => fileInput.click());

  fileInput.addEventListener('change', updateSelectedFile);

  dropzone.addEventListener('dragover', (event) => {
    event.preventDefault();
    dropzone.classList.add('drag-over');
  });

  dropzone.addEventListener('dragleave', () => {
    dropzone.classList.remove('drag-over');
  });

  dropzone.addEventListener('drop', (event) => {
    event.preventDefault();
    dropzone.classList.remove('drag-over');
    if (!event.dataTransfer || !event.dataTransfer.files || !event.dataTransfer.files.length) {
      return;
    }
    const file = event.dataTransfer.files[0];
    if (!isAllowedExtension(file.name)) {
      showToast(`不支持的文件类型：${file.name}`, 'error');
      return;
    }
    const transfer = new DataTransfer();
    transfer.items.add(file);
    fileInput.files = transfer.files;
    updateSelectedFile();
  });

  uploadButton.addEventListener('click', () => {
    const file = fileInput.files && fileInput.files[0];
    if (!file) {
      showToast('请先选择需要上传的文件', 'warning');
      return;
    }
    if (!isAllowedExtension(file.name)) {
      showToast('文件类型不被支持，请选择 JSON/CSV/XLS/XLSX/ZIP/RAR/7Z', 'error');
      return;
    }
    uploadFile(file);
  });

  function isAllowedExtension(filename) {
    const lower = filename.toLowerCase();
    return allowedExtensions.some((ext) => lower.endsWith(ext));
  }

  function updateSelectedFile() {
    const file = fileInput.files && fileInput.files[0];
    if (!file) {
      selectedInfo.textContent = '当前未选择任何文件';
      return;
    }
    selectedInfo.textContent = `${file.name} · ${formatSize(file.size)}`;
  }

  function formatSize(size) {
    if (typeof size !== 'number' || Number.isNaN(size)) {
      return '—';
    }
    if (size >= 1024 * 1024 * 1024) {
      return `${(size / (1024 * 1024 * 1024)).toFixed(2)} GB`;
    }
    if (size >= 1024 * 1024) {
      return `${(size / (1024 * 1024)).toFixed(2)} MB`;
    }
    if (size >= 1024) {
      return `${(size / 1024).toFixed(2)} KB`;
    }
    return `${size} B`;
  }

  function setUploadingState(isUploading) {
    uploadButton.disabled = isUploading;
    uploadButton.innerHTML = isUploading
      ? '<i class="bi bi-arrow-repeat spin"></i> 正在上传...'
      : originalButtonHtml;
  }

  function clearSelection() {
    fileInput.value = '';
    updateSelectedFile();
  }

  function uploadFile(file) {
    setUploadingState(true);
    const formData = new FormData();
    formData.append('file', file);

    fetch('/ingredient/api/ingredient/upload-file', {
      method: 'POST',
      body: formData,
      credentials: 'same-origin'
    })
      .then(async (response) => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !data.success) {
          throw new Error(data.message || '文件上传失败');
        }
        showToast(data.message || '文件上传成功', 'success');
        clearSelection();
        fetchFileList();
      })
      .catch((error) => {
        console.error('Ingredient upload error:', error);
        showToast(error.message || '文件上传失败，请稍后再试', 'error');
      })
      .finally(() => {
        setUploadingState(false);
      });
  }

  function fetchFileList() {
    fileListContainer.innerHTML = '<div class="empty-state">正在加载文件列表...</div>';
    fetch('/ingredient/api/ingredient/files', { method: 'GET', credentials: 'same-origin' })
      .then(async (response) => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !data.success) {
          throw new Error(data.message || '获取文件列表失败');
        }
        renderFileList(Array.isArray(data.data) ? data.data : []);
      })
      .catch((error) => {
        console.error('Ingredient file list error:', error);
        fileListContainer.innerHTML = '<div class="empty-state">文件列表加载失败，请刷新后重试。</div>';
        showToast(error.message || '文件列表加载失败', 'error');
      });
  }

  function renderFileList(files) {
    if (!files.length) {
      fileListContainer.innerHTML = '<div class="empty-state">暂无文件，请先上传。</div>';
      return;
    }

    let rows = '';
    files.forEach((item) => {
      const name = escapeHtml(item.name || '');
      const isDirectory = Boolean(item.is_directory);
      const typeLabel = isDirectory ? '文件夹' : '文件';
      const sizeLabel = formatSize(item.size);
      const modified = escapeHtml(item.modified_at || '—');
      const downloadUrl = item.download_url || '#';
      const downloadLabel = isDirectory ? '下载文件夹（ZIP）' : '下载文件';

      rows += `
        <tr>
          <td>${name}</td>
          <td>${typeLabel}</td>
          <td>${sizeLabel}</td>
          <td>${modified}</td>
          <td><a class="download-link" href="${downloadUrl}" target="_blank" rel="noopener">${downloadLabel}</a></td>
        </tr>
      `;
    });

    fileListContainer.innerHTML = `
      <table class="file-table">
        <thead>
          <tr>
            <th>名称</th>
            <th>类型</th>
            <th>大小</th>
            <th>最近更新</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    `;
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  fetchFileList();
})();
