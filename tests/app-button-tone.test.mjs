import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { NConfigProvider, darkTheme, lightTheme } from 'naive-ui'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'

// 使用真实按钮和明暗主题，防止仅传入 tone 却被通用主色覆盖。
test('业务按钮的语义色在明暗主题实际生效，加载禁用与原生按钮类型保持兼容', async t => {
  const server = await createServer({ configFile: false, plugins: [vue()],
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  t.after(() => server.close())
  const { default: Button } = await server.ssrLoadModule('/src/renderer/src/components/app/AppButton.vue')
  for (const theme of [lightTheme, darkTheme]) {
    const render = props => renderToString(createSSRApp({
      render: () => h(NConfigProvider, { theme }, () => h(Button, props, () => '操作'))
    }))
    for (const tone of ['error', 'warning', 'success', 'info']) {
      const color = theme.common[`${tone}Color`]
      const html = await render({ tone })
      assert.ok(html.includes(`--n-color:${color};`), `${theme.name} ${tone} 应使用语义色`)
      assert.ok(html.includes(`n-button--${tone}-type`))
      assert.match(html, /type="button"/)
      assert.doesNotMatch(html, / disabled(?:\s|>)/)
      const disabled = await render({ tone, disabled: true })
      assert.match(disabled, / disabled(?:\s|>)/)
      assert.ok(disabled.includes(`--n-color-disabled:${color};`))
    }
    const loading = await render({ tone: 'error', loading: true, type: 'submit' })
    assert.match(loading, / disabled(?:\s|>)/)
    assert.match(loading, /type="submit"/)
    // 刷新、关闭等无语义色按钮继续使用既有次要按钮主题。
    assert.ok((await render({})).includes('--n-color:var(--workspace-field-background);'))
  }
})
