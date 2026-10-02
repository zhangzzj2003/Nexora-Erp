import assert from 'node:assert/strict'
import { test } from 'node:test'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { resolve } from 'node:path'
import { buildSite } from '../scripts/build-docs-site.mjs'
import { showcaseImages, sourceImages } from '../docs/site/product-showcase.mjs'
import { mountProductGallery, watchImage } from '../docs/site/product-gallery.mjs'
import { previewResponse, ledger, productionCostReport, journals, receipts, receivablesPayables } from '../scripts/site-preview/fixtures.mjs'

test('七张统一尺寸原图随构建复制，双语轨道入口、业务定位与原有演示同时保留', () => {
  const output = mkdtempSync(resolve(tmpdir(), 'nexora-gallery-'))
  try {
    buildSite(output)
    for (const item of [...showcaseImages, ...sourceImages]) {
      const bytes = readFileSync(resolve(output, 'assets/screenshots', item.file))
      assert.equal(bytes.subarray(1, 4).toString(), 'PNG')
      assert.equal(bytes.readUInt32BE(16), 1800)
      assert.equal(bytes.readUInt32BE(20), 1200)
    }
    for (const language of ['zh-CN', 'en']) {
      const html = readFileSync(resolve(output, language, 'index.html'), 'utf8')
      assert.equal([...html.matchAll(/data-product-image/g)].length, 5)
      assert.ok(html.indexOf('id="product-preview"') < html.indexOf('id="business-demo"'))
      assert.match(html, /href="#core-capabilities"/)
      assert.match(html, /href="#product-preview"/)
      assert.match(html, /<dialog[^>]+aria-labelledby="product-lightbox-title"/)
      assert.match(html, /<form method="dialog"><button[^>]+autofocus/)
      assert.match(html, /class="lightbox-original"/)
      // 图片及大图链接共享内容版本，避免发布后仍看到旧界面。
      assert.match(html, /screenshots\/home\.png\?v=[a-f0-9]{12}/)
      assert.match(html, /class="image-error" role="status" hidden/)
      assert.match(html, /product-gallery\.mjs/)
      assert.match(html, /data-stage="3"/)
      assert.match(html, /class="page-orbit" aria-hidden="true"/)
      assert.match(html, /data-surface="screenshots"/)
      for (const key of ['screenshots', 'sandbox']) assert.match(html, new RegExp(`data-surface-select="${key}"`))
      for (const key of ['materials', 'inventory', 'production', 'journals']) {
        assert.ok(html.includes(`href="#preview-${key}"`))
        assert.ok(html.includes(`id="preview-${key}"`))
      }
      for (const item of sourceImages) assert.ok(html.includes(`data-real-anchor="${item.key}"`))
      assert.doesNotMatch(html,/real-app-shell|real-workspace-mask|real-detail-image|@3x/)
      for (const item of sourceImages) assert.ok(html.includes(`live-preview/stage.html?surface=${item.key}`))
      assert.equal([...html.matchAll(/class="live-preview-frame"/g)].length,3)
      assert.equal([...html.matchAll(/data-preview-error role="status" hidden/g)].length,3)
      assert.equal([...html.matchAll(/class="live-preview-focus"/g)].length,3)
      assert.equal([...html.matchAll(/data-source-detail=/g)].length,3)
      assert.equal([...html.matchAll(/data-source-id="receipt:101:1"/g)].length,3)
      assert.match(html,/data-detail-summary aria-live="polite"/)
      assert.ok(readFileSync(resolve(output,'assets/source-details.mjs'),'utf8').includes('mountSourceDetails'))
      assert.equal([...html.matchAll(/data-orbit-card/g)].length, 5)
      assert.ok(readFileSync(resolve(output, 'assets/product-orbit.mjs'), 'utf8').includes('createWebGLGuide'))
      assert.match(html, /data-action="reset"/)
      assert.match(html, /development\.html/)
      for (const item of showcaseImages) {
        assert.ok(html.includes(`href="../assets/screenshots/${item.file}?v=`))
        assert.ok(html.includes(item[language === 'en' ? 'en' : 'zh'][0]))
      }
      if (language === 'zh-CN') {
        for (const text of ['面向企业内部的桌面 ERP', '探索业务演示', '查看核心能力', '电子生产物料管理', '跨业务来源追溯', '独立审核后过账', '当前界面预览 · 示例数据', '在线局域网']) assert.ok(html.includes(text), text)
        assert.doesNotMatch(html, /自动凭证待补/)
      } else {
        for (const text of ['Desktop ERP', 'Explore business demo', 'Core capabilities', 'journal drafts', 'independently review', 'Current interface preview · Sample data', 'interface is currently Chinese', 'Online LAN']) assert.ok(html.includes(text), text)
      }
    }
  } finally {
    // 仅清理本测试创建的临时构建目录。
    rmSync(output, { recursive: true, force: true })
  }
})

