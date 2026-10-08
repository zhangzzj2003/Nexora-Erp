// 资金响应在共享边界校验；旧固定归档没有审批字段时仍可只读查询。
export function validatePaymentRecordResponse(value: unknown): void {
  if (Array.isArray(value)) { value.forEach(validatePaymentRecordResponse); return }
  if (!value || typeof value !== 'object') return
  const row = value as Record<string, unknown>
  if (['receivable', 'payable'].includes(String(row.kind)) && (
    ['settlement', 'refund', 'reversal'].includes(String(row.action)) && ('order_id' in row || 'opening_line_id' in row)
    || 'from_order_id' in row && 'to_order_id' in row
    || 'from_line_id' in row && 'to_line_id' in row) && 'status' in row) {
    if (!['draft', 'executed', 'cancelled'].includes(String(row.status)) || !Number.isSafeInteger(row.version) || Number(row.version) < 1
      || !['executed_at', 'cancelled_at'].every(key => row[key] === null || typeof row[key] === 'string')
      || !['executed_by', 'cancelled_by'].every(key => row[key] === null || Number.isSafeInteger(row[key]) && Number(row[key]) > 0)
      || typeof row.cancellation_reason !== 'string'
      || row.status === 'draft' && (row.executed_at !== null || row.cancelled_at !== null)) throw Error('服务端资金执行状态格式不匹配')
  }
  Object.values(row).forEach(validatePaymentRecordResponse)
}
