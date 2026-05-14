const auth = require('../../utils/auth');
const api = require('../../utils/api');

Page({
  data: {
    loading: false,
    error: '',
    userInfo: null,
    phone: '',
    email: '',
    bindMsg: '',
    bindOk: false
  },

  onLoad() {
    const info = getApp().globalData.userInfo;
    if (info) {
      this.setData({ userInfo: info });
    }
  },

  wxLogin() {
    this.setData({ loading: true, error: '' });
    auth.login().then(data => {
      this.setData({ loading: false, userInfo: data });
      wx.showToast({ title: '登录成功', icon: 'success' });
      setTimeout(() => { wx.switchTab({ url: '/pages/index/index' }); }, 1000);
    }).catch(err => {
      this.setData({ loading: false, error: err.message || '登录失败' });
    });
  },

  onPhoneInput(e) { this.setData({ phone: e.detail.value }); },
  onEmailInput(e) { this.setData({ email: e.detail.value }); },

  bindInfo() {
    const { phone, email } = this.data;
    if (!phone && !email) {
      this.setData({ bindMsg: '请填写手机号或邮箱', bindOk: false });
      return;
    }
    api.bindUser({ phone, email }).then(data => {
      if (data.error) {
        this.setData({ bindMsg: data.error, bindOk: false });
      } else {
        this.setData({ bindMsg: '绑定成功', bindOk: true });
      }
    }).catch(() => {
      this.setData({ bindMsg: '绑定失败', bindOk: false });
    });
  }
});
