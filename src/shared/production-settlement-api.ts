// 成本结算草稿不能携带正式执行信息；递归校验列表与固定归档中的原生状态。
export function validateProductionSettlementResponse(value: unknown): void {
  if (Array.isArray(value)) { value.forEach(validateProductionSettlementResponse); return }
  if (!value || typeof value !== 'object') return
  const row = value as Record<string, unknown>
  if ('work_order_id' in row && 'material_amount' in row && 'accepted_quantity' in row && 'status' in row) {
    const positive = (value: unknown) => Number.isSafeInteger(value) && Number(value) > 0
    const time = (value: unknown) => value === null || typeof value === 'string' && Number.isFinite(Date.parse(value))
    if (!['draft', 'active', 'cancelled', 'reversed'].includes(String(row.status)) || !positive(row.version)
      || !['executed_at', 'cancelled_at'].every(key => time(row[key]))
      || !['executed_by', 'cancelled_by'].every(key => row[key] === null || positive(row[key]))
      || typeof row.cancellation_reason !== 'string'
      || (row.executed_at === null) !== (row.executed_by === null)
      || (row.cancelled_at === null) !== (row.cancelled_by === null)
      || row.status === 'draft' && (row.executed_at !== null || row.cancelled_at !== null)
      || row.status === 'cancelled' && (row.cancelled_at === null || !row.cancellation_reason.trim() || row.executed_at !== null)) {
      throw Error('服务端成本结算执行状态格式不匹配')
    }
  }
  Object.values(row).forEach(validateProductionSettlementResponse)
}
