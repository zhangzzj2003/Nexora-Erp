import { detailControlsMarkup } from '../docs/site/source-details.mjs'
import { createHash } from 'node:crypto'
import { readFileSync, mkdirSync, writeFileSync, copyFileSync } from 'node:fs'
import { resolve, dirname, posix } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'
import { Marked } from 'marked'
import { sandboxMarkup } from '../docs/site/sandbox-ui.mjs'
import { showcaseMarkup, showcaseImages, sourceImages } from '../docs/site/product-showcase.mjs'
import { pageEntryScript } from '../docs/site/hero-entrance.mjs'

export const repository = 'https://github.com/zhangzzj2003/Nexora-Erp'
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const languages = {
  'zh-CN': { other: 'en', readme: 'README.md', guide: 'docs/development.zh-CN.md',
    features: '项目功能', progress: '开发进度', docs: '开发文档', skip: '跳到正文', contents: '本页目录', source: '查看 Markdown',
    title: '<span class="hero-title-line">每一步业务，</span><br><span class="hero-title-line hero-title-accent">彼此相连。</span>', subtitle: '联光 ERP · 面向企业内部的桌面 ERP',
    intro: '面向电子生产，将物料、采购、库存、生产与销售连接起来，让业务记录与财务来源有据可查。', scope: '内部试用 · 单公司 · 多仓库 · 在线局域网',
    button: '探索业务演示', code: '查看核心能力', home: '项目介绍', lang: 'EN',
    flows: [['采购', 'PURCHASE', '申请与订单'], ['库存', 'INVENTORY', '收发与台账'], ['生产', 'PRODUCTION', '工单与成本'], ['销售', 'SALES', '出库与退货']],
    pillars: [['电子生产物料管理', '按类别自动编码，集中维护规格、封装与制造商料号，让采购和生产使用同一份物料档案。'], ['跨业务来源追溯', '采购、库存、生产与销售保留单据关联、操作者与更正记录，查清每笔数量和金额的来处。'], ['业务与财务衔接', '从已确认业务生成凭证草稿，独立审核后过账；核对材料、人工和制造费用的成本来源。']], footer: '内部试用 · 单公司 · 在线局域网', download: '下载 Markdown' },
  en: { other: 'zh-CN', readme: 'README.en.md', guide: 'docs/development.en.md',
    features: 'Features', progress: 'Progress', docs: 'Development guide', skip: 'Skip to content', contents: 'On this page', source: 'View Markdown',
    title: '<span class="hero-title-line">Every operation.</span><br><span class="hero-title-line hero-title-accent">Connected.</span>', subtitle: 'Nexora ERP · Desktop ERP for internal operations',
    intro: 'For electronic production: connect materials, purchasing, inventory, production and sales through traceable business and financial origins.', scope: 'Internal trial · Single company · Multiple warehouses · Online LAN',
    button: 'Explore business demo', code: 'Core capabilities', home: 'Overview', lang: '中文',
    flows: [['Purchasing', 'PURCHASE', 'Requests & orders'], ['Inventory', 'INVENTORY', 'Movements & ledgers'], ['Production', 'PRODUCTION', 'Work orders & costs'], ['Sales', 'SALES', 'Shipments & returns']],
    pillars: [['Electronic materials', 'Category-based codes, specifications, packages and manufacturer part numbers keep purchasing and production on the same material records.'], ['Traceable business origins', 'Purchasing, inventory, production and sales preserve document links, operators and corrections so quantities and amounts can be traced.'], ['Business and finance', 'Generate journal drafts from confirmed business sources, independently review and post them, and reconcile material, labor and overhead costs.']], footer: 'Internal trial · Single company · Online LAN', download: 'Download Markdown' }
}

export function escapeHtml(value) {
  return value.replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char])
}

