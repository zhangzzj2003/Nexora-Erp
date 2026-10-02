import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync,readFileSync,existsSync,mkdirSync,writeFileSync,rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { resolve } from 'node:path'
import postcss from 'postcss'
import { buildWebsite } from '../scripts/build-docs-site.mjs'
import { displayMarkup, } from '../docs/site/workspace-display.mjs'
import { displayStyles } from '../scripts/site-display.mjs'

// 发布产物必须直接包含展示内容，即使关闭 JavaScript 也能看到界面，不再启动子应用。
test('官网直接生成三窗 HTML 与项目样式，无 iframe、应用分包或加载状态', async()=>{
  const output=mkdtempSync(resolve(tmpdir(),'nexora-display-'))
  try {
    // 更新旧产物时也清除历史嵌入应用，仅清理构建专属目录。
    mkdirSync(resolve(output,'assets/live-preview'),{recursive:true})
    writeFileSync(resolve(output,'assets/live-preview/stage.html'),'old generated app')
    await buildWebsite(output)
    assert.equal(existsSync(resolve(output,'assets/live-preview')),false)
    for(const language of ['zh-CN','en']) {
      const html=readFileSync(resolve(output,language,'index.html'),'utf8')
      assert.equal([...html.matchAll(/data-display-canvas/g)].length,3)
      assert.equal([...html.matchAll(/data-display-source="receipt:101:1"/g)].length,3)
      assert.match(html,/app-display\.css\?v=[a-f0-9]{12}/)
      assert.doesNotMatch(html,/<iframe|stage\.html|preview-loading|preview-error|正在加载业务视图|Loading business view/)
      assert.match(html,/workspace-record-lines/)
      assert.match(html,/EL-IC-000001 × 200/)
    }
    const runtime=readFileSync(resolve(output,'assets/source-details.mjs'),'utf8')
    assert.doesNotMatch(runtime,/postMessage|setTimeout|fetch\(|import\(.*main|message'/)
  }finally{rmSync(output,{recursive:true,force:true})}
})
// 验证取来的样式既保持项目的关键视觉值，也全部隔离在展示作用域里。
test('工作台、浅色主题和表格样式复用项目规则，任何选择器都不污染官网',()=>{
  const css=displayStyles(),root=postcss.parse(css)
  root.walkRules(rule=>{for(const selector of rule.selectors) assert.ok(selector.startsWith('.erp-display'),selector)})
  assert.match(css,/background: #edf1f5/)
  assert.match(css,/--vxe-ui-table-border-color: #e5edf1/)
  assert.match(css,/font-size:19\.5px/)
  // 明细锚点贴合文字，手机移动的终点不能是单元格的空白末端。
  assert.match(css,/workspace-record-lines>span\{[^}]*width:max-content;max-width:100%/)
  assert.doesNotMatch(css,/@import|data-theme='dark'|100vw|100svh/)
  for(const key of ['receipt','stock','finance']) assert.match(displayMarkup(key),/aria-hidden="true" inert/)
  assert.throws(()=>displayMarkup('invalid'),/未知官网展示页面/)
})
