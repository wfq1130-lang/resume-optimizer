const api = require('./api');
const app = getApp();

function login() {
  return new Promise((resolve, reject) => {
    wx.login({
      success(res) {
        if (res.code) {
          api.login(res.code).then(data => {
            if (data.token) {
              wx.setStorageSync('token', data.token);
              app.globalData.token = data.token;
              resolve(data);
            } else {
              reject(new Error(data.error || '登录失败'));
            }
          }).catch(reject);
        } else {
          reject(new Error('wx.login 失败'));
        }
      },
      fail: reject
    });
  });
}

function checkLogin() {
  const token = app.globalData.token;
  if (!token) {
    wx.navigateTo({ url: '/pages/login/login' });
    return false;
  }
  return true;
}

function logout() {
  wx.removeStorageSync('token');
  app.globalData.token = '';
  app.globalData.userInfo = null;
  wx.navigateTo({ url: '/pages/index/index' });
}

module.exports = { login, checkLogin, logout };
