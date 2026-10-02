import assert from 'node:assert/strict'
import { test } from 'node:test'
import { mkdtempSync, readFileSync, existsSync, readdirSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { resolve, dirname } from 'node:path'
import { buildSite, buildWebsite, renderMarkdown, resolveLink } from '../scripts/build-docs-site.mjs'
import { mountScene, sceneAt, focusLayout } from '../docs/site/motion.mjs'

test('轨道在留白中连续并由真实界面和紧凑文字表面自然遮挡', () => {
  const css = readFileSync(new URL('../docs/site/product-showcase.css', import.meta.url), 'utf8')
  // 验证前后关系和父级层叠约束，避免只提高卡片却仍被 main 的层叠上下文限制。
  const level = name => Number(css.match(new RegExp(`--site-layer-${name}:(\\d+)`))?.[1])
  assert.ok(level('orbit') < level('surface'))
  assert.ok(level('surface') < level('navigation'))
  const orbit = css.match(/\.page-orbit\{([^}]+)\}/)?.[1]
  assert.match(orbit, /position:fixed/)
  assert.match(orbit, /z-index:var\(--site-layer-orbit\)/)
  assert.match(orbit, /pointer-events:none/)
  assert.match(css, /\.overview main,\.overview footer\{[^}]*z-index:auto/)
  assert.match(css, /:is\(\.product-shot>\.product-image-link,\.hero-peek,\.cover-content,\.cover-scroll,\.scroll-scene,\.home-content\)\{[^}]*z-index:var\(--site-layer-surface\)/)
  // 共享层级不能修改定位：:is 内卡片选择器会提高整条规则优先级，覆盖卫星的 absolute。
  const surfaces = css.match(/\.overview :is\(\.product-shot>\.product-image-link,[^}]+\}/)?.[0]
  assert.doesNotMatch(surfaces, /position:/)
  assert.match(css, /\.hero-peek\{position:absolute/)
  assert.match(css, /\.hero-peek-0\{left:-60px/)
  assert.match(css, /\.hero-peek-1\{right:-60px/)
  assert.match(css, /\.product-showcase-heading>:is\(p,h2\),\.product-shot figcaption>:is\([^}]*width:fit-content/)
  for (const selector of ['product-showcase-heading', 'product-shot figcaption']) {
    const rule = css.match(new RegExp(`\\.${selector}\\{([^}]+)\\}`))?.[1]
    assert.doesNotMatch(rule, /background:|z-index:/)
  }
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
        // 同步启动位于样式和正文前，首次锚点访问不会先绘制动画状态。
        assert.ok(html.indexOf('<script data-page-entry>') < html.indexOf('rel="stylesheet"'))
        assert.ok(html.indexOf('<script data-page-entry>') < html.indexOf('<body'))
        assert.match(html, /scope="col"/)
        if (page === 'index.html') {
          assert.match(html, /class="hero" data-cover/)
          // 双语首屏共用分层标题结构，新增控制器也进入资源版本和预加载图。
          assert.match(html, /class="hero-title-line"/)
          assert.match(html, /class="hero-title-line hero-title-accent"/)
          // 标题与无障碍文案同步移除标点，不残留悬挂句号节点。
          const headline=html.match(/<h1[^>]*>([\s\S]*?)<\/h1>/)?.[1].replace(/<[^>]+>/g,'')
          assert.equal(headline,language==='en' ? 'Every operationConnected' : '每一步业务彼此相连')
          assert.match(html,language==='en' ? /aria-label="Stay tuned"/ : /aria-label="敬请期待"/)
          assert.doesNotMatch(html,/class="finale-punctuation"/)
          assert.match(html, /href="#business-demo"/)
          assert.match(html, /class="scroll-scene"[^>]*id="business-demo"/)
          // 收尾位于正文之后、页脚之前；双语完整文案与原生回到首页入口始终可读。
          assert.match(html, /id="coming-next" data-orbit-finale/)
          assert.ok(html.indexOf('id="coming-next"') > html.indexOf('</article>'))
          assert.ok(html.indexOf('id="coming-next"') < html.indexOf('<footer'))
          assert.ok(html.includes(language === 'en' ? 'Stay tuned' : '敬请期待'))
          assert.match(html, /class="finale-back" href="#main"/)
          // 终点属于背景椭圆，正文主线不再跨越标题并续到页脚。
          assert.match(html, /class="finale-ring" data-finale-ring[^>]*><span class="finale-origin" data-orbit-node="finale"/)
          assert.match(html, /class="finale-title-text"/)
          assert.doesNotMatch(html, /<footer[^>]*data-orbit-node/)

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

test('首帧保持即时定位，首屏动画只在明确出场模式启用且无脚本仍可读', () => {
  const css = readFileSync(new URL('../docs/site/site.css', import.meta.url), 'utf8')
  const hero = readFileSync(new URL('../docs/site/product-showcase.css', import.meta.url), 'utf8')
  assert.match(css, /html\{scroll-behavior:auto/)
  assert.match(css, /html\[data-navigation-ready\]\{scroll-behavior:smooth\}/)
  assert.match(css, /@media\(prefers-reduced-motion:reduce\)\{html,html\[data-navigation-ready\]\{scroll-behavior:auto\}/)
  for (const rule of hero.matchAll(/([^{}]+)\{([^{}]*animation:hero-enter-[^{}]+)\}/g)) {
    assert.match(rule[1], /html\[data-hero-entrance=intro\]/)
  }
  assert.match(hero, /html\[data-hero-entrance=intro\] \.hero:not\(\[data-hero-settled\]\) \.hero-title-line\{animation:hero-enter-copy/)
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
