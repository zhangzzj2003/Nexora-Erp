import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { Marked } from 'marked'
import { renderMarkdown } from '../scripts/build-docs-site.mjs'

// Windows 检出使用 CRLF，统一换行后再按标题提取章节。
const readme = readFileSync(new URL('../README.md', import.meta.url), 'utf8').replace(/\r\n/g, '\n')
const progress = readme.split('## 开发进度\n')[1].split('\n## ')[0]
const table = new Marked().lexer(progress).find(token => token.type === 'table')

// U+2060 不占显示宽度，只约束中文断行；不能插入链接地址或长说明。
test('开发进度的阶段与状态禁止逐字断行，说明仍可自然换行', () => {
  assert.ok(table)
  assert.equal(table.header.length, 3)
  assert.ok(table.rows.length >= 20)
  for (const row of [table.header, ...table.rows]) {
    for (const cell of row.slice(0, 2)) {
      const label = cell.tokens.find(token => token.type === 'link')?.text ?? cell.text
      assert.ok(label.includes('\u2060'), label)
      assert.ok(label.split('\u2060').every(character => [...character].length === 1), label)
    }
    assert.ok(!row[2].text.includes('\u2060'))
  }
})

test('防换行处理保留文档链接，并兼容官网的 Markdown 渲染', () => {
  const { html } = renderMarkdown(progress, 'README.md', 'zh-CN')
  for (const row of table.rows) {
    const link = row[0].tokens.find(token => token.type === 'link')
    if (link) {
      assert.ok(!link.href.includes('\u2060'))
      assert.ok(link.href.startsWith('docs/'))
      assert.ok(html.includes(link.text))
    }
  }
  assert.ok(html.includes('<table>'))
  assert.ok(html.includes('阶\u2060段'))
  assert.ok(!html.includes('&lt;table'))
  assert.ok(!html.includes('维护文案时保留'))
})
