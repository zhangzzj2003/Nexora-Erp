import { app, BrowserWindow, dialog, ipcMain, Menu, nativeImage, Tray } from 'electron'
import { join } from 'node:path'
import { mkdirSync } from 'node:fs'
import { writeFile } from 'node:fs/promises'
import { callBackend, getBackendHealth } from './backend'
import type { ErpOperations } from '../shared/erp-api'
import type { HostInput } from '../shared/desktop-api'
import { keepDesktopInTray, trayServiceLabel } from './tray-state'
import { windowChromeOptions } from './window-chrome'
import { windowOverlayTheme } from '../shared/window-chrome'
import { activateSaved, approveConnection, createHost, disconnect, finishHostSetup, hostFingerprint, hostStatus,
  loadConnections, prepareConnection, recentProfiles, restartHost, resume, shutdownConnections,
  startDiscovery, stopDiscovery, stopHost, upgradeHost } from './connections'

let mainWindow: BrowserWindow | null = null
let tray: Tray | null = null
let startupError: string | null = null

if (process.env.NEXORA_USER_DATA_DIR) {
  // 集成验收使用独立用户目录，避免测试创建的服务端影响真实工作资料。
  mkdirSync(process.env.NEXORA_USER_DATA_DIR, { recursive: true })
  app.setPath('userData', process.env.NEXORA_USER_DATA_DIR)
}

function assertMainWindow(event: Electron.IpcMainInvokeEvent): void {
  if (!mainWindow || event.sender !== mainWindow.webContents
    || event.senderFrame !== mainWindow.webContents.mainFrame) throw new Error('不允许的窗口请求')
}

function ensureTray(): void {
  if (tray) return
  // 托盘仅提供入口；打包版固定主机的生命周期由操作系统管理。
  tray = new Tray(nativeImage.createFromPath(join(__dirname, '../../resources/tray.png')))
  tray.setToolTip('Nexora ERP')
  tray.on('double-click', openMainWindow)
  void updateTray()
}

function openMainWindow(): void {
  if (!mainWindow) createWindow()
  else {
    mainWindow.show()
    mainWindow.focus()
  }
}

async function updateTray(): Promise<void> {
  if (!tray) return
  const status = await hostStatus().catch(() => null)
  if (!tray) return
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: '打开 Nexora ERP', click: openMainWindow },
    { label: trayServiceLabel(status), enabled: false },
    { label: '刷新服务状态', click: () => { void updateTray() } },
    { label: '停止本机服务', enabled: status?.running ?? false, click: () => {
      void stopHost().then(updateTray).catch((error: unknown) => {
        dialog.showErrorBox('停止本机服务失败', error instanceof Error ? error.message : '请检查系统服务状态')
      })
    } },
    { type: 'separator' },
    { label: '退出桌面应用', click: () => app.quit() }
  ]))
}

function createWindow(): void {
  // 渲染进程保持隔离；桌面能力通过预加载脚本的受限接口提供。
  const window = new BrowserWindow({
    // 标题栏由页面统一绘制，窗口按钮仍由操作系统提供。
    ...windowChromeOptions(process.platform),
    width: 1120,
    height: 720,
    minWidth: 820,
    minHeight: 560,
    backgroundColor: '#0c1424',
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  })

  // Windows 直接移除窗口菜单，避免按 Alt 后重新出现默认英文菜单栏。
  if (process.platform === 'win32') window.setMenu(null)

  mainWindow = window
  window.on('closed', () => {
    if (mainWindow === window) {
      mainWindow = null
      // 窗口关闭后托盘仍常驻，主动结束仅供该窗口使用的局域网扫描。
      stopDiscovery()
    }
  })

  // 当前页面不需要弹出新窗口，先阻止页面内容自行打开外部地址。
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))

  if (process.env.ELECTRON_RENDERER_URL) {
    void window.loadURL(process.env.ELECTRON_RENDERER_URL)
  } else {
    void window.loadFile(join(__dirname, '../renderer/index.html'))
  }
}

