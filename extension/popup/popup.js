// Popup logic

document.addEventListener('DOMContentLoaded', () => {
  checkAuth();
  bindEvents();
});

function bindEvents() {
  // Login
  document.getElementById('login-btn').addEventListener('click', doLogin);
  document.getElementById('register-btn').addEventListener('click', doRegister);
  document.getElementById('go-register').addEventListener('click', (e) => {
    e.preventDefault();
    document.getElementById('not-logged-in').style.display = 'none';
    document.getElementById('register-form').style.display = 'block';
  });
  document.getElementById('go-login').addEventListener('click', (e) => {
    e.preventDefault();
    document.getElementById('register-form').style.display = 'none';
    document.getElementById('not-logged-in').style.display = 'block';
  });

  // Tabs
  document.querySelectorAll('.tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      document.querySelectorAll('.tab-content').forEach(c => c.style.display = 'none');
      document.getElementById('tab-' + btn.dataset.tab).style.display = 'block';
    });
  });

  // Actions
  document.getElementById('analyze-btn').addEventListener('click', doAnalyze);
  document.getElementById('generate-btn').addEventListener('click', doGenerate);
  document.getElementById('logout-btn').addEventListener('click', doLogout);
}

function checkAuth() {
  chrome.storage.local.get(['token'], (items) => {
    if (items.token) {
      showLoggedIn();
    } else {
      showLoggedOut();
    }
  });
}

function showLoggedIn() {
  document.getElementById('not-logged-in').style.display = 'none';
  document.getElementById('register-form').style.display = 'none';
  document.getElementById('logged-in').style.display = 'block';
  document.querySelector('.status-dot').classList.add('logged-in');

  // Fetch user info
  chrome.runtime.sendMessage({ type: 'GET_USER_INFO' }, (resp) => {
    if (resp && resp.username) {
      document.getElementById('user-name').textContent = resp.realname || resp.username;
      document.getElementById('user-quota').textContent = resp.free_quota || 0;
    }
  });

  loadHistory();
}

function showLoggedOut() {
  document.getElementById('logged-in').style.display = 'none';
  document.getElementById('register-form').style.display = 'none';
  document.getElementById('not-logged-in').style.display = 'block';
  document.querySelector('.status-dot').classList.remove('logged-in');
}

function doLogin() {
  const account = document.getElementById('login-account').value.trim();
  const password = document.getElementById('login-password').value;
  if (!account || !password) {
    showError('login-error', '请填写账号和密码');
    return;
  }

  document.getElementById('login-btn').disabled = true;
  document.getElementById('login-btn').textContent = '登录中...';

  chrome.runtime.sendMessage({
    type: 'LOGIN',
    data: { account, password }
  }, (resp) => {
    document.getElementById('login-btn').disabled = false;
    document.getElementById('login-btn').textContent = '登录';
    if (resp && resp.ok) {
      showLoggedIn();
    } else {
      showError('login-error', (resp && resp.error) || '登录失败');
    }
  });
}

function doRegister() {
  const username = document.getElementById('reg-username').value.trim();
  const password = document.getElementById('reg-password').value;
  const email = document.getElementById('reg-email').value.trim();

  if (!username || !password) {
    showError('reg-error', '请填写用户名和密码');
    return;
  }
  if (username.length < 3) {
    showError('reg-error', '用户名至少3位');
    return;
  }
  if (password.length < 6) {
    showError('reg-error', '密码至少6位');
    return;
  }

  document.getElementById('register-btn').disabled = true;
  document.getElementById('register-btn').textContent = '注册中...';

  chrome.runtime.sendMessage({
    type: 'REGISTER',
    data: { username, password, email }
  }, (resp) => {
    document.getElementById('register-btn').disabled = false;
    document.getElementById('register-btn').textContent = '注册';
    if (resp && resp.ok) {
      document.getElementById('register-form').style.display = 'none';
      document.getElementById('not-logged-in').style.display = 'block';
      alert('注册成功，请登录');
    } else {
      showError('reg-error', (resp && resp.error) || '注册失败');
    }
  });
}

