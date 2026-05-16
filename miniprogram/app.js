App({
  onLaunch() {
    const token = wx.getStorageSync('token');
    this.globalData.token = token || '';
    if (token) {
      this.fetchUserInfo();
    }
  },

  globalData: {
    token: '',
    apiBase: 'http://127.0.0.1:5002',
    userInfo: null
  },

  fetchUserInfo() {
    const that = this;
    wx.request({
      url: that.globalData.apiBase + '/api/v1/user/info',
      header: { 'Authorization': 'Bearer ' + that.globalData.token },
      success(res) {
        if (res.statusCode === 200) {
          that.globalData.userInfo = res.data;
        } else {
          wx.removeStorageSync('token');
          that.globalData.token = '';
        }
      },
      fail() {
        that.globalData.token = '';
      }
    });
  }
});
