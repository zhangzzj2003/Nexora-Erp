import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import { parse } from '@vue/compiler-sfc'
import { baseParse } from '@vue/compiler-dom'
import { scrollActiveTabIntoView, visibleTabScrollLeft } from '../src/renderer/src/utils/workspace-tab-strip.ts'

test('标签栏在侧栏右侧独占一行，位于业务滚动区之外', () => {
  // 直接检查模板的父子关系，防止标签再次被放进原生标题栏或业务滚动区。
  const tree = file => baseParse(parse(readFileSync(new URL(file, import.meta.url), 'utf8')).descriptor.template.content)
  function elements(node, tag) {
    return (node.children ?? []).flatMap(child => [
      ...(child.tag === tag ? [child] : []), ...elements(child, tag)
    ])
  }
  const shell = tree('../src/renderer/src/views/WorkspaceShell.vue')
  const content = elements(shell, 'main').find(node => node.props.some(prop => prop.name === 'class' && prop.value?.content === 'content'))
  const tabs = content.children.find(node => node.tag === 'WorkspaceTabs')
  const scroll = content.children.find(node => node.tag === 'div' && node.props.some(prop => prop.value?.content === 'content-body'))
  assert.ok(tabs && scroll, '标签和业务滚动区必须是内容列的直接子节点')
  assert.ok(content.children.indexOf(tabs) < content.children.indexOf(scroll))
  assert.equal(elements(scroll, 'WorkspaceTabs').length, 0)
  assert.equal(elements(tree('../src/renderer/src/App.vue'), 'WorkspaceTabs').length, 0)
})

// 同时覆盖新增标签向右跟随和切回旧标签向左跟随，防止页面栏停在原位置。
test('新标签超出右边界时滚到可见位置', () => {
  assert.equal(visibleTabScrollLeft(0, 300, 310, 430), 130)
  assert.equal(visibleTabScrollLeft(130, 300, 420, 540), 240)
})

test('切回左侧标签时向前滚动，已可见的标签不移动页面栏', () => {
  assert.equal(visibleTabScrollLeft(240, 300, 70, 180), 70)
  assert.equal(visibleTabScrollLeft(70, 300, 110, 220), 70)
  assert.equal(visibleTabScrollLeft(240, 300, 0, 120), 0)
})

test('标签超出窗口时对真实容器发出滚动，已可见时不重复滚动', () => {
  const targets = []
  const tab = { getBoundingClientRect: () => ({ left: 450, right: 560 }) }
  const strip = {
    scrollLeft: 0,
    clientWidth: 300,
    querySelector: () => tab,
    getBoundingClientRect: () => ({ left: 100, right: 400 }),
    scrollTo: options => targets.push(options)
  }

  // 第一次进入最右侧标签时必须真正驱动容器；回到可视区后不产生额外滚动。
  scrollActiveTabIntoView(strip)
  assert.deepEqual(targets, [{ left: 160, behavior: 'auto' }])
  strip.scrollLeft = 160
  tab.getBoundingClientRect = () => ({ left: 290, right: 400 })
  scrollActiveTabIntoView(strip)
  assert.equal(targets.length, 1)
})