export function resolveLink(href, source, language) {
  if (/^(https?:|mailto:)/i.test(href) || href.startsWith('#')) return href
  // 禁止文档链接生成可执行协议；相对路径统一按仓库位置解析。
  if (/^[a-z][a-z\d+.-]*:/i.test(href) || href.startsWith('//')) throw new Error(`不允许的文档链接: ${href}`)
  const [path, fragment] = href.split('#')
  const normalized = posix.normalize(posix.join(posix.dirname(source), path))
  const routes = { 'README.md': '../zh-CN/', 'README.en.md': '../en/', 'docs/development.zh-CN.md': '../zh-CN/development.html', 'docs/development.en.md': '../en/development.html' }
  if (normalized.startsWith('../')) throw new Error(`文档链接越出仓库: ${href}`)
  if (routes[normalized]) return routes[normalized] + (fragment ? `#${fragment}` : '')
  return `${repository}/${path.endsWith('/') ? 'tree' : 'blob'}/main/${normalized.split('/').map(encodeURIComponent).join('/')}${fragment ? `#${fragment}` : ''}`
}

export function renderMarkdown(markdown, source, language, home = false) {
  const headings = []
  let index = 0
  const parser = new Marked({ gfm: true })
  parser.use({ renderer: {
    html({ text }) { return escapeHtml(text) },
    link({ href, tokens }) { return `<a href="${escapeHtml(resolveLink(href, source, language))}">${this.parser.parseInline(tokens)}</a>` },
    heading({ depth, tokens }) {
      const text = this.parser.parseInline(tokens)
      const id = `section-${++index}`
      if (depth === 2) headings.push({ id, text })
      return `<h${depth} id="${id}">${text}</h${depth}>\n`
    },
    table(token) {
      const header = token.header.map(cell => `<th scope="col">${this.parser.parseInline(cell.tokens)}</th>`).join('')
      const rows = token.rows.map(row => `<tr>${row.map(cell => `<td>${this.parser.parseInline(cell.tokens)}</td>`).join('')}</tr>`).join('')
      return `<div class="table-scroll" tabindex="0" role="region" aria-label="${language === 'en' ? 'Scrollable table' : '可横向滚动的表格'}"><table><thead><tr>${header}</tr></thead><tbody>${rows}</tbody></table></div>`
    }
  } })
  const body = home ? markdown.slice(markdown.indexOf('## ')) : markdown
  return { html: parser.parse(body), headings }
}

function header(language, guide, headings) {
  const t = languages[language]
  const current = guide ? 'development.html' : './'
  return `<a class="skip" href="#main">${t.skip}</a><header class="site-header"><a class="brand" href="./"><img src="../assets/brand.png" alt="" width="36" height="36"><span>Nexora</span></a><nav aria-label="${language === 'en' ? 'Main navigation' : '主导航'}"><a href="./#section-1">${t.features}</a><a href="./#section-2">${t.progress}</a><a href="development.html" ${guide ? 'aria-current="page"' : ''}>${t.docs}</a></nav><div class="header-end"><a href="${repository}">GitHub ↗</a><a class="language" href="../${t.other}/${current}" lang="${t.other}" hreflang="${t.other}">${t.lang}</a></div></header>`
}

