const auth = require('../../utils/auth');
const api = require('../../utils/api');

Page({
  data: {
    fileName: '',
    resumeText: '',
    jdText: '',
    loading: false,
    error: ''
  },

  onShow() {
    if (!auth.checkLogin()) return;
    const info = getApp().globalData.userInfo;
    if (info) {
      this.setData({ quota: info.free_quota, isPaid: info.is_paid });
    }
  },

  chooseFile() {
    const that = this;
    wx.chooseMessageFile({
      count: 1,
      type: 'file',
      extension: ['pdf', 'docx', 'doc', 'txt', 'md'],
      success(res) {
        const file = res.tempFiles[0];
        that.setData({ fileName: file.name, filePath: file.path });
      }
    });
  },

  onResumeInput(e) {
    this.setData({ resumeText: e.detail.value });
  },

  onJdInput(e) {
    this.setData({ jdText: e.detail.value });
  },

  submitAnalyze() {
    const { resumeText, fileName, filePath } = this.data;
    if (!fileName && (!resumeText || resumeText.length < 20)) {
      this.setData({ error: '请上传简历文件或粘贴至少20字简历内容' });
      return;
    }
    if (!auth.checkLogin()) return;

    this.setData({ loading: true, error: '' });

    const formData = { jd_text: this.data.jdText };
    if (fileName && filePath) {
      formData.resume_file = filePath;
    }
    if (resumeText) {
      formData.resume_text = resumeText;
    }

    // Use wx.uploadFile for multipart support
    if (fileName && filePath) {
      wx.uploadFile({
        url: getApp().globalData.apiBase + '/api/v1/analyze',
        filePath: filePath,
        name: 'resume_file',
        formData: { jd_text: this.data.jdText, resume_text: this.data.resumeText },
        header: { 'Authorization': 'Bearer ' + getApp().globalData.token },
        success(res) {
          const data = JSON.parse(res.data);
          if (data.error) {
            this.setData({ error: data.error, loading: false });
            return;
          }
          wx.navigateTo({ url: '/pages/result/result?id=' + data.analysis_id });
        },
        fail() {
          this.setData({ error: '上传失败，请重试', loading: false });
        }
      });
    } else {
      api.analyze(formData).then(data => {
        this.setData({ loading: false });
        if (data.error) {
          this.setData({ error: data.error });
          return;
        }
        wx.navigateTo({ url: '/pages/result/result?id=' + data.analysis_id });
      }).catch(() => {
        this.setData({ loading: false, error: '网络请求失败' });
      });
    }
  }
});
