import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync, existsSync } from 'node:fs'
import { resolve } from 'node:path'

// 同时检验产物上传与部署门槛，防止 PR 或普通验证意外覆盖公开网站。
test('官网仅在明确手动发布或启用的主线推送时上传并部署',()=>{
  const workflow=readFileSync(new URL('../.github/workflows/docs-site.yml',import.meta.url),'utf8')
  assert.match(workflow,/publish:\s+description:[^\n]+\s+type: boolean\s+default: false/)
  const gates=[...workflow.matchAll(/^\s+if: (.+)$/gm)].map(match=>match[1])
  assert.equal(gates.length,2)
  const cases=[
    ['pull_request','refs/pull/148/merge',true,'true',false],
    ['push','refs/heads/codex/site-product-showcase',true,'true',false],
    ['push','refs/heads/main',false,'false',false],
    ['push','refs/heads/main',false,'true',true],
    ['workflow_dispatch','refs/heads/main',false,'true',false],
    ['workflow_dispatch','refs/heads/codex/site-product-showcase',true,'false',true],
  ]
  for(const gate of gates){
    // GitHub 的条件子集与 JavaScript 相同，直接用实际配置验证事件矩阵。
    const allowed=Function('github','inputs','vars',`return Boolean(${gate})`)
    for(const [event_name,ref,publish,PAGES_ENABLED,expected] of cases)
      assert.equal(allowed({event_name,ref},{publish},{PAGES_ENABLED}),expected,`${event_name}: ${ref}`)
  }
  assert.match(workflow,/needs: build/)
  assert.match(workflow,/pages: write\s+id-token: write/)
  assert.match(workflow,/name: github-pages/)
  assert.equal([...workflow.matchAll(/path: dist\/site\//g)].length,2)
})

// README 的双语入口必须指向线上站点，图片随仓库提供，不能依赖本机地址。
test('双语 README 提供可点击的官网预览和线上入口',()=>{
  for(const [file,language] of [['README.md','zh-CN'],['README.en.md','en']]){
    const readme=readFileSync(new URL('../'+file,import.meta.url),'utf8')
    const url=`https://zhangzzj2003.github.io/Nexora-Erp/${language}/`
    assert.ok(readme.includes(url))
    assert.match(readme,/\[!\[[^\]]+\]\(docs\/site\/website-preview\.jpg\)\]\(https:\/\/zhangzzj2003\.github\.io\/Nexora-Erp\/(?:zh-CN|en)\/\)/)
    assert.ok(existsSync(resolve('docs/site/website-preview.jpg')))
    assert.doesNotMatch(readme,/GitHub Pages 暂未启用|GitHub Pages is not enabled yet|127\.0\.0\.1:8765/)
  }
})
