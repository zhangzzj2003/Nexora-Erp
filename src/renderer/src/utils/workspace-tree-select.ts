import type { GlobalThemeOverrides, TreeSelectOption } from 'naive-ui'
import type { ThemeColorPalette } from './theme-color'
import { workspaceSelectKey, workspaceSelectTheme } from './workspace-select.ts'
import type { WorkspaceSelectOption, WorkspaceSelectValue } from './workspace-select'

export interface WorkspaceTreeSelectOption<T extends WorkspaceSelectValue = WorkspaceSelectValue> extends WorkspaceSelectOption<T> {
  children?: readonly WorkspaceTreeSelectOption<T>[]
  searchText?: string
}

// 树节点沿用公共下拉的带类型键；显示路径可搜索，回传仍是原始业务值。
export function workspaceTreeOptions<T extends WorkspaceSelectValue>(
  options: readonly WorkspaceTreeSelectOption<T>[], path: readonly string[] = [], disabled = false
): TreeSelectOption[] {
  return options.map(option => {
    const labels = [...path, option.label]
    const blocked = disabled || !!option.disabled
    return {key: workspaceSelectKey(option.value), label: option.label, disabled: blocked,
      searchText: `${labels.join(' / ')} ${String(option.value ?? '')} ${option.searchText ?? ''}`,
      ...(option.children?.length ? {children: workspaceTreeOptions(option.children, labels, blocked)} : {})}
  })
}

// 菜单打开后目录或权限可能变化，每次选择都重新核对当前树和祖先禁用状态。
export function resolveWorkspaceTreeSelection<T extends WorkspaceSelectValue>(
  options: readonly WorkspaceTreeSelectOption<T>[], key: unknown, disabled = false
): WorkspaceTreeSelectOption<T> | undefined {
  if (disabled || typeof key !== 'string') return undefined
  for (const option of options) {
    if (option.disabled) continue
    if (workspaceSelectKey(option.value) === key) return option
    const child = resolveWorkspaceTreeSelection(option.children ?? [], key)
    if (child) return child
  }
  return undefined
}

// 触发框复用现有下拉主题，传送到 body 的树菜单也使用相同的明暗配色。
export function workspaceTreeSelectTheme(dark: boolean, palette?: ThemeColorPalette): NonNullable<GlobalThemeOverrides['TreeSelect']> {
  const select = workspaceSelectTheme(dark, palette)
  const accent = palette?.accent ?? (dark ? '#78d6cd' : '#237d7a')
  return {
    menuColor: dark ? '#16253a' : '#ffffff', menuBorderRadius: '10px', menuPadding: '6px', menuHeight: '320px',
    menuBoxShadow: select.menuBoxShadow,
    peers: {
      InternalSelection: select.peers?.InternalSelection,
      Tree: {fontSize: '13px', nodeHeight: '34px', nodeBorderRadius: '6px',
        nodeTextColor: dark ? '#e4edf8' : '#24394f', nodeTextColorDisabled: dark ? '#8496ae' : '#8d9bab',
        arrowColor: dark ? '#9cb0c7' : '#718399',
        nodeColorHover: dark ? '#23374e' : '#f0f5f8',
        nodeColorActive: palette?.tint ?? (dark ? '#203e49' : '#e5f4f2'),
        nodeColorPressed: palette?.activeTint ?? (dark ? '#294b54' : '#d8eeeb'),
        loadingColor: accent, lineColor: dark ? '#425570' : '#d4dce6'}
    }
  }
}
