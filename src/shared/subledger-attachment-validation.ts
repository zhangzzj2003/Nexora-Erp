import type { SubledgerAttachment } from './erp-api'

function invalid(): never { throw new Error('历史原单附件响应无效，请升级服务端或刷新核对。') }
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return invalid()
  const row = value as Record<string, unknown>
  if ('content' in row || 'content_base64' in row) return invalid()
  return row
}
function positive(value: unknown): value is number { return typeof value === 'number' && Number.isSafeInteger(value) && value > 0 }
function count(value: unknown): value is number { return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 }
function text(value: unknown, max: number): value is string {
  return typeof value === 'string' && !!value.trim() && value.length <= max && !/[\x00-\x1f]/.test(value)
}
function date(value: unknown): boolean { return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) }

function source(value: unknown, openingId: number): Record<string, unknown> {
  const row = object(value)
  if (row.opening_id !== openingId || !['receivable', 'payable'].includes(String(row.kind)) || row.currency !== 'CNY'
    || !date(row.document_date) || !date(row.effective_date)
    || ['id','party_id','account_id','opening_version','opening_balance_id','ledger_opening_version'].some(key => !positive(row[key]))
    || ['party_name','account_name','account_code','document_reference'].some(key => !text(row[key],120))
    || ['debit','credit'].some(key => typeof row[key] !== 'string' || !/^\d{1,20}\.\d{2}$/.test(row[key] as string))
    || !Array.isArray(row.auxiliary) || row.auxiliary.length > 3) return invalid()
  const partyKind = row.kind === 'receivable' ? 'customer' : 'supplier', kinds = new Set<string>()
  for (const value of row.auxiliary) {
    const item = object(value), kind = String(item.kind)
    if (![partyKind,'department','project'].includes(kind) || kinds.has(kind) || !positive(item.id)
      || !text(item.name,120) || !text(item.code,120) || kind === partyKind && item.id !== row.party_id) return invalid()
    kinds.add(kind)
  }
  if (!kinds.has(partyKind)) return invalid()
  return row
}

function item(value: unknown, openingId: number): SubledgerAttachment {
  const row = object(value), suffix = typeof row.file_name === 'string' ? row.file_name.toLowerCase().split('.').at(-1) : ''
  const media: Record<string,string> = { pdf:'application/pdf',png:'image/png',jpg:'image/jpeg',jpeg:'image/jpeg' }
  if (!positive(row.id) || row.opening_id !== openingId || !text(row.file_name,120) || !suffix || row.media_type !== media[suffix]
    || /[<>:"/\\|?*]/.test(row.file_name) || !positive(row.byte_count) || row.byte_count > 5*1024*1024
    || typeof row.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(row.sha256) || !text(row.reason,200)
    || !positive(row.created_by) || !text(row.created_by_name,120) || !text(row.created_at,40)
    || typeof row.can_reverse !== 'boolean' || typeof row.approved_original !== 'boolean'
    || !['matched','changed','missing'].includes(String(row.source_status))
    || (row.source_status === 'missing' ? row.current_line_id !== null : !positive(row.current_line_id))) return invalid()
  source(row.source,openingId)
  if (row.reversal !== null) {
    const reversal = object(row.reversal)
    if (!positive(reversal.id) || !positive(reversal.created_by) || !text(reversal.reason,200)
      || !text(reversal.created_by_name,120) || !text(reversal.created_at,40) || row.can_reverse) return invalid()
  }
  if (row.approved_original && row.can_reverse) return invalid()
  return row as unknown as SubledgerAttachment
}

export function validateSubledgerAttachmentResult(action: string, value: unknown, openingId: number): void {
  if (action !== 'subledgerAttachments') {
    const row = item(value,openingId)
    if (action === 'reverseSubledgerAttachment' && !row.reversal) return invalid()
    return
  }
  const page = object(value)
  if (page.opening_id !== openingId || !positive(page.opening_version) || typeof page.can_modify !== 'boolean'
    || !['draft','submitted','approved','rejected','confirmed','cancelled','reversed'].includes(String(page.opening_status))
    || !positive(page.page) || page.page > 1000000 || !positive(page.page_size) || page.page_size > 100
    || !count(page.total) || !count(page.active_count) || !count(page.changed_count)
    || page.active_count > page.total || page.changed_count > page.active_count || !Array.isArray(page.items)
    || page.items.length > page.page_size || !Array.isArray(page.lines) || page.lines.length > 500) return invalid()
  const lineIds = new Set<number>(), ids = new Set<number>()
  for (const value of page.lines) {
    const row = source(value,openingId)
    if (row.opening_version !== page.opening_version || lineIds.has(row.id as number)) return invalid()
    lineIds.add(row.id as number)
  }
  for (const value of page.items) {
    const row = item(value,openingId)
    if (ids.has(row.id) || row.source.opening_version > page.opening_version
      || row.current_line_id !== null && !lineIds.has(row.current_line_id)) return invalid()
    ids.add(row.id)
  }
}
