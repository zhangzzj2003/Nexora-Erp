import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { parse, compileStyle } from '@vue/compiler-sfc'
import postcss from 'postcss'
import { windowOverlayTheme } from '../src/shared/window-chrome.ts'

test('顶栏与底栏在明暗主题共用背景、分隔线和原生安全区高度', () => {
  const base = postcss.parse(readFileSync(new URL('../src/renderer/src/style.css', import.meta.url), 'utf8'))
  const dark = postcss.parse(readFileSync(new URL('../src/renderer/src/dark-theme.css', import.meta.url), 'utf8'))
  const light = postcss.parse(readFileSync(new URL('../src/renderer/src/light-theme.css', import.meta.url), 'utf8'))
  const { descriptor } = parse(readFileSync(new URL('../src/renderer/src/components/app/AppTitleBar.vue', import.meta.url), 'utf8'))
  const { code, errors } = compileStyle({ source: descriptor.styles[0].content, filename: 'AppTitleBar.vue', id: 'data-v-window-bar-test', scoped: true })
  assert.deepEqual(errors, [])
  const title = postcss.parse(code)
  const values = (sheet, selector) => {
    const declarations = {}
    sheet.walkRules(rule => {
      if (rule.selectors.includes(selector)) rule.walkDecls(decl => { declarations[decl.prop] = decl.value })
    })
    return declarations
  }
  const header = values(title, '.app-titlebar[data-v-window-bar-test]')
  const footer = values(base, '.onboard-footer')
  assert.equal(header.height, 'var(--app-window-bar-height)')
  assert.equal(footer.height, header.height)
  assert.equal(header.background, 'var(--app-window-bar-background)')
  assert.equal(footer.background, header.background)
  assert.equal(header['border-bottom'], '1px solid var(--app-window-bar-border)')
  assert.equal(footer['border-top'], header['border-bottom'])
  assert.equal(values(base, ':root')['--app-window-bar-height'], `${windowOverlayTheme('light').height}px`)
  // 禁止主题或响应式规则重新覆盖单侧表面，防止深色模式与窄窗口退回旧色块。
  for (const sheet of [base, light, dark, title]) {
    sheet.walkRules(rule => {
      if (!rule.selectors.some(selector => /\.(?:app-titlebar|onboard-footer|app-status-footer)(?:\[|$)/.test(selector))) return
      rule.walkDecls(decl => {
        if (/^(?:height|background(?:-color)?|border(?:-(?:top|bottom|color))?)$/.test(decl.prop)) {
          assert.match(decl.value, /var\(--app-window-bar-(?:height|background|border)\)/)
        }
      })
    })
  }
  assert.equal(values(base, ':root')['--app-window-bar-background'], '#fff')
  assert.equal(values(dark, ":root[data-theme='dark']")['--app-window-bar-background'], '#111d32')
  assert.equal(values(base, ':root')['--app-window-bar-border'], '#dfe6ed')
  assert.equal(values(dark, ":root[data-theme='dark']")['--app-window-bar-border'], '#33445f')
})

test('底栏等高后仍容纳两行长提示，窄窗口只收缩水平留白', () => {
  const sheet = postcss.parse(readFileSync(new URL('../src/renderer/src/style.css', import.meta.url), 'utf8'))
  const declarations = selector => {
    const result = {}
    sheet.walkRules(rule => {
      if (rule.selector === selector) rule.walkDecls(decl => { result[decl.prop] = decl.value })
    })
    return result
  }
  const footer = declarations('.onboard-footer')
  const status = declarations('.onboard-footer-status')
  const text = declarations('.onboard-footer-status-text')
  // 两行正文、上下留白和分隔线之和不能超过栏高，长错误继续在正文内滚动。
  const twoLines = Number.parseFloat(status['font-size']) * Number(status['line-height']) * 2
  assert.ok(twoLines + Number.parseFloat(footer.padding) * 2 + 1 <= windowOverlayTheme('light').height)
  assert.equal(text['max-height'], '3em')
  assert.equal(text['overflow-y'], 'auto')
  assert.equal(text['overflow-wrap'], 'anywhere')
  sheet.walkAtRules('media', media => {
    media.walkRules('.app-status-footer', rule => {
      rule.walkDecls(decl => assert.ok(!['height', 'padding', 'padding-block', 'padding-top', 'padding-bottom'].includes(decl.prop)))
    })
  })
  const transitions = readFileSync(new URL('../src/renderer/src/theme-transitions.css', import.meta.url), 'utf8')
  // 正常切换和减少动态效果都同时覆盖上下栏，避免只有底栏缓慢变色。
  assert.equal((transitions.match(/\.app-titlebar, \.onboard-footer/g) ?? []).length, 2)
})

test('登录和工作台共用连接底栏，业务反馈交由通知层展示', () => {
  const shell = readFileSync(new URL('../src/renderer/src/views/WorkspaceShell.vue', import.meta.url), 'utf8')
  const onboarding = readFileSync(new URL('../src/renderer/src/views/OnboardingView.vue', import.meta.url), 'utf8')
  const footer = readFileSync(new URL('../src/renderer/src/components/app/AppStatusFooter.vue', import.meta.url), 'utf8')

  // 所有阶段只实例化同一个底栏，避免工作台遗漏连接状态。
  assert.match(shell, /<AppStatusFooter \/>/)
  assert.match(onboarding, /<AppStatusFooter \/>/)
  assert.doesNotMatch(shell, /<footer v-if="isAuthScreen"/)
  assert.doesNotMatch(shell, /v-if="notice" class="message success" role="status"/)
  assert.doesNotMatch(shell, /v-if="error" class="message error" role="alert"/)
  assert.doesNotMatch(shell, /v-if="connectionLost" class="message/)
  // 服务端名称仍保留原文，未选择的界面提示随公共语言切换。
  assert.match(footer, /server\?\.name \|\| t\('未选择服务端'\)/)
  assert.match(footer, /server\?\.version/)
  assert.match(footer, /:role="status\.tone === 'error' \? 'alert' : 'status'"/)
})

test('页面内容滚动时，公共底栏仍固定在视口底部', () => {
  const css = readFileSync(new URL('../src/renderer/src/style.css', import.meta.url), 'utf8')
  const rule = (selector) => css.match(new RegExp(`${selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')} \\{([^}]+)\\}`, 'm'))?.[1] ?? ''

  // 滚动区域和底栏必须属于同一个定高列容器，长库存页才不会盖住底栏。
  assert.match(rule('.app-shell'), /height: 100vh;[^}]*overflow: hidden;/)
  assert.match(rule('.content'), /height: 100vh;[^}]*flex-direction: column;[^}]*overflow: hidden;/)
  assert.match(rule('.content-body'), /min-height: 0;[^}]*flex: 1;[^}]*overflow-y: auto;/)
  assert.match(rule('.onboard-footer'), /flex: none;/)
  assert.match(rule('.app-status-footer'), /grid-template-columns: minmax\(0, 1fr\) minmax\(0, 1fr\);/)
  assert.match(css, /@media \(max-width: 760px\)[\s\S]*?\.content \{ height: auto; min-height: 0; flex: 1; \}/)
})

