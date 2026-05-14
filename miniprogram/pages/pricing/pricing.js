const auth = require('../../utils/auth');
const api = require('../../utils/api');

Page({
  data: {
    quota: 0,
    showPayment: false,
    qrCode: '',
    orderNo: '',
    mockMode: false,
    payPlanName: '',
    payAmount: '',
    payStatus: '',
    payMsg: '',
    pollTimer: null
  },

  onShow() {
    if (!auth.checkLogin()) return;
    const info = getApp().globalData.userInfo;
    if (info) {
      this.setData({ quota: info.free_quota });
    }
  },

  buy(e) {
    const plan = e.currentTarget.dataset.plan;
    const nameMap = { single: '单次分析', monthly: '包月无限次' };
    const priceMap = { single: '¥9.90', monthly: '¥29.90/月' };

    if (!auth.checkLogin()) return;

    this.setData({
      showPayment: true,
      qrCode: '',
      mockMode: false,
      payPlanName: nameMap[plan] || plan,
      payAmount: priceMap[plan] || '',
      payStatus: '',
      payMsg: ''
    });

    api.createOrder(plan).then(data => {
      if (data.error) {
        this.setData({ payMsg: data.error, payStatus: 'fail' });
        return;
      }
      this.setData({ orderNo: data.order_no });
      if (data.mock) {
        this.setData({ mockMode: true, payAmount: '¥' + data.amount + ' - ' + data.plan_name });
      } else if (data.qr_code) {
        this.setData({ qrCode: data.qr_code });
        this.startPoll();
      }
    }).catch(() => {
      this.setData({ payMsg: '创建订单失败', payStatus: 'fail' });
    });
  },

  startPoll() {
    if (this.data.pollTimer) clearInterval(this.data.pollTimer);
    const timer = setInterval(() => {
      api.getPaymentStatus(this.data.orderNo).then(data => {
        if (data.status === 'paid') {
          clearInterval(timer);
          this.setData({ payMsg: '支付成功！', payStatus: 'paid' });
          setTimeout(() => {
            this.setData({ showPayment: false });
            getApp().fetchUserInfo();
            wx.showToast({ title: '购买成功', icon: 'success' });
          }, 1500);
        }
      });
    }, 3000);
    this.setData({ pollTimer: timer });
  },

  simulatePay() {
    wx.request({
      url: getApp().globalData.apiBase + '/api/payment/simulate/' + this.data.orderNo,
      method: 'POST',
      header: { 'Authorization': 'Bearer ' + getApp().globalData.token },
      success: res => {
        if (res.data.status === 'paid') {
          this.setData({ payMsg: '支付成功！', payStatus: 'paid' });
          setTimeout(() => {
            this.setData({ showPayment: false });
            getApp().fetchUserInfo();
            wx.showToast({ title: '购买成功', icon: 'success' });
          }, 1500);
        }
      }
    });
  },

  closePayment() {
    if (this.data.pollTimer) {
      clearInterval(this.data.pollTimer);
      this.setData({ pollTimer: null });
    }
    this.setData({ showPayment: false });
  }
});
