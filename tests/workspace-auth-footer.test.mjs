import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

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
  assert.match(footer, /server\?\.name \|\| '未选择服务端'/)
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
  const css = readFileSync(new URL('../src/renderer/src/style.css', import.meta.url), 'utf8')

  // 未登录时不挂载侧栏，内容始终占第二列；同一个底栏随列宽变化移动。
  assert.match(shell, /:class="\{ 'has-sidebar': screen === 'app' \}"/)
  assert.match(shell, /<Transition name="sidebar-slide">\s*<WorkspaceSidebar v-if="screen === 'app'" \/>/)
  assert.match(shell, /:class="\{ 'auth-screen': isAuthScreen \}"/)
  assert.match(shell, /import \{ nexoraLogo \} from '\.\.\/assets\/brand'/)
  assert.match(shell, /<span v-if="isAuthScreen" class="auth-header-mark" aria-hidden="true">\s*<img :src="nexoraLogo" alt="" \/>/)
  assert.match(css, /\.app-shell \{[^}]*grid-template-columns: 0px minmax\(0, 1fr\);[^}]*transition: grid-template-columns/)
  assert.match(css, /\.app-shell\.has-sidebar \{ grid-template-columns: 238px minmax\(0, 1fr\); \}/)
  assert.match(css, /\.content \{ grid-column: 2;/)
  assert.match(css, /\.auth-screen \.auth-card \{ margin: auto; \}/)
  assert.match(css, /\.auth-header-mark \{ width: 52px; height: 52px;/)
  assert.match(css, /\.sidebar-slide-enter-from, \.sidebar-slide-leave-to \{ transform: translateX\(-100%\); \}/)
  assert.match(css, /@media \(prefers-reduced-motion: reduce\) \{[\s\S]*?\.app-shell, \.sidebar-slide-enter-active, \.sidebar-slide-leave-active,[^}]*\{ transition: none;/)
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
