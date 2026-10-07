import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { before, after, test } from 'node:test'
import { createPinia } from 'pinia'
import { createSSRApp, h, nextTick } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { setup as setupSsrStyles } from '@css-render/vue3-ssr'
import { createServer } from 'vite'
import { parse, compileStyle } from '@vue/compiler-sfc'
import vue from '@vitejs/plugin-vue'
import Icons from 'unplugin-icons/vite'
import { LOCALE_STORAGE_KEY, readLocalePreference, saveLocalePreference } from '../src/renderer/src/utils/locale-preference.ts'

let server, useSettingsStore, useThemeStore, translateCopy, englishCopy
before(async () => {
  // 执行真实 store 和 Vue 页面，避免测试只复制实现或检查静态字符串。
  server = await createServer({ configFile: false, plugins: [vue(), Icons({ compiler: 'vue3' }), {
    name: 'settings-ssr-memory-router',
    // SSR 没有浏览器 location，只替换地址历史；表单与 Pinia 业务状态仍执行真实代码。
    load(id) {
      if (id.endsWith('/router/browser-router.ts'))
        return "import { createRouter, createMemoryHistory } from 'vue-router'; export const workspaceRouter = createRouter({ history: createMemoryHistory(), routes: [] })"
    }
  }],
    optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  ;({ useThemeStore } = await server.ssrLoadModule('/src/renderer/src/store/theme-store.ts'))
  ;({ useSettingsStore } = await server.ssrLoadModule('/src/renderer/src/store/settings-store.ts'))
  ;({ translateCopy } = await server.ssrLoadModule('/src/renderer/src/i18n/common-copy.ts'))
  ;({ englishCopy } = await server.ssrLoadModule('/src/renderer/src/i18n/en-US.ts'))
})
after(() => server?.close())

test('首次编号风格卡片补齐边框，卡片与焦点层圆角覆盖连体按钮端点规则', async () => {
  // 编译真实局部样式：独立卡片必须有完整边框，且不能改变常规设置的连体样式。
  const source = readFileSync(new URL('../src/renderer/src/components/workspace/DocumentNumberingSettings.vue', import.meta.url), 'utf8')
  const { descriptor } = parse(source)
  const { code, errors } = compileStyle({ source: descriptor.styles[0].content, filename: 'DocumentNumberingSettings.vue', id: 'data-v-border-test', scoped: true })
  assert.deepEqual(errors, [])
  const rules = [...code.matchAll(/([^{}]+)\{([^{}]+)\}/g)]
  const borderRules = rules.filter(([, selector, rule]) => selector.includes('.n-radio-button') && /border:\s*1px solid/.test(rule))
  assert.equal(borderRules.length, 1)
  assert.match(borderRules[0][1], /\.numbering-settings--initial\[data-v-border-test\]/)
  assert.match(borderRules[0][2], /border:\s*1px solid var\(--n-button-border-color\)/)
  const checked = rules.find(([, selector]) => selector.includes('.n-radio-button.n-radio-button--checked'))
  assert.ok(checked)
  assert.match(checked[2], /border-color:\s*var\(--n-button-border-color-active\)/)
  const focus = rules.find(([, selector]) => selector.includes('.n-radio-button__state-border'))
  assert.ok(focus)
  assert.match(borderRules[0][2], /border-radius:\s*10px/)
  assert.match(focus[2], /border-radius:\s*inherit/)
  // 使用实际依赖生成的首尾规则比较优先级，避免 Naive UI 后插入样式再次覆盖局部圆角。
  const naiveStyle = (await import('../node_modules/naive-ui/es/radio/src/styles/radio-group.cssr.mjs')).default
  const endpoints = [...naiveStyle.render({ bPrefix: '.n-' }).matchAll(/([^{}]+)\{([^{}]+)\}/g)]
    .filter(([, selector, rule]) => /:(first|last)-child/.test(selector) && /border-.*-radius:/.test(rule))
  assert.equal(endpoints.length, 4)
  // 这些端点选择器只包含类、局部属性与首尾伪类，三者按同一权重计数。
  const specificity = selector => (selector.match(/\.[\w-]+|\[[^\]]+\]|:(?:first|last)-child/g) ?? []).length
  for (const [, selector] of endpoints) {
    const own = selector.includes('__state-border') ? focus[1] : borderRules[0][1]
    assert.ok(specificity(own) > specificity(selector), `圆角覆盖必须优先于 ${selector.trim()}`)
  }
})

test('Windows 设置面板避开原生标题栏，Mac、Linux 与浏览器保留原布局', async t => {
  const oldWindow = globalThis.window
  t.after(() => { globalThis.window = oldWindow })
  const { default: SettingsDrawer } = await server.ssrLoadModule('/src/renderer/src/components/app/AppSettingsDrawer.vue')
  // 渲染真实 Naive UI 抽屉，验证样式落在面板而不是内部滚动区或遮罩上。
  for (const platform of ['win32', 'darwin', 'linux', undefined]) {
    globalThis.window = platform ? { nexora: { platform } } : undefined
    const pinia = createPinia(), settings = useSettingsStore(pinia)
    settings.openSettings()
    const app = createSSRApp({ render: () => h(SettingsDrawer) }).use(pinia)
    setupSsrStyles(app)
    const context = {}
    const html = await renderToString(app, context)
    const content = html + Object.values(context.teleports ?? {}).join('')
    const panel = content.match(/<div(?=[^>]*\bid="app-settings-panel")(?=[^>]*\bclass="[^"]*\bn-drawer\b)[^>]*>/)?.[0]
    assert.ok(panel, '布局偏移必须应用于真实抽屉面板')
    assert.match(panel, /role="dialog"/)
    assert.match(panel, /width:min\(400px, 100vw\)/)
    if (platform === 'win32') assert.match(panel, /top:48px/)
    else assert.doesNotMatch(panel, /top:48px/)
    assert.match(content, /aria-label="关闭设置"/)
  }
})

