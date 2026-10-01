import type { BrowserWindowConstructorOptions } from 'electron'
import { usesIntegratedTitleBar, windowOverlayTheme } from '../shared/window-chrome.ts'

export function windowChromeOptions(platform: string): BrowserWindowConstructorOptions {
  if (!usesIntegratedTitleBar(platform)) return {}
  // 两端都隐藏系统标题文字，但保留各自的原生窗口控件和系统交互。
  return {
    titleBarStyle: 'hidden',
    titleBarOverlay: platform === 'win32' ? windowOverlayTheme('light') : true,
    ...(platform === 'darwin' ? { trafficLightPosition: { x: 16, y: 17 } } : {})
  }
}
