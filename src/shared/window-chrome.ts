// 原生窗口按钮与页面共用高度；背景统一由页面绘制，图标随主题同步。
export const titleBarHeight = 48
export type WindowTheme = 'light' | 'dark'

export function windowOverlayTheme(mode: unknown): { color: string; symbolColor: string; height: number } {
  // IPC 输入不能直接透传给 Electron；只接受应用已有的两种主题。
  if (mode !== 'light' && mode !== 'dark') throw new Error('窗口主题参数无效')
  return {
    // 原生按钮位于网页之上；透明底色才能透出顶部栏、分隔线和弹窗遮罩。
    color: '#00000000',
    symbolColor: mode === 'dark' ? '#e6edf8' : '#17213b',
    height: titleBarHeight
  }
}

export function usesIntegratedTitleBar(platform: string | undefined): boolean {
  // 普通浏览器与未验收的 Linux 桌面沿用原布局，不隐藏其原生标题栏。
  return platform === 'darwin' || platform === 'win32'
}
