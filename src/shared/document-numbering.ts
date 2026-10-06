// 配置属于服务端实例；语言仅预选风格，客户端不参与单号流水计算。
export interface DocumentNumberingInput {
  style: 'pinyin' | 'english'
  timezone_mode: 'server' | 'utc' | 'specified'
  timezone: string | null
  version: number
}
export interface DocumentNumberingConfig {
  configured: boolean
  style: DocumentNumberingInput['style'] | null
  timezone_mode: DocumentNumberingInput['timezone_mode']
  timezone: string | null
  version: number
  locked: boolean
  configured_by: number | null
  configured_at: string | null
  server_time: string
  business_time: string
  business_date: string
  timezones: string[]
  backfilled_count: number
  undated_count: number
}
export interface NumberedDocument {
  // 旧库首次设置前允许空值；保留可选类型供历史快照读取，不猜测编号。
  readonly document_no?: string | null
  readonly source_document_no?: string | null
  readonly [key: `${string}_document_no`]: string | null | undefined
}
export interface DocumentNumberingOperations {
  documentNumbering: { input: undefined; output: DocumentNumberingConfig }
  saveDocumentNumbering: { input: DocumentNumberingInput; output: DocumentNumberingConfig }
}
export function documentNumberingBody(value: unknown): DocumentNumberingInput {
  if (!value || typeof value !== 'object') throw new Error('编号设置格式不正确')
  const row = value as Record<string, unknown>
  if (typeof row.style !== 'string' || !['pinyin', 'english'].includes(row.style)
    || typeof row.timezone_mode !== 'string' || !['server', 'utc', 'specified'].includes(row.timezone_mode)
    || !Number.isSafeInteger(row.version) || Number(row.version) < 0
    || (row.timezone_mode === 'specified' ? typeof row.timezone !== 'string'
      || !row.timezone || row.timezone.length > 100 : row.timezone !== null)) {
    throw new Error('请选择编号风格和有效时区')
  }
  return { style: row.style as DocumentNumberingInput['style'],
    timezone_mode: row.timezone_mode as DocumentNumberingInput['timezone_mode'],
    timezone: row.timezone as string | null, version: row.version as number }
}
export function validateDocumentNumbering(value: unknown): asserts value is DocumentNumberingConfig {
  if (!value || typeof value !== 'object') throw new Error('服务端编号规则格式不匹配')
  const row = value as Record<string, unknown>
  if (typeof row.configured !== 'boolean' || typeof row.locked !== 'boolean'
    || !Number.isSafeInteger(row.version) || Number(row.version) < 0
    || !(row.style === null || row.style === 'pinyin' || row.style === 'english')
    || typeof row.timezone_mode !== 'string' || !['server', 'utc', 'specified'].includes(row.timezone_mode)
    || !(row.timezone === null || typeof row.timezone === 'string')
    || (row.configured && row.style === null) || (row.locked && !row.configured)
    || (row.timezone_mode === 'specified' && (typeof row.timezone !== 'string' || !row.timezone))
    || !Array.isArray(row.timezones) || row.timezones.some(item => typeof item !== 'string')
    || typeof row.server_time !== 'string' || !Number.isFinite(Date.parse(row.server_time))
    || typeof row.business_time !== 'string' || !Number.isFinite(Date.parse(row.business_time))
    || typeof row.business_date !== 'string' || !/^\d{8}$/.test(row.business_date)
    || !(row.configured_by === null || Number.isSafeInteger(row.configured_by) && Number(row.configured_by) > 0)
    || !(row.configured_at === null || typeof row.configured_at === 'string')
    || !Number.isSafeInteger(row.backfilled_count) || Number(row.backfilled_count) < 0
    || !Number.isSafeInteger(row.undated_count) || Number(row.undated_count) < 0) {
    throw new Error('服务端编号规则格式不匹配，请核对版本')
  }
}
// 展示时直接使用已保存的完整单号，切换语言不能重新翻译前缀。
export function documentLabel(value: { id?: number | null; document_no?: string | null }): string {
  return value.document_no || (value.id ? `#${value.id}` : '—')
}
export function relatedDocumentLabel(value: object, field: string, frozen?: object): string {
  const row = value as Record<string, unknown>
  // 固定快照不能被展示字段改写；来源单号由外层响应提供，旧 ID 作为兼容回退。
  const source = frozen as Record<string, unknown> | undefined
  return typeof row[`${field}_document_no`] === 'string' && row[`${field}_document_no`]
    ? String(row[`${field}_document_no`]) : (row[`${field}_id`] || source?.[`${field}_id`])
      ? `#${row[`${field}_id`] || source?.[`${field}_id`]}` : '—'
}

// 搜索只读取编号字段，不能把编号风格重新按当前界面语言拼接。
export function documentSearch(value: object): string {
  return Object.entries(value).filter(([key]) => key === 'document_no' || key.endsWith('_document_no'))
    .map(([, number]) => typeof number === 'string' ? number : '').join(' ')
}

// 受限桥接对响应中的编号逐层校验；不要求历史快照新增字段，也不接受任意前缀内容。
export function validateDocumentNumbers(value: unknown): void {
  if (Array.isArray(value)) { value.forEach(validateDocumentNumbers); return }
  if (!value || typeof value !== 'object') return
  for (const [key, part] of Object.entries(value)) {
    if (key === 'document_no' || key.endsWith('_document_no')) {
      if (part !== null && (typeof part !== 'string' || !/^[A-Z]+-\d{8}-\d{6,}$/.test(part))) {
        throw new Error('服务端业务单号格式不匹配')
      }
    } else validateDocumentNumbers(part)
  }
}
