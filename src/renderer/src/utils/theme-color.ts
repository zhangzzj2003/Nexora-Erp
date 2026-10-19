// 只允许固定预设进入主题，避免损坏的本机偏好注入任意 CSS 值。
export const themeColorPresets = [
  // 相近色系集中排列；青绿继续放在首位，保持缺省配色与旧偏好兼容。
  { key: 'teal', label: '青绿', primary: '#237d7a', darkAccent: '#78d6cd' },
  { key: 'green', label: '森林绿', primary: '#15803d', darkAccent: '#86efac' },
  { key: 'cyan', label: '青蓝', primary: '#0e7490', darkAccent: '#67e8f9' },
  { key: 'blue', label: '海蓝', primary: '#2563eb', darkAccent: '#93c5fd' },
  { key: 'indigo', label: '靛蓝', primary: '#4f46e5', darkAccent: '#a5b4fc' },
  { key: 'violet', label: '紫罗兰', primary: '#7c3aed', darkAccent: '#c4b5fd' },
  { key: 'fuchsia', label: '品红', primary: '#a21caf', darkAccent: '#f0abfc' },
  { key: 'rose', label: '玫红', primary: '#be185d', darkAccent: '#f9a8d4' },
  { key: 'red', label: '朱红', primary: '#b91c1c', darkAccent: '#fca5a5' },
  { key: 'orange', label: '暖橙', primary: '#c2410c', darkAccent: '#fdba74' },
  { key: 'amber', label: '琥珀', primary: '#b45309', darkAccent: '#fcd34d' },
  { key: 'slate', label: '岩灰', primary: '#475569', darkAccent: '#cbd5e1' }
] as const
export type ThemeColor = typeof themeColorPresets[number]['key']
export const themeColorStorageKey = 'nexora-theme-color'
type PreferenceStorage = Pick<Storage, 'getItem' | 'setItem'>

export function isThemeColor(value: unknown): value is ThemeColor {
  return themeColorPresets.some((preset) => preset.key === value)
}

export function readThemeColor(storage?: PreferenceStorage): ThemeColor {
  try {
    const value = storage?.getItem(themeColorStorageKey)
    return isThemeColor(value) ? value : 'teal'
  } catch { return 'teal' }
}

export function saveThemeColor(storage: PreferenceStorage | undefined, value: ThemeColor): void {
  // 隐私模式拒绝存储时仍允许当前窗口使用所选主题色。
  try { storage?.setItem(themeColorStorageKey, value) } catch { /* 偏好存储不可用不阻断界面。 */ }
}

function mix(color: string, background: string, weight: number): string {
  const channels = [1, 3, 5].map((offset) => Math.round(
    parseInt(color.slice(offset, offset + 2), 16) * weight +
    parseInt(background.slice(offset, offset + 2), 16) * (1 - weight)
  ).toString(16).padStart(2, '0'))
  return `#${channels.join('')}`
}

export function themeColorPalette(color: ThemeColor, dark: boolean) {
  const preset = themeColorPresets.find((item) => item.key === color) ?? themeColorPresets[0]
  const accent = dark ? preset.darkAccent : mix(preset.primary, '#000000', .84)
  const surface = dark ? '#16253a' : '#ffffff'
  // 深色模式提升强调文字亮度；主按钮保持深色底和白字，所有预设统一验证对比度。
  return {
    primary: preset.primary,
    hover: mix(preset.primary, '#000000', .88),
    pressed: mix(preset.primary, '#000000', .76),
    accent,
    accentHover: mix(accent, dark ? '#ffffff' : '#000000', .9),
    accentPressed: mix(accent, dark ? '#ffffff' : '#000000', .82),
    tint: mix(accent, surface, dark ? .13 : .09),
    activeTint: mix(accent, surface, dark ? .21 : .17),
    ring: `${accent}29`,
    lightPreview: preset.primary,
    darkPreview: preset.darkAccent
  }
}
export type ThemeColorPalette = ReturnType<typeof themeColorPalette>

export function themeColorVariables(palette: ThemeColorPalette): Readonly<Record<string, string>> {
  // 原有共享控件与传送到 body 的菜单都从根节点继承同一组语义变量。
  return {
    '--workspace-field-accent': palette.accent,
    '--app-button-primary': palette.primary,
    '--app-button-primary-hover': palette.hover,
    '--app-button-primary-pressed': palette.pressed,
    '--app-button-secondary-hover': palette.tint,
    '--app-button-secondary-text': palette.accent,
    '--app-accent-tint': palette.tint,
    '--app-accent-active-tint': palette.activeTint,
    '--app-accent-ring': palette.ring,
    '--app-accent-light-preview': palette.lightPreview,
    '--app-accent-dark-preview': palette.darkPreview
  }
}
