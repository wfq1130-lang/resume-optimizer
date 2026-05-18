document.addEventListener('DOMContentLoaded', () => {
  chrome.storage.local.get(['apiBase', 'token'], (items) => {
    document.getElementById('api-base').value = items.apiBase || '';
    if (items.token) {
      document.getElementById('account-info').innerHTML = '<span style="color:#22c55e;font-weight:600">已登录</span>';
    }
  });

  document.getElementById('save-api-btn').addEventListener('click', () => {
    const apiBase = document.getElementById('api-base').value.trim();
    if (!apiBase) {
      showStatus('api-status', '请输入服务器地址', 'error');
      return;
    }
    chrome.storage.local.set({ apiBase }, () => {
      showStatus('api-status', '保存成功', 'success');
    });
  });

  document.getElementById('logout-btn').addEventListener('click', () => {
    chrome.storage.local.remove('token', () => {
      document.getElementById('account-info').innerHTML = '<span style="color:#ef4444">已退出</span>';
    });
  });
});

function showStatus(id, msg, type) {
  const el = document.getElementById(id);
  el.textContent = msg;
  el.className = 'status ' + type;
  setTimeout(() => { el.textContent = ''; el.className = 'status'; }, 3000);
}
