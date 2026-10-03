import type { CrmForecast } from './crm-api'

const amount = (value: unknown): value is string => typeof value === 'string' && /^\d+\.\d{2}$/.test(value)
const count = (value: unknown): value is number => Number.isSafeInteger(value) && (value as number) >= 0

export function validateCrmForecast(value: unknown): asserts value is CrmForecast {
  if (!value || typeof value !== 'object') throw new Error('商机预测响应格式不匹配')
  const forecast = value as Record<string, unknown>
  if (forecast.currency !== 'CNY' || !count(forecast.rated_count) || !count(forecast.unrated_count)
    || !amount(forecast.estimated_amount) || !amount(forecast.weighted_amount) || !Array.isArray(forecast.rows)
    || forecast.rows.length !== forecast.rated_count) throw new Error('商机预测响应格式不匹配')
  for (const item of forecast.rows) {
    if (!item || typeof item !== 'object') throw new Error('商机预测明细格式不匹配')
    const row = item as Record<string, unknown>
    if (!count(row.id) || row.id === 0 || !count(row.customer_id) || row.customer_id === 0
      || typeof row.customer_name !== 'string' || typeof row.title !== 'string' || typeof row.owner_name !== 'string'
      || !['prospect', 'qualified', 'proposal', 'negotiation'].includes(String(row.stage))
      || typeof row.expected_close_date !== 'string' || !amount(row.estimated_amount)
      || !count(row.probability_percent) || (row.probability_percent as number) > 100
      || !amount(row.weighted_amount) || typeof row.overdue !== 'boolean') throw new Error('商机预测明细格式不匹配')
  }
}