test('语言偏好只接受支持的值，缺失、损坏和存储失败时使用中文', () => {
  for (const value of [null, '', 'zh-CN', 'en', 'invalid'])
    assert.equal(readLocalePreference({ getItem: () => value }), 'zh-CN')
  assert.equal(readLocalePreference({ getItem: () => 'en-US' }), 'en-US')
  assert.equal(readLocalePreference(undefined), 'zh-CN')
  assert.equal(readLocalePreference({ getItem() { throw new Error('blocked') } }), 'zh-CN')
  assert.doesNotThrow(() => saveLocalePreference({ setItem() { throw new Error('blocked') } }, 'en-US'))
})

test('语言切换同步根语言和本地记忆，开合抽屉不重置偏好并拒绝非法值', async t => {
  const values = new Map()
  const oldWindow = globalThis.window, oldDocument = globalThis.document
  globalThis.window = { localStorage: { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value) } }
  globalThis.document = { documentElement: { lang: '' } }
  t.after(() => { globalThis.window = oldWindow; globalThis.document = oldDocument })
  const pinia = createPinia(), settings = useSettingsStore(pinia)
  settings.openSettings()
  assert.equal(settings.settingsOpen, true)
  settings.setLocale('en-US')
  await nextTick()
  assert.equal(settings.t('设置'), 'Settings')
  assert.equal(globalThis.document.documentElement.lang, 'en-US')
  assert.equal(values.get(LOCALE_STORAGE_KEY), 'en-US')
  settings.setLocale('invalid')
  settings.closeSettings()
  assert.equal(settings.settingsOpen, false)
  settings.openSettings()
  assert.equal(settings.locale, 'en-US')
  // 新窗口恢复语言，但抽屉不会因为上次打开而在启动时自动弹出。
  const restored = useSettingsStore(createPinia())
  assert.equal(restored.locale, 'en-US')
  assert.equal(restored.settingsOpen, false)
  settings.setLocale('zh-CN')
  await nextTick()
  assert.equal(settings.t('设置'), '设置')
})

