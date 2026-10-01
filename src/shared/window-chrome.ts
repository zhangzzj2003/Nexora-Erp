// 原生窗口按钮与页面共用高度和配色，避免主题切换后顶部出现两种背景。
export const titleBarHeight = 48
export type WindowTheme = 'light' | 'dark'

export function windowOverlayTheme(mode: unknown): { color: string; symbolColor: string; height: number } {
  // IPC 输入不能直接透传给 Electron；只接受应用已有的两种主题。
  if (mode !== 'light' && mode !== 'dark') throw new Error('窗口主题参数无效')
  return {
    color: mode === 'dark' ? '#111d32' : '#ffffff',
    symbolColor: mode === 'dark' ? '#e6edf8' : '#17213b',
    height: titleBarHeight
  }
}

export function usesIntegratedTitleBar(platform: string | undefined): boolean {
  // 普通浏览器与未验收的 Linux 桌面沿用原布局，不隐藏其原生标题栏。
  return platform === 'darwin' || platform === 'win32'
}
