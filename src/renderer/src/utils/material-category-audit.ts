import type { MaterialCategoryChange, MaterialCategoryNode, MaterialSpecField, MaterialSpecKind } from '../../../shared/material-api'

const kinds: Record<MaterialSpecKind, string> = {text:'文字', number:'数值', enum:'选项', boolean:'是 / 否', date:'日期'}
type AuditRow = {id: number; label: string; before: string; after: string}
const enabled = (row: MaterialCategoryNode | MaterialSpecField): string => row.deleted ? '已移除' : row.enabled ? '启用' : '停用'

// 以稳定字段编号对照快照，只展示实际变化的业务文案，不让内部存储结构进入操作界面。
export function materialCategoryAuditRows(change: MaterialCategoryChange): AuditRow[] {
  const result: AuditRow[] = []
  function add(label: string, before?: string, after?: string): void {
    if (before !== after) result.push({id:result.length + 1, label, before:before || '—', after:after || '—'})
  }
  const before = change.before, after = change.after
  add('类别名称', before?.name, after.name)
  add('编码前缀', before?.code, after.code)
  add('所属大类', before ? before.parent_code ?? '大类' : undefined, after.parent_code ?? '大类')
  add('类别状态', before ? enabled(before) : undefined, enabled(after))
  add('显示顺序', before ? String(before.sort_order) : undefined, String(after.sort_order))
  add('类别说明', before?.notes ?? '', after.notes)
  const oldFields = new Map(before?.fields.map(field => [field.id, field]) ?? [])
  const newFields = new Map(after.fields.map(field => [field.id, field]))
  for (const id of new Set([...oldFields.keys(), ...newFields.keys()])) {
    const old = oldFields.get(id), next = newFields.get(id)
    const name = next?.name ?? old!.name
    if (!old || !next) {
      add(`规格字段：${name}`, old ? '已存在' : undefined, next ? '新增' : '已移除')
    }
    add(`${name} · 名称`, old?.name, next?.name)
    add(`${name} · 类型`, old ? kinds[old.kind] : undefined, next ? kinds[next.kind] : undefined)
    add(`${name} · 单位`, old?.unit ?? '', next?.unit ?? '')
    add(`${name} · 常用选项`, old?.options.join('、') ?? '', next?.options.join('、') ?? '')
    add(`${name} · 自定义值`, old ? old.allow_custom ? '允许' : '不允许' : undefined, next ? next.allow_custom ? '允许' : '不允许' : undefined)
    add(`${name} · 必填`, old ? old.required ? '是' : '否' : undefined, next ? next.required ? '是' : '否' : undefined)
    add(`${name} · 状态`, old ? enabled(old) : undefined, next ? enabled(next) : '已移除')
    add(`${name} · 显示顺序`, old ? String(old.sort_order) : undefined, next ? String(next.sort_order) : undefined)
  }
  return result
}
