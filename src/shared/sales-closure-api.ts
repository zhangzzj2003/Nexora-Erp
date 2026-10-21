// 终止证据固定当时的数量；退货或冲销后的实时交付另在原单展示。
export interface SalesOrderClosure {
  reason: string; created_by: number; created_by_name: string; created_at: string
  lines: {id:number; material_id:number; sku:string; material_name:string; unit:string;
    quantity:string; shipped_quantity:string; closed_quantity:string}[]
}
export interface SalesOrderCloseInput {
  reason: string
  expected_lines: {line_id:number; shipped_quantity:string}[]
}
export function salesCloseFields(value: unknown): SalesOrderCloseInput {
  const input = value as Partial<SalesOrderCloseInput> | null
  if (!input || typeof input.reason !== 'string' || !input.reason.trim() || input.reason.length > 500)
    throw Error('请填写 1～500 字的终止原因')
  if (!Array.isArray(input.expected_lines) || !input.expected_lines.length || input.expected_lines.length > 100)
    throw Error('订单明细无效，请重新打开订单')
  const lines = input.expected_lines.map(line=> {
    if (!line || !Number.isInteger(line.line_id) || line.line_id <= 0 || typeof line.shipped_quantity !== 'string' ||
        !/^\d{1,7}(?:\.\d{1,3})?$/.test(line.shipped_quantity)) throw Error('订单出库实绩无效')
    return {line_id:line.line_id, shipped_quantity:line.shipped_quantity}
  })
  if (new Set(lines.map(line=>line.line_id)).size !== lines.length) throw Error('订单明细不能重复')
  return {reason:input.reason.trim(), expected_lines:lines}
}