function hero(language) {
  const t = languages[language]
  const en = language === 'en'
  const labels = en ? ['Receipt', 'Stock', 'Payable', 'Trace'] : ['入库', '库存', '财务', '追溯']
  const captions = en ? ['Warehouse confirmation starts the record.', 'The same transaction writes the stock movement.', 'The receipt becomes a traceable payable source.', 'Follow each source back to the original receipt.'] : ['仓库确认入库，业务记录由此开始。', '同一事务写入库存流水，数量与来源一起保留。', '已确认入库形成应付来源，金额可追溯到原单。', '沿着来源记录，查回同一张入库单。']
  // 首屏使用真实界面作为空间节点，四步路径直接解释产品覆盖的业务。
  const journey = en ? ['Materials', 'Inventory', 'Production', 'Finance'] : ['物料', '库存', '生产', '财务']
  const peeks = ['home', 'materials'].map((key, index) => `<div class="hero-peek hero-peek-${index}" aria-hidden="true"><img src="../assets/screenshots/${key}.png" alt="" width="1800" height="1200"><span>${en ? ['One workspace', 'Shared material records'][index] : ['业务全貌，一眼看清', '从同一份物料开始'][index]}</span><i data-orbit-node></i></div>`).join('')
  const cover = `<section class="hero" data-cover>${peeks}<div class="cover-content"><p class="hero-eyebrow">${en ? 'CONNECTED OPERATIONS' : '联光 ERP · 业务彼此相连'}</p><h1>${t.title}</h1><p class="subtitle">${t.subtitle}</p><p class="hero-description">${t.intro}</p><p class="hero-scope">${t.scope}</p><div class="actions"><a class="primary" href="#business-demo">${t.button} <span aria-hidden="true">↗</span></a><a href="#core-capabilities">${t.code} <span aria-hidden="true">↗</span></a></div><nav class="hero-journey" aria-label="${en ? 'Connected business areas' : '相连的业务领域'}">${journey.map((label, index) => `<a href="#preview-${['materials', 'inventory', 'production', 'journals'][index]}"><span>${String(index + 1).padStart(2, '0')}</span>${label}</a>${index < 3 ? '<i aria-hidden="true">→</i>' : ''}`).join('')}</nav><div class="guide-origin" data-orbit-node aria-hidden="true"><span class="cover-stem"></span></div></div><a class="cover-scroll" href="#product-preview"><span>${en ? 'Scroll to see the workspace' : '向下滚动，看见真实工作空间'}</span><svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4"><path d="M12 4v16m-5-5 5 5 5-5"/></svg></a><div class="cover-guide" hidden aria-hidden="true"><svg><path class="cover-guide-path"/><circle class="cover-guide-tip" r="2.5"/></svg></div></section>`
  return `${cover}${showcaseMarkup(language)}<section class="scroll-scene" data-surface="screenshots" id="business-demo" aria-label="${en ? 'Interactive receipt, stock and payable demo' : '入库、库存与应付交互演示'}"><div class="scene-sticky"><div class="stage-heading"><span class="stage-orbit-label"><i class="stage-orbit-node" data-orbit-node="stage" aria-hidden="true"></i>${en ? 'Follow a receipt. Explore every connection.' : '从一张入库单，看见业务的每一次连接。'}</span><div class="surface-controls" role="group" aria-label="${en ? 'Choose interface preview or interactive demo' : '选择真实界面或业务演示'}"><button type="button" data-surface-select="screenshots" aria-pressed="true">${en ? 'Real interfaces' : '真实界面'}</button><button type="button" data-surface-select="sandbox" aria-pressed="false">${en ? 'Business demo' : '业务演示'}</button></div><button type="button" data-action="reset">${en ? 'Reset demo' : '重置演示'}</button></div>${detailControlsMarkup(language)}<div class="scene-board">${sandboxMarkup(language)}<svg class="connection-layer" aria-hidden="true"><defs><filter id="line-glow" x="-80%" y="-100%" width="260%" height="300%"><feGaussianBlur stdDeviation="3"/></filter></defs><g data-connection="0"><path class="connection-glow"/><path class="connection-line"/><circle class="connection-node" r="4"/></g><g data-connection="1"><path class="connection-glow"/><path class="connection-line"/><circle class="connection-node" r="4"/></g></svg></div><div class="scene-narration">${captions.map((caption,index)=>`<p data-caption="${index}" ${index ? 'hidden' : ''}>${caption}</p>`).join('')}</div><div class="scene-controls"><div role="group" aria-label="${en ? 'Select a flow step' : '选择演示步骤'}">${labels.map((label,index)=>`<button type="button" data-stage="${index}" aria-pressed="${index===0}">${label}</button>`).join('')}</div><button type="button" data-overview>${en ? 'Overview' : '返回总览'}</button></div><p class="demo-status" data-demo-status role="status" aria-live="polite"></p><p class="demo-disclaimer"><span class="real-surface-note">${en ? 'Real component preview · Sample data · Scroll to enlarge; focus a view for details. Switch to Business demo to interact.' : '真实组件预览 · 示例数据 · 随滚动放大，可聚焦明细；切换业务演示后可操作。'}</span><span class="sandbox-surface-note">${en ? 'Interactive demo · Local sample data · Refresh to reset' : '网页交互演示 · 使用本地示例数据 · 刷新恢复初始状态'}</span></p><noscript><p class="no-script-note">${en ? 'DEMO-001: 12 units received → stock +12 → payable ¥120.00. Enable JavaScript to interact.' : 'DEMO-001：入库 12 件 → 库存 +12 → 应付 ¥120.00。启用 JavaScript 后可操作演示。'}</p></noscript></div></section><section class="pillars" id="core-capabilities" data-orbit-node="edge" aria-label="${t.home}">${t.pillars.map(([name,detail])=>`<div><h2>${name}</h2><p>${detail}</p></div>`).join('')}</section><div class="foundation"><p>Electron / Vue 3 / FastAPI / SQLite</p><a href="#section-2">${t.progress} →</a></div>`
}

