import assert from 'node:assert/strict'
import { test } from 'node:test'
import { mkdtempSync, readFileSync, existsSync, readdirSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { resolve, dirname } from 'node:path'
import { buildSite, buildWebsite, renderMarkdown, resolveLink } from '../scripts/build-docs-site.mjs'
import { mountScene, sceneAt, focusLayout } from '../docs/site/motion.mjs'

test('全页轨道覆盖内容背景且不拦截输入，导航保留更高层级', () => {
  const css = readFileSync(new URL('../docs/site/product-showcase.css', import.meta.url), 'utf8')
  // 验证实际共享样式的层级约束，避免局部背景或后续改动再次把轨道放到内容后面。
  const level = name => Number(css.match(new RegExp(`--site-layer-${name}:(\\d+)`))?.[1])
  assert.ok(level('content') < level('orbit'))
  assert.ok(level('orbit') < level('navigation'))
  const orbit = css.match(/\.page-orbit\{([^}]+)\}/)?.[1]
  assert.match(orbit, /position:fixed/)
  assert.match(orbit, /z-index:var\(--site-layer-orbit\)/)
  assert.match(orbit, /pointer-events:none/)
  assert.match(css, /\.overview main,\.overview footer\{[^}]*z-index:var\(--site-layer-content\)/)
  assert.match(css, /\.overview>\.site-header\{z-index:var\(--site-layer-navigation\)/)
})

test('双语页面和文档在 GitHub Pages 子路径下保持资源、语言、目录链接有效', async () => {
  const prefix = resolve(tmpdir(), 'nexora-docs-test-')
  const output = mkdtempSync(prefix)
  try {
    await buildWebsite(output)
    for (const language of ['zh-CN', 'en']) {
      for (const page of ['index.html', 'development.html']) {
        const path = resolve(output, language, page)
        const html = readFileSync(path, 'utf8')
        assert.ok(html.includes(`<html lang="${language}">`))
        assert.ok(html.includes(`../${language === 'en' ? 'zh-CN' : 'en'}/${page === 'index.html' ? './' : page}`))
        assert.match(html, /<h1[ >]/)
        assert.match(html, /scope="col"/)
        if (page === 'index.html') {
          assert.match(html, /class="hero" data-cover/)
          // 双语首屏共用分层标题结构，新增控制器也进入资源版本和预加载图。
          assert.match(html, /class="hero-title-line"/)
          assert.match(html, /class="hero-title-line hero-title-accent"/)
          assert.match(html, /href="#business-demo"/)
          assert.match(html, /class="scroll-scene"[^>]*id="business-demo"/)
          assert.doesNotMatch(html, /data-pause|data-resume|window-reflection/)
          assert.match(html, /data-stage="3"/)
        }
        for (const match of html.matchAll(/(?:href|src)="([^"#]+)(?:#([^" ]+))?"/g)) {
          const href = match[1].split('?')[0]
          if (/^https?:/.test(href)) continue
          const target = resolve(dirname(path), href, href.endsWith('/') ? 'index.html' : '')
          assert.ok(existsSync(target), `${page}: ${href}`)
          if (match[2]) assert.ok(readFileSync(target, 'utf8').includes(`id="${match[2]}"`), href)
        }
        for (const [, id] of html.matchAll(/href="#([^"]+)"/g)) assert.ok(html.includes(`id="${id}"`), id)
      }
    }
    assert.equal(readdirSync(resolve(output, 'sources')).length, 4)
    assert.ok(existsSync(resolve(output, 'assets/webgl-stage.mjs')))
    assert.ok(existsSync(resolve(output, 'assets/scene-geometry.mjs')))
    assert.ok(existsSync(resolve(output, 'assets/cover-motion.mjs')))
    assert.ok(existsSync(resolve(output, 'assets/hero-entrance.mjs')))
    // HTML 与整个模块依赖图使用同一内容版本，不会混入更新前的缓存。
    const home=readFileSync(resolve(output,'zh-CN/index.html'),'utf8')
    const version=home.match(/assets\/motion\.mjs\?v=([a-f0-9]{12})/)?.[1]
    assert.ok(version)
    for(const [,file] of home.matchAll(/rel="modulepreload" href="\.\.\/assets\/([\w-]+\.mjs)\?v=[a-f0-9]{12}"/g)){
      const js=readFileSync(resolve(output,'assets',file),'utf8')
      for(const [,dependency,token] of js.matchAll(/['"]\.\/([\w-]+\.mjs)\?v=([a-f0-9]{12})['"]/g)){
        assert.equal(token,version);assert.ok(existsSync(resolve(output,'assets',dependency)))
      }
    }
    assert.match(readFileSync(resolve(output, 'assets/sandbox.css'), 'utf8'), /\.scroll-scene\{[^}]*overflow-anchor:none/)
    const cn = readFileSync(resolve(output, 'zh-CN/development.html'), 'utf8')
    const en = readFileSync(resolve(output, 'en/development.html'), 'utf8')
    for (const text of ['dist:win', 'dist:mac', 'NEXORA_PYTHON', 'PAGES_ENABLED', 'period-closing.md']) {
      assert.ok(cn.includes(text)); assert.ok(en.includes(text))
    }
    assert.equal([...cn.matchAll(/<h2 /g)].length, [...en.matchAll(/<h2 /g)].length)
    assert.ok(!cn.includes('src="../assets/motion.mjs"'))
  } finally {
    // 只删除本测试创建的临时目录，校验绝对路径后执行清理。
    assert.ok(output.startsWith(prefix))
    rmSync(output, { recursive: true, force: true })
  }
})

test('Markdown 使用真实仓库路径，拒绝可执行协议及越界链接，原始 HTML 不执行', () => {
  assert.equal(resolveLink('../README.en.md', 'docs/development.zh-CN.md', 'zh-CN'), '../en/')
  assert.match(resolveLink('ledger-foundation.md', 'docs/development.en.md', 'en'), /\/blob\/main\/docs\/ledger-foundation.md$/)
  assert.match(resolveLink('docs/site/', 'README.md', 'zh-CN'), /\/tree\/main\/docs\/site\/$/)
  for (const href of ['javascript:alert(1)', 'data:text/html,test', '//evil.example', '../../secret']) {
    assert.throws(() => resolveLink(href, 'README.md', 'en'))
  }
  const rendered = renderMarkdown('# Title\n\n<script>alert(1)</script>\n\n## One\n\n## One', 'README.md', 'en')
  assert.ok(!rendered.html.includes('<script>'))
  assert.equal(new Set(rendered.headings.map(h => h.id)).size, 2)
})
