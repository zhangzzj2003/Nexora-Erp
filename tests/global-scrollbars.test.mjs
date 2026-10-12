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
