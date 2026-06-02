const fs = require('fs');
const path = require('path');

const rootDir = path.resolve(__dirname, '..');
const contentPath = path.join(rootDir, 'scratch', 'content.html');
const outputPath = path.join(rootDir, 'scratch', 'index.html');

if (!fs.existsSync(contentPath)) {
  console.error("Error: content.html does not exist.");
  process.exit(1);
}

const content = fs.readFileSync(contentPath, 'utf8');

const htmlTemplate = `<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="UTF-8">
  <title>2026 熊本阿蘇 7 日親子自駕：終極作戰手冊 (旅行大師 Edition)</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700&display=swap');
    
    @page {
      size: A4;
      margin: 20mm 15mm 20mm 15mm;
      @bottom-right {
        content: counter(page);
        font-family: 'Noto Sans TC', 'Microsoft JhengHei', sans-serif;
        font-size: 9pt;
        color: #718096;
      }
    }
    
    body {
      font-family: 'Noto Sans TC', 'Microsoft JhengHei', system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      font-size: 10.5pt;
      line-height: 1.6;
      color: #2d3748;
      background-color: #ffffff;
      margin: 0;
      padding: 0;
    }

    h1, h2, h3, h4, h5, h6 {
      color: #1a202c;
      font-weight: 700;
      margin-top: 1.5em;
      margin-bottom: 0.5em;
      page-break-after: avoid;
    }

    h1 {
      font-size: 22pt;
      border-bottom: 2px solid #e2e8f0;
      padding-bottom: 8px;
      margin-top: 0;
      color: #0f172a;
    }

    /* 針對主要的每一章，我們可以在 PDF 輸出時強制分頁 */
    h1:not(:first-of-type) {
      page-break-before: always;
      margin-top: 20px;
    }

    h2 {
      font-size: 16pt;
      border-bottom: 1px solid #edf2f7;
      padding-bottom: 6px;
      color: #1e293b;
    }

    h3 {
      font-size: 13pt;
      color: #334155;
    }

    h4 {
      font-size: 11pt;
      color: #475569;
    }

    p {
      margin-top: 0;
      margin-bottom: 1em;
      text-align: justify;
    }

    a {
      color: #2b6cb0;
      text-decoration: none;
    }

    hr {
      border: 0;
      border-top: 1px solid #e2e8f0;
      margin: 20px 0;
    }

    blockquote {
      margin: 1.5em 0;
      padding: 12px 18px;
      background-color: #f8fafc;
      border-left: 4px solid #3b82f6;
      color: #475569;
      border-radius: 0 6px 6px 0;
      page-break-inside: avoid;
    }
    
    blockquote p {
      margin: 0;
    }

    /* 表格樣式極度重要，為了美觀與防斷開 */
    table {
      width: 100%;
      border-collapse: collapse;
      margin: 1.5em 0;
      font-size: 9.5pt;
      page-break-inside: avoid;
    }

    tr {
      page-break-inside: avoid;
      page-break-after: auto;
    }

    th, td {
      border: 1px solid #cbd5e1;
      padding: 8px 10px;
      text-align: left;
    }

    th {
      background-color: #f1f5f9;
      color: #1e293b;
      font-weight: 700;
    }

    tbody tr:nth-child(even) {
      background-color: #f8fafc;
    }

    ul, ol {
      margin-top: 0;
      margin-bottom: 1em;
      padding-left: 20px;
    }

    li {
      margin-bottom: 0.4em;
    }

    code {
      font-family: Consolas, Monaco, 'Andale Mono', 'Ubuntu Mono', monospace;
      background-color: #f1f5f9;
      padding: 2px 6px;
      font-size: 90%;
      border-radius: 4px;
      color: #0f172a;
    }

    pre {
      font-family: Consolas, Monaco, 'Andale Mono', 'Ubuntu Mono', monospace;
      background-color: #f8fafc;
      border: 1px solid #e2e8f0;
      padding: 15px;
      overflow: auto;
      border-radius: 6px;
      margin: 1.5em 0;
      page-break-inside: avoid;
    }

    pre code {
      background-color: transparent;
      padding: 0;
      font-size: 9pt;
      color: inherit;
    }

    /* 強制手動分頁的 class */
    .page-break {
      page-break-before: always;
    }

    /* 熊本熊主題彩蛋與樣式 */
    .highlight-box {
      border: 1px solid #fca5a5;
      background-color: #fef2f2;
      padding: 12px;
      border-radius: 6px;
      margin: 1em 0;
      border-left: 4px solid #ef4444;
    }

    /* 調整表格裡的清單，讓它更緊湊 */
    td ul, td ol {
      margin: 0;
      padding-left: 15px;
    }
  </style>
</head>
<body>
  <div style="max-width: 100%;">
    ${content}
  </div>
</body>
</html>
`;

fs.writeFileSync(outputPath, htmlTemplate, 'utf8');
console.log("SUCCESS: index.html has been generated successfully.");
