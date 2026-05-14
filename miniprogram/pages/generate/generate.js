const auth = require('../../utils/auth');
const api = require('../../utils/api');

Page({
  data: {
    userInput: '',
    scene: '',
    loading: false,
    error: '',
    result: '',
    tips: ''
  },

  onInput(e) {
    this.setData({ userInput: e.detail.value });
  },

  selectScene(e) {
    const s = e.currentTarget.dataset.scene;
    this.setData({ scene: this.data.scene === s ? '' : s });
  },

  submitGenerate() {
    const { userInput } = this.data;
    if (!userInput || userInput.length < 10) {
      this.setData({ error: '请至少输入10个字描述你的情况' });
      return;
    }
    if (!auth.checkLogin()) return;

    this.setData({ loading: true, error: '' });
    api.generate({ user_input: userInput, scene: this.data.scene }).then(data => {
      this.setData({ loading: false });
      if (data.error) {
        this.setData({ error: data.error });
        return;
      }
      this.setData({ result: data.resume_text, tips: data.tips });
    }).catch(() => {
      this.setData({ loading: false, error: '网络请求失败' });
    });
  }
});
