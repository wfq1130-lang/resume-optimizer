// Content script — injects "AI优化" button into job sites

(function() {
  'use strict';

  // Site-specific selectors for extracting resume text and JD text
  const SITE_CONFIG = {
    'zhaopin.com': {
      resume: ['.resume-preview', '.resume-detail-content', '.resume-box'],
      jd: ['.job-detail-box', '.job-description', '.jd-content']
    },
    'liepin.com': {
      resume: ['.resume-content', '.resume-preview-box'],
      jd: ['.job-description', '.job-detail', '.job-main']
    },
    'zhipin.com': {
      resume: ['.resume-container', '.resume-preview'],
      jd: ['.job-detail', '.job-sec', '.detail-content']
    },
    '51job.com': {
      resume: ['.resume-box', '.resume-preview'],
      jd: ['.job-detail', '.bmsg.job-box', '.job-detail-box']
    },
    'linkedin.com': {
      resume: ['.profile-section', '.resume-view', '.resume-content'],
      jd: ['.job-description', '.description__text', '.jobs-description']
    },
    'indeed.com': {
      resume: ['.resume-view', '.resume-content', '.resume-body'],
      jd: ['.job-description', '#jobDescriptionText', '.jobsearch-jobDescriptionText']
    },
    'glassdoor.com': {
      resume: ['.resume-content', '.profile-body'],
      jd: ['.job-description', '.desc', '.jd-body']
    }
  };

  const host = window.location.hostname;
  let config = null;
  for (const key in SITE_CONFIG) {
    if (host.includes(key)) {
      config = SITE_CONFIG[key];
      break;
    }
  }
  if (!config) return;

  // Inject floating action button
  function injectButton() {
    if (document.getElementById('ai-resume-optimizer-btn')) return;

    const container = document.createElement('div');
    container.id = 'ai-resume-optimizer-btn';
    container.innerHTML = `
      <button id="ai-opt-btn" title="AI优化简历">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 013 3L7 19l-4 1 1-4L16.5 3.5z"/>
        </svg>
        AI优化
      </button>
    `;
    document.body.appendChild(container);
    document.getElementById('ai-opt-btn').addEventListener('click', onOptimizeClick);
  }

  // Extract text from page using configured selectors
  function extractText(selectors) {
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el && el.textContent.trim().length > 50) {
        return el.textContent.trim();
      }
    }
    // Fallback: try to find largest text block
    const articles = document.querySelectorAll('article, .main-content, [role="main"]');
    for (const article of articles) {
      if (article.textContent.trim().length > 100) {
        return article.textContent.trim();
      }
    }
    return '';
  }

  function onOptimizeClick() {
    const resumeText = extractText(config.resume);
    const jdText = extractText(config.jd);

    if (!resumeText && !jdText) {
      showToast('未能识别简历或JD内容，请手动复制到弹窗中分析');
      chrome.runtime.sendMessage({ type: 'OPEN_POPUP' });
      return;
    }

    showOverlay(resumeText, jdText);
  }

  // Show analysis results in an overlay
  function showOverlay(resumeText, jdText) {
    // Remove existing overlay
    const existing = document.getElementById('ai-opt-overlay');
    if (existing) existing.remove();

    const overlay = document.createElement('div');
    overlay.id = 'ai-opt-overlay';
    overlay.innerHTML = `
      <div class="ai-opt-overlay-mask"></div>
      <div class="ai-opt-overlay-panel">
        <div class="ai-opt-overlay-header">
          <h3>AI简历优化</h3>
          <button class="ai-opt-close">&times;</button>
        </div>
        <div class="ai-opt-overlay-body">
          <div class="ai-opt-section">
            <label>简历内容 ${resumeText ? '' : '(未识别)'}</label>
            <textarea id="ai-opt-resume" rows="5">${resumeText}</textarea>
          </div>
          <div class="ai-opt-section">
            <label>JD描述 ${jdText ? '' : '(未识别)'}</label>
            <textarea id="ai-opt-jd" rows="3">${jdText}</textarea>
          </div>
          <button id="ai-opt-start" class="ai-opt-btn-primary">开始分析</button>
          <div id="ai-opt-result" style="display:none;margin-top:12px"></div>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    overlay.querySelector('.ai-opt-close').addEventListener('click', () => overlay.remove());
    overlay.querySelector('.ai-opt-overlay-mask').addEventListener('click', () => overlay.remove());
    overlay.querySelector('#ai-opt-start').addEventListener('click', async () => {
      const resume = overlay.querySelector('#ai-opt-resume').value.trim();
      const jd = overlay.querySelector('#ai-opt-jd').value.trim();
      if (!resume || resume.length < 20) {
        alert('简历内容至少需要20个字');
        return;
      }
      const btn = overlay.querySelector('#ai-opt-start');
      btn.disabled = true;
      btn.textContent = '分析中...';

      chrome.runtime.sendMessage({
        type: 'ANALYZE',
        data: { resumeText: resume, jdText: jd }
      }, (result) => {
        btn.disabled = false;
        btn.textContent = '开始分析';
        showResult(overlay, result);
      });
    });
  }

  function showResult(overlay, result) {
    const container = overlay.querySelector('#ai-opt-result');
    container.style.display = 'block';

    if (result.error) {
      container.innerHTML = `<div style="color:#ef4444;font-size:13px">${result.error}</div>`;
      return;
    }

    let scoresHtml = '';
    if (result.scores) {
      scoresHtml = '<div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px">';
      for (const [k, v] of Object.entries(result.scores)) {
        scoresHtml += `<span style="background:#ede9fe;color:#4f46e5;padding:2px 8px;border-radius:4px;font-size:12px">${k}: ${v}</span>`;
      }
      scoresHtml += '</div>';
    }

    const suggestions = (result.suggestions || []).slice(0, 5).map((s, i) => `<li>${s}</li>`).join('');

    container.innerHTML = `
      <div style="background:#f8fafc;border-radius:8px;padding:12px;margin-top:10px">
        <div style="font-size:16px;font-weight:700;color:#4f46e5;margin-bottom:6px">综合评分: ${result.overall_score || '--'}</div>
        ${scoresHtml}
        ${suggestions ? '<ul style="font-size:12px;color:#475569;line-height:1.8;padding-left:16px">' + suggestions + '</ul>' : ''}
        ${result.optimized_resume ? `<details style="margin-top:8px"><summary style="cursor:pointer;font-weight:600;font-size:13px">查看优化后的简历</summary><pre style="white-space:pre-wrap;font-size:12px;background:#fff;padding:8px;border-radius:4px;max-height:300px;overflow:auto">${result.optimized_resume}</pre></details>` : ''}
      </div>
    `;
  }

  function showToast(msg) {
    const toast = document.createElement('div');
    toast.style.cssText = 'position:fixed;bottom:24px;right:24px;background:#1e293b;color:#fff;padding:10px 20px;border-radius:8px;font-size:13px;z-index:99999;animation:fadeIn .3s';
    toast.textContent = msg;
    document.body.appendChild(toast);
    setTimeout(() => { toast.style.opacity = '0'; setTimeout(() => toast.remove(), 300); }, 3000);
  }

  // Watch for DOM changes (SPA navigation)
  let debounceTimer;
  const observer = new MutationObserver(() => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(injectButton, 500);
  });
  observer.observe(document.body, { childList: true, subtree: true });

  // Initial injection
  if (document.readyState === 'complete') {
    injectButton();
  } else {
    window.addEventListener('load', injectButton);
  }
})();
