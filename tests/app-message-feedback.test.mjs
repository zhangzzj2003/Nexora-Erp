import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { createSSRApp, getCurrentInstance, h, ref } from 'vue'
import { createPinia } from 'pinia'
import { renderToString } from '@vue/server-renderer'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import Icons from 'unplugin-icons/vite'
import { observeAppMessageFeedback } from '../src/renderer/src/utils/app-message-feedback.ts'

test('全局反馈只在新消息出现时发出，清空后相同操作仍会再次提示', () => {
  const notice = ref('')
  const error = ref('')
  const shown = []
  const stop = observeAppMessageFeedback({ notice, error }, (tone, content) => {
    shown.push({ tone, content })
  })

  notice.value = '库存已切换。'
  notice.value = ''
  notice.value = '库存已切换。'
  error.value = '刷新失败'
  error.value = ''
  assert.deepEqual(shown, [
    { tone: 'success', content: '库存已切换。' },
    { tone: 'success', content: '库存已切换。' },
    { tone: 'error', content: '刷新失败' }
  ])

  stop()
  notice.value = '数据已刷新。'
  assert.equal(shown.length, 3)
})

test('全应用提供右上角通知，工作台不再渲染整行成功与失败横幅', () => {
  const app = readFileSync(new URL('../src/renderer/src/App.vue', import.meta.url), 'utf8')
  const provider = readFileSync(new URL('../src/renderer/src/components/feedback/AppMessageProvider.vue', import.meta.url), 'utf8')
  const bridge = readFileSync(new URL('../src/renderer/src/components/feedback/AppMessageBridge.vue', import.meta.url), 'utf8')
  const shell = readFileSync(new URL('../src/renderer/src/views/WorkspaceShell.vue', import.meta.url), 'utf8')

  // 提供器必须包住引导页和工作台，桥接器才能在任何页面收到业务反馈。
  assert.match(app, /<AppMessageProvider>[\s\S]*<OnboardingView[\s\S]*<WorkspaceShell v-else \/>[\s\S]*<\/AppMessageProvider>/)
  assert.match(provider, /<NMessageProvider placement="top-right"/)
  assert.doesNotMatch(provider, /:max=/)
  assert.match(provider, /<AppMessageBridge \/>/)
  assert.match(bridge, /observeAppMessageFeedback\(\{ notice, error \}/)
  assert.doesNotMatch(shell, /class="message (?:success|error)"/)
})

test('真实通知提供器在 Mac 和 Windows 避开顶部栏，保留关闭与悬停行为', async t => {
  const oldWindow = globalThis.window
  const server = await createServer({ configFile: false, plugins: [vue(), Icons({ compiler: 'vue3' }), {
    name: 'message-test-memory-router',
    // SSR 只替换浏览器地址历史，反馈桥接仍执行真实 Pinia 状态。
    load(id) {
      if (id.endsWith('/router/browser-router.ts'))
        return "import { createRouter, createMemoryHistory } from 'vue-router'; export const workspaceRouter = createRouter({ history: createMemoryHistory(), routes: [] })"
    }
  }], optimizeDeps: { noDiscovery: true, include: [] },
  server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  t.after(async () => { globalThis.window = oldWindow; await server.close() })
  const { default: Provider } = await server.ssrLoadModule('/src/renderer/src/components/feedback/AppMessageProvider.vue')

  for (const platform of ['darwin', 'win32', 'linux', undefined]) {
    globalThis.window = platform ? { nexora: { platform } } : undefined
    let providerProps
    const Probe = {
      setup() {
        // 在真实 NMessageProvider 的插槽读取生效参数，避免仅检查源码字符串。
        providerProps = getCurrentInstance().parent.props
        return () => h('span', '页面内容')
      }
    }
    const app = createSSRApp({ render: () => h(Provider, null, { default: () => h(Probe) }) }).use(createPinia())
    assert.match(await renderToString(app), /页面内容/)
    assert.equal(providerProps.placement, 'top-right')
    assert.equal(providerProps.duration, 4000)
    assert.equal(providerProps.closable, true)
    assert.equal(providerProps.keepAliveOnHover, true)
    if (platform === 'darwin' || platform === 'win32') assert.deepEqual(providerProps.containerStyle, { top: '60px' })
    else assert.equal(providerProps.containerStyle, undefined)
  }
})