test('登录页占满窗口，进入工作台后侧栏与底栏同步过渡', () => {
  const shell = readFileSync(new URL('../src/renderer/src/views/WorkspaceShell.vue', import.meta.url), 'utf8')
  const auth = readFileSync(new URL('../src/renderer/src/views/AuthView.vue', import.meta.url), 'utf8')
  const css = readFileSync(new URL('../src/renderer/src/style.css', import.meta.url), 'utf8')

  // 未登录时不挂载侧栏，内容始终占第二列；同一个底栏随列宽变化移动。
  assert.match(shell, /:class="\{ 'has-sidebar': screen === 'app' \}"/)
  assert.match(shell, /<Transition name="sidebar-slide">\s*<WorkspaceSidebar v-if="screen === 'app'" \/>/)
  // 产品目录新增专属布局，但登录和编号引导必须继续使用各自的原有条件。
  assert.match(shell, /:class="\{ 'auth-screen': isAuthScreen, 'numbering-onboarding': isNumberingScreen, 'product-catalog-screen': isProductWorkspace \}"/)
  assert.match(shell, /const isProductWorkspace = computed\(\(\) => screen\.value === 'app' && activeTab\.value === 'products'\)/)
  // 品牌与凭据卡片作为一组居中，工作台标题不再在登录时占据左上角。
  assert.match(shell, /v-if="!isNumberingScreen && !isAuthScreen" class="topbar"/)
  assert.doesNotMatch(shell, /auth-header-mark/)
  assert.match(auth, /import \{ nexoraLogo \} from '\.\.\/assets\/brand'/)
  assert.match(auth, /class="auth-stage"[\s\S]*class="auth-brand"[\s\S]*class="auth-brand-mark"[\s\S]*<img :src="nexoraLogo" alt="" \/>/)
  assert.match(auth, /NEXORA WORKSPACE/)
  assert.match(auth, /<h1\b[^>]*>\{\{ t\('开始使用联光 ERP'\) \}\}<\/h1>/)
  // 浏览器与 Linux 没有融合标题栏，设置入口仍独立保留在登录内容上方。
  assert.match(shell, /v-if="isAuthScreen && !integratedTitleBar" class="auth-session-bar"[\s\S]*?<ThemeToggle \/>[\s\S]*?<AppSettingsButton \/>/)
  assert.match(css, /\.app-shell \{[^}]*grid-template-columns: 0px minmax\(0, 1fr\);[^}]*transition: grid-template-columns/)
  assert.match(css, /\.app-shell\.has-sidebar \{ grid-template-columns: 238px minmax\(0, 1fr\); \}/)
  assert.match(css, /\.content \{ grid-column: 2;/)
  // 禁止卡片收缩，让矮窗口通过内容区滚动而不是挤压表单；自动外边距只在空间足够时居中。
  assert.match(css, /\.auth-screen \.auth-stage \{[^}]*flex: none;[^}]*width: min\(100%, 1000px\);[^}]*margin: auto;/)
  assert.match(css, /\.sidebar-slide-enter-from, \.sidebar-slide-leave-to \{ transform: translateX\(-100%\); \}/)
  assert.match(css, /@media \(prefers-reduced-motion: reduce\) \{[\s\S]*?\.app-shell, \.sidebar-slide-enter-active, \.sidebar-slide-leave-active,[^}]*\{ transition: none;/)
})

