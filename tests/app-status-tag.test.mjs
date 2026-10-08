import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'

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
