<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { NButton, NConfigProvider, dateZhCN, zhCN } from 'naive-ui'
import type { GlobalThemeOverrides } from 'naive-ui'
// 应用内品牌标记与安装包图标共用第一版 Nexus + Aurora 标志。
import nexoraLogo from '../../../resources/icon.png'
// 从 Remix Icon 的 ri 图标集按需导入，构建时会把 SVG 打包进应用。
import IconArrowRightUpLine from '~icons/ri/arrow-right-up-line'
import IconRadarLine from '~icons/ri/radar-line'
import IconServerLine from '~icons/ri/server-line'
import IconHistoryLine from '~icons/ri/history-line'
import IconAddLine from '~icons/ri/add-line'
import IconCheckboxCircleLine from '~icons/ri/checkbox-circle-line'
import IconErrorWarningLine from '~icons/ri/error-warning-line'
import IconRefreshLine from '~icons/ri/refresh-line'
import IconStackLine from '~icons/ri/stack-line'
import IconArchiveLine from '~icons/ri/archive-line'
import IconFileList3Line from '~icons/ri/file-list-3-line'
import IconTeamLine from '~icons/ri/team-line'
import IconSettings3Line from '~icons/ri/settings-3-line'
import type { Material, Movement, Permission, Receipt, Role, Stock, Supplier, User } from '../../shared/erp-api'
import type { ConnectionCandidate, DiscoveryResult, HostStatus, ServerProfile } from '../../shared/desktop-api'

type Screen = 'loading' | 'welcome' | 'manual' | 'scan' | 'results' | 'create' | 'trust' | 'ready' | 'offline' | 'setup' | 'login' | 'app'
type Tab = 'stock' | 'catalog' | 'receipts' | 'users' | 'settings'

// 让新增的 Naive UI 控件沿用工作台现有的青绿色主色。
const naiveThemeOverrides: GlobalThemeOverrides = {
  common: { primaryColor: '#237d7a', primaryColorHover: '#1d6c69', primaryColorPressed: '#195d5a' }
}

const screen = ref<Screen>('loading')
const activeTab = ref<Tab>('stock')
const version = ref('')
const notice = ref('')
const error = ref('')
const busy = ref(false)
const user = ref<User | null>(null)
const username = ref('')
const password = ref('')
const materials = ref<Material[]>([])
const suppliers = ref<Supplier[]>([])
const stock = ref<Stock[]>([])
const movements = ref<Movement[]>([])
const receipts = ref<Receipt[]>([])
const roles = ref<Role[]>([])
const permissions = ref<Permission[]>([])
const users = ref<User[]>([])
const roleDrafts = ref<Record<number, string[]>>({})
const rolePermissionDrafts = ref<Record<string, string[]>>({})
const roleLabelDrafts = ref<Record<string, string>>({})
const resetPasswords = ref<Record<number, string>>({})
const materialForm = ref({ sku: '', name: '', unit: '件' })
const supplierForm = ref({ name: '' })
const receiptForm = ref({ supplier_id: 0, reference: '', lines: [{ material_id: 0, quantity: '1' }] })
const newUser = ref({ username: '', password: '', roles: ['viewer'] as string[] })
const newRole = ref({ code: '', label: '', permissions: ['inventory.view'] as string[] })
const passwordChange = ref({ current_password: '', new_password: '' })
const server = ref<ServerProfile | null>(null)
const candidate = ref<ConnectionCandidate | null>(null)
const recentServers = ref<ServerProfile[]>([])
const discoveries = ref<DiscoveryResult[]>([])
const scanSeconds = ref(0)
const scanning = ref(false)
const manualForm = ref({ address: '', port: 8000 })
const hostForm = ref({ name: '我的 Nexora ERP', dataDir: '', port: 8000,
  username: 'admin', password: '', confirm: '' })
const trustChecked = ref(false)
const host = ref<HostStatus>({ configured: false, running: false, fingerprint: null })
let scanTimer: ReturnType<typeof setInterval> | null = null
let unsubscribeDiscovery: (() => void) | null = null

const can = (permission: string): boolean => user.value?.permissions.includes(permission) ?? false
// 导航权限仍按原规则计算；图标与文字绑定，避免图标单独承载含义。
const visibleTabs = computed(() => [
  ...(can('inventory.view') ? [{ key: 'stock' as const, label: '库存总览', icon: IconStackLine }, { key: 'catalog' as const, label: '基础资料', icon: IconArchiveLine }, { key: 'receipts' as const, label: '采购入库', icon: IconFileList3Line }] : []),
  ...(can('users.manage') ? [{ key: 'users' as const, label: '用户权限', icon: IconTeamLine }] : []),
  { key: 'settings' as const, label: '连接与服务', icon: IconSettings3Line }
])

function displayError(cause: unknown): string {
  const message = cause instanceof Error ? cause.message : '操作失败'
  return message.replace(/^Error invoking remote method '[^']+': Error: /, '')
}

