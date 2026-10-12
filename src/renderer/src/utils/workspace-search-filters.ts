import { dateFieldError } from './date-field.ts'
import type { WorkspaceSelectOption, WorkspaceSelectValue } from './workspace-select'

// 页面决定字段与业务值，公共组件只负责展示和合法的输入事件。
export type WorkspaceSearchFilterField =
  | { kind: 'select'; key: string; label: string; options: readonly WorkspaceSelectOption[] }
  | { kind: 'date'; key: string; label: string; minKey?: string; maxKey?: string }

export function updateWorkspaceSearchFilter<T extends Record<string, WorkspaceSelectValue>>(
  filters: T,
  field: WorkspaceSearchFilterField,
  value: WorkspaceSelectValue,
  disabled = false,
): T | undefined {
  if (disabled || !Object.hasOwn(filters, field.key)) return undefined
  if (field.kind === 'select') {
    if (!field.options.some(option => !option.disabled && Object.is(option.value, value))) return undefined
  } else {
    // 手输日期仍校验真实日历日期；倒置范围由页面提示，允许先改任意一端再调整另一端。
    if (typeof value !== 'string' || dateFieldError(value, {})) return undefined
  }
  return { ...filters, [field.key]: value }
}
