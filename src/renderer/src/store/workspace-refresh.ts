interface RefreshContext {
  session: string
  path: string
}

// 刷新只重载当前业务页，不重新初始化窗口或清空登录会话和已打开标签。
export function createWorkspaceRefresh(options: {
  context: () => RefreshContext | undefined
  blocked: () => boolean
  setLoading: (loading: boolean) => void
  reloadData: () => Promise<void>
  remountPage: () => Promise<void>
  reportError: (cause: unknown) => void
}) {
  let loading = false
  let disposed = false
  async function refresh(): Promise<void> {
    const started = options.context()
    if (!started || disposed || loading || options.blocked()) return
    const stillCurrent = (): boolean => {
      const current = options.context()
      return !disposed && current?.session === started.session && current.path === started.path
    }
    loading = true
    options.setLoading(true)
    try {
      await options.reloadData()
      // 刷新期间切页、退出或换服务端时，迟到结果不能重建另一个页面。
      if (stillCurrent()) await options.remountPage()
    } catch (cause) {
      if (stillCurrent()) options.reportError(cause)
    } finally {
      loading = false
      options.setLoading(false)
    }
  }
  return { refresh, dispose: () => { disposed = true } }
}
