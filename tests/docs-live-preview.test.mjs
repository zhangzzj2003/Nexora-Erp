import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync,readFileSync,readdirSync,rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { resolve } from 'node:path'
import { buildWebsite } from '../scripts/build-docs-site.mjs'

// 实际构建 Vue 入口，防止只生成 iframe 标签却遗漏组件包或使用错误的绝对路径。
test('官网构建包含原 App 及动态样式，桥接隔离于示例会话', async()=>{
  const output=mkdtempSync(resolve(tmpdir(),'nexora-live-'))
  try {
    await buildWebsite(output)
    const root=resolve(output,'assets/live-preview'),html=readFileSync(resolve(root,'stage.html'),'utf8')
    assert.match(html,/src="\.\/assets\/stage-[^" ]+\.js"/)
    const files=readdirSync(resolve(root,'assets'))
    const js=files.filter(file=>file.endsWith('.js')).map(file=>readFileSync(resolve(root,'assets',file),'utf8')).join('\n')
    // 原 App 延迟装配，CSS 由动态导入的依赖预加载；核对引用和实际产物。
    const css=files.find(file=>/^main-.*\.css$/.test(file))
    assert.ok(css);assert.ok(js.includes(css))
    assert.match(readFileSync(resolve(root,'assets',css),'utf8'),/workspace/)
    assert.match(js,/nexora:preview-row/);assert.match(js,/nexora:select-preview-item/)
    // 全 App 的隔离桥接仅接受已配置示例读取；写入拒绝由另一组快照测试覆盖。
    const entry=readFileSync(new URL('../scripts/site-preview/main.mjs',import.meta.url),'utf8')
    assert.match(entry,/callApi: async operation => previewResponse\(operation\)/)
    assert.match(entry,/store.initialize = async \(\) => \{\}/)
    assert.match(entry,/export const previewReady/)
    assert.doesNotMatch(entry,/fetch\(|connectServer\(/)
  }finally{rmSync(output,{recursive:true,force:true})}
})