// 用最小事件节点验证真实增强脚本的失败路径；模态焦点约束交给原生 dialog 并在浏览器验收。
function galleryFixture() {
  const image = Object.assign(new EventTarget(), { complete: false, naturalWidth: 0, alt: '工作台 · 示例数据' })
  const focusState = { activeElement: null }
  const fallback = { hidden: true }, title = {}, original = { focus() { focusState.activeElement = this } }, closeButton = { focus() { focusState.activeElement = this } }, modalImage = Object.assign(new EventTarget(), { complete: false })
  const modalError = { hidden: true }
  const dialog = Object.assign(new EventTarget(), {
    open: false, ownerDocument: focusState,
    showModal() { this.open = true },
    close() { this.open = false; this.dispatchEvent(new Event('close')) },
    getBoundingClientRect: () => ({ left: 10, top: 10, right: 100, bottom: 100 }),
    querySelector: selector => ({ img: modalImage, h2: title, button: closeButton, '.lightbox-original': original, '.lightbox-error': modalError })[selector],
  })
  const link = Object.assign(new EventTarget(), {
    href: 'https://example.test/assets/home.png', dataset: {}, focused: false,
    focus() { this.focused = true },
    querySelector: selector => selector === 'img' ? image : fallback,
    closest: () => ({ querySelector: () => ({ textContent: '工作台首页' }) }),
  })
  const root = { querySelector: () => dialog, querySelectorAll: () => [link] }
  const click = (node, properties = {}) => {
    const event = Object.assign(new Event('click', { cancelable: true }), { button: 0, clientX: 50, clientY: 50, ...properties })
    node.dispatchEvent(event)
    return event
  }
  return { root, image, fallback, modalImage, modalError, dialog, link, title, original, closeButton, focusState, click }
}

test('大图使用原始资源并恢复焦点，修饰键和不支持 dialog 时保留原图链接', () => {
  const f = galleryFixture()
  mountProductGallery(f.root)
  assert.equal(f.click(f.link, { ctrlKey: true }).defaultPrevented, false)
  assert.equal(f.click(f.link, { button: 1 }).defaultPrevented, false)
  assert.equal(f.dialog.open, false)
  assert.equal(f.click(f.link).defaultPrevented, true)
  assert.equal(f.dialog.open, true)
  assert.equal(f.modalImage.src, f.link.href)
  assert.equal(f.original.href, f.link.href)
  assert.equal(f.title.textContent, '工作台首页')
  assert.equal(f.modalImage.alt, f.image.alt)
  // 首尾 Tab 循环由增强脚本兜底，中间移动仍使用原生键盘行为。
  f.original.focus()
  const tab = Object.assign(new Event('keydown', { cancelable: true }), { key: 'Tab', shiftKey: false })
  f.dialog.dispatchEvent(tab)
  assert.equal(tab.defaultPrevented, true)
  assert.equal(f.focusState.activeElement, f.closeButton)
  const reverse = Object.assign(new Event('keydown', { cancelable: true }), { key: 'Tab', shiftKey: true })
  f.dialog.dispatchEvent(reverse)
  assert.equal(f.focusState.activeElement, f.original)
  f.click(f.dialog)
  assert.equal(f.dialog.open, true)
  f.click(f.dialog, { clientX: 0 })
  assert.equal(f.dialog.open, false)
  assert.equal(f.link.focused, true)
  // 三窗链接没有 figure，仍以明确标题打开同一大图。
  f.link.dataset = { imageTitle: '采购入库' }; f.link.closest = () => null
  f.click(f.link)
  assert.equal(f.title.textContent, '采购入库')
  f.dialog.close()
  const unsupported = galleryFixture()
  unsupported.dialog.showModal = undefined
  mountProductGallery(unsupported.root)
  assert.equal(unsupported.click(unsupported.link).defaultPrevented, false)
})