function localTime(value: string): string {
  // SQLite 的 CURRENT_TIMESTAMP 是 UTC，展示时换算成用户设备的本地时区。
  const date = new Date(value.replace(' ', 'T') + 'Z')
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

async function checkConnection(): Promise<void> {
  if (!window.nexora) {
    screen.value = 'offline'
    error.value = '请在 Electron 桌面应用中打开此页面。'
    return
  }
  busy.value = true
  error.value = ''
  try {
    const state = await window.nexora.startup()
    if (state.status === 'connected') {
      server.value = state.server
      screen.value = 'login'
    } else if (state.status === 'needs_setup') {
      server.value = state.server
      screen.value = 'setup'
    } else if (state.status === 'offline') {
      server.value = state.server ?? null
      screen.value = 'offline'
      error.value = state.message
    } else {
      screen.value = 'welcome'
    }
    recentServers.value = await window.nexora.recentServers()
    host.value = await window.nexora.hostStatus()
  } catch (cause) {
    screen.value = 'offline'
    error.value = displayError(cause)
  } finally {
    busy.value = false
  }
}

function clearMessage(): void { error.value = ''; notice.value = '' }

async function go(screenName: Screen): Promise<void> {
  clearMessage()
  if (screen.value === 'scan') await stopScan()
  screen.value = screenName
}

async function switchServer(): Promise<void> {
  if (!window.nexora) return
  if (user.value) {
    try { await window.nexora.callApi('logout', undefined) } catch { /* 网络中断时仍清理本地连接。 */ }
  }
  user.value = null
  server.value = null
  await window.nexora.disconnect()
  recentServers.value = await window.nexora.recentServers()
  await go('welcome')
}

async function connectManual(): Promise<void> {
  if (!window.nexora || busy.value) return
  busy.value = true
  clearMessage()
  try {
    candidate.value = await window.nexora.prepareConnection(manualForm.value.address, Number(manualForm.value.port))
    trustChecked.value = false
    if (candidate.value.trusted) {
      server.value = await window.nexora.approveConnection(candidate.value.id, candidate.value.fingerprint)
      await go('ready')
    } else await go('trust')
  } catch (cause) { error.value = displayError(cause) }
  finally { busy.value = false }
}

async function connectSaved(profile: ServerProfile): Promise<void> {
  if (!window.nexora || busy.value) return
  busy.value = true
  clearMessage()
  try {
    server.value = await window.nexora.activateSaved(profile.id)
    await go('ready')
  } catch (cause) {
    error.value = displayError(cause)
    manualForm.value = { address: profile.host, port: profile.port }
    screen.value = 'manual'
  } finally { busy.value = false }
}

async function approveTrust(): Promise<void> {
  if (!window.nexora || !candidate.value || !trustChecked.value) return
  busy.value = true
  try {
    server.value = await window.nexora.approveConnection(candidate.value.id, candidate.value.fingerprint)
    recentServers.value = await window.nexora.recentServers()
    await go('ready')
  } catch (cause) { error.value = displayError(cause) }
  finally { busy.value = false }
}

async function startScan(): Promise<void> {
  if (!window.nexora) return
  await go('scan')
  scanSeconds.value = 0
  discoveries.value = []
  scanning.value = true
  unsubscribeDiscovery?.()
  unsubscribeDiscovery = window.nexora.onDiscovery((results) => { discoveries.value = results })
  try {
    await window.nexora.startDiscovery()
    scanTimer = setInterval(() => { scanSeconds.value += 1 }, 1000)
  } catch (cause) {
    scanning.value = false
    error.value = displayError(cause)
  }
}

async function stopScan(): Promise<void> {
  if (scanTimer) clearInterval(scanTimer)
  scanTimer = null
  if (scanning.value) await window.nexora?.stopDiscovery()
  scanning.value = false
  unsubscribeDiscovery?.()
  unsubscribeDiscovery = null
}

async function showResults(): Promise<void> {
  await stopScan()
  screen.value = 'results'
}

async function pickDiscovered(item: DiscoveryResult): Promise<void> {
  manualForm.value = { address: item.host, port: item.port }
  await connectManual()
}

async function chooseDataDir(): Promise<void> {
  if (!window.nexora) return
  const path = await window.nexora.chooseDataDir()
  if (path) hostForm.value.dataDir = path
}

async function createLocalHost(): Promise<void> {
  if (!window.nexora || busy.value) return
  if (hostForm.value.password !== hostForm.value.confirm) {
    error.value = '两次输入的管理员密码不一致'
    return
  }
  busy.value = true
  clearMessage()
  try {
    server.value = await window.nexora.createHost({
      name: hostForm.value.name, dataDir: hostForm.value.dataDir, port: Number(hostForm.value.port),
      username: hostForm.value.username, password: hostForm.value.password
    })
    hostForm.value.password = ''
    hostForm.value.confirm = ''
    recentServers.value = await window.nexora.recentServers()
    host.value = await window.nexora.hostStatus()
    await go('ready')
  } catch (cause) {
    const failure = displayError(cause)
    await checkConnection()
    error.value = failure
  }
  finally { busy.value = false }
}

async function stopLocalHost(): Promise<void> {
  if (!window.nexora || busy.value) return
  await window.nexora.stopHost()
  host.value = await window.nexora.hostStatus()
  notice.value = '本机服务已停止。'
  if (server.value?.isLocal) {
    // 服务已退出，主进程也已清除令牌，此时无需再向停掉的服务发送登出请求。
    user.value = null
    await switchServer()
  }
}

async function restartLocalHost(): Promise<void> {
  if (!window.nexora || busy.value) return
  busy.value = true
  clearMessage()
  try {
    server.value = await window.nexora.restartHost()
    host.value = await window.nexora.hostStatus()
    if (screen.value === 'offline' || screen.value === 'create') await go('ready')
    notice.value = '本机服务已启动。'
  } catch (cause) { error.value = displayError(cause) }
  finally { busy.value = false }
}

async function authenticate(): Promise<void> {
  if (!window.nexora || busy.value) return
  busy.value = true
  error.value = ''
  try {
    if (screen.value === 'setup') {
      await window.nexora.finishHostSetup(username.value, password.value)
      screen.value = 'login'
      notice.value = '管理员已创建，请登录。'
      password.value = ''
      return
    }
    user.value = await window.nexora.callApi('login', { username: username.value, password: password.value })
    password.value = ''
    screen.value = 'app'
    await refreshData()
    activeTab.value = visibleTabs.value[0]?.key ?? 'stock'
  } catch (cause) {
    error.value = displayError(cause)
  } finally {
    busy.value = false
  }
}

async function refreshData(): Promise<void> {
  if (!window.nexora || !user.value) return
  // 每次写操作后重新读取服务端权限；角色变化立即反映到当前页面。
  user.value = await window.nexora.callApi('me', undefined)
  if (!visibleTabs.value.some((item) => item.key === activeTab.value)) activeTab.value = visibleTabs.value[0]?.key ?? 'settings'
  // 页面只显示当前角色可访问的入口；数据访问仍以服务端授权为准。
  if (can('inventory.view')) {
    [materials.value, suppliers.value, stock.value, receipts.value, movements.value] = await Promise.all([
      window.nexora.callApi('materials', undefined),
      window.nexora.callApi('suppliers', undefined),
      window.nexora.callApi('stock', undefined),
      window.nexora.callApi('receipts', undefined),
      window.nexora.callApi('movements', undefined)
    ])
  }
  if (can('users.manage')) {
    [permissions.value, roles.value, users.value] = await Promise.all([
      window.nexora.callApi('permissions', undefined), window.nexora.callApi('roles', undefined),
      window.nexora.callApi('users', undefined)
    ])
    roleDrafts.value = Object.fromEntries(users.value.map((entry) => [entry.id, [...entry.roles]]))
    rolePermissionDrafts.value = Object.fromEntries(roles.value.map((entry) => [entry.code, [...entry.permissions]]))
    roleLabelDrafts.value = Object.fromEntries(roles.value.map((entry) => [entry.code, entry.label]))
  } else {
    permissions.value = []
    roles.value = []
    users.value = []
  }
}

async function perform(action: () => Promise<unknown>, success: string): Promise<void> {
  if (busy.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    await action()
    await refreshData()
    notice.value = success
  } catch (cause) {
    error.value = displayError(cause)
  } finally {
    busy.value = false
  }
}

function addLine(): void {
  receiptForm.value.lines.push({ material_id: 0, quantity: '1' })
}

function removeLine(index: number): void {
  if (receiptForm.value.lines.length > 1) receiptForm.value.lines.splice(index, 1)
}

async function createMaterial(): Promise<void> {
  if (!window.nexora) return
  await perform(async () => {
    // Vue 的响应式代理不能通过 Electron IPC，发送前只取普通字段。
    await window.nexora!.callApi('createMaterial', { ...materialForm.value })
    materialForm.value = { sku: '', name: '', unit: '件' }
  }, '物料已保存。')
}

async function createSupplier(): Promise<void> {
  if (!window.nexora) return
  await perform(async () => {
    await window.nexora!.callApi('createSupplier', { name: supplierForm.value.name })
    supplierForm.value = { name: '' }
  }, '供应商已保存。')
}

async function createReceipt(): Promise<void> {
  if (!window.nexora) return
  await perform(async () => {
    await window.nexora!.callApi('createReceipt', {
      supplier_id: receiptForm.value.supplier_id,
      reference: receiptForm.value.reference,
      lines: receiptForm.value.lines.map((line) => ({ material_id: line.material_id, quantity: line.quantity }))
    })
    receiptForm.value = { supplier_id: 0, reference: '', lines: [{ material_id: 0, quantity: '1' }] }
  }, '入库单草稿已创建，等待仓库员确认。')
}

async function postReceipt(receiptId: number): Promise<void> {
  if (!window.nexora) return
  await perform(() => window.nexora!.callApi('postReceipt', { receiptId }), `入库单 #${receiptId} 已确认，库存流水已生成。`)
}

async function createUser(): Promise<void> {
  if (!window.nexora) return
  await perform(async () => {
    await window.nexora!.callApi('createUser', {
      username: newUser.value.username, password: newUser.value.password, roles: [...newUser.value.roles]
    })
    newUser.value = { username: '', password: '', roles: ['viewer'] }
  }, '用户已创建。')
}

async function saveRoles(userId: number): Promise<void> {
  if (!window.nexora) return
  await perform(async () => {
    await window.nexora!.callApi('setUserRoles', { userId, roles: [...(roleDrafts.value[userId] ?? [])] })
    if (user.value?.id === userId) user.value = await window.nexora!.callApi('me', undefined)
  }, '角色已更新。')
}

async function createRole(): Promise<void> {
  if (!window.nexora) return
  await perform(async () => {
    await window.nexora!.callApi('createRole', { code: newRole.value.code, label: newRole.value.label,
      permissions: [...newRole.value.permissions] })
    newRole.value = { code: '', label: '', permissions: ['inventory.view'] }
  }, '自定义角色已创建。')
}

async function saveRole(code: string): Promise<void> {
  if (!window.nexora) return
  await perform(() => window.nexora!.callApi('updateRole', { code, label: roleLabelDrafts.value[code],
    permissions: [...(rolePermissionDrafts.value[code] ?? [])] }), '角色权限已更新。')
}

async function setUserStatus(entry: User): Promise<void> {
  if (!window.nexora) return
  await perform(() => window.nexora!.callApi('setUserStatus', { userId: entry.id,
    is_active: !entry.is_active }), entry.is_active ? '账号已停用，原有登录已失效。' : '账号已启用。')
}

async function resetUserPassword(userId: number): Promise<void> {
  if (!window.nexora) return
  await perform(async () => {
    await window.nexora!.callApi('resetUserPassword', { userId, password: resetPasswords.value[userId] })
    resetPasswords.value[userId] = ''
  }, '密码已重置，用户需要重新登录。')
}

async function changeOwnPassword(): Promise<void> {
  if (!window.nexora || busy.value) return
  busy.value = true
  error.value = ''
  try {
    await window.nexora.callApi('changePassword', { ...passwordChange.value })
    passwordChange.value = { current_password: '', new_password: '' }
    user.value = null
    screen.value = 'login'
    notice.value = '密码已修改，请使用新密码重新登录。'
  } catch (cause) { error.value = displayError(cause) }
  finally { busy.value = false }
}

async function logout(): Promise<void> {
  if (!window.nexora) return
  try { await window.nexora.callApi('logout', undefined) } catch { /* 本地界面仍退出，重连后需要再次登录。 */ }
  user.value = null
  screen.value = 'login'
  notice.value = ''
  error.value = ''
}

onMounted(async () => {
  if (window.nexora) version.value = await window.nexora.getVersion().catch(() => '')
  if (window.nexora) hostForm.value.dataDir = await window.nexora.defaultDataDir().catch(() => '')
  await checkConnection()
})

onUnmounted(() => { void stopScan() })
</script>

<template>
  <!-- 统一设置 Naive UI 中文环境；现有页面可逐步使用组件。 -->
  <NConfigProvider :locale="zhCN" :date-locale="dateZhCN" :theme-overrides="naiveThemeOverrides">
  <div v-if="screen !== 'app' && screen !== 'login' && screen !== 'setup'" class="onboarding">
    <header class="onboard-top"><div class="onboard-logo"><span class="onboard-mark"><img :src="nexoraLogo" alt="" /></span><strong>NEXORA <small>ERP</small></strong></div><span class="onboard-top-note">企业运营工作台 <span v-if="version">· v{{ version }}</span></span></header>
    <main class="onboard-main">
      <div class="onboard-hero">
        <p class="onboard-kicker">NEXORA · CONNECT</p>
        <h1>{{ screen === 'welcome' ? '选择你的工作方式' : screen === 'manual' ? '连接现有服务端' : screen === 'scan' ? '正在查找局域网服务端' : screen === 'results' ? '选择服务端' : screen === 'create' ? '创建本机服务端' : screen === 'trust' ? '核对服务端身份' : screen === 'ready' ? '服务端已就绪' : screen === 'offline' ? '连接暂时中断' : '正在准备工作台' }}</h1>
        <p>{{ screen === 'welcome' ? '连接团队已有的服务端，或者在这台电脑上创建一个。' : screen === 'manual' ? '输入局域网地址，连接团队的 Nexora ERP。' : screen === 'scan' ? '正在发现同一局域网中可用的 Nexora 服务端。' : screen === 'results' ? '以下服务端由当前网络实际发现；选择后仍需核对身份。' : screen === 'create' ? '数据保存在所选目录；服务会在登录期间持续运行。' : screen === 'trust' ? '请与服务端电脑上的指纹逐字核对，再使用账号密码登录。' : screen === 'ready' ? '连接和服务状态已确认，可以进入工作台。' : screen === 'offline' ? '检查网络或本机服务，再试一次。' : '请稍候。' }}</p>
      </div>
      <div v-if="error" class="onboard-alert" role="alert">{{ error }}</div>
      <div v-if="notice" class="onboard-alert success" role="status">{{ notice }}</div>

      <section v-if="screen === 'loading'" class="onboard-panel loading-panel"><div class="scan-orbit"></div><h2>正在检查上次连接…</h2></section>

      <section v-else-if="screen === 'welcome'" class="choice-grid" aria-label="启动方式">
        <!-- 启动方式保留文字说明，Remix Icon 只作为辅助视觉标记。 -->
        <button class="choice-card" type="button" @click="go('manual')"><span class="choice-index">01 / CONNECT</span><span class="choice-symbol"><IconArrowRightUpLine aria-hidden="true" /></span><strong>连接服务端</strong><span>知道地址时直接填写，也可以选择最近使用过的服务端。</span><em>填写连接信息 <span aria-hidden="true">→</span></em></button>
        <button class="choice-card featured" type="button" @click="startScan"><span class="choice-index">02 / DISCOVER</span><span class="choice-symbol radar-symbol"><IconRadarLine aria-hidden="true" /></span><strong>扫描局域网</strong><span>自动发现同一网络中的服务端，再核对身份并连接。</span><em>开始扫描 <span aria-hidden="true">→</span></em></button>
        <button class="choice-card" type="button" @click="go('create')"><span class="choice-index">03 / HOST</span><span class="choice-symbol"><IconServerLine aria-hidden="true" /></span><strong>新建服务端</strong><span>在这台电脑上创建服务端，供团队在局域网中使用。</span><em>开始创建 <span aria-hidden="true">→</span></em></button>
      </section>

      <section v-else-if="screen === 'manual'" class="onboard-columns">
        <form class="onboard-panel onboard-form" @submit.prevent="connectManual"><div class="panel-heading"><span class="panel-icon"><IconArrowRightUpLine aria-hidden="true" /></span><div><h2>服务端地址</h2><p>只支持本机和局域网地址，连接将使用 HTTPS。</p></div></div><label>IP 地址或主机名<input v-model.trim="manualForm.address" required placeholder="例如 192.168.1.100" autocomplete="off" /></label><label>端口<input v-model.number="manualForm.port" type="number" min="1" max="65535" required /></label><div class="onboard-actions"><button class="secondary" type="button" @click="go('welcome')">返回首页</button><button class="primary" type="submit" :disabled="busy">{{ busy ? '正在检查…' : '检查并连接' }}</button></div></form>
        <div class="onboard-panel"><div class="panel-heading"><span class="panel-icon"><IconHistoryLine aria-hidden="true" /></span><div><h2>最近连接</h2><p>仅保存地址和已核对的证书，不保存密码。</p></div></div><div v-if="!recentServers.length" class="onboard-empty">还没有连接记录。可以填写地址，或扫描局域网。</div><button v-for="entry in recentServers" :key="entry.id" class="server-row" type="button" :disabled="busy" @click="connectSaved(entry)"><span><strong>{{ entry.name }}</strong><small>{{ entry.host }}:{{ entry.port }}</small></span><span class="server-row-action">连接 →</span></button></div>
      </section>

      <section v-else-if="screen === 'scan'" class="onboard-panel scan-panel"><div class="scan-visual"><div class="scan-orbit"><span class="scan-core">N</span></div></div><div class="scan-copy"><p class="onboard-kicker">LIVE DISCOVERY</p><h2>已扫描 {{ scanSeconds }} 秒</h2><p>发现 {{ discoveries.length }} 个可用服务端。结果会随着网络变化更新。</p><div class="scan-live"><span class="status-dot"></span>{{ scanning ? '正在发现' : '已暂停' }}</div></div><div class="onboard-actions scan-actions"><button class="secondary" type="button" @click="go('welcome')">返回首页</button><button class="secondary" type="button" @click="showResults">暂停并查看结果</button><button class="primary" type="button" @click="startScan">重新扫描</button></div></section>

      <section v-else-if="screen === 'results'" class="onboard-panel"><div class="panel-heading"><span class="panel-icon"><IconRadarLine aria-hidden="true" /></span><div><h2>发现 {{ discoveries.length }} 个服务端</h2><p>选择在线服务端，下一步核对证书指纹。</p></div></div><div v-if="!discoveries.length" class="onboard-empty">当前没有发现可用服务端。请确认两台电脑在同一局域网，或手动填写地址。</div><button v-for="entry in discoveries" :key="entry.id" class="server-row" type="button" :disabled="!entry.online || busy" @click="pickDiscovered(entry)"><span><strong>{{ entry.name }}</strong><small>{{ entry.host }}:{{ entry.port }} · v{{ entry.version }}</small></span><span :class="entry.online ? 'online' : 'offline'">{{ entry.online ? '在线 · 连接 →' : '离线' }}</span></button><div class="onboard-actions"><button class="secondary" type="button" @click="go('manual')">手动填写</button><button class="primary" type="button" @click="startScan">重新扫描</button></div></section>

      <section v-else-if="screen === 'create'" class="onboard-columns create-columns"><div v-if="host.configured" class="onboard-panel"><div class="panel-heading"><span class="panel-icon"><IconServerLine aria-hidden="true" /></span><div><h2>此电脑已有服务端</h2><p>一个电脑只创建一个本机实例。你可以继续使用已有服务端。</p></div></div><div class="onboard-actions"><button class="secondary" type="button" @click="go('welcome')">返回首页</button><button class="primary" type="button" :disabled="busy" @click="restartLocalHost">{{ host.running ? '连接本机服务' : '启动本机服务' }}</button></div></div><form v-else class="onboard-panel onboard-form" @submit.prevent="createLocalHost"><div class="panel-heading"><span class="panel-icon"><IconAddLine aria-hidden="true" /></span><div><h2>本机服务配置</h2><p>第一版使用 SQLite，每台电脑只创建一个本机实例。</p></div></div><div class="form-grid"><label>实例名称<input v-model.trim="hostForm.name" required maxlength="80" placeholder="例如 总公司 ERP" /></label><label>服务端口<input v-model.number="hostForm.port" type="number" min="1" max="65535" required /></label></div><label>数据目录<div class="path-picker"><input v-model.trim="hostForm.dataDir" required placeholder="选择 SQLite 数据保存位置" /><button class="secondary" type="button" @click="chooseDataDir">选择</button></div></label><div class="form-grid"><label>首位管理员账号<input v-model.trim="hostForm.username" required minlength="3" maxlength="40" autocomplete="username" /></label><span class="form-hint">已有数据库会原样保留；已有管理员请使用原账号登录。</span></div><div class="form-grid"><label>管理员密码<input v-model="hostForm.password" type="password" required minlength="12" maxlength="128" autocomplete="new-password" placeholder="至少 12 位" /></label><label>确认密码<input v-model="hostForm.confirm" type="password" required minlength="12" autocomplete="new-password" /></label></div><div class="onboard-actions"><button class="secondary" type="button" @click="go('welcome')">返回首页</button><button class="primary" type="submit" :disabled="busy">{{ busy ? '正在创建服务端…' : '创建并启动' }}</button></div></form><aside class="onboard-panel setup-summary"><p class="onboard-kicker">DEPLOYMENT SUMMARY</p><h2>这台电脑将成为服务端</h2><dl><div><dt>业务数据库</dt><dd>SQLite</dd></div><div><dt>访问方式</dt><dd>局域网 HTTPS</dd></div><div><dt>后台运行</dt><dd>登录期间由托盘保持</dd></div><div><dt>外部客户端</dt><dd>需核对证书指纹并登录</dd></div></dl><p class="summary-note">服务端数据集中保存在此电脑。客户端断网后不能继续编辑或自动同步。</p></aside></section>

      <section v-else-if="screen === 'trust' && candidate" class="onboard-panel trust-panel"><span class="trust-icon">◇</span><h2>{{ candidate.changed ? '服务端证书已变化' : '首次连接，需要确认身份' }}</h2><p>请到服务端电脑的“服务端已就绪”页面，核对以下完整 SHA-256 指纹。不要只凭本页面显示的名称判断身份。</p><div class="fingerprint">{{ candidate.fingerprint }}</div><p class="muted">{{ candidate.name }} · {{ candidate.host }}:{{ candidate.port }}</p><label class="check trust-check"><input v-model="trustChecked" type="checkbox" />我已通过服务端电脑或可信渠道核对完整指纹</label><div class="onboard-actions"><button class="secondary" type="button" @click="go('manual')">取消</button><button class="primary" type="button" :disabled="!trustChecked || busy" @click="approveTrust">确认身份并连接</button></div></section>

      <section v-else-if="screen === 'ready' && server" class="onboard-columns ready-columns"><div class="onboard-panel ready-primary"><div class="ready-symbol"><IconCheckboxCircleLine aria-hidden="true" /></div><p class="onboard-kicker">CONNECTION READY</p><h2>{{ server.isLocal ? '本机服务已启动' : '连接已建立' }}</h2><p>使用服务端账号登录后，就可以进入 ERP 工作台。</p><div class="onboard-actions"><button class="primary" type="button" @click="go('login')">进入登录 →</button><button class="secondary" type="button" @click="switchServer">切换服务端</button></div></div><div class="onboard-panel"><div class="panel-heading"><span class="panel-icon"><IconServerLine aria-hidden="true" /></span><div><h2>当前服务端</h2><p>连接信息与身份核验</p></div></div><dl class="server-details"><div><dt>名称</dt><dd>{{ server.name }}</dd></div><div><dt>地址</dt><dd>{{ server.host }}:{{ server.port }}</dd></div><div><dt>版本</dt><dd>v{{ server.version }}</dd></div><div><dt>状态</dt><dd class="online">运行中</dd></div></dl><template v-if="server.isLocal"><p class="fingerprint-label">请将此指纹提供给需要连接的团队成员核对：</p><div class="fingerprint compact">{{ server.fingerprint }}</div></template></div></section>

      <section v-else-if="screen === 'offline'" class="onboard-panel offline-panel"><span class="offline-symbol"><IconErrorWarningLine aria-hidden="true" /></span><h2>{{ server?.name || '服务端' }} · 暂时无法连接</h2><p>服务端可能未启动、网络不可达或证书发生变化。重新连接前请确认服务端身份。</p><div class="onboard-actions"><button class="primary" type="button" :disabled="busy" @click="checkConnection">重试连接</button><button v-if="host.configured && !host.running" class="secondary" type="button" :disabled="busy" @click="restartLocalHost">启动本机服务</button><button class="secondary" type="button" @click="switchServer">切换服务端</button></div></section>
    </main>
    <footer class="onboard-footer"><span>联光 ERP · 让业务流转有据可查</span><span>局域网内连接 · 账号权限由服务端管理</span></footer>
  </div>
  <div v-else class="app-shell">
    <aside class="sidebar">
      <div class="brand"><span class="brand-mark"><img :src="nexoraLogo" alt="" /></span><div><strong>NEXORA</strong><small>联光 ERP · {{ server?.isLocal ? '本机服务' : '团队工作台' }}</small></div></div>
      <div v-if="screen === 'app'" class="side-group">
        <p class="side-label">工作台</p>
        <!-- 导航图标随可见标签一起生成，不改变现有权限判断。 -->
        <button v-for="item in visibleTabs" :key="item.key" class="nav-item" :class="{ active: activeTab === item.key }" type="button" @click="activeTab = item.key"><component :is="item.icon" class="nav-icon" aria-hidden="true" />{{ item.label }}</button>
      </div>
      <div class="sidebar-bottom"><span class="status-dot"></span> {{ server?.name || 'Nexora ERP' }} <small v-if="version">v{{ version }}</small></div>
    </aside>

    <main class="content">
      <header class="topbar">
        <div><p class="eyebrow">NEXORA WORKSPACE</p><h1>{{ screen === 'app' ? visibleTabs.find(item => item.key === activeTab)?.label : '开始使用联光 ERP' }}</h1></div>
        <div v-if="user" class="account"><span>{{ user.username }}<small>{{ user.roles.join(' · ') }}</small></span><button class="text-button" type="button" @click="logout">退出登录</button></div>
      </header>

      <div v-if="error" class="message error" role="alert">{{ error }}</div>
      <div v-if="notice" class="message success" role="status">{{ notice }}</div>

      <section v-if="screen === 'setup' || screen === 'login'" class="card auth-card">
        <p class="eyebrow">{{ screen === 'setup' ? '首次使用' : '欢迎回来' }}</p>
        <h2>{{ screen === 'setup' ? '创建首位管理员' : '登录工作台' }}</h2>
        <p class="muted">{{ screen === 'setup' ? '管理员可以创建用户并分配角色。请设置至少 12 位的密码。' : `使用 ${server?.name || '当前服务端'} 的账号访问采购、库存与用户权限。` }}</p>
        <form @submit.prevent="authenticate">
          <label>用户名<input v-model.trim="username" autocomplete="username" minlength="3" maxlength="40" required placeholder="例如 admin" /></label>
          <label>密码<input v-model="password" type="password" :autocomplete="screen === 'setup' ? 'new-password' : 'current-password'" :minlength="screen === 'setup' ? 12 : undefined" required placeholder="输入密码" /></label>
          <button class="primary" type="submit" :disabled="busy">{{ busy ? '请稍候…' : screen === 'setup' ? '创建管理员' : '登录' }}</button>
        </form>
        <button class="text-button auth-switch" type="button" @click="switchServer">切换服务端</button>
      </section>

      <template v-else-if="screen === 'app'">
        <section v-if="activeTab === 'stock'" class="stack">
          <div class="summary-grid"><div class="metric"><span>物料种类</span><strong>{{ materials.length }}</strong></div><div class="metric"><span>已确认入库单</span><strong>{{ receipts.filter(item => item.status === 'posted').length }}</strong></div><div class="metric"><span>库存流水</span><strong>{{ movements.length }}</strong></div></div>
          <div class="card">
            <div class="section-heading">
              <div><p class="eyebrow">INVENTORY</p><h2>当前库存</h2></div>
              <!-- 用 Naive UI 按钮接入现有刷新操作，并以 Tailwind 工具类避免窄屏挤压。 -->
              <NButton text type="primary" class="shrink-0" :disabled="busy" @click="perform(refreshData, '数据已刷新。')"><template #icon><IconRefreshLine aria-hidden="true" /></template>刷新</NButton>
            </div>
            <div class="table-wrap"><table><thead><tr><th>物料编码</th><th>物料名称</th><th>数量</th></tr></thead><tbody><tr v-for="item in stock" :key="item.id"><td class="mono">{{ item.sku }}</td><td>{{ item.name }}</td><td><strong>{{ item.quantity }}</strong> {{ item.unit }}</td></tr><tr v-if="!stock.length"><td colspan="3" class="muted">暂无物料，先到基础资料中添加。</td></tr></tbody></table></div>
          </div>
          <div class="card"><div class="section-heading"><div><p class="eyebrow">AUDIT TRAIL</p><h2>入库流水</h2></div></div><div class="table-wrap"><table><thead><tr><th>时间</th><th>物料</th><th>入库数量</th><th>来源</th></tr></thead><tbody><tr v-for="item in movements" :key="item.id"><td>{{ localTime(item.created_at) }}</td><td>{{ item.material_name }} <small class="mono">{{ item.sku }}</small></td><td>+{{ item.quantity }} {{ item.unit }}</td><td>入库单 #{{ item.receipt_id }}</td></tr><tr v-if="!movements.length"><td colspan="4" class="muted">确认入库单后，这里会显示库存流水。</td></tr></tbody></table></div></div>
        </section>

        <section v-if="activeTab === 'catalog'" class="stack">
          <div class="two-columns"><div class="card"><div class="section-heading"><div><p class="eyebrow">MATERIALS</p><h2>物料</h2></div></div><form v-if="can('catalog.manage')" class="inline-form" @submit.prevent="createMaterial"><label>物料编码<input v-model.trim="materialForm.sku" required maxlength="40" placeholder="SKU-001" /></label><label>名称<input v-model.trim="materialForm.name" required maxlength="120" placeholder="物料名称" /></label><label>单位<input v-model.trim="materialForm.unit" required maxlength="20" placeholder="件" /></label><button class="primary" type="submit" :disabled="busy">添加物料</button></form><div class="table-wrap"><table><thead><tr><th>编码</th><th>名称</th><th>单位</th></tr></thead><tbody><tr v-for="item in materials" :key="item.id"><td class="mono">{{ item.sku }}</td><td>{{ item.name }}</td><td>{{ item.unit }}</td></tr><tr v-if="!materials.length"><td colspan="3" class="muted">暂无物料。</td></tr></tbody></table></div></div>
          <div class="card"><div class="section-heading"><div><p class="eyebrow">SUPPLIERS</p><h2>供应商</h2></div></div><form v-if="can('catalog.manage')" class="inline-form" @submit.prevent="createSupplier"><label>供应商名称<input v-model.trim="supplierForm.name" required maxlength="120" placeholder="输入供应商名称" /></label><button class="primary" type="submit" :disabled="busy">添加供应商</button></form><div class="table-wrap"><table><thead><tr><th>名称</th></tr></thead><tbody><tr v-for="item in suppliers" :key="item.id"><td>{{ item.name }}</td></tr><tr v-if="!suppliers.length"><td class="muted">暂无供应商。</td></tr></tbody></table></div></div></div>
        </section>

        <section v-if="activeTab === 'receipts'" class="stack">
          <div v-if="can('receipt.create')" class="card"><div class="section-heading"><div><p class="eyebrow">PURCHASE RECEIPT</p><h2>新建入库单</h2></div><span class="pill">草稿</span></div><form @submit.prevent="createReceipt"><div class="form-grid"><label>供应商<select v-model.number="receiptForm.supplier_id" required><option :value="0" disabled>选择供应商</option><option v-for="item in suppliers" :key="item.id" :value="item.id">{{ item.name }}</option></select></label><label>外部单号（可选）<input v-model.trim="receiptForm.reference" maxlength="100" placeholder="采购单或送货单号" /></label></div><h3>入库明细</h3><div v-for="(line, index) in receiptForm.lines" :key="index" class="line-row"><label>物料<select v-model.number="line.material_id" required><option :value="0" disabled>选择物料</option><option v-for="item in materials" :key="item.id" :value="item.id">{{ item.sku }} · {{ item.name }}</option></select></label><label>数量<input v-model.trim="line.quantity" type="number" min="0.001" max="1000000" step="0.001" required /></label><button class="text-button" type="button" :disabled="receiptForm.lines.length === 1" @click="removeLine(index)">移除</button></div><div class="form-actions"><button class="secondary" type="button" @click="addLine">添加明细</button><button class="primary" type="submit" :disabled="busy || !materials.length || !suppliers.length">保存草稿</button></div></form></div>
          <div class="card"><div class="section-heading"><div><p class="eyebrow">RECEIPT LOG</p><h2>入库单</h2></div></div><div v-if="!receipts.length" class="muted">暂无入库单。</div><article v-for="item in receipts" :key="item.id" class="receipt"><div class="receipt-head"><div><strong>#{{ item.id }} · {{ item.supplier_name }}</strong><p class="muted">{{ localTime(item.created_at) }} · 创建人 {{ item.created_by_name }} <span v-if="item.reference">· {{ item.reference }}</span></p></div><div class="receipt-actions"><span class="pill" :class="item.status">{{ item.status === 'posted' ? '已入库' : '待确认' }}</span><button v-if="item.status === 'draft' && can('receipt.post')" class="primary small" type="button" :disabled="busy" @click="postReceipt(item.id)">确认入库</button></div></div><div class="receipt-lines"><span v-for="line in item.lines" :key="line.id">{{ line.material_name }} × {{ line.quantity }} {{ line.unit }}</span></div></article></div>
        </section>

        <section v-if="activeTab === 'users' && can('users.manage')" class="stack">
          <div class="card"><div class="section-heading"><div><p class="eyebrow">ACCESS</p><h2>创建用户</h2></div></div><form class="inline-form" @submit.prevent="createUser"><label>用户名<input v-model.trim="newUser.username" required minlength="3" maxlength="40" placeholder="英文、数字或下划线" /></label><label>初始密码<input v-model="newUser.password" type="password" required minlength="12" maxlength="128" autocomplete="new-password" placeholder="至少 12 位" /></label><fieldset><legend>角色</legend><label v-for="role in roles" :key="role.code" class="check"><input v-model="newUser.roles" type="checkbox" :value="role.code" />{{ role.label }}</label></fieldset><button class="primary" type="submit" :disabled="busy || !newUser.roles.length">创建用户</button></form></div>
          <div class="card">
            <div class="section-heading"><div><p class="eyebrow">TEAM</p><h2>用户与角色</h2></div></div>
            <div v-for="entry in users" :key="entry.id" class="user-row">
              <div><strong>{{ entry.username }}</strong><small>#{{ entry.id }} · {{ entry.is_active ? '已启用' : '已停用' }}</small></div>
              <div class="user-access">
                <div class="role-picker"><label v-for="role in roles" :key="role.code" class="check"><input v-model="roleDrafts[entry.id]" type="checkbox" :value="role.code" />{{ role.label }}</label></div>
                <label class="reset-field">新密码<input v-model="resetPasswords[entry.id]" type="password" minlength="12" maxlength="128" autocomplete="new-password" placeholder="重置密码至少 12 位" /></label>
              </div>
              <div class="user-actions">
                <button class="secondary small" type="button" :disabled="busy || !roleDrafts[entry.id]?.length" @click="saveRoles(entry.id)">保存角色</button>
                <button class="secondary small" type="button" :disabled="busy || entry.id === user?.id || !resetPasswords[entry.id] || resetPasswords[entry.id].length < 12" @click="resetUserPassword(entry.id)">重置密码</button>
                <button class="secondary small" type="button" :disabled="busy || entry.id === user?.id" @click="setUserStatus(entry)">{{ entry.is_active ? '停用账号' : '启用账号' }}</button>
              </div>
            </div>
          </div>
          <div class="card">
            <div class="section-heading"><div><p class="eyebrow">ROLE SETTINGS</p><h2>角色与权限</h2></div></div>
            <form class="inline-form" @submit.prevent="createRole">
              <div class="form-grid"><label>角色代码<input v-model.trim="newRole.code" required minlength="3" maxlength="40" pattern="[a-z][a-z0-9_]*" placeholder="例如 stock_clerk" /></label><label>角色名称<input v-model.trim="newRole.label" required maxlength="40" placeholder="例如 库存专员" /></label></div>
              <fieldset><legend>授权范围</legend><label v-for="permission in permissions" :key="permission.code" class="check"><input v-model="newRole.permissions" type="checkbox" :value="permission.code" />{{ permission.label }}</label></fieldset>
              <button class="primary" type="submit" :disabled="busy">创建自定义角色</button>
            </form>
            <div v-for="role in roles" :key="role.code" class="role-row">
              <div><strong>{{ role.label }}</strong><small>{{ role.code }} · {{ role.is_builtin ? '内置角色' : '自定义角色' }}</small></div>
              <div v-if="role.is_builtin" class="muted">{{ role.permissions.map(code => permissions.find(item => item.code === code)?.label ?? code).join(' · ') }}</div>
              <div v-else class="role-editor"><label>名称<input v-model.trim="roleLabelDrafts[role.code]" maxlength="40" /></label><fieldset><legend>权限</legend><label v-for="permission in permissions" :key="permission.code" class="check"><input v-model="rolePermissionDrafts[role.code]" type="checkbox" :value="permission.code" />{{ permission.label }}</label></fieldset><button class="secondary small" type="button" :disabled="busy || !roleLabelDrafts[role.code]" @click="saveRole(role.code)">保存权限</button></div>
            </div>
          </div>
        </section>
        <section v-if="activeTab === 'settings'" class="stack"><div class="card"><div class="section-heading"><div><p class="eyebrow">CONNECTION</p><h2>当前连接</h2></div></div><dl class="server-details"><div><dt>服务端</dt><dd>{{ server?.name }}</dd></div><div><dt>地址</dt><dd>{{ server?.host }}:{{ server?.port }}</dd></div><div><dt>证书指纹</dt><dd class="mono">{{ server?.fingerprint }}</dd></div></dl><button class="secondary" type="button" @click="switchServer">切换服务端</button></div><div class="card"><div class="section-heading"><div><p class="eyebrow">ACCOUNT</p><h2>修改我的密码</h2></div></div><form class="inline-form" @submit.prevent="changeOwnPassword"><div class="form-grid"><label>当前密码<input v-model="passwordChange.current_password" type="password" required autocomplete="current-password" /></label><label>新密码<input v-model="passwordChange.new_password" type="password" required minlength="12" maxlength="128" autocomplete="new-password" placeholder="至少 12 位" /></label></div><p class="muted">修改后所有设备都需要重新登录。</p><button class="primary" type="submit" :disabled="busy">修改密码</button></form></div><div v-if="host.configured" class="card"><div class="section-heading"><div><p class="eyebrow">LOCAL HOST</p><h2>本机服务</h2></div><span class="pill" :class="{ posted: host.running }">{{ host.running ? '运行中' : '已停止' }}</span></div><p class="muted">关闭窗口时本机服务继续运行；退出应用或登录会话后停止。</p><div class="onboard-actions"><button v-if="host.running" class="secondary" type="button" @click="stopLocalHost">停止本机服务</button><button v-else class="primary" type="button" @click="restartLocalHost">启动本机服务</button></div></div></section>
      </template>
    </main>
  </div>
  </NConfigProvider>
</template>
