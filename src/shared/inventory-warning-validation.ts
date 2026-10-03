// 服务端返回的空状态、数量和审计必须先核对，失败不能被当成零库存。
type Check = (value: unknown) => boolean
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value)
const text: Check = value => typeof value === 'string'
const positive: Check = value => typeof value === 'number' && Number.isSafeInteger(value) && value > 0
const count: Check = value => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
const decimal: Check = value => typeof value === 'string' && /^\d+(?:\.\d+)?$/.test(value)
const quantity: Check = value => typeof value === 'string' && /^-?\d+(?:\.\d+)?$/.test(value)
const array = (check: Check): Check => value => Array.isArray(value) && value.every(check)
function fields(value: unknown, spec: Record<string, Check>): boolean {
  return object(value) && Object.entries(spec).every(([key, check]) => check(value[key]))
}
const statuses = ['normal', 'low', 'out_of_stock', 'disabled'] as const
const snapshot: Check = value => fields(value, {id:positive, warehouse_id:positive, material_id:positive,
  version:positive, threshold:decimal, enabled:value=>typeof value==='boolean', created_by:positive, created_at:text,
  warehouse_code:text, warehouse_name:text, sku:text, material_name:text, unit:text})
const row: Check = value => snapshot(value) && fields(value, {quantity, status:value=>statuses.includes(value as typeof statuses[number]),
  shortage:value=>value===null || decimal(value)}) && object(value)
  && (value.enabled ? value.status!=='disabled' && value.shortage!==null : value.status==='disabled' && value.shortage===null)
const change: Check = value => fields(value, {id:positive, reason:text, changed_by:positive, changed_by_name:text, created_at:text,
  before:value=>value===null || snapshot(value), after:snapshot})
const detail: Check = value => fields(value, {row, changes:array(change)})
const overview: Check = value => fields(value, {as_of:text, warehouse_id:value=>value===null || positive(value), rows:array(row),
  warehouses:array(value=>fields(value,{id:positive,code:text,name:text})), materials:array(value=>fields(value,{id:positive,sku:text,name:text,unit:text})),
  summary:value=>fields(value,Object.fromEntries([...statuses,'configured','unconfigured'].map(key=>[key,count])))})
const warningEvent: Check = value => fields(value, {id:positive, rule_id:positive, warehouse_id:positive,
  material_id:positive, previous_status:value=>value===null || statuses.includes(value as typeof statuses[number]),
  status:value=>value==='low' || value==='out_of_stock', quantity, threshold:decimal, shortage:decimal,
  rule_version:positive, warehouse_code:text, warehouse_name:text, sku:text, material_name:text, unit:text,
  observed_at:text, created_at:text})
const eventPage: Check = value => fields(value, {as_of:text, warehouse_id:value=>value===null || positive(value),
  events:array(warningEvent), next_before_id:value=>value===null || positive(value)})
export function validateInventoryWarningResult(action: string, value: unknown): void {
  const check = action==='inventoryWarnings' ? overview : action==='inventoryWarningEvents' ? eventPage
    : ['inventoryWarningDetail','saveInventoryWarning'].includes(action) ? detail : null
  if (check && !check(value)) throw new Error('库存预警响应格式不匹配，请核对服务端版本后重新读取。')
}
