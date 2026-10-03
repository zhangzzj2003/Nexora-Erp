import { contextBridge, ipcRenderer } from 'electron'
import type { DesktopApi } from '../shared/desktop-api'

// 只暴露明确的查询方法，不把 ipcRenderer 整体交给页面。
const desktopApi: DesktopApi = {
  platform: process.platform,
  // 页面只能同步既定主题，不能自定义原生窗口参数。
  setWindowTheme: (mode) => ipcRenderer.invoke('window:set-theme', mode),
  getVersion: () => ipcRenderer.invoke('app:get-version') as Promise<string>,
  getBackendHealth: () => ipcRenderer.invoke('backend:get-health'),
  // 所有业务请求都由主进程按固定操作表转发，页面不能构造任意 URL。
  callApi: (action, payload) => ipcRenderer.invoke('erp:call', action, payload),
  saveReportCsv: (fileName, csv) => ipcRenderer.invoke('report:save-csv', fileName, csv),
  saveCrmQuotePdf: (id) => ipcRenderer.invoke('crm:save-quote-pdf', id),
  notifyInventoryWarning: (notice) => ipcRenderer.invoke('inventory:notify-warning', notice),
  startup: () => ipcRenderer.invoke('connection:startup'),
  recentServers: () => ipcRenderer.invoke('connection:recent'),
  prepareConnection: (address, port) => ipcRenderer.invoke('connection:prepare', address, port),
  approveConnection: (id, fingerprint) => ipcRenderer.invoke('connection:approve', id, fingerprint),
  activateSaved: (id) => ipcRenderer.invoke('connection:activate', id),
  disconnect: () => ipcRenderer.invoke('connection:disconnect'),
  createHost: (input) => ipcRenderer.invoke('host:create', input),
  finishHostSetup: (username, password) => ipcRenderer.invoke('host:finish-setup', username, password),
  defaultDataDir: () => ipcRenderer.invoke('host:default-dir'),
  chooseDataDir: () => ipcRenderer.invoke('host:choose-dir'),
  restartHost: () => ipcRenderer.invoke('host:restart'),
  stopHost: () => ipcRenderer.invoke('host:stop'),
  upgradeHost: () => ipcRenderer.invoke('host:upgrade'),
  hostStatus: () => ipcRenderer.invoke('host:status'),
  startDiscovery: () => ipcRenderer.invoke('discovery:start'),
  stopDiscovery: () => ipcRenderer.invoke('discovery:stop'),
  onDiscovery: (callback) => {
    // 事件监听只接收主进程发出的发现结果，离开页面时可主动解绑。
    const listener = (_event: Electron.IpcRendererEvent, results: Parameters<typeof callback>[0]): void => callback(results)
    ipcRenderer.on('discovery:update', listener)
    return () => ipcRenderer.removeListener('discovery:update', listener)
  }
}

contextBridge.exposeInMainWorld('nexora', desktopApi)
