({
  // Please visit the URL below for more information:
  // https://shd101wyy.github.io/markdown-preview-enhanced/#/extend-parser

  onWillParseMarkdown: async function(markdown) {
    return markdown;
  },

  onDidParseMarkdown: async function(html) {
    return html.replaceAll(/=議題(\d+)=/g, '<span class="el-tag el-tag--dark issue">議題$1</span>');
  },
})