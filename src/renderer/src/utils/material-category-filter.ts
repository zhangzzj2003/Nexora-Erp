import type { MaterialCategory } from '../../../shared/material-api'
import type { WorkspaceTreeSelectOption } from './workspace-tree-select'

// 查询保留停用分类以便查历史；停用只限制新建归类，不限制现有物料的筛选。
export function materialCategoryFilterOptions(categories: readonly MaterialCategory[]): WorkspaceTreeSelectOption<string>[] {
  return [{value: '', label: '全部分类'}, {value: 'unclassified', label: '未分类'},
    ...categories.map(group => ({value: group.code, label: `${group.name}${group.enabled === false ? '（已停用）' : ''}`,
      children: group.children.map(child => ({value: child.code,
        label: `${child.name}${child.enabled === false ? '（已停用）' : ''}`}))}))]
}
