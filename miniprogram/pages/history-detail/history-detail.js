const api = require('../../utils/api');

Page({
  data: {
    data: {},
    scores: [],
    suggestions: [],
    error: ''
  },

  onLoad(options) {
    const id = options.id;
    if (!id) {
      this.setData({ error: '缺少记录ID' });
      return;
    }
    api.getResult(id).then(data => {
      if (data.error) {
        this.setData({ error: data.error });
        return;
      }
      const scoresArr = [];
      if (data.scores) {
        Object.keys(data.scores).forEach(k => {
          scoresArr.push({ name: k, value: data.scores[k] });
        });
      }
      this.setData({
        data: data,
        scores: scoresArr,
        suggestions: data.suggestions || []
      });
    }).catch(() => {
      this.setData({ error: '加载失败' });
    });
  }
});
