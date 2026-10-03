import type { OpportunityImportRow } from '../../../../../shared/crm-api'
import { dateFieldError } from '../../../utils/date-field.ts'

function fields(line: string): string[] {
  const result: string[] = []
  let value = ''
  let quoted = false
  let closed = false
  for (let index = 0; index < line.length; index++) {
    const char = line[index]
    if (quoted) {
      if (char === '"' && line[index + 1] === '"') { value += '"'; index++ }
      else if (char === '"') { quoted = false; closed = true }
      else value += char
    } else if (char === ',') {
      result.push(value); value = ''; closed = false
    } else if (char === '"' && !value && !closed) quoted = true
    else if (closed || char === '"') throw new Error('CSV 引号格式无效')
    else value += char
  }
  if (quoted) throw new Error('CSV 引号未闭合')
  result.push(value)
  return result
}

export function parseOpportunityCsv(text: string): OpportunityImportRow[] {
  if (text.length > 256 * 1024) throw new Error('CSV 文件不能超过 256 KiB')
  const lines = text.replace(/^\uFEFF/, '').split(/\r\n|\n|\r/)
  while (lines.length && !lines[lines.length - 1].trim()) lines.pop()
  const header = fields(lines[0] ?? '').map(value => value.trim())
  const names = ['客户编号', '商机名称', '负责人编号', '预计金额', '预计成交日期', '联系人编号', '备注']
  const english = ['customer_id', 'title', 'owner_id', 'estimated_amount', 'expected_close_date', 'contact_id', 'note']
  if (![names, english].some(expected => (header.length === 5 || header.length === 7)
    && header.every((name, index) => name === expected[index]))) {
    throw new Error('请使用 UTF-8 CSV，前五列为客户编号、商机名称、负责人编号、预计金额、预计成交日期；可追加联系人编号、备注')
  }
  if (lines.length < 2 || lines.length > 101) throw new Error('每次须导入 1 至 100 条商机')
  return lines.slice(1).map((line, index) => {
    const row = fields(line).map(value => value.trim())
    const identifier = (value: string): number | null => /^[1-9]\d*$/.test(value) && Number.isSafeInteger(Number(value)) ? Number(value) : null
    const customer_id = identifier(row[0])
    const owner_id = identifier(row[2])
    const contact_id = row[5] ? identifier(row[5]) : null
    const [title, estimated_amount, expected_close_date, note = ''] = [row[1], row[3], row[4], row[6]]
    if (row.length !== header.length || !customer_id || !owner_id || (row[5] && !contact_id)
      || !title || title.length > 160 || note.length > 1000
      || row.some(value => /[\x00-\x1f]/.test(value))) throw new Error(`第 ${index + 2} 行商机资料或列数无效`)
    if (!/^\d+(?:\.\d{1,2})?$/.test(estimated_amount) || Number(estimated_amount) > 100_000_000_000)
      throw new Error(`第 ${index + 2} 行预估金额无效`)
    if (dateFieldError(expected_close_date, {required:true, min:'1900-01-01', max:'2199-12-31'}))
      throw new Error(`第 ${index + 2} 行预计成交日期无效`)
    return {customer_id, title, owner_id, estimated_amount, expected_close_date, contact_id, note}
  })
}

export function parseOpportunityCsvBytes(bytes: ArrayBuffer): OpportunityImportRow[] {
  return parseOpportunityCsv(new TextDecoder('utf-8', {fatal:true}).decode(bytes))
}