function page(language, guide, rendered) {
  const t = languages[language]
  const title = guide ? `${t.docs} · Nexora ERP` : `Nexora ERP · ${t.home}`
  const source = guide ? t.guide : t.readme
  const toc = `<aside class="toc"><nav aria-label="${t.contents}"><p>${t.contents}</p>${rendered.headings.map(h => `<a href="#${h.id}">${h.text}</a>`).join('')}<a class="source-link" href="${repository}/blob/main/${source}">${t.source} ↗</a></nav></aside>`
  return `<!doctype html><html lang="${language}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><script data-page-entry>${pageEntryScript}</script><title>${title}</title><meta name="description" content="${escapeHtml(guide ? t.docs + ': Electron, Vue, FastAPI, testing, builds and GitHub Pages.' : t.intro)}"><link rel="icon" href="../assets/brand.png"><link rel="stylesheet" href="../assets/site.css">${guide ? '' : '<link rel="stylesheet" href="../assets/sandbox.css"><link rel="stylesheet" href="../assets/product-showcase.css">'}</head><body class="${guide ? 'guide' : 'overview'}">${guide ? '' : '<div class="page-orbit" aria-hidden="true"><svg></svg></div>'}${header(language,guide,rendered.headings)}<main id="main" ${guide ? 'class="doc-layout"' : ''}>${guide ? toc : hero(language)}<article class="prose ${guide ? '' : 'home-content'}" ${guide ? '' : 'data-orbit-node="edge"'}>${rendered.html}<p class="download"><a href="../sources/${posix.basename(source)}" download>${t.download} ↓</a></p></article></main><footer ${guide ? '' : 'data-orbit-node="edge"'}><a class="brand-text" href="./">Nexora ERP</a><span>${t.footer}</span><a href="${repository}">GitHub ↗</a></footer>${guide ? '' : '<script type="module" src="../assets/motion.mjs"></script><script type="module" src="../assets/product-gallery.mjs"></script>'}</body></html>`
}