test('缓存失败、后续图片错误和重新加载成功都有可读提示，大图也保留原图入口', () => {
  const image = Object.assign(new EventTarget(), { complete: true, naturalWidth: 0 })
  const fallback = {}
  watchImage(image, fallback)
  assert.equal(image.hidden, true)
  assert.equal(fallback.hidden, false)
  image.dispatchEvent(new Event('load'))
  assert.equal(image.hidden, false)
  assert.equal(fallback.hidden, true)
  image.dispatchEvent(new Event('error'))
  assert.equal(fallback.hidden, false)
  const f = galleryFixture()
  mountProductGallery(f.root); f.click(f.link)
  assert.equal(f.link.dataset.imageReady,'false')
  f.image.dispatchEvent(new Event('load'));assert.equal(f.link.dataset.imageReady,'true')
  f.image.dispatchEvent(new Event('error'));assert.equal(f.link.dataset.imageReady,'false')
  f.modalImage.dispatchEvent(new Event('error'))
  assert.equal(f.modalError.hidden, false)
  assert.equal(f.original.href, f.link.href)
})

test('示例桥接拒绝未知读写且快照隔离，成本来源与库存、审核状态一致', () => {
  for (const operation of ['login', 'createJournal', 'postJournal', 'confirmReceipt', '__proto__']) assert.throws(() => previewResponse(operation), /未连接业务服务/)
  const snapshot = previewResponse('inventoryLedger')
  snapshot.rows[0].quantity = '999'
  assert.equal(ledger.rows[0].quantity, '200')
  for (const group of ledger.groups) {
    const change = ledger.rows.filter(row => row.sku === group.sku && row.warehouse_name === group.warehouse_name).reduce((sum, row) => sum + Number(row.quantity), 0)
    assert.equal(Number(group.opening_quantity) + change, Number(group.closing_quantity))
  }
  const sources = productionCostReport.material_sources
  for (const source of sources) {
    const movement = ledger.rows.find(row => row.id === source.movement_id)
    assert.equal(movement.source_type, 'material_issue')
    assert.equal(movement.sku, source.sku)
    assert.equal(-Number(movement.quantity), Number(source.net_quantity))
  }
  assert.equal(sources.reduce((sum, row) => sum + Number(row.amount), 0), Number(productionCostReport.orders[0].known_material_amount))
  // 入库数量、应付来源与凭证金额来自同一示例；不能各张图独立拼造。
  const receipt = receipts[0]
  const amount = receipt.lines.reduce((sum, line) => sum + Number(line.quantity) * Number(line.unit_price), 0)
  assert.equal(amount, Number(receivablesPayables.payable_amount))
  assert.equal(amount, receivablesPayables.entries.reduce((sum, row) => sum + Number(row.amount), 0))
  assert.equal(amount, Number(journals[0].total_debit))
  for (const line of receipt.lines) {
    const movement = ledger.rows.find(row => row.source_type === 'receipt' && row.source_id === receipt.id && row.sku === line.sku)
    assert.equal(movement.quantity, line.quantity)
  }
  for (const journal of journals.filter(row => ['approved', 'posted'].includes(row.status))) assert.ok(!journal.author_ids.includes(journal.reviewed_by))
})
