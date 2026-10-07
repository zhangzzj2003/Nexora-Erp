import type { AppState } from './state'
import type {
  ConnectionCandidate,
  DiscoveryResult,
  ServerProfile
} from '../../../shared/desktop-api'
import { displayError } from '../utils/formatters.ts'
import type { Screen } from './types'

// 连接、发现、主机控制与身份状态在同一生命周期内管理，退出时会释放扫描订阅。
export function createConnectionActions(
  state: AppState,
  refreshData: () => Promise<void>
) {
  const {
    screen,
    notice,
    error,
    busy,
    user,
    username,
    password,
    selectedWarehouseId,
    passwordChange,
    server,
    candidate,
    recentServers,
    discoveries,
    scanSeconds,
    scanning,
    manualForm,
    hostForm,
    trustChecked,
    host,
    connectionLost,
    connectionNotice
  } = state
  let scanTimer: ReturnType<typeof setInterval> | null = null
  let checkingHealth = false
  let unsubscribeDiscovery: (() => void) | null = null

  async function checkConnection(): Promise<void> {
    if (!window.nexora) {
      screen.value = 'offline'
      error.value = '请在 Electron 桌面应用中打开此页面。'
      return
    }
    busy.value = true
    error.value = ''
    try {
      const startupState = await window.nexora.startup()
      connectionLost.value = false
      connectionNotice.value = ''
      if (startupState.status === 'connected') {
        server.value = startupState.server
        try {
          // Pinia 在页面刷新后重新创建；从服务端核验主进程会话再恢复账号和权限。
          user.value = await window.nexora.callApi('me', undefined)
          state.documentNumbering.value = await window.nexora.callApi('documentNumbering', undefined)
          screen.value = !state.documentNumbering.value.configured && user.value.roles.includes('admin') ? 'numbering' : 'app'
        } catch (cause) {
          // 主进程没有令牌或服务端已撤销会话时，不展示旧账号的数据。
          user.value = null
          screen.value = 'login'
          const message = displayError(cause)
          if (message !== '请先登录') error.value = message
        }
        if (user.value && screen.value === 'app') {
          // 业务数据读取失败时保留已验证的登录状态，并显示具体错误供重试。
          try {
            await refreshData()
          } catch (cause) {
            error.value = displayError(cause)
          }
        }
      } else if (startupState.status === 'needs_setup') {
        server.value = startupState.server
        screen.value = 'setup'
      } else if (startupState.status === 'offline') {
        server.value = startupState.server ?? null
        screen.value = 'offline'
        error.value = startupState.message
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

  function clearMessage(): void {
    error.value = ''
    notice.value = ''
    connectionNotice.value = ''
  }

  async function go(screenName: Screen): Promise<void> {
    clearMessage()
    if (screen.value === 'scan') await stopScan()
    screen.value = screenName
  }

  async function switchServer(): Promise<void> {
    if (!window.nexora) return
    if (user.value) {
      try {
        await window.nexora.callApi('logout', undefined)
      } catch {
        /* 网络中断时仍清理本地连接。 */
      }
    }
    user.value = null
    state.documentNumbering.value = null
    connectionLost.value = false
    connectionNotice.value = ''
    server.value = null
    // 仓库编号只在当前服务端有效，切换实例时重置筛选，避免请求另一实例不存在的仓库。
    selectedWarehouseId.value = 0
    await window.nexora.disconnect()
    recentServers.value = await window.nexora.recentServers()
    await go('welcome')
  }

  async function connectManual(): Promise<void> {
    if (!window.nexora || busy.value) return
    busy.value = true
    clearMessage()
    try {
      candidate.value = await window.nexora.prepareConnection(
        manualForm.value.address,
        Number(manualForm.value.port)
      )
      trustChecked.value = false
      if (candidate.value.trusted) {
        server.value = await window.nexora.approveConnection(
          candidate.value.id,
          candidate.value.fingerprint
        )
        await go('ready')
      } else await go('trust')
    } catch (cause) {
      error.value = displayError(cause)
    } finally {
      busy.value = false
    }
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
    } finally {
      busy.value = false
    }
  }

  async function approveTrust(): Promise<void> {
    if (!window.nexora || !candidate.value || !trustChecked.value) return
    busy.value = true
    try {
      server.value = await window.nexora.approveConnection(
        candidate.value.id,
        candidate.value.fingerprint
      )
      recentServers.value = await window.nexora.recentServers()
      await go('ready')
    } catch (cause) {
      error.value = displayError(cause)
    } finally {
      busy.value = false
    }
  }

  async function startScan(): Promise<void> {
    if (!window.nexora) return
    await go('scan')
    scanSeconds.value = 0
    discoveries.value = []
    scanning.value = true
    unsubscribeDiscovery?.()
    unsubscribeDiscovery = window.nexora.onDiscovery((results) => {
      discoveries.value = results
    })
    try {
      await window.nexora.startDiscovery()
      scanTimer = setInterval(() => {
        scanSeconds.value += 1
      }, 1000)
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
        name: hostForm.value.name,
        dataDir: hostForm.value.dataDir,
        port: Number(hostForm.value.port),
        username: hostForm.value.username,
        password: hostForm.value.password
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
    } finally {
      busy.value = false
    }
  }

  async function stopLocalHost(): Promise<void> {
    if (!window.nexora || busy.value) return
    busy.value = true
    clearMessage()
    try {
      await window.nexora.stopHost()
      host.value = await window.nexora.hostStatus()
      if (server.value?.isLocal) {
        // 服务已退出，主进程也已清除令牌，此时无需再向停掉的服务发送登出请求。
        user.value = null
        await switchServer()
      }
      // 切回连接向导后再写入一次反馈，避免切屏过程中重复弹出同一条消息。
      notice.value = '本机服务已停止。'
    } catch (cause) {
      error.value = displayError(cause)
    } finally {
      busy.value = false
    }
  }

  async function restartLocalHost(): Promise<void> {
    if (!window.nexora || busy.value) return
    busy.value = true
    clearMessage()
    try {
      server.value = await window.nexora.restartHost()
      host.value = await window.nexora.hostStatus()
      if (screen.value === 'offline' || screen.value === 'create')
        await go('ready')
      notice.value = '本机服务已启动。'
    } catch (cause) {
      error.value = displayError(cause)
    } finally {
      busy.value = false
    }
  }

  async function upgradeLocalHost(): Promise<void> {
    if (!window.nexora || busy.value) return
    busy.value = true
    clearMessage()
    try {
      // 升级命令会在停止服务后创建成组备份，并保留原实例的数据目录与证书。
      server.value = await window.nexora.upgradeHost()
      host.value = await window.nexora.hostStatus()
      notice.value = '系统服务已升级，升级前备份保存在主机系统数据目录。'
    } catch (cause) {
      error.value = displayError(cause)
    } finally {
      busy.value = false
    }
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
      user.value = await window.nexora.callApi('login', {
        username: username.value,
        password: password.value
      })
      password.value = ''
      state.documentNumbering.value = await window.nexora.callApi('documentNumbering', undefined)
      if (!state.documentNumbering.value.configured && user.value.roles.includes('admin')) {
        screen.value = 'numbering'
        return
      }
      screen.value = 'app'
      connectionNotice.value = ''
      await refreshData()
    } catch (cause) {
      error.value = displayError(cause)
    } finally {
      busy.value = false
    }
  }

  async function changeOwnPassword(): Promise<void> {
    if (!window.nexora || busy.value) return
    if (connectionLost.value) {
      error.value = '服务端连接已中断，恢复后再修改密码。'
      return
    }
    busy.value = true
    error.value = ''
    try {
      await window.nexora.callApi('changePassword', {
        ...passwordChange.value
      })
      passwordChange.value = { current_password: '', new_password: '' }
      user.value = null
      screen.value = 'login'
      notice.value = '密码已修改，请使用新密码重新登录。'
    } catch (cause) {
      error.value = displayError(cause)
    } finally {
      busy.value = false
    }
  }

  async function logout(): Promise<void> {
    if (!window.nexora) return
    try {
      await window.nexora.callApi('logout', undefined)
    } catch {
      /* 本地界面仍退出，重连后需要再次登录。 */
    }
    user.value = null
    screen.value = 'login'
    connectionNotice.value = ''
    notice.value = ''
    error.value = ''
  }

  async function monitorConnection(): Promise<void> {
    if (
      !window.nexora ||
      checkingHealth ||
      !['app', 'numbering', 'login', 'setup', 'ready'].includes(screen.value)
    )
      return
    checkingHealth = true
    try {
      let health = await window.nexora.getBackendHealth()
      if (!health.connected && connectionLost.value && server.value && !server.value.isLocal) {
        try {
          // 固定地址持续不可用时，主进程只会用原证书身份尝试发现新地址；恢复后重新读取业务数据。
          server.value = await window.nexora.activateSaved(server.value.id)
          health = await window.nexora.getBackendHealth()
        } catch (cause) {
          const message = displayError(cause)
          if (message.includes('证书已变化')) error.value = message
        }
      }
      if (!health.connected) {
        connectionLost.value = true
        connectionNotice.value = ''
        return
      }
      if (!connectionLost.value) return
      // TLS 请求仍使用固定证书；恢复后从服务端重读，避免展示断线期间的旧库存。
      connectionLost.value = false
      error.value = ''
      if (screen.value === 'numbering') {
        state.documentNumbering.value = await window.nexora.callApi('documentNumbering', undefined)
        if (state.documentNumbering.value.configured) { screen.value = 'app'; await refreshData() }
      }
      if (screen.value === 'app') {
        try {
          await refreshData()
        } catch {
          user.value = null
          screen.value = 'login'
          connectionNotice.value = '连接已恢复，请重新登录后查看最新数据。'
          return
        }
      }
      connectionNotice.value = '服务端连接已恢复，数据已更新。'
    } catch {
      connectionLost.value = true
      connectionNotice.value = ''
    } finally {
      checkingHealth = false
    }
  }
  return {
    checkConnection,
    clearMessage,
    go,
    switchServer,
    connectManual,
    connectSaved,
    approveTrust,
    startScan,
    stopScan,
    showResults,
    pickDiscovered,
    chooseDataDir,
    createLocalHost,
    stopLocalHost,
    restartLocalHost,
    upgradeLocalHost,
    authenticate,
    changeOwnPassword,
    logout,
    monitorConnection
  }
}