test('翻译参数按当前语言替换，服务端名称和未知业务消息保留原文', () => {
  assert.equal(translateCopy('en-US', '使用 {server} 的账号访问采购、库存与用户权限。', { server: '联光总部' }),
    'Use your 联光总部 account to access purchasing, inventory and user permissions.')
  assert.equal(translateCopy('zh-CN', '发现 {count} 个服务端', { count: 0 }), '发现 0 个服务端')
  assert.equal(translateCopy('en-US', '发现 {count} 个服务端', { count: 2 }), 'Found 2 servers')
  assert.equal(translateCopy('en-US', '后端业务错误'), '后端业务错误')
  assert.equal(translateCopy('en-US', '{constructor}'), '{constructor}')
})

test('公共界面显式翻译文案和所有导航标签都有英文覆盖', async () => {
  const root = new URL('../src/renderer/src/', import.meta.url)
  const files = ['views/AuthView.vue', 'views/OnboardingView.vue', 'components/app/AppSettingsDrawer.vue',
    'components/app/AppSettingsButton.vue', 'components/app/ThemeToggle.vue', 'components/workspace/WorkspaceSidebar.vue',
    'components/workspace/WorkspaceTabs.vue', 'components/workspace/WorkspaceTitleNavigation.vue',
    ...readdirSync(new URL('views/onboarding/', root)).filter(name => name.endsWith('.vue')).map(name => `views/onboarding/${name}`)]
  for (const file of files) {
    const source = readFileSync(new URL(file, root), 'utf8')
    for (const [, , copy] of source.matchAll(/\bt\((['"])(.*?)\1/g))
      assert.ok(englishCopy[copy], `${file} 缺少英文：${copy}`)
  }
  const { workspaceRouteGroups } = await server.ssrLoadModule('/src/renderer/src/router/workspace-routes.ts')
  for (const group of workspaceRouteGroups) {
    assert.ok(englishCopy[group.label], group.label)
    for (const route of group.routes) assert.ok(englishCopy[route.label], route.label)
  }
  const { onboardingCopy } = await server.ssrLoadModule('/src/renderer/src/i18n/zh-CN.ts')
  for (const copy of Object.values(onboardingCopy)) {
    assert.ok(englishCopy[copy.title], copy.title)
    assert.ok(englishCopy[copy.description], copy.description)
  }
})

test('真实登录和管理员表单按语言渲染，保留草稿、密码约束与离线保护', async () => {
  const { default: AuthView } = await server.ssrLoadModule('/src/renderer/src/views/AuthView.vue')
  const { usePiniaAppStore } = await server.ssrLoadModule('/src/renderer/src/store/app-store.ts')
  const pinia = createPinia(), store = usePiniaAppStore(pinia), settings = useSettingsStore(pinia)
  store.screen = 'login'; store.username = 'draft-admin'; store.password = 'draft-password'
  store.connectionLost = true
  async function render() {
    const app = createSSRApp({ render: () => h(AuthView) }).use(pinia)
    setupSsrStyles(app)
    return renderToString(app)
  }
  assert.match(await render(), /登录工作台/)
  settings.setLocale('en-US')
  const english = await render()
  assert.match(english, /Sign in to your workspace/)
  assert.match(english, /value="draft-admin"/)
  assert.match(english, /placeholder="Enter your password"/)
  assert.match(english, /type="submit"[^>]*disabled/)
  assert.equal(store.password, 'draft-password')
  store.screen = 'setup'
  const setup = await render()
  assert.match(setup, /Create the first administrator/)
  assert.match(setup, /at least 12 characters/)
  // 最小长度由 AppInput 挂载到真实输入框后安装；SSR 验证初始化密码语义。
  assert.match(setup, /autocomplete="new-password"/)
  assert.equal(store.username, 'draft-admin')
})

// 执行真实主题 store，覆盖恢复、非法值和明暗独立性；DOM 只记录同步结果。
test('颜色切换同步根变量，保留语言和抽屉状态，重启恢复颜色且不影响明暗偏好', async t => {
  const values = new Map(), styles = new Map()
  const oldWindow = globalThis.window, oldDocument = globalThis.document
  globalThis.window = { localStorage: { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value) } }
  globalThis.document = { documentElement: { dataset: {}, style: { setProperty: (key, value) => styles.set(key, value) } } }
  t.after(() => { globalThis.window = oldWindow; globalThis.document = oldDocument })
  const pinia = createPinia(), theme = useThemeStore(pinia), settings = useSettingsStore(pinia)
  settings.setLocale('en-US'); settings.openSettings()
  theme.setThemeColor('violet'); await nextTick()
  assert.equal(styles.get('--app-button-primary'), '#7c3aed')
  assert.equal(globalThis.document.documentElement.dataset.themeColor, 'violet')
  assert.equal(values.get('nexora-theme-color'), 'violet')
  theme.setDarkTheme(true); await nextTick()
  assert.equal(theme.themeColor, 'violet')
  assert.equal(styles.get('--workspace-field-accent'), '#c4b5fd')
  assert.equal(settings.locale, 'en-US'); assert.equal(settings.settingsOpen, true)
  theme.setThemeColor('url(malicious)'); await nextTick()
  assert.equal(theme.themeColor, 'violet')
  const restored = useThemeStore(createPinia())
  assert.equal(restored.themeColor, 'violet'); assert.equal(restored.themeMode, 'dark')
  theme.setDarkTheme(false); await nextTick()
  assert.equal(styles.get('--workspace-field-accent'), theme.colorPalette.accent)
  assert.equal(theme.themeColor, 'violet')
  // 存储拒绝写入时主题仍生效，不能让隐私模式阻断操作。
  globalThis.window.localStorage.setItem = () => { throw new Error('blocked') }
  theme.setThemeColor('rose'); await nextTick()
  assert.equal(styles.get('--app-button-primary'), '#be185d')
})

test('首次编号设置真实组件显示三步进度和下一步，锁定查看仍显示完整规则', async t => {
  const previous = globalThis.window
  globalThis.window = { nexora: { platform: 'linux' } }
  t.after(() => { globalThis.window = previous })
  const { default: Numbering } = await server.ssrLoadModule('/src/renderer/src/components/workspace/DocumentNumberingSettings.vue')
  const { usePiniaAppStore } = await server.ssrLoadModule('/src/renderer/src/store/app-store.ts')
  const pinia = createPinia(), store = usePiniaAppStore(pinia), settings = useSettingsStore(pinia)
  // 使用真实 Pinia 和 Naive UI 表单，确认首次页与系统查看页没有混用提交入口。
  store.user = { id: 1, username: 'admin', roles: ['admin'], permissions: [] }
  store.documentNumbering = { configured: false, style: null, timezone_mode: 'server', timezone: null,
    version: 0, locked: false, configured_by: null, configured_at: null,
    server_time: '2026-10-07T00:01:00+08:00', business_time: '2026-10-07T00:01:00+08:00',
    business_date: '20261007', timezones: ['UTC', 'Asia/Shanghai', 'America/New_York'], backfilled_count: 0, undated_count: 0 }
  async function render(initial) {
    const app = createSSRApp({ render: () => h(Numbering, { initial }) }).use(pinia)
    setupSsrStyles(app)
    return renderToString(app)
  }
  const chinese = await render(true)
  assert.match(chinese, /aria-label="设置进度"/); assert.match(chinese, /aria-current="step"/)
  assert.match(chinese, /选择编号风格/); assert.match(chinese, /下一步/)
  assert.doesNotMatch(chinese, /保存编号规则/); assert.match(chinese, /切换服务端/)
  assert.match(chinese, /QTRK-20261007-000001/); assert.match(chinese, /OIN-20261007-000001/)
  settings.setLocale('en-US')
  const english = await render(true)
  assert.match(english, /Choose a numbering style/); assert.match(english, /Setup progress/)
  assert.match(english, /Next/); assert.doesNotMatch(english, /选择编号风格/)
  store.documentNumbering = { ...store.documentNumbering, configured: true, style: 'english', locked: true, version: 1 }
  const locked = await render(false)
  assert.doesNotMatch(locked, /class="app-stepper"/); assert.match(locked, /2026-10-07 00:01:00\+08:00/)
  assert.match(locked, /locked/); assert.doesNotMatch(locked, />Save numbering rules</)
})
