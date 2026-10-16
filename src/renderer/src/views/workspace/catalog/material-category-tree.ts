import type { MaterialCategory, MaterialCategoryNode } from '../../../../../shared/material-api'

type CategoryEntry = Pick<MaterialCategoryNode, 'code' | 'name'> & Partial<MaterialCategoryNode>
export type MaterialCategoryStatus = 'all' | 'enabled' | 'disabled'
export interface MaterialCategoryTreeRow {
  code: string; name: string; parent_code: string | null; parentName: string; path: string
  notes: string; enabled: boolean | undefined; parentEnabled: boolean | undefined
  material_count: number | undefined; sort_order: number | undefined
  depth: 0 | 1; expanded: boolean; childCount: number; manageable: boolean; contextOnly: boolean
}

// 旧服务只提供名称和前缀，不能靠树的展示补造版本或开放维护接口。
export function categorySupportsManagement(node: CategoryEntry): node is MaterialCategoryNode {
  return Number.isSafeInteger(node.version) && Number(node.version) > 0 && Array.isArray(node.fields)
}

export function materialCategoryTreeRows(categories: readonly MaterialCategory[], query: string,
  status: MaterialCategoryStatus, collapsed: ReadonlySet<string>): MaterialCategoryTreeRow[] {
  const keyword = query.trim().toLowerCase(), filtering = !!keyword || status !== 'all'
  const textMatches = (node: CategoryEntry): boolean => `${node.name} ${node.code} ${node.notes ?? ''}`.toLowerCase().includes(keyword)
  const statusMatches = (node: CategoryEntry): boolean => status === 'all' || node.enabled === (status === 'enabled')
  const rows: MaterialCategoryTreeRow[] = []
  function row(node: CategoryEntry, parent: MaterialCategory | null, childCount: number, expanded: boolean, contextOnly = false): MaterialCategoryTreeRow {
    return {code: node.code, name: node.name, parent_code: parent?.code ?? null, parentName: parent?.name ?? '',
      path: parent ? `${parent.name} / ${node.name}` : node.name, notes: node.notes ?? '', enabled: node.enabled,
      parentEnabled: parent?.enabled, material_count: node.material_count, sort_order: node.sort_order,
      depth: parent ? 1 : 0, expanded, childCount, manageable: categorySupportsManagement(node), contextOnly}
  }
  for (const group of categories) {
    if (group.deleted) continue
    const children = group.children.filter(child => !child.deleted)
    const parentTextMatches = textMatches(group), parentMatches = parentTextMatches && statusMatches(group)
    // 大类名称也是子类的路径；子类命中时保留父行，即使父类本身不符合状态筛选。
    const matches = filtering ? children.filter(child => (parentTextMatches || textMatches(child)) && statusMatches(child)) : children
    if (filtering && !parentMatches && !matches.length) continue
    const expanded = filtering || !collapsed.has(group.code)
    rows.push(row(group, null, children.length, expanded, filtering && !parentMatches))
    if (expanded) rows.push(...matches.map(child => row(child, group, 0, false)))
  }
  return rows
}