test('登录页面板统一承载左右区域，窄屏收起说明但保留品牌和同一份表单', () => {
  const auth = readFileSync(new URL('../src/renderer/src/views/AuthView.vue', import.meta.url), 'utf8')
  const { descriptor } = parse(auth)
  // 编译页面真实局部样式，断言响应式规则不会因作用域转换丢失。
  const { code, errors } = compileStyle({ source: descriptor.styles[0].content, filename: 'AuthView.vue', id: 'data-v-auth-layout-test', scoped: true })
  assert.deepEqual(errors, [])
  const stageRule = code.match(/\.auth-stage\[data-v-auth-layout-test\] \{([^}]+)\}/)?.[1] ?? ''
  assert.match(stageRule, /display: grid;/)
  assert.match(stageRule, /grid-template-columns: minmax\(0, 1fr\) minmax\(0, 440px\);/)
  // 两栏共用一套面板边界，防止表单重新出现独立卡片的圆角与阴影。
  assert.match(stageRule, /\bborder: 1px solid/)
  assert.match(stageRule, /border-radius: 22px;/)
  assert.match(stageRule, /box-shadow: (?!none)[^;]+;/)
  const stylesheet = postcss.parse(code)
  stylesheet.walkRules(rule => {
    if (rule.selector === '.auth-card[data-v-auth-layout-test]')
      assert.doesNotMatch(rule.toString(), /\b(?:border(?:-[\w-]+)?|box-shadow)\s*:/)
  })
  // 使用 CSS 解析树读取整个媒体规则，避免编译器换行或内部花括号影响断言。
  const responsive = stylesheet.nodes.filter(node => node.type === 'atrule' && node.name === 'media')
  const singleColumn = responsive.find(node => node.params === '(max-width: 860px)')?.toString() ?? ''
  assert.match(singleColumn, /\.auth-stage\[data-v-auth-layout-test\] \{[^}]*grid-template-columns: minmax\(0, 1fr\);[^}]*max-width: 440px;/)
  assert.match(singleColumn, /\.auth-intro-copy\[data-v-auth-layout-test\], \.auth-domains\[data-v-auth-layout-test\] \{\s*display: none;\s*\}/)
  assert.doesNotMatch(singleColumn, /\.auth-(?:brand|card)\[data-v-auth-layout-test\] \{[^}]*display: none;/)
  const narrow = responsive.find(node => node.params === '(max-width: 480px)')?.toString() ?? ''
  assert.match(narrow, /\.auth-stage\[data-v-auth-layout-test\] \{[^}]*border-radius: 18px;/)
  assert.match(narrow, /\.auth-card\[data-v-auth-layout-test\] \{[^}]*padding: 28px 24px 0;/)
  // 响应布局复用同一凭据表单，避免缩放窗口时切换实例而清空输入。
  assert.equal((descriptor.template.content.match(/<form\b/g) ?? []).length, 1)
})

