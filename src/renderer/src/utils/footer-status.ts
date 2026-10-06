import type { ServerProfile } from '../../../shared/desktop-api'
import type { Screen } from '../store/types'

export interface FooterStatusInput {
  screen: Screen
  server: Pick<ServerProfile, 'name' | 'version'> | null
  connectionLost: boolean
  connectionNotice: string
  error: string
  notice: string
  busy: boolean
}

export interface FooterStatus {
  message: string
  tone: 'success' | 'error' | 'pending' | 'idle'
}

// 引导页保留连接操作的反馈；进入登录或工作台后只汇报服务连接本身。
export function resolveFooterStatus(input: FooterStatusInput): FooterStatus {
  const isOnboarding = !['login', 'setup', 'numbering', 'app'].includes(input.screen)
  if (isOnboarding) {
    if (input.error) return { message: input.error, tone: 'error' }
    if (input.notice) return { message: input.notice, tone: 'success' }
    if (input.screen === 'ready') return { message: '已连接', tone: 'success' }
    if (input.busy || input.screen === 'loading')
      return { message: '正在检查连接', tone: 'pending' }
    if (input.screen === 'offline') return { message: '连接已中断', tone: 'error' }
    return { message: '未连接', tone: 'idle' }
  }

  if (input.connectionLost)
    return { message: '服务端连接已中断，正在重试。恢复连接前无法保存更改。', tone: 'error' }
  if (input.connectionNotice)
    return { message: input.connectionNotice, tone: 'success' }
  if (!input.server) return { message: '等待连接服务端', tone: 'pending' }
  return { message: '已连接', tone: 'success' }
}
