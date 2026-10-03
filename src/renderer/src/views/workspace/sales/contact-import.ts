import type { ContactImportRow } from '../../../../../shared/crm-api'

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

export function parseContactCsv(text: string): ContactImportRow[] {
  if (text.length > 256 * 1024) throw new Error('CSV 文件不能超过 256 KiB')
  const lines = text.replace(/^\uFEFF/, '').split(/\r\n|\n|\r/)
  while (lines.length && !lines[lines.length - 1].trim()) lines.pop()
  const header = fields(lines[0] ?? '').map(value => value.trim())
  const names = ['客户编号', '联系人姓名', '职务', '电话', '邮箱', '备注']
  const english = ['customer_id', 'name', 'job_title', 'phone', 'email', 'note']
  const valid = [names, english].some(expected =>
    (header.length === 2 || header.length === 6) && header.every((name, index) => name === expected[index]))
  if (!valid) throw new Error('请使用 UTF-8 CSV，首列为客户编号、联系人姓名；可依次添加职务、电话、邮箱、备注')
  if (lines.length < 2 || lines.length > 101) throw new Error('每次须导入 1 至 100 位联系人')
  return lines.slice(1).map((line, index) => {
    const row = fields(line).map(value => value.trim())
    if (row.length !== header.length || !/^[1-9]\d*$/.test(row[0])
      || !Number.isSafeInteger(Number(row[0]))) throw new Error(`第 ${index + 2} 行客户编号或列数无效`)
    const [name, job_title = '', phone = '', email = '', note = ''] = row.slice(1)
    if (!name || name.length > 120 || job_title.length > 120 || phone.length > 80
      || email.length > 160 || note.length > 1000 || row.some(value => /[\x00-\x1f]/.test(value))) {
      throw new Error(`第 ${index + 2} 行联系人资料无效`)
    }
    return { customer_id: Number(row[0]), name, job_title, phone, email, note }
  })
}

export function parseContactCsvBytes(bytes: ArrayBuffer): ContactImportRow[] {
  return parseContactCsv(new TextDecoder('utf-8', { fatal: true }).decode(bytes))
}