test('侧栏底部显示当前用户、角色和退出，服务端身份交给公共底栏', () => {
  const sidebar = readFileSync(new URL('../src/renderer/src/components/workspace/WorkspaceSidebar.vue', import.meta.url), 'utf8')
  const card = readFileSync(new URL('../src/renderer/src/components/workspace/SidebarAccountCard.vue', import.meta.url), 'utf8')
  const shell = readFileSync(new URL('../src/renderer/src/views/WorkspaceShell.vue', import.meta.url), 'utf8')
  const css = readFileSync(new URL('../src/renderer/src/style.css', import.meta.url), 'utf8')

  // 登录前不显示旧用户；公共底栏继续展示服务端身份。
  assert.match(sidebar, /v-if="screen === 'app' && user" class="sidebar-bottom"/)
  assert.match(sidebar, /<SidebarAccountCard \/>/)
  assert.doesNotMatch(sidebar, /<small v-if="version"/)
  assert.match(card, /v-if="user"[\s\S]*?class="sidebar-account"/)
  assert.match(card, /<strong :title="user\.username">\{\{ user\.username \}\}<\/strong>/)
  assert.match(card, /<small :title="roleText">\{\{ roleText \}\}<\/small>/)
  assert.match(card, /@click="menuOpen = !menuOpen"/)
  assert.doesNotMatch(card, /@mouseenter="menuOpen = true"/)
  assert.match(card, /document\.addEventListener\('pointerdown', closeWhenClickOutside\)/)
  assert.match(card, /@focusout="closeWhenFocusLeaves"/)
  assert.match(card, /@keydown\.esc\.stop="closeOnEscape"/)
  assert.match(card, /v-if="menuOpen"[\s\S]*?@click="logout"/)
  // 左下角主题入口已移除；顶部入口保留，账号菜单不会重新塞入重复开关。
  assert.doesNotMatch(card, /ThemeToggle/)
  assert.match(shell, /class="account-identity"[\s\S]*?user\.username[\s\S]*?accountRole/)
  assert.match(shell, /v-if="user" class="account"[\s\S]*?@click="logout"/)
  assert.match(css, /\.account \{ display: none;/)
  assert.match(css, /@media \(max-width: 760px\)[\s\S]*?\.account \{ display: flex; \}/)
  assert.match(css, /\.account-identity \{ display: none; \}/)
  assert.match(css, /@media \(max-width: 760px\)[\s\S]*?\.account-identity \{ display: block; \}/)
})
