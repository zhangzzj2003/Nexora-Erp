import type { DocumentNumberingConfig, DocumentNumberingInput } from '../../../shared/document-numbering'

// 预览只换算服务端返回的时间；正式日期和流水始终由后端决定。
export function numberingDate(config: DocumentNumberingConfig, input: DocumentNumberingInput): string {
  if (input.timezone_mode === 'server') return config.server_time.slice(0, 10).replaceAll('-', '')
  try {
    const parts = new Intl.DateTimeFormat('en-US', { timeZone: input.timezone_mode === 'utc' ? 'UTC' : input.timezone ?? 'UTC',
      year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date(config.server_time))
    return ['year', 'month', 'day'].map(key => parts.find(part => part.type === key)?.value ?? '').join('')
  } catch { return '' }
}
