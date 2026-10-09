import type { Permission } from '../../../shared/erp-api'

export interface PermissionDocument {
  code: string
  label: string
  permissions: Permission[]
}

export interface PermissionModule {
  code: string
  label: string
  documents: PermissionDocument[]
}

export interface PermissionOperationGroup {
  code: 'read-write' | 'approval'
  label: string
  permissions: Permission[]
}

// 中文名称允许管理员修改；用稳定的操作代码分类，避免改名后审核权限混入读写权限。
const approvalActions = new Set(['review', 'verify', 'approve'])

export function documentPermissionGroups(document: PermissionDocument): PermissionOperationGroup[] {
  const groups: PermissionOperationGroup[] = [
    { code: 'read-write', label: '读写操作', permissions: [] },
    { code: 'approval', label: '审核操作', permissions: [] }
  ]
  for (const permission of document.permissions) {
    const action = permission.code.slice(permission.code.lastIndexOf('.') + 1)
    // 确认、冲销和检验属于业务执行；仅审核、核准、批准归入审核组。
    groups[approvalActions.has(action) ? 1 : 0].permissions.push(permission)
  }
  // 不显示空分类，旧服务端和新操作代码仍保留全部授权叶子。
  return groups.filter((group) => group.permissions.length > 0)
}

export function operationGroupPermissionCodes(group: PermissionOperationGroup): string[] {
  return group.permissions.map((permission) => permission.code)
}

const moduleOrder = ['warehouse', 'catalog', 'purchase', 'sales', 'finance', 'production', 'system', 'other']

function modulePosition(code: string): number {
  const position = moduleOrder.indexOf(code)
  return position < 0 ? moduleOrder.length : position
}

export function buildPermissionTree(permissions: readonly Permission[]): PermissionModule[] {
  const modules = new Map<string, PermissionModule>()
  for (const permission of permissions) {
    // 旧服务端没有层级字段时仍能展示权限，避免授权项从页面消失。
    const [moduleGroup, documentGroup] = permission.group_path ?? []
    const moduleCode = moduleGroup?.code || 'other'
    const documentCode = documentGroup?.code || 'unclassified'
    let module = modules.get(moduleCode)
    if (!module) {
      module = { code: moduleCode, label: moduleGroup?.label || '其他权限', documents: [] }
      modules.set(moduleCode, module)
    }
    let document = module.documents.find((entry) => entry.code === documentCode)
    if (!document) {
      document = { code: documentCode, label: documentGroup?.label || '待分类权限', permissions: [] }
      module.documents.push(document)
    }
    document.permissions.push(permission)
  }
  return [...modules.values()]
    .sort((left, right) => modulePosition(left.code) - modulePosition(right.code))
    .map((module) => ({
      ...module,
      documents: module.documents
        .sort((left, right) => left.label.localeCompare(right.label, 'zh-CN'))
        .map((document) => ({
          ...document,
          permissions: document.permissions.sort((left, right) => left.label.localeCompare(right.label, 'zh-CN'))
        }))
    }))
}

export function documentPermissionCodes(document: PermissionDocument): string[] {
  return document.permissions.map((permission) => permission.code)
}

export function modulePermissionCodes(module: PermissionModule): string[] {
  return module.documents.flatMap(documentPermissionCodes)
}

export function selectedPermissionCount(selected: readonly string[], codes: readonly string[]): number {
  const selectedCodes = new Set(selected)
  return codes.filter((code) => selectedCodes.has(code)).length
}

export function togglePermissionCodes(
  selected: readonly string[],
  codes: readonly string[],
  checked: boolean
): string[] {
  const next = new Set(selected)
  for (const code of codes) {
    if (checked) next.add(code)
    else next.delete(code)
  }
  // 父级只做批量选择，提交给服务端的始终是操作叶子的代码。
  return [...next]
}
