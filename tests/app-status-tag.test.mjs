import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import { parse } from '@vue/compiler-sfc'
import postcss from 'postcss'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'

test('冲销标签与统计在明暗主题均使用红色，取消仍使用中性色', () => {
  // 同时检查两个真实组件的主题声明，防止只修列表或漏掉深色主题。
  for (const [path, selector, property] of [
    ['app/AppStatusTag.vue', '.app-status-tag', '--app-status-tag-color'],
    ['workspace/WorkspaceSummaryFilters.vue', '.summary-filter', '--summary-tone'],
  ]) {
    const source = readFileSync(new URL(`../src/renderer/src/components/${path}`, import.meta.url), 'utf8')
    const { descriptor } = parse(source)
    const styles = postcss.parse(descriptor.styles.map(style => style.content).join('\n'))
    for (const [prefix, reversed, neutral] of [
      ['', '#bb3650', '#626d7e'],
      [":root[data-theme='dark'] ", '#ff9baf', '#b1bccd'],
    ]) {
      for (const [tone, expected] of [['reversed', reversed], ['neutral', neutral]]) {
        let actual
        styles.walkRules(`${prefix}${selector}--${tone}`, rule => {
          rule.walkDecls(property, declaration => { actual = declaration.value })
        })
        assert.equal(actual, expected, `${path}: ${prefix}${tone}`)
      }
    }
  }
})

// 使用真实组件验证公共接口；业务终态优先级由其他入库页面回归测试负责。
test('公共状态标签保留完整文字、默认中性色和不可交互的装饰圆点', async t => {
  const server = await createServer({ configFile: false, plugins: [vue()],
    server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  t.after(() => server.close())
  const { default: Tag } = await server.ssrLoadModule('/src/renderer/src/components/app/AppStatusTag.vue')
  const render = props => renderToString(createSSRApp({ render: () => h(Tag, props) }))
  for (const tone of ['success', 'pending', 'info', 'ready', 'danger', 'neutral', 'reversed']) {
    const html = await render({ label: '已批准，待入库', tone })
    assert.ok(html.includes(`app-status-tag--${tone}`))
    assert.ok(html.includes('已批准，待入库'))
    assert.match(html, /class="app-status-tag__dot" aria-hidden="true"/)
    assert.doesNotMatch(html, /<button|tabindex|role="status"/)
  }
  // 标签文案通过 Vue 文本插值转义，不把历史单据内容解释为 HTML。
  const html = await render({ label: '<script>异常状态</script>' })
  assert.ok(html.includes('app-status-tag--neutral'))
  assert.ok(html.includes('&lt;script&gt;异常状态&lt;/script&gt;'))
  assert.doesNotMatch(html, /<script>/)
})