app.whenReady().then(() => {
  try { loadConnections() }
  catch (error) { startupError = error instanceof Error ? error.message : '连接配置无法读取' }
  ensureTray()
  // 只接受本应用窗口发来的版本查询，避免暴露通用 IPC 通道。
  ipcMain.handle('app:get-version', (event) => {
    assertMainWindow(event)
    return app.getVersion()
  })

  ipcMain.handle('window:set-theme', (event, mode: unknown) => {
    assertMainWindow(event)
    const overlay = windowOverlayTheme(mode)
    // macOS 红黄绿按钮保留原生外观；Windows 的按钮底色随页面主题同步。
    if (process.platform === 'win32') mainWindow?.setTitleBarOverlay(overlay)
  })

  createWindow()
  ipcMain.handle('backend:get-health', (event) => {
    assertMainWindow(event)
    return getBackendHealth()
  })
  ipcMain.handle('erp:call', (event, action: keyof ErpOperations, payload: unknown) => {
    // 业务通道仅接受当前主窗口主框架的调用。
    assertMainWindow(event)
    return callBackend(action, payload)
  })
  ipcMain.handle('report:save-csv', async (event, fileName: unknown, csv: unknown) => {
    assertMainWindow(event)
    // 仅允许保存报表 CSV；路径由系统文件对话框选择，不接受渲染进程路径。
    if (typeof fileName !== 'string' || !/^[a-z0-9_-]{1,80}\.csv$/.test(fileName)
      || typeof csv !== 'string' || csv.length > 10_000_000 || !csv.startsWith('\ufeff')) {
      throw new Error('报表导出参数无效')
    }
    if (!mainWindow) throw new Error('窗口不可用')
    const selected = await dialog.showSaveDialog(mainWindow, {
      defaultPath: fileName, filters: [{ name: 'CSV', extensions: ['csv'] }]
    })
    if (selected.canceled || !selected.filePath) return null
    await writeFile(selected.filePath, csv, { encoding: 'utf8' })
    return selected.filePath
  })
  ipcMain.handle('connection:startup', async (event) => {
    assertMainWindow(event)
    if (startupError) return { status: 'offline', message: startupError }
    const state = await resume()
    updateTray()
    return state
  })
  ipcMain.handle('connection:recent', (event) => { assertMainWindow(event); return recentProfiles() })
  ipcMain.handle('connection:prepare', (event, address: string, port: number) => {
    assertMainWindow(event); return prepareConnection(address, port)
  })
  ipcMain.handle('connection:approve', (event, id: string, fingerprint: string) => {
    assertMainWindow(event); return approveConnection(id, fingerprint)
  })
  ipcMain.handle('connection:activate', (event, id: string) => {
    assertMainWindow(event); return activateSaved(id)
  })
  ipcMain.handle('connection:disconnect', (event) => { assertMainWindow(event); disconnect() })
  ipcMain.handle('host:create', async (event, input: HostInput) => {
    assertMainWindow(event)
    const result = await createHost(input)
    updateTray()
    return result
  })
  ipcMain.handle('host:finish-setup', async (event, username: string, password: string) => {
    assertMainWindow(event)
    await finishHostSetup(username, password)
    updateTray()
  })
  ipcMain.handle('host:default-dir', (event) => {
    assertMainWindow(event)
    return join(app.getPath('home'), '.nexora-erp')
  })
  ipcMain.handle('host:choose-dir', async (event) => {
    assertMainWindow(event)
    if (!mainWindow) return null
    const selection = await dialog.showOpenDialog(mainWindow, { properties: ['openDirectory', 'createDirectory'] })
    return selection.canceled ? null : selection.filePaths[0] ?? null
  })
  ipcMain.handle('host:restart', async (event) => {
    assertMainWindow(event)
    const result = await restartHost()
    updateTray()
    return result
  })
  ipcMain.handle('host:stop', async (event) => { assertMainWindow(event); await stopHost(); updateTray() })
  ipcMain.handle('host:upgrade', async (event) => {
    assertMainWindow(event)
    const profile = await upgradeHost()
    void updateTray()
    return profile
  })
  ipcMain.handle('host:status', async (event) => {
    assertMainWindow(event)
    return { ...await hostStatus(), fingerprint: hostFingerprint() }
  })
  ipcMain.handle('discovery:start', (event) => {
    assertMainWindow(event)
    startDiscovery((results) => mainWindow?.webContents.send('discovery:update', results))
  })
  ipcMain.handle('discovery:stop', (event) => { assertMainWindow(event); stopDiscovery() })
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  // 两种受支持的桌面系统均保留托盘；明确退出桌面应用仍不停止系统服务。
  if (keepDesktopInTray(process.platform)) return
  if (app.isPackaged) { app.quit(); return }
  void hostStatus().then((status) => { if (!status.running) app.quit() })
})

app.on('before-quit', () => {
  // 显式退出时销毁托盘，避免仍在进行的状态查询更新已释放的图标。
  tray?.destroy()
  tray = null
  shutdownConnections()
})
