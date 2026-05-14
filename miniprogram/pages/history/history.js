const auth = require('../../utils/auth');
const api = require('../../utils/api');

Page({
  data: {
    list: [],
    page: 1,
    loading: false,
    hasMore: true
  },

  onShow() {
    if (!auth.checkLogin()) return;
    this.loadData();
  },

  onReachBottom() {
    if (this.data.hasMore && !this.data.loading) {
      this.loadMore();
    }
  },

  loadData() {
    this.setData({ loading: true });
    api.getHistory(1).then(data => {
      this.setData({
        list: data.items || [],
        page: 1,
        loading: false,
        hasMore: (data.items || []).length >= 20
      });
    }).catch(() => {
      this.setData({ loading: false });
    });
  },

  loadMore() {
    const page = this.data.page + 1;
    this.setData({ loading: true });
    api.getHistory(page).then(data => {
      const items = this.data.list.concat(data.items || []);
      this.setData({
        list: items,
        page: page,
        loading: false,
        hasMore: (data.items || []).length >= 20
      });
    }).catch(() => {
      this.setData({ loading: false });
    });
  },

  goDetail(e) {
    const id = e.currentTarget.dataset.id;
    wx.navigateTo({ url: '/pages/history-detail/history-detail?id=' + id });
  }
});
