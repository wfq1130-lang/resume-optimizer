// Background service worker — proxy API requests and manage auth

const DEFAULT_API_BASE = 'http://127.0.0.1:5001';

// On install, set defaults
chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.sync.get(['apiBase', 'token'], (items) => {
    if (!items.apiBase) {
      chrome.storage.sync.set({ apiBase: DEFAULT_API_BASE });
    }
  });
});

// Listen for messages from popup or content scripts
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  switch (message.type) {
    case 'ANALYZE':
      handleAnalyze(message.data, sendResponse);
      return true; // async

    case 'GENERATE':
      handleGenerate(message.data, sendResponse);
      return true;

    case 'GET_HISTORY':
      handleGetHistory(sendResponse);
      return true;

    case 'GET_RESULT':
      handleGetResult(message.data, sendResponse);
      return true;

    case 'LOGIN':
      handleLogin(message.data, sendResponse);
      return true;

    case 'REGISTER':
      handleRegister(message.data, sendResponse);
      return true;

    case 'GET_USER_INFO':
      handleGetUserInfo(sendResponse);
      return true;

    case 'GET_TOKEN':
      chrome.storage.sync.get(['token'], (items) => sendResponse({ token: items.token || '' }));
      return true;

    default:
      sendResponse({ error: 'Unknown message type' });
  }
});

function getBase() {
  return new Promise(resolve => {
    chrome.storage.sync.get(['apiBase'], (items) => {
      resolve(items.apiBase || DEFAULT_API_BASE);
    });
  });
}

function getToken() {
  return new Promise(resolve => {
    chrome.storage.sync.get(['token'], (items) => {
      resolve(items.token || '');
    });
  });
}

async function apiCall(path, options = {}) {
  const base = await getBase();
  const token = await getToken();
  const headers = options.headers || {};
  if (token) {
    headers['Authorization'] = 'Bearer ' + token;
  }

  const resp = await fetch(base + path, {
    method: options.method || 'GET',
    headers,
    body: options.body
  });

  if (resp.status === 401) {
    await chrome.storage.sync.remove('token');
    return { error: '未登录，请先登录' };
  }
  return resp.json();
}

async function handleAnalyze(data, sendResponse) {
  try {
    const formData = new FormData();
    if (data.resumeText) formData.append('resume_text', data.resumeText);
    if (data.jdText) formData.append('jd_text', data.jdText);
    if (data.resumeFile) formData.append('resume_file', data.resumeFile);

    const base = await getBase();
    const token = await getToken();
    const resp = await fetch(base + '/api/v1/analyze', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token },
      body: formData
    });
    const result = await resp.json();
    sendResponse(result);
  } catch (e) {
    sendResponse({ error: '请求失败: ' + e.message });
  }
}

async function handleGenerate(data, sendResponse) {
  try {
    const base = await getBase();
    const token = await getToken();
    const formData = new URLSearchParams();
    formData.append('user_input', data.userInput);
    if (data.scene) formData.append('scene', data.scene);

    const resp = await fetch(base + '/api/v1/generate', {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer ' + token,
        'Content-Type': 'application/x-www-form-urlencoded'
      },
      body: formData.toString()
    });
    sendResponse(await resp.json());
  } catch (e) {
    sendResponse({ error: '请求失败: ' + e.message });
  }
}

async function handleGetHistory(sendResponse) {
  try {
    const result = await apiCall('/api/v1/history');
    sendResponse(result);
  } catch (e) {
    sendResponse({ error: '请求失败' });
  }
}

async function handleGetResult(data, sendResponse) {
  try {
    const result = await apiCall('/api/v1/result/' + data.id);
    sendResponse(result);
  } catch (e) {
    sendResponse({ error: '请求失败' });
  }
}

async function handleLogin(data, sendResponse) {
  try {
    const base = await getBase();
    const resp = await fetch(base + '/api/v1/credentials-login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account: data.account, password: data.password })
    });
    const result = await resp.json();
    if (result.token) {
      await chrome.storage.sync.set({ token: result.token });
      sendResponse({ ok: true, user: result });
    } else {
      sendResponse({ error: result.error || '登录失败' });
    }
  } catch (e) {
    sendResponse({ error: '登录失败: ' + e.message });
  }
}

async function handleRegister(data, sendResponse) {
  try {
    const base = await getBase();
    const resp = await fetch(base + '/api/v1/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: data.username, password: data.password, email: data.email || '' })
    });
    const result = await resp.json();
    if (result.token) {
      await chrome.storage.sync.set({ token: result.token });
      sendResponse({ ok: true, user: result });
    } else {
      sendResponse({ error: result.error || '注册失败' });
    }
  } catch (e) {
    sendResponse({ error: '注册失败: ' + e.message });
  }
}

async function handleGetUserInfo(sendResponse) {
  try {
    const result = await apiCall('/api/v1/user/info');
    sendResponse(result);
  } catch (e) {
    sendResponse({ error: '获取用户信息失败' });
  }
}