function doAnalyze() {
  const resumeFile = document.getElementById('resume-file').files[0];
  const resumeText = document.getElementById('resume-text').value.trim();
  const jdText = document.getElementById('jd-text').value.trim();

  if (!resumeFile && (!resumeText || resumeText.length < 20)) {
    alert('请上传简历文件或粘贴至少20字简历内容');
    return;
  }

  const btn = document.getElementById('analyze-btn');
  btn.disabled = true;
  btn.textContent = '分析中...';
  document.getElementById('analyze-result').style.display = 'none';

  chrome.runtime.sendMessage({
    type: 'ANALYZE',
    data: { resumeText, jdText, resumeFile }
  }, (result) => {
    btn.disabled = false;
    btn.textContent = '开始分析';
    showResult('analyze-result', result);
  });
}

function doGenerate() {
  const userInput = document.getElementById('gen-input').value.trim();
  const scene = document.getElementById('gen-scene').value;

  if (!userInput || userInput.length < 10) {
    alert('请至少输入10个字');
    return;
  }

  const btn = document.getElementById('generate-btn');
  btn.disabled = true;
  btn.textContent = '生成中...';
  document.getElementById('gen-result').style.display = 'none';

  chrome.runtime.sendMessage({
    type: 'GENERATE',
    data: { userInput, scene }
  }, (result) => {
    btn.disabled = false;
    btn.textContent = 'AI生成';
    showResult('gen-result', result);
  });
}

function loadHistory() {
  chrome.runtime.sendMessage({ type: 'GET_HISTORY' }, (data) => {
    const container = document.getElementById('history-list');
    if (!data || data.error) {
      container.innerHTML = '<p style="color:#94a3b8;text-align:center;padding:20px">暂无记录</p>';
      return;
    }
    const items = (data.items || []).slice(0, 5);
    if (!items.length) {
      container.innerHTML = '<p style="color:#94a3b8;text-align:center;padding:20px">暂无记录</p>';
      return;
    }
    container.innerHTML = items.map(item => `
      <div class="history-item" data-id="${item.id}">
        <span>${item.resume_filename || '文本输入'}</span>
        <span style="font-weight:700;color:#4f46e5">${item.overall_score || '--'}</span>
      </div>
    `).join('');

    container.querySelectorAll('.history-item').forEach(el => {
      el.addEventListener('click', () => {
        chrome.runtime.sendMessage({ type: 'GET_RESULT', data: { id: el.dataset.id } }, (result) => {
          showResult('analyze-result', result);
          document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
          document.querySelector('.tab[data-tab="optimize"]').classList.add('active');
          document.querySelectorAll('.tab-content').forEach(c => c.style.display = 'none');
          document.getElementById('tab-optimize').style.display = 'block';
          window.scrollTo(0, document.getElementById('analyze-result').offsetTop);
        });
      });
    });
  });
}

function showResult(containerId, result) {
  const container = document.getElementById(containerId);
  container.style.display = 'block';

  if (!result || result.error) {
    container.innerHTML = `<div class="error">${result ? result.error : '请求失败'}</div>`;
    return;
  }

  const scoresHtml = result.scores ?
    Object.entries(result.scores).map(([k, v]) => `<span style="background:#ede9fe;color:#4f46e5;padding:2px 8px;border-radius:4px;font-size:11px">${k}: ${v}</span>`).join(' ') : '';

  const suggestionsHtml = (result.suggestions || []).slice(0, 5)
    .map(s => `<li>${s}</li>`).join('');

  container.innerHTML = `
    <div class="result-box">
      <h4>综合评分: ${result.overall_score || '--'}</h4>
      ${scoresHtml ? '<div style="display:flex;flex-wrap:wrap;gap:4px;margin:8px 0">' + scoresHtml + '</div>' : ''}
      ${suggestionsHtml ? '<ul style="margin-top:8px">' + suggestionsHtml + '</ul>' : ''}
      ${result.optimized_resume ? `
        <details style="margin-top:8px">
          <summary style="cursor:pointer;font-weight:600">优化后的简历</summary>
          <pre>${result.optimized_resume}</pre>
        </details>
      ` : ''}
      ${result.resume_text ? `
        <details style="margin-top:8px">
          <summary style="cursor:pointer;font-weight:600">生成的简历</summary>
          <pre>${result.resume_text}</pre>
        </details>
      ` : ''}
    </div>
  `;
}

function showError(id, msg) {
  const el = document.getElementById(id);
  el.textContent = msg;
  el.style.display = 'block';
  setTimeout(() => { el.style.display = 'none'; }, 3000);
}

function doLogout() {
  chrome.storage.local.remove('token', () => {
    showLoggedOut();
  });
}
