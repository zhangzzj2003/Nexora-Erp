import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import postcss from 'postcss'

const stylesheet = postcss.parse(readFileSync(new URL('../src/renderer/src/style.css', import.meta.url), 'utf8'))
const rules = []
stylesheet.walkRules(rule => rules.push(rule))
const declarations = rule => Object.fromEntries(rule.nodes.filter(node => node.type === 'decl').map(node => [node.prop, node.value]))

// 双轴容器必须保留横向入口；禁止用隐藏全部滚动条或裁切内容替代纵向宽度设置。
test('全局原生滚动条清零纵向宽度，保留可见横向手柄及容器滚动行为', () => {
  const nativeRules = rules.filter(rule => rule.selector === '*::-webkit-scrollbar')
  assert.equal(nativeRules.length, 1)
  assert.equal(declarations(nativeRules[0]).width, '0')
  assert.ok(parseFloat(declarations(nativeRules[0]).height) > 0)
  assert.notEqual(declarations(nativeRules[0]).display, 'none')
  const thumb = rules.find(rule => rule.selector === '*::-webkit-scrollbar-thumb:horizontal')
  assert.ok(declarations(thumb).background, '横向手柄必须可见，不能留下透明空轨道')
  for (const rule of rules.filter(rule => ['*', 'html', 'body', ':root'].includes(rule.selector))) {
    const values = declarations(rule)
    assert.notEqual(values['scrollbar-width'], 'none')
    assert.ok(!['hidden', 'clip'].includes(values['overflow-y']))
    assert.ok(!['hidden', 'clip'].includes(values.overflow))
  }
})

// 设置抽屉、下拉选项等使用自绘轨道，必须只命中纵向并覆盖组件动态注入的显示样式。
test('Naive UI 仅隐藏纵向轨道，且不关闭承载内容的滚动容器', () => {
  const customRules = rules.filter(rule => rule.selector.includes('scrollbar-rail'))
  assert.equal(customRules.length, 1)
  assert.equal(customRules[0].selector, ':root .n-scrollbar-rail--vertical')
  assert.deepEqual(declarations(customRules[0]), { display: 'none' })
  assert.equal(customRules[0].nodes.find(node => node.prop === 'display').important, true)
})

// 截图中的详情与主内容区仍需纵向滚动，避免隐藏条形后底部明细变得不可达。
test('公共弹窗、工作台和侧栏保留纵向自动滚动', () => {
  for (const selector of ['.n-modal.n-card > .n-card-content', '.content-body', '.side-group', '.onboard-main']) {
    assert.ok(rules.some(rule => rule.selector === selector && declarations(rule)['overflow-y'] === 'auto'), selector)
  }
  const dialog = readFileSync(new URL('../src/renderer/src/components/workspace/WorkspaceDocumentDialog.vue', import.meta.url), 'utf8')
  assert.match(dialog, /\.document-body\s*\{[^}]*overflow-y:\s*auto/)
})

// 分割线属于公共组件操作插槽；限定弹窗直接子元素，不把普通卡片或正文表格页脚一起改掉。
test('公共弹窗操作区统一分割线和留白，保持固定且适配明暗主题', () => {
  for (const selector of ['.n-modal.n-card > .n-card__footer', '.n-modal.n-card > .n-card__action']) {
    const rule = rules.find(rule => rule.parent.type === 'root' && rule.selectors.includes(selector)
      && declarations(rule)['border-top'])
    assert.ok(rule, `${selector} 必须自动提供分割线`)
    const values = declarations(rule)
    assert.equal(values['border-top'], '1px solid var(--workspace-field-border)')
    assert.equal(values.background, 'var(--app-modal-background)')
    assert.equal(values['flex-shrink'], '0')
    assert.ok(values.padding.split(' ').every(part => parseFloat(part) > 0), '操作按钮与分割线需要留白')
    assert.ok(!['auto', 'scroll'].includes(values['overflow-y']), '操作区不参与正文滚动')
    assert.ok(rules.some(rule => rule.parent.type === 'atrule' && rule.parent.params === '(max-width: 650px)'
      && rule.selectors.includes(selector) && declarations(rule).padding === '16px'))
  }
})
