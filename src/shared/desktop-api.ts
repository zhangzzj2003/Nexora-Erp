import type { ErpOperations, JournalAttachment } from './erp-api'
import type { AfterSalesAttachment } from './after-sales-api'
import type { InventoryWarningNotice } from './inventory-warning-notification'

// 渲染进程只能调用这里列出的桌面能力，后续新增接口也应先定义清楚类型。
export type BackendHealth =
  | { connected: true; version: string }
  | { connected: false; message: string }

export interface ServerProfile {
  id: string
  name: string
  host: string
  port: number
  fingerprint: string
  version: string
  isLocal: boolean
}

export interface ConnectionCandidate extends ServerProfile {
  trusted: boolean
  changed: boolean
}

export interface DiscoveryResult extends ServerProfile { online: boolean }

export interface HostInput {
  name: string
  dataDir: string
  port: number
  username: string
  password: string
}

export type StartupState =
  | { status: 'welcome' }
  | { status: 'connected'; server: ServerProfile }
  | { status: 'needs_setup'; server: ServerProfile }
  | { status: 'offline'; message: string; server?: ServerProfile }

export interface HostStatus { configured: boolean; running: boolean; systemManaged: boolean; migrationNeeded: boolean; fingerprint: string | null }

export interface DesktopApi {
  // 平台是只读标识，不向页面暴露 Node.js 的 process 对象。
  readonly platform: string
  setWindowTheme: (mode: 'light' | 'dark') => Promise<void>
  getVersion: () => Promise<string>
  getBackendHealth: () => Promise<BackendHealth>
  saveReportCsv: (fileName: string, csv: string) => Promise<string | null>
  saveCrmQuotePdf: (id: number) => Promise<string | null>
  uploadJournalAttachment: (journalId: number, reason: string) => Promise<JournalAttachment | null>
  saveJournalAttachment: (journalId: number, attachmentId: number) => Promise<string | null>
  uploadAfterSalesAttachment: (caseId: number, reason: string) => Promise<AfterSalesAttachment | null>
  saveAfterSalesAttachment: (caseId: number, attachmentId: number) => Promise<string | null>
  notifyInventoryWarning: (notice: InventoryWarningNotice) => Promise<boolean>
  callApi: <K extends keyof ErpOperations>(action: K, payload: ErpOperations[K]['input']) => Promise<ErpOperations[K]['output']>
  startup: () => Promise<StartupState>
  recentServers: () => Promise<ServerProfile[]>
  prepareConnection: (address: string, port: number) => Promise<ConnectionCandidate>
  approveConnection: (id: string, fingerprint: string) => Promise<ServerProfile>
  activateSaved: (id: string) => Promise<ServerProfile>
  disconnect: () => Promise<void>
  createHost: (input: HostInput) => Promise<ServerProfile>
  finishHostSetup: (username: string, password: string) => Promise<void>
  defaultDataDir: () => Promise<string>
  chooseDataDir: () => Promise<string | null>
  restartHost: () => Promise<ServerProfile>
  stopHost: () => Promise<void>
  upgradeHost: () => Promise<ServerProfile>
  hostStatus: () => Promise<HostStatus>
  startDiscovery: () => Promise<void>
  stopDiscovery: () => Promise<void>
  onDiscovery: (callback: (results: DiscoveryResult[]) => void) => () => void
}