export function buildSite(output = resolve(root, 'dist/site')) {
  mkdirSync(resolve(output, 'assets'), { recursive: true })
  mkdirSync(resolve(output, 'sources'), { recursive: true })
  // 整个模块图共用内容版本，避免更新后入口与被缓存的旧依赖混用。
  const siteFiles=['site.css','product-showcase.css','product-gallery.mjs','product-showcase.mjs','product-orbit.mjs','hero-entrance.mjs','source-details.mjs','motion.mjs','cover-motion.mjs','scene-geometry.mjs','webgl-stage.mjs','sandbox.mjs','sandbox-ui.mjs','sandbox.css']
  const version=createHash('sha256').update(siteFiles.map(file=>readFileSync(resolve(root,'docs/site',file),'utf8')).join('\n')).digest('hex').slice(0,12)
  for (const file of siteFiles) {
    const source=readFileSync(resolve(root,'docs/site',file),'utf8')
    writeFileSync(resolve(output,'assets',file),file.endsWith('.mjs') ? source.replace(/(['"])(\.\/[\w-]+\.mjs)\1/g,(_,quote,path)=>`${quote}${path}?v=${version}${quote}`) : source)
  }
  mkdirSync(resolve(output, 'assets/screenshots'), { recursive: true })
  // 版本来自图片内容，更新截图后不会继续命中浏览器中的旧图或旧失败缓存。
  const imageVersions = new Map()
  for (const image of [...showcaseImages, ...sourceImages]) {
    if (imageVersions.has(image.file)) continue
    const source = resolve(root, 'docs/site/screenshots', image.file)
    imageVersions.set(image.file, createHash('sha256').update(readFileSync(source)).digest('hex').slice(0, 12))
    copyFileSync(source, resolve(output, 'assets/screenshots', image.file))
  }
  copyFileSync(resolve(root, 'resources/icon.png'), resolve(output, 'assets/brand.png'))
  copyFileSync(resolve(root, 'docs/site/fonts/InterVariable.woff2'), resolve(output, 'assets/InterVariable.woff2'))
  copyFileSync(resolve(root, 'docs/site/fonts/LICENSE.txt'), resolve(output, 'assets/FONT-LICENSE.txt'))
  for (const [language, t] of Object.entries(languages)) {
    mkdirSync(resolve(output, language), { recursive: true })
    for (const guide of [false, true]) {
      const source = guide ? t.guide : t.readme
      const markdown = readFileSync(resolve(root, source), 'utf8')
      let html = page(language, guide, renderMarkdown(markdown,source,language,!guide))
      html=html.replace(/(\.\.\/assets\/[\w-]+\.(?:css|mjs))"/g,`$1?v=${version}"`)
      // 提前获取官网模块，不与随后启动的完整界面抢首轮请求。
      if (!guide) html=html.replace('</head>',siteFiles.filter(file=>file.endsWith('.mjs')&&file!=='product-showcase.mjs').map(file=>`<link rel="modulepreload" href="../assets/${file}?v=${version}">`).join('')+'</head>')
      for (const [file, version] of imageVersions) html = html.replaceAll(`../assets/screenshots/${file}`, `../assets/screenshots/${file}?v=${version}`)
      writeFileSync(resolve(output, language, guide ? 'development.html' : 'index.html'), html)
      writeFileSync(resolve(output, 'sources', posix.basename(source)), markdown)
    }
  }
  writeFileSync(resolve(output, 'index.html'), '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="0;url=zh-CN/"><title>Nexora ERP</title></head><body><a href="zh-CN/">简体中文</a> · <a href="en/">English</a></body></html>')
  writeFileSync(resolve(output, '.nojekyll'), '')
  return output
}

// 完整发布构建包含真实 Vue 展示组件；静态生成函数保留给快速文案测试。
export async function buildWebsite(output = resolve(root, 'dist/site')) {
  buildSite(output)
  const { buildLivePreview } = await import('./build-live-preview.mjs')
  const version=await buildLivePreview(resolve(output,'assets/live-preview'))
  for (const language of Object.keys(languages)) {
    const path=resolve(output,language,'index.html')
    writeFileSync(path,readFileSync(path,'utf8').replaceAll('stage.html?surface=','stage.html?v='+version+'&amp;surface='))
  }
  return output
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  console.log(`官网已生成：${await buildWebsite()}`)
}
