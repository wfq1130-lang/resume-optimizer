const app = getApp();

function request(path, options = {}) {
  const token = app.globalData.token;
  const header = options.header || {};
  if (token) {
    header['Authorization'] = 'Bearer ' + token;
  }
  const url = app.globalData.apiBase + path;

  return new Promise((resolve, reject) => {
    wx.request({
      url,
      method: options.method || 'GET',
      data: options.data,
      header,
      success(res) {
        if (res.statusCode === 401) {
          wx.removeStorageSync('token');
          app.globalData.token = '';
          wx.navigateTo({ url: '/pages/login/login' });
          reject(new Error('未登录'));
          return;
        }
        resolve(res.data);
      },
      fail(err) {
        reject(err);
      }
    });
  });
}

module.exports = {
  login(code) {
    return request('/api/v1/wx-login', { method: 'POST', data: { code } });
  },

  getUserInfo() {
    return request('/api/v1/user/info');
  },

  bindUser(data) {
    return request('/api/v1/user/bind', { method: 'POST', data });
  },

  analyze(formData) {
    return request('/api/v1/analyze', {
      method: 'POST',
      data: formData
    });
  },

  generate(data) {
    return request('/api/v1/generate', { method: 'POST', data });
  },

  getHistory(page = 1) {
    return request('/api/v1/history?page=' + page);
  },

  getResult(id) {
    return request('/api/v1/result/' + id);
  },

  createOrder(planType) {
    return request('/api/v1/create-order', {
      method: 'POST',
      data: { plan_type: planType }
    });
  },

  getPaymentStatus(orderNo) {
    return request('/api/v1/payment/status/' + orderNo);
  }
};
