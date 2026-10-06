import {validateInventoryWarningResult} from '../shared/inventory-warning-validation.ts'
import {validatePhysicalLotResult} from '../shared/physical-lot-validation.ts'
import {physicalLotEvidenceBody,physicalLotEvidenceGroupBody,physicalLotEvidencePairBody,physicalLotMovementEvidenceBody,physicalLotReverseBody} from '../shared/physical-lot-api.ts'
import {inboundLotBody,receiptLotBody,validatePostedInboundLots,validatePostedReceiptLots} from '../shared/receipt-lot-validation.ts'
import {completionLotBody,validatePostedCompletionLots} from '../shared/completion-lot-validation.ts'
import {outboundLotBody,validateOutboundLotOptions,validatePostedOutboundLots} from '../shared/outbound-lot-api.ts'
import {shipmentLotBody,validateShipmentLotOptions,validatePostedShipmentLots} from '../shared/shipment-lot-api.ts'
import {materialIssueLotBody,validateMaterialIssueLotOptions,validatePostedMaterialIssueLots} from '../shared/material-issue-lot-api.ts'
import {materialReturnLotBody,validateMaterialReturnLotOptions,validatePostedMaterialReturnLots} from '../shared/material-return-lot-api.ts'
import {transferLotBody,validateTransferLotOptions,validatePostedTransferLots} from '../shared/transfer-lot-api.ts'
import {stocktakeLotBody,validateStocktakeLotOptions,validatePostedStocktakeLots} from '../shared/stocktake-lot-api.ts'
import {adjustmentLotBody,validateAdjustmentLotOptions,validatePostedAdjustmentLots} from '../shared/adjustment-lot-api.ts'
import {salesReturnLotBody,validateSalesReturnLotOptions,validatePostedSalesReturnLots} from '../shared/sales-return-lot-api.ts'
import {warningThresholdValid} from '../shared/inventory-warning-api.ts'
import { materialBody, validateMaterialResult } from '../shared/material-validation.ts'
import type { BackendHealth } from '../shared/desktop-api'
import type { ErpOperations } from '../shared/erp-api'
import {validateDashboardResult} from '../shared/dashboard-api.ts'
import {validateEquipmentResult} from '../shared/equipment-validation.ts'
import {validateCustomerImportPreview,validateCustomerImportResult} from '../shared/customer-import-validation.ts'
import {validateContactImportPreview,validateContactImportResult} from '../shared/contact-import-validation.ts'
import {validateOpportunityImportPreview,validateOpportunityImportResult} from '../shared/opportunity-import-validation.ts'
import {validateCrmForecast} from '../shared/crm-forecast-validation.ts'
import {validateJournalAttachmentResult} from '../shared/journal-attachment-validation.ts'
import {validateAfterSalesAttachmentResult} from '../shared/after-sales-attachment-validation.ts'
import {validateCrmQuoteAttachmentResult} from '../shared/crm-quote-attachment-validation.ts'
import {validateSalesContractAttachmentResult} from '../shared/sales-contract-attachment-validation.ts'
import {validateCrmRecordAttachmentResult} from '../shared/crm-record-attachment-validation.ts'
import type {CrmAttachmentKind} from '../shared/crm-api.ts'
import {validateEquipmentAttachmentResult} from '../shared/equipment-attachment-validation.ts'
import type {EquipmentAttachmentKind} from '../shared/equipment-api.ts'
import { request as httpsRequest } from 'node:https'
import { createHash } from 'node:crypto'

export interface BackendTarget {
  host: string
  port: number
  instanceId: string
  certificate: string
}

let sessionToken: string | null = null
let selectedTarget: BackendTarget | null = null
let sessionRevision = 0

function setSessionToken(token: string | null, forceRevision = false): void {
  if (forceRevision || sessionToken !== token) sessionRevision++
  sessionToken = token
}

// 只暴露不含令牌的会话代号，供主进程丢弃跨账号或跨实例的迟到预警响应。
export function backendSessionMarker(): number | null {
  return sessionToken ? sessionRevision : null
}

function sameBackendIdentity(left: BackendTarget | null, right: BackendTarget | null): boolean {
  // 地址可能因局域网变化而更新；实例编号和已信任证书同时一致才允许沿用会话。
  return !!left && !!right && left.instanceId === right.instanceId
    && left.certificate === right.certificate
}

// 令牌只跟随已经核验过的服务端身份，绝不因地址相同就信任另一张证书。
export function retainedSessionToken(token: string | null, current: BackendTarget | null,
                                     next: BackendTarget | null): string | null {
  return sameBackendIdentity(current, next) ? token : null
}

export function selectBackend(target: BackendTarget | null): void {
  // 刷新页面会重新选中同一服务端，只有真正切换实例或证书时才丢弃令牌。
  setSessionToken(retainedSessionToken(sessionToken, selectedTarget, target))
  selectedTarget = target
}

function backendBase(): URL {
  const base = new URL(process.env.NEXORA_API_URL || 'http://127.0.0.1:8000')
  if (!['http:', 'https:'].includes(base.protocol) || base.username || base.password
    || !['127.0.0.1', 'localhost', '[::1]'].includes(base.hostname)) {
    throw new Error('后端地址配置无效，请检查 NEXORA_API_URL。')
  }
  return base
}

async function sendRequest(path: string, method: string, headers: Record<string, string>, body?: unknown,
                           timeout = 10000, targetOverride?: BackendTarget | null,
                           maxResponseBytes?: number): Promise<Response> {
  const target = targetOverride === undefined ? selectedTarget : targetOverride
  if (!target) {
    // 开发环境仍支持显式配置的旧地址，桌面向导连接一律走证书固定的 HTTPS。
    return fetch(new URL(path, backendBase()), {
      method, headers, body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(timeout), redirect: 'error'
    })
  }
  return new Promise((resolve, reject) => {
    const req = httpsRequest({
      hostname: target.host, port: target.port, path, method, headers,
      ca: target.certificate, servername: `nexora-${target.instanceId}.local`,
      rejectUnauthorized: true, timeout
    }, (incoming) => {
      const chunks: Buffer[] = []
      let size = 0
      incoming.on('data', (chunk: Buffer) => {
        size += chunk.length
        if (maxResponseBytes !== undefined && size > maxResponseBytes) {
          req.destroy(new Error('服务端返回的文件过大'))
          return
        }
        chunks.push(chunk)
      })
      incoming.on('end', () => resolve(new Response(incoming.statusCode === 204 ? null : Buffer.concat(chunks), {
        status: incoming.statusCode ?? 500,
        headers: {
          'content-type': String(incoming.headers['content-type'] ?? ''),
          'x-nexora-sha256': String(incoming.headers['x-nexora-sha256'] ?? ''),
          'x-nexora-file-extension': String(incoming.headers['x-nexora-file-extension'] ?? '')
        }
      })))
    })
    req.on('timeout', () => req.destroy(new Error('连接超时')))
    req.on('error', reject)
    if (body !== undefined) req.write(JSON.stringify(body))
    req.end()
  })
}

export async function fetchCrmQuotePdf(value: unknown): Promise<{ id: number; bytes: Buffer; isCurrent: () => boolean }> {
  const id = positiveId({ id: value }, 'id')
  if (!sessionToken) throw new Error('请先登录')
  const token = sessionToken
  const target = selectedTarget
  let response: Response
  try {
    response = await sendRequest(`/api/v1/crm/quotes/${id}/pdf`, 'GET',
      { Authorization: `Bearer ${token}` }, undefined, 20000, target, 5_000_000)
  } catch (cause) {
    if (cause instanceof Error && cause.message === '服务端返回的文件过大') throw cause
    throw new Error('无法读取报价 PDF，请检查网络、服务状态和证书。')
  }
  if (!response.ok) {
    if (response.status === 401 && sessionToken === token) setSessionToken(null)
    const data: unknown = await response.json().catch(() => undefined)
    const detail = data && typeof data === 'object' && 'detail' in data ? data.detail : undefined
    throw new Error(typeof detail === 'string' ? detail : `报价 PDF 请求失败（HTTP ${response.status}）`)
  }
  if (!response.headers.get('content-type')?.toLowerCase().startsWith('application/pdf')) {
    throw new Error('服务端返回的报价文件格式无效')
  }
  const reader = response.body?.getReader()
  if (!reader) throw new Error('服务端未返回报价文件')
  const chunks: Buffer[] = []
  let size = 0
  for (;;) {
    const { done, value: chunk } = await reader.read()
    if (done) break
    size += chunk.byteLength
    if (size > 5_000_000) {
      await reader.cancel()
      throw new Error('报价 PDF 超过大小限制')
    }
    chunks.push(Buffer.from(chunk))
  }
  const bytes = Buffer.concat(chunks)
  if (bytes.length < 16 || !bytes.subarray(0, 5).equals(Buffer.from('%PDF-'))
    || !bytes.subarray(-1024).includes(Buffer.from('%%EOF'))) {
    throw new Error('服务端返回的报价文件格式无效')
  }
  return { id, bytes, isCurrent: () => sessionToken === token
    && (target === null ? selectedTarget === null : sameBackendIdentity(selectedTarget, target)) }
}

async function fetchStoredAttachment(documentType: 'journal' | 'after-sales' | 'crm-quote' | 'crm-record' | 'equipment' | 'sales-contract', documentValue: unknown,
    attachmentValue: unknown, recordKind?: CrmAttachmentKind | EquipmentAttachmentKind, orderValue?: unknown): Promise<{
  documentId: number; attachmentId: number; extension: string; bytes: Buffer; isCurrent: () => boolean
}> {
  const documentId = positiveId({ id: documentValue }, 'id')
  const attachmentId = positiveId({ id: attachmentValue }, 'id')
  const orderId = documentType === 'sales-contract' ? positiveId({ id: orderValue }, 'id') : null
  if (!sessionToken) throw new Error('请先登录')
  const token = sessionToken
  const target = selectedTarget
  let response: Response
  try {
    const path = documentType === 'journal'
      ? `/api/v1/finance/journals/${documentId}/attachments/${attachmentId}`
      : documentType === 'after-sales'
        ? `/api/v1/after-sales/cases/${documentId}/attachments/${attachmentId}`
        : documentType === 'crm-quote'
          ? `/api/v1/crm/quotes/${documentId}/attachments/${attachmentId}`
          : documentType === 'sales-contract'
            ? `/api/v1/sales-orders/${orderId}/contract/revisions/${documentId}/attachments/${attachmentId}`
          : documentType === 'equipment'
            ? `/api/v1/equipment/${recordKind}/${documentId}/attachments/${attachmentId}`
            : `/api/v1/crm/records/${recordKind}/${documentId}/attachments/${attachmentId}`
    response = await sendRequest(path,
      'GET', { Authorization: `Bearer ${token}` }, undefined, 30000, target, 5 * 1024 * 1024)
  } catch (cause) {
    if (cause instanceof Error && cause.message === '服务端返回的文件过大') throw cause
    throw new Error('无法读取附件，请检查网络、服务状态和证书。')
  }
  if (!response.ok) {
    if (response.status === 401 && sessionToken === token) setSessionToken(null)
    const data: unknown = await response.json().catch(() => undefined)
    const detail = data && typeof data === 'object' && 'detail' in data ? data.detail : undefined
    throw new Error(typeof detail === 'string' ? detail : `附件请求失败（HTTP ${response.status}）`)
  }
  const digest = response.headers.get('x-nexora-sha256') ?? ''
  const extension = response.headers.get('x-nexora-file-extension') ?? ''
  if (!response.headers.get('content-type')?.toLowerCase().startsWith('application/octet-stream')
    || !/^[a-f0-9]{64}$/.test(digest) || !['.pdf', '.png', '.jpg', '.jpeg'].includes(extension)) {
    throw new Error('服务端返回的附件元数据无效')
  }
  const reader = response.body?.getReader()
  if (!reader) throw new Error('服务端未返回附件')
  const chunks: Buffer[] = []
  let size = 0
  for (;;) {
    const { done, value: chunk } = await reader.read()
    if (done) break
    size += chunk.byteLength
    if (size > 5 * 1024 * 1024) {
      await reader.cancel()
      throw new Error('附件超过大小限制')
    }
    chunks.push(Buffer.from(chunk))
  }
  const bytes = Buffer.concat(chunks)
  if (!bytes.length || createHash('sha256').update(bytes).digest('hex') !== digest) {
    throw new Error('附件内容校验失败')
  }
  const valid = extension === '.pdf' ? bytes.subarray(0, 5).equals(Buffer.from('%PDF-'))
    && bytes.subarray(-1024).includes(Buffer.from('%%EOF'))
    : extension === '.png' ? bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))
    : bytes.subarray(0, 3).equals(Buffer.from([255, 216, 255]))
      && bytes.subarray(-2).equals(Buffer.from([255, 217]))
  if (!valid) throw new Error('服务端返回的附件格式无效')
  return { documentId, attachmentId, extension, bytes,
    isCurrent: () => sessionToken === token &&
      (target === null ? selectedTarget === null : sameBackendIdentity(selectedTarget, target)) }
}

export async function fetchJournalAttachment(journalValue: unknown, attachmentValue: unknown) {
  const file = await fetchStoredAttachment('journal', journalValue, attachmentValue)
  return { ...file, journalId: file.documentId }
}

export async function fetchAfterSalesAttachment(caseValue: unknown, attachmentValue: unknown) {
  const file = await fetchStoredAttachment('after-sales', caseValue, attachmentValue)
  return { ...file, caseId: file.documentId }
}

export async function fetchCrmQuoteAttachment(quoteValue: unknown, attachmentValue: unknown) {
  const file = await fetchStoredAttachment('crm-quote', quoteValue, attachmentValue)
  return { ...file, quoteId: file.documentId }
}

export async function fetchSalesContractAttachment(orderValue: unknown, revisionValue: unknown, attachmentValue: unknown) {
  const file = await fetchStoredAttachment('sales-contract', revisionValue, attachmentValue, undefined, orderValue)
  return { ...file, orderId: positiveId({ id: orderValue }, 'id'), revisionId: file.documentId }
}

export async function fetchCrmRecordAttachment(kindValue: unknown, recordValue: unknown, attachmentValue: unknown) {
  const kind = crmRecordKind(kindValue)
  const file = await fetchStoredAttachment('crm-record', recordValue, attachmentValue, kind)
  return { ...file, kind, recordId: file.documentId }
}

export async function fetchEquipmentAttachment(kindValue: unknown, recordValue: unknown, attachmentValue: unknown) {
  const kind = equipmentAttachmentKind(kindValue)
  const file = await fetchStoredAttachment('equipment', recordValue, attachmentValue, kind)
  return { ...file, kind, recordId: file.documentId }
}

export async function getServerInfo(target?: BackendTarget): Promise<{ id: string; name: string; version: string; ready: boolean }> {
  const response = await sendRequest('/api/v1/server/info', 'GET', {}, undefined, 5000, target)
  if (!response.ok) throw new Error(`服务端身份检查失败（HTTP ${response.status}）`)
  const info: unknown = await response.json()
  if (!info || typeof info !== 'object' || !('id' in info) || typeof info.id !== 'string'
    || !('name' in info) || typeof info.name !== 'string'
    || !('version' in info) || typeof info.version !== 'string'
    || !('ready' in info) || typeof info.ready !== 'boolean') {
    throw new Error('服务端身份响应格式无效')
  }
  if ((target ?? selectedTarget) && info.id !== (target ?? selectedTarget)?.instanceId) throw new Error('服务端实例身份已变化')
  return info as { id: string; name: string; version: string; ready: boolean }
}

function positiveId(payload: unknown, key: string): number {
  const value = payload && typeof payload === 'object' ? (payload as Record<string, unknown>)[key] : undefined
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value <= 0) {
    throw new Error('记录编号无效')
  }
  return value
}

function crmRecordKind(value: unknown): CrmAttachmentKind {
  if (value !== 'contact' && value !== 'activity' && value !== 'opportunity') {
    throw new Error('客户关系记录类型无效')
  }
  return value
}

function equipmentAttachmentKind(value: unknown): EquipmentAttachmentKind {
  if (value !== 'asset' && value !== 'job') throw new Error('设备维护附件类型无效')
  return value
}

function bankText(value: unknown, label: string, max: number, required = true): string {
  if (typeof value !== 'string' || value.length > max || /[\x00-\x1f]/.test(value)
    || (required && !value.trim())) throw new Error(`${label}无效`)
  return value.trim()
}

function bankCsvBody(payload: unknown): Record<string, unknown> {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) throw new Error('银行 CSV 参数无效')
  const value = payload as Record<string, unknown>
  const account_id = positiveId(value, 'account_id')
  const file_name = bankText(value.file_name, 'CSV 文件名', 120)
  if (/[\\/]/.test(file_name) || !file_name.toLowerCase().endsWith('.csv')) throw new Error('CSV 文件名无效')
  const content_base64 = value.content_base64
  if (typeof content_base64 !== 'string' || !content_base64.length || content_base64.length > 1_398_104
    || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(content_base64)) {
    throw new Error('CSV 文件内容无效')
  }
  return { account_id, file_name, content_base64 }
}

function attachmentBody(payload: unknown): Record<string, unknown> {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) throw new Error('附件参数无效')
  const value = payload as Record<string, unknown>
  const file_name = value.file_name
  const reason = value.reason
  const content_base64 = value.content_base64
  if (typeof file_name !== 'string' || !file_name.trim() || file_name.length > 120
    || /[<>:"\/\\|?*\x00-\x1f]/.test(file_name) || file_name.trim().endsWith('.')
    || !/\.(?:pdf|png|jpe?g)$/i.test(file_name)) throw new Error('附件文件名无效')
  if (typeof reason !== 'string' || !reason.trim() || reason.length > 200
    || /[\x00-\x1f]/.test(reason)) throw new Error('附件依据无效')
  if (typeof content_base64 !== 'string' || !content_base64.length
    || content_base64.length > 6_990_508 || !/^[A-Za-z0-9+/]*={0,2}$/.test(content_base64)) {
    throw new Error('附件内容无效')
  }
  const bytes = Buffer.from(content_base64, 'base64')
  if (!bytes.length || bytes.length > 5 * 1024 * 1024
    || bytes.toString('base64') !== content_base64) throw new Error('附件内容无效')
  return { file_name: file_name.trim(), content_base64, reason: reason.trim() }
}

function bankBalanceDate(value: unknown): string {
  const day = bankText(value, '银行调节日期', 10)
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || Number.isNaN(Date.parse(`${day}T00:00:00Z`))
    || new Date(`${day}T00:00:00Z`).toISOString().slice(0, 10) !== day) throw new Error('银行调节日期无效')
  return day
}

function bankBalanceAmount(value: unknown): string {
  const amount = bankText(value, '银行余额', 20)
  if (!/^-?(?:0|[1-9]\d*)(?:\.\d{1,2})?$/.test(amount)
    || !Number.isFinite(Number(amount)) || Math.abs(Number(amount)) > 1_000_000_000_000) {
    throw new Error('银行余额无效')
  }
  return amount
}

function bankBalanceIds(value: unknown): number[] {
  if (!Array.isArray(value) || value.length < 1 || value.length > 20
    || value.some(item => typeof item !== 'number' || !Number.isSafeInteger(item) || item <= 0)
    || new Set(value).size !== value.length) throw new Error('银行勾对明细编号无效')
  return value
}

function bankBalanceBody(payload: unknown, kind: 'binding' | 'preview' | 'match' | 'report' | 'decision' | 'reason' | 'opening-clearance'): Record<string, unknown> {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) throw new Error('银行余额调节参数无效')
  const value = payload as Record<string, unknown>
  const reason = () => bankText(value.reason, '银行调节依据', 200)
  if (kind === 'reason') return { reason: reason() }
  if (kind === 'decision') {
    if (value.action !== 'approve' && value.action !== 'reject') throw new Error('银行调节复核动作无效')
    return { action: value.action, reason: reason() }
  }
  if (kind === 'binding') {
    const effective_date = bankBalanceDate(value.effective_date)
    const input = value.opening_items ?? []
    if (!Array.isArray(input) || input.length > 100) throw new Error('银行期初未达项无效')
    const opening_items = input.map((entry: unknown) => {
      if (!entry || typeof entry !== 'object' || Array.isArray(entry)) throw new Error('银行期初未达项无效')
      const item = entry as Record<string, unknown>
      if (item.side !== 'bank' && item.side !== 'book') throw new Error('银行期初未达项方向无效')
      const occurred_on = bankBalanceDate(item.occurred_on)
      if (occurred_on >= effective_date) throw new Error('银行期初未达项日期须早于启用日')
      const amount = bankBalanceAmount(item.amount)
      if (Number(amount) === 0) throw new Error('银行期初未达项金额不能为零')
      return { side: item.side, occurred_on, amount,
        reference: bankText(item.reference, '期初未达项依据编号', 100),
        description: bankText(item.description, '期初未达项说明', 200) }
    })
    if (new Set(opening_items.map(item => `${item.side}:${item.reference}`)).size !== opening_items.length) {
      throw new Error('同侧期初未达项依据编号不能重复')
    }
    return { ledger_account_id: positiveId(value, 'ledger_account_id'),
      opening_balance: bankBalanceAmount(value.opening_balance), effective_date,
      version: positiveId(value, 'version'), reason: reason(), opening_items }
  }
  if (kind === 'opening-clearance') return { source_ids: bankBalanceIds(value.source_ids), reason: reason() }
  if (kind === 'match') return { account_id: positiveId(value, 'account_id'),
    bank_line_ids: bankBalanceIds(value.bank_line_ids), journal_line_ids: bankBalanceIds(value.journal_line_ids),
    reason: reason() }
  return { account_id: positiveId(value, 'account_id'), as_of_date: bankBalanceDate(value.as_of_date),
    declared_bank_closing: bankBalanceAmount(value.declared_bank_closing),
    ...(kind === 'report' ? { reason: reason() } : {}) }
}

function bankBody(payload: unknown, kind: 'account' | 'lines' | 'match' | 'reverse'): Record<string, unknown> {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) throw new Error('银行勾对参数无效')
  const value = payload as Record<string, unknown>
  if (kind === 'account') {
    const code = bankText(value.code, '银行账户编码', 32)
    if (!/^[A-Z0-9][A-Z0-9_-]{0,31}$/.test(code)) throw new Error('银行账户编码无效')
    return { code, name: bankText(value.name, '银行账户名称', 80) }
  }
  if (kind === 'reverse') return { reason: bankText(value.reason, '撤销原因', 200) }
  if (kind === 'match') {
    const statement_line_id = positiveId(value, 'statement_line_id')
    const source_id = positiveId(value, 'source_id')
    if (value.source_type !== 'order_payment' && value.source_type !== 'subledger_payment') throw new Error('收付款来源无效')
    return { statement_line_id, source_type: value.source_type, source_id, reason: bankText(value.reason, '勾对依据', 200) }
  }
  const account_id = positiveId(value, 'account_id')
  if (!Array.isArray(value.lines) || value.lines.length < 1 || value.lines.length > 500) throw new Error('银行流水明细无效')
  const lines = value.lines.map((entry: unknown) => {
    if (!entry || typeof entry !== 'object' || Array.isArray(entry)) throw new Error('银行流水明细无效')
    const row = entry as Record<string, unknown>
    const occurred_on = bankText(row.occurred_on, '银行交易日期', 10)
    if (!/^\d{4}-\d{2}-\d{2}$/.test(occurred_on) || Number.isNaN(Date.parse(`${occurred_on}T00:00:00Z`))) throw new Error('银行交易日期无效')
    const amount = bankText(row.amount, '银行金额', 20)
    if (!/^-?(?:0|[1-9]\d*)(?:\.\d{1,2})?$/.test(amount) || !Number.isFinite(Number(amount))
      || Number(amount) === 0 || Math.abs(Number(amount)) > 1_000_000_000_000) throw new Error('银行金额无效')
    return { transaction_id: bankText(row.transaction_id, '银行交易号', 100), occurred_on,
      amount, counterparty: bankText(row.counterparty, '对方户名', 120, false), note: bankText(row.note, '备注', 200, false) }
  })
  if (new Set(lines.map(line => line.transaction_id)).size !== lines.length) throw new Error('同批银行交易号不能重复')
  return { account_id, lines }
}

function customerImportNames(payload: unknown): string[] {
  const names = payload && typeof payload === 'object' && !Array.isArray(payload)
    ? (payload as Record<string, unknown>).names : undefined
  if (!Array.isArray(names) || names.length < 1 || names.length > 100
    || names.some(name => typeof name !== 'string' || !name.trim()
      || name.trim().length > 120 || /[\x00-\x1f]/.test(name))) {
    throw new Error('客户导入名单无效')
  }
  return names.map(name => (name as string).trim())
}

function contactImportRows(payload: unknown): ErpOperations['contactImportPreview']['input']['rows'] {
  const rows = payload && typeof payload === 'object' && !Array.isArray(payload)
    ? (payload as Record<string, unknown>).rows : undefined
  if (!Array.isArray(rows) || rows.length < 1 || rows.length > 100) throw new Error('联系人导入名单无效')
  return rows.map(row => {
    if (!row || typeof row !== 'object' || Array.isArray(row)) throw new Error('联系人导入明细无效')
    const source = row as Record<string, unknown>
    const field = (key: string, maximum: number, required = false): string => {
      const value = source[key]
      if (typeof value !== 'string' || value.trim().length > maximum || /[\x00-\x1f]/.test(value)
        || (required && !value.trim())) throw new Error('联系人导入明细无效')
      return value.trim()
    }
    return { customer_id: positiveId(row, 'customer_id'), name: field('name', 120, true),
      job_title: field('job_title', 120), phone: field('phone', 80),
      email: field('email', 160), note: field('note', 1000) }
  })
}

function opportunityImportRows(payload: unknown): ErpOperations['opportunityImportPreview']['input']['rows'] {
  const rows = payload && typeof payload === 'object' && !Array.isArray(payload)
    ? (payload as Record<string, unknown>).rows : undefined
  if (!Array.isArray(rows) || rows.length < 1 || rows.length > 100) throw new Error('商机导入名单无效')
  return rows.map(row => {
    if (!row || typeof row !== 'object' || Array.isArray(row)) throw new Error('商机导入明细无效')
    const source = row as Record<string, unknown>
    const text = (key: string, maximum: number, required = false): string => {
      const value = source[key]
      if (typeof value !== 'string' || value.trim().length > maximum || /[\x00-\x1f]/.test(value)
        || (required && !value.trim())) throw new Error('商机导入明细无效')
      return value.trim()
    }
    const estimated_amount = text('estimated_amount', 18, true)
    if (!/^\d+(?:\.\d{1,2})?$/.test(estimated_amount) || Number(estimated_amount) > 100_000_000_000)
      throw new Error('商机预估金额无效')
    const expected_close_date = text('expected_close_date', 10, true)
    if (!/^\d{4}-\d{2}-\d{2}$/.test(expected_close_date)) throw new Error('预计成交日期无效')
    return {customer_id: positiveId(row, 'customer_id'), title: text('title', 160, true),
      owner_id: positiveId(row, 'owner_id'), estimated_amount, expected_close_date,
      contact_id: source.contact_id == null ? null : positiveId(row, 'contact_id'),
      note: text('note', 1000)}
  })
}

function equipmentHours(value: unknown, maximum: number, allowZero: boolean): string {
  if (typeof value !== 'string' || !/^\d+(?:\.\d{1,2})?$/.test(value)
    || Number(value) > maximum || (!allowZero && Number(value) <= 0)) {
    throw new Error('运行小时须为范围内的精确十进制文本，最多两位小数')
  }
  return value
}

function maintenanceQuantity(value: unknown): string {
  if(typeof value!=='string' || !/^\d+(?:\.\d{1,3})?$/.test(value)
    || Number(value)<=0 || Number(value)>1_000_000)throw new Error('备件数量须为正数，最多三位小数')
  return value
}

function equipmentEvidence(value: unknown, label: string, maximum=200): string {
  if (typeof value !== 'string' || !value.trim() || value.trim().length > maximum)throw new Error(`${label}无效`)
  return value.trim()
}

function masterDataEdit(payload: unknown, warehouse: boolean): Record<string, string | number> {
  const source = payload && typeof payload === 'object' && !Array.isArray(payload)
    ? payload as Record<string, unknown> : {}
  const name = source.name
  const reason = source.reason
  if (typeof name !== 'string' || !name.trim() || name.trim().length > (warehouse ? 80 : 120)
    || typeof reason !== 'string' || !reason.trim() || reason.trim().length > 500) {
    throw new Error('档案名称或修改原因无效')
  }
  const body: Record<string, string | number> = { name: name.trim(), version: positiveId(payload, 'version'), reason: reason.trim() }
  if (warehouse) {
    if (typeof source.code !== 'string' || !/^[A-Za-z0-9_-]{1,40}$/.test(source.code)) throw new Error('仓库编码无效')
    body.code = source.code.toUpperCase()
  }
  return body
}

function roleCode(payload: unknown): string {
  // 自定义角色代码写入 URL 前先按服务端规则校验，避免路径注入。
  const code = payload && typeof payload === 'object' ? (payload as Record<string, unknown>).code : undefined
  if (typeof code !== 'string' || !/^[a-z][a-z0-9_]{2,39}$/.test(code)) throw new Error('角色代码无效')
  return code
}

function permissionCode(payload: unknown): string {
  // 仅把合法的固定权限代码放入请求路径，不接受页面提供的任意 URL 片段。
  const code = payload && typeof payload === 'object' ? (payload as Record<string, unknown>).code : undefined
  if (typeof code !== 'string' || code.length > 80 || !/^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$/.test(code)) {
    throw new Error('权限代码无效')
  }
  return code
}

function operation(action: keyof ErpOperations, payload: unknown): { method: string; path: string; body?: unknown } {
  // 明确列出可调用的接口，禁止页面拼接任意后端路径。
  switch (action) {
    case 'dashboard': {
      const period = payload && typeof payload === 'object' ? (payload as Record<string,unknown>).period : undefined
      if (period !== '7d' && period !== '30d') throw new Error('首页统计范围无效')
      return {method:'POST', path:'/api/v1/dashboard/query', body:{period}}
    }
    case 'setupStatus': return { method: 'GET', path: '/api/v1/setup/status' }
    case 'inventoryWarnings': {
      if(payload!==undefined && (!payload || typeof payload!=='object' || Array.isArray(payload)))throw new Error('预警查询范围无效')
      const source=payload as {warehouseId?:unknown}|undefined
      const warehouse=source?.warehouseId
      return {method:'GET',path:'/api/v1/inventory/warnings'+(warehouse===undefined?'':`?warehouse_id=${positiveId({id:warehouse},'id')}`)}
    }
    case 'inventoryWarningEvents': {
      if(payload!==undefined && (!payload || typeof payload!=='object' || Array.isArray(payload)))throw new Error('预警事件查询范围无效')
      const source=payload as {warehouseId?:unknown;beforeId?:unknown}|undefined
      const query:string[]=[]
      if(source?.warehouseId!==undefined)query.push(`warehouse_id=${positiveId({id:source.warehouseId},'id')}`)
      if(source?.beforeId!==undefined)query.push(`before_id=${positiveId({id:source.beforeId},'id')}`)
      return {method:'GET',path:'/api/v1/inventory/warnings/events'+(query.length?`?${query.join('&')}`:'')}
    }
    case 'physicalLotOverview':
    case 'physicalLotUnallocated': {
      if (!payload || typeof payload !== 'object' || Array.isArray(payload)) throw new Error('实物批次查询范围无效')
      const source = payload as Record<string, unknown>
      const parts: string[] = []
      if (source.warehouse_id !== null) parts.push(`warehouse_id=${positiveId({id: source.warehouse_id}, 'id')}`)
      if (source.material_id !== null) parts.push(`material_id=${positiveId({id: source.material_id}, 'id')}`)
      return {method: 'GET', path: '/api/v1/inventory/physical-lots/'
        + (action === 'physicalLotOverview' ? 'overview' : 'unallocated-movements')
        + (parts.length ? `?${parts.join('&')}` : '')}
    }
    case 'physicalLotHistory':
      return {method: 'GET', path: `/api/v1/inventory/physical-lots/${positiveId(payload, 'lot_id')}/history`}
    case 'physicalLotEvidence':
      return {method: 'POST', path: '/api/v1/inventory/physical-lots/reclassifications',
        body: physicalLotEvidenceBody(payload)}
    case 'physicalLotEvidenceReverse':
      return {method: 'POST',
        path: `/api/v1/inventory/physical-lots/reclassifications/${positiveId(payload, 'record_id')}/reverse`,
        body: physicalLotReverseBody(payload)}
    case 'physicalLotMovementEvidence':
      return {method: 'POST',
        path: `/api/v1/inventory/physical-lots/movements/${positiveId(payload,'movement_id')}/evidence`,
        body: physicalLotMovementEvidenceBody(payload)}
    case 'physicalLotMovementEvidenceReverse':
      return {method: 'POST',
        path: `/api/v1/inventory/physical-lots/movement-evidence/${positiveId(payload,'record_id')}/reverse`,
        body: physicalLotReverseBody(payload)}
    case 'physicalLotEvidencePair':
      return {method: 'POST', path: '/api/v1/inventory/physical-lots/evidence-pairs',
        body: physicalLotEvidencePairBody(payload)}
    case 'physicalLotEvidencePairReverse':
      return {method: 'POST',
        path: `/api/v1/inventory/physical-lots/evidence-pairs/${positiveId(payload,'record_id')}/reverse`,
        body: physicalLotReverseBody(payload)}
    case 'physicalLotEvidenceGroup':
      return {method: 'POST', path: '/api/v1/inventory/physical-lots/evidence-groups',
        body: physicalLotEvidenceGroupBody(payload)}
    case 'physicalLotEvidenceGroupReverse':
      return {method: 'POST',
        path: `/api/v1/inventory/physical-lots/evidence-groups/${positiveId(payload,'record_id')}/reverse`,
        body: physicalLotReverseBody(payload)}
    case 'inventoryWarningDetail':
    case 'saveInventoryWarning': {
      const warehouse=positiveId(payload,'warehouse_id'),material=positiveId(payload,'material_id')
      const path=`/api/v1/inventory/warnings/rules/${warehouse}/${material}`
      if(action==='inventoryWarningDetail')return {method:'GET',path}
      const source=payload as Record<string,unknown>
      if(typeof source.version!=='number' || !Number.isSafeInteger(source.version) || source.version<0)throw new Error('预警版本无效')
      if(typeof source.threshold!=='string' || !warningThresholdValid(source.threshold))throw new Error('预警阈值须为非负精确文本，最多三位小数且不超过一百万')
      if(typeof source.enabled!=='boolean')throw new Error('预警启停选择无效')
      if(typeof source.reason!=='string' || !source.reason.trim() || source.reason.trim().length>200)throw new Error('请填写预警修订原因，最多200字')
      return {method:'PUT',path,body:{version:source.version,threshold:source.threshold,enabled:source.enabled,reason:source.reason.trim()}}
    }
    case 'equipmentOverview': return {method:'GET',path:'/api/v1/equipment/overview'}
    case 'equipmentDetail': return {method:'GET',path:`/api/v1/equipment/assets/${positiveId(payload,'id')}`}
    case 'maintenancePlanDetail': return {method:'GET',path:`/api/v1/equipment/plans/${positiveId(payload,'id')}`}
    case 'maintenanceHourPlanDetail': return {method:'GET',path:`/api/v1/equipment/hour-plans/${positiveId(payload,'id')}`}
    case 'maintenanceJobDetail': return {method:'GET',path:`/api/v1/equipment/jobs/${positiveId(payload,'id')}`}
    case 'createMaintenancePurchaseRequest': {
      const source=payload as Record<string,unknown>
      if(!source || typeof source!=='object' || Array.isArray(source) || !Array.isArray(source.parts)
          || source.parts.length<1 || source.parts.length>100)throw new Error('维护采购明细无效')
      const parts=source.parts.map(row=>{
        if(!row || typeof row!=='object' || Array.isArray(row) || typeof row.quantity!=='string')throw new Error('备件数量须为精确字符串')
        return {material_id:positiveId(row,'material_id'),quantity:maintenanceQuantity(row.quantity)}
      })
      return {method:'POST',path:`/api/v1/equipment/jobs/${positiveId(source,'id')}/purchase-requests`,
        body:{version:positiveId(source,'version'),reason:equipmentEvidence(source.reason,'采购原因'),
          evidence:equipmentEvidence(source.evidence,'采购依据',600),parts}}
    }
    case 'recordEquipmentMeter': {
      const source=payload as Record<string,unknown>
      if(!source || typeof source!=='object' || Array.isArray(source) || typeof source.correction!=='boolean')throw new Error('设备读数无效')
      const previous=source.previous_reading_id==null?null:positiveId(source,'previous_reading_id')
      return {method:'POST',path:'/api/v1/equipment/meter-readings',body:{equipment_id:positiveId(source,'equipment_id'),
        hours:equipmentHours(source.hours,1_000_000_000,true),reference:equipmentEvidence(source.reference,'读数依据',100),
        reason:equipmentEvidence(source.reason,'读数原因'),previous_reading_id:previous,correction:source.correction}}
    }
    case 'saveEquipment':
    case 'saveMaintenancePlan':
    case 'saveMaintenanceHourPlan':
    case 'saveMaintenanceJob': {
      if(!payload || typeof payload!=='object' || Array.isArray(payload))throw new Error('设备维护资料无效')
      const source=payload as Record<string,unknown>
      const fields=action==='saveEquipment'?['code','name','serial_number','location','status','reason']
        :action==='saveMaintenancePlan'?['reference','title','interval_days','next_due','enabled','reason']
        :action==='saveMaintenanceHourPlan'?['reference','title','interval_hours','next_due_hours','enabled','reason']
        :['reference','kind','request_note','reason']
      const body:Record<string,unknown>=Object.fromEntries(fields.map(key=>[key,source[key]]))
      if(action==='saveEquipment' && !['active','inactive','retired'].includes(String(source.status)))throw new Error('设备状态无效')
      if(action!=='saveEquipment')body.equipment_id=positiveId(source,'equipment_id')
      if(action==='saveMaintenancePlan'){
        if(typeof source.enabled!=='boolean')throw new Error('计划启停选择无效')
        body.interval_days=positiveId(source,'interval_days')
      }
      if(action==='saveMaintenanceHourPlan'){
        if(typeof source.enabled!=='boolean')throw new Error('计划启停选择无效')
        body.interval_hours=equipmentHours(source.interval_hours,1_000_000,false)
        body.next_due_hours=equipmentHours(source.next_due_hours,1_000_000_000,true)
      }
      if(action==='saveMaintenanceJob'){
        if(!['preventive','corrective'].includes(String(source.kind)))throw new Error('维护方式无效')
        body.assigned_to=positiveId(source,'assigned_to')
        for(const key of ['plan_id','hour_plan_id','work_order_id','warehouse_id'])body[key]=source[key]==null?null:positiveId(source,key)
        if((source.kind==='preventive')!==(!!body.plan_id!==!!body.hour_plan_id))throw new Error('维护计划关联无效')
        if(!Array.isArray(source.parts) || source.parts.length>100)throw new Error('维护耗材明细无效')
        body.parts=source.parts.map(row=>{
          if(!row || typeof row!=='object' || typeof row.quantity!=='string')throw new Error('耗材数量须为精确字符串')
          return {material_id:positiveId(row,'material_id'),quantity:row.quantity}
        })
      }
      const edit=source.id!==undefined
      if(edit)body.version=positiveId(source,'version')
      const kind=action==='saveEquipment'?'assets':action==='saveMaintenancePlan'?'plans':action==='saveMaintenanceHourPlan'?'hour-plans':'jobs'
      return {method:edit?'PUT':'POST',path:`/api/v1/equipment/${kind}${edit?'/'+positiveId(source,'id'):''}`,body}
    }
    case 'changeMaintenanceJob': {
      const source=payload as ErpOperations['changeMaintenanceJob']['input']
      if(!source || !['submit','approve','reject','start','report','rework','accept','cancel','reverse'].includes(source.action))throw new Error('维护操作无效')
      const body:Record<string,unknown>={version:positiveId(source,'version'),reason:source.reason,evidence:source.evidence}
      if(source.action==='report'){
        if(typeof source.solution!=='string' || typeof source.labor_hours!=='string' || typeof source.service_amount!=='string')throw new Error('报工须明确填写结果、工时和费用')
        Object.assign(body,{solution:source.solution,labor_hours:source.labor_hours,service_amount:source.service_amount})
      }else if(['solution','labor_hours','service_amount'].some(key=>key in source))throw new Error('只有报工可以登记结果、工时和费用')
      return {method:'POST',path:`/api/v1/equipment/jobs/${positiveId(source,'id')}/${source.action}`,body}
    }
    case 'afterSalesOverview': return {method:'GET',path:'/api/v1/after-sales'}
    case 'afterSalesDetail': return {method:'GET',path:`/api/v1/after-sales/cases/${positiveId(payload,'id')}`}
    case 'afterSalesAttachments': return {method:'GET',path:`/api/v1/after-sales/cases/${positiveId(payload,'id')}/attachments`}
    case 'addAfterSalesAttachment': return {method:'POST',path:`/api/v1/after-sales/cases/${positiveId(payload,'id')}/attachments`,
      body:attachmentBody(payload)}
    case 'reverseAfterSalesAttachment': {
      const reason=bankText((payload as ErpOperations['reverseAfterSalesAttachment']['input']).reason,'撤销原因',200)
      return {method:'POST',path:`/api/v1/after-sales/cases/${positiveId(payload,'caseId')}/attachments/${positiveId(payload,'attachmentId')}/reverse`,
        body:{reason}}
    }
    case 'crmQuoteAttachments': return {method:'GET',path:`/api/v1/crm/quotes/${positiveId(payload,'id')}/attachments`}
    case 'addCrmQuoteAttachment': return {method:'POST',path:`/api/v1/crm/quotes/${positiveId(payload,'id')}/attachments`,
      body:attachmentBody(payload)}
    case 'reverseCrmQuoteAttachment': {
      const reason=bankText((payload as ErpOperations['reverseCrmQuoteAttachment']['input']).reason,'撤销原因',200)
      return {method:'POST',path:`/api/v1/crm/quotes/${positiveId(payload,'quoteId')}/attachments/${positiveId(payload,'attachmentId')}/reverse`,
        body:{reason}}
    }
    case 'crmRecordAttachments': return {method:'GET',path:`/api/v1/crm/records/${crmRecordKind((payload as ErpOperations['crmRecordAttachments']['input']).kind)}/${positiveId(payload,'id')}/attachments`}
    case 'addCrmRecordAttachment': return {method:'POST',path:`/api/v1/crm/records/${crmRecordKind((payload as ErpOperations['addCrmRecordAttachment']['input']).kind)}/${positiveId(payload,'id')}/attachments`,
      body:attachmentBody(payload)}
    case 'reverseCrmRecordAttachment': {
      const data=payload as ErpOperations['reverseCrmRecordAttachment']['input']
      const reason=bankText(data.reason,'撤销原因',200)
      return {method:'POST',path:`/api/v1/crm/records/${crmRecordKind(data.kind)}/${positiveId(payload,'id')}/attachments/${positiveId(payload,'attachmentId')}/reverse`,
        body:{reason}}
    }
    case 'equipmentAttachments': return {method:'GET',path:`/api/v1/equipment/${equipmentAttachmentKind((payload as ErpOperations['equipmentAttachments']['input']).kind)}/${positiveId(payload,'id')}/attachments`}
    case 'addEquipmentAttachment': return {method:'POST',path:`/api/v1/equipment/${equipmentAttachmentKind((payload as ErpOperations['addEquipmentAttachment']['input']).kind)}/${positiveId(payload,'id')}/attachments`,
      body:attachmentBody(payload)}
    case 'reverseEquipmentAttachment': {
      const data=payload as ErpOperations['reverseEquipmentAttachment']['input']
      const reason=bankText(data.reason,'撤销原因',200)
      return {method:'POST',path:`/api/v1/equipment/${equipmentAttachmentKind(data.kind)}/${positiveId(payload,'id')}/attachments/${positiveId(payload,'attachmentId')}/reverse`,
        body:{reason}}
    }
    case 'saveAfterSalesCase': {
      const source=payload as Record<string,unknown>
      if(!source || typeof source!=='object' || !['return','exchange','repair'].includes(String(source.kind))
        || !['none','free','charge'].includes(String(source.charge_mode)))throw new Error('售后方式或收费选择无效')
      if(!Array.isArray(source.parts) || source.parts.length>100)throw new Error('维修耗材明细无效')
      const body:Record<string,unknown>=Object.fromEntries(['reference','kind','quantity','complaint','solution',
        'charge_mode','fee_amount','customer_acceptance','replacement_quantity','replacement_unit_price','reason'].map(key=>[key,source[key]]))
      if(source.warranty_days!=null && (typeof source.warranty_days!=='number' || !Number.isInteger(source.warranty_days)
        || source.warranty_days<1 || source.warranty_days>36500))
        throw new Error('保修天数无效')
      const warrantyBasis=source.warranty_basis??''
      if(typeof warrantyBasis!=='string' || warrantyBasis.length>400)throw new Error('保修依据无效')
      body.warranty_days=source.warranty_days??null
      body.warranty_basis=warrantyBasis
      body.shipment_line_id=positiveId(source,'shipment_line_id')
      body.warehouse_id=source.warehouse_id==null?null:positiveId(source,'warehouse_id')
      body.replacement_material_id=source.replacement_material_id==null?null:positiveId(source,'replacement_material_id')
      body.parts=source.parts.map(row=>({material_id:positiveId(row,'material_id'),quantity:row.quantity}))
      const edit=source.id!==undefined
      if(edit)body.version=positiveId(source,'version')
      return {method:edit?'PUT':'POST',path:`/api/v1/after-sales/cases${edit?'/'+positiveId(source,'id'):''}`,body}
    }
    case 'changeAfterSalesCase': {
      const source=payload as ErpOperations['changeAfterSalesCase']['input']
      if(!source || !['submit','approve','reject','process','receive','inspect','close','cancel','reverse'].includes(source.action))throw new Error('售后操作无效')
      if(source.inspection_result!=null && !['pass','fail'].includes(source.inspection_result))throw new Error('维修检验结果无效')
      return {method:'POST',path:`/api/v1/after-sales/cases/${positiveId(source,'id')}/${source.action}`,
        body:{version:positiveId(source,'version'),reason:source.reason,evidence:source.evidence,inspection_result:source.inspection_result??null}}
    }
    case 'assessAfterSalesResponsibility': {
      const source=payload as ErpOperations['assessAfterSalesResponsibility']['input']
      if(!source || !['company','customer','third_party','undetermined'].includes(source.outcome))throw new Error('责任核定结果无效')
      return {method:'POST',path:`/api/v1/after-sales/cases/${positiveId(source,'id')}/responsibility`,
        body:{version:positiveId(source,'version'),outcome:source.outcome,
          basis:bankText(source.basis,'责任依据',400),reason:bankText(source.reason,'核定原因',200)}}
    }
    case 'recordAfterSalesLabor': {
      const source=payload as ErpOperations['recordAfterSalesLabor']['input']
      if(!source || typeof source.hours!=='string' || !/^(?:0|[1-9]\d*)(?:\.\d{1,2})?$/.test(source.hours)
        || Number(source.hours)<=0 || Number(source.hours)>100000)throw new Error('维修工时无效')
      return {method:'POST',path:`/api/v1/after-sales/cases/${positiveId(source,'id')}/labor`,
        body:{version:positiveId(source,'version'),hours:source.hours,reason:source.reason,evidence:source.evidence}}
    }
    case 'reverseAfterSalesLabor': {
      const source=payload as ErpOperations['reverseAfterSalesLabor']['input']
      if(!source)throw new Error('维修工时记录无效')
      return {method:'POST',path:`/api/v1/after-sales/cases/${positiveId(source,'id')}/labor/${positiveId(source,'entry_id')}/reverse`,
        body:{version:positiveId(source,'version'),reason:source.reason,evidence:source.evidence}}
    }
    case 'afterSalesLaborCost': return {method:'GET',path:`/api/v1/after-sales/cases/${positiveId(payload,'id')}/labor-cost`}
    case 'afterSalesRepairMargin': return {method:'GET',path:`/api/v1/after-sales/cases/${positiveId(payload,'id')}/repair-margin`}
    case 'valueAfterSalesLaborCost': {
      const source=payload as ErpOperations['valueAfterSalesLaborCost']['input']
      if(!source || (source.hourly_rate!==null && (typeof source.hourly_rate!=='string' ||
        !/^(?:0|[1-9]\d*)(?:\.\d{1,2})?$/.test(source.hourly_rate) ||
        Number(source.hourly_rate)<=0 || Number(source.hourly_rate)>100000)))throw new Error('内部小时成本无效')
      return {method:'POST',path:`/api/v1/after-sales/cases/${positiveId(source,'id')}/labor-cost/${positiveId(source,'entry_id')}`,
        body:{version:positiveId(source,'version'),hourly_rate:source.hourly_rate,
          reason:bankText(source.reason,'核价原因',200),evidence:bankText(source.evidence,'核价依据',400)}}
    }
    case 'qualityOverview': return { method:'GET', path:'/api/v1/production-quality' }
    case 'qualityDetail': return { method:'GET', path:`/api/v1/production-quality/dispositions/${positiveId(payload,'id')}` }
    case 'saveQualityDisposition': {
      const source = payload as Record<string, unknown>
      if (!source || typeof source !== 'object' || !['scrap','rework'].includes(String(source.kind))
        || !['absorb','expense','carry'].includes(String(source.loss_treatment))) throw new Error('处置方式或成本处理无效')
      if (!Array.isArray(source.materials) || source.materials.length > 100) throw new Error('返工材料明细无效')
      const body: Record<string, unknown> = Object.fromEntries(['reference','kind','quantity','loss_treatment','defect','action_note','reason'].map(key=>[key,source[key]]))
      body.completion_id = positiveId(source,'completion_id')
      body.warehouse_id = source.warehouse_id == null ? null : positiveId(source,'warehouse_id')
      body.materials = source.materials.map(row=>({material_id:positiveId(row,'material_id'),quantity:row.quantity}))
      const edit = source.id !== undefined
      if (edit) body.version = positiveId(source,'version')
      return {method:edit?'PUT':'POST',path:`/api/v1/production-quality/dispositions${edit?'/'+positiveId(source,'id'):''}`,body}
    }
    case 'changeQualityDisposition': {
      const source = payload as ErpOperations['changeQualityDisposition']['input']
      if (!source || !['submit','approve','reject','post','cancel','reverse'].includes(source.action)) throw new Error('不允许的质量处置操作')
      return {method:'POST',path:`/api/v1/production-quality/dispositions/${positiveId(source,'id')}/${source.action}`,
        body:{version:positiveId(source,'version'),reason:source.reason}}
    }
    case 'crmOptions': return { method: 'GET', path: '/api/v1/crm/options' }
    case 'crmOverview': return { method: 'GET', path: '/api/v1/crm/overview' }
    case 'crmForecast': return { method: 'GET', path: '/api/v1/crm/forecast' }
    case 'contactImportPreview': return { method: 'POST', path: '/api/v1/crm/contacts/import-preview',
      body: { rows: contactImportRows(payload) } }
    case 'importContacts': {
      const rows = contactImportRows(payload)
      const source = payload as Record<string, unknown>
      if (typeof source.reason !== 'string' || !source.reason.trim() || source.reason.trim().length > 200
        || typeof source.allow_similar !== 'boolean') throw new Error('联系人导入依据或同名确认无效')
      return { method: 'POST', path: '/api/v1/crm/contacts/import',
        body: { rows, reason: source.reason.trim(), allow_similar: source.allow_similar } }
    }
    case 'opportunityImportPreview': return { method: 'POST', path: '/api/v1/crm/opportunities/import-preview',
      body: { rows: opportunityImportRows(payload) } }
    case 'importOpportunities': {
      const rows = opportunityImportRows(payload)
      const source = payload as Record<string, unknown>
      if (typeof source.reason !== 'string' || !source.reason.trim() || source.reason.trim().length > 200
        || typeof source.allow_similar !== 'boolean') throw new Error('商机导入依据或同名确认无效')
      return { method: 'POST', path: '/api/v1/crm/opportunities/import',
        body: { rows, reason: source.reason.trim(), allow_similar: source.allow_similar } }
    }
    case 'customerOwnerChanges': return { method: 'GET', path: `/api/v1/customers/${positiveId(payload,'id')}/owner-changes` }
    case 'assignCustomerOwner': {
      const source=payload as ErpOperations['assignCustomerOwner']['input']
      return {method:'PUT',path:`/api/v1/customers/${positiveId(payload,'id')}/owner`,
        body:{owner_id:positiveId(payload,'owner_id'),version:positiveId(payload,'version'),reason:source.reason}}
    }
    case 'crmDetail':
    case 'crmChanges': {
      const { kind } = payload as ErpOperations['crmDetail']['input']
      if (!['contact','activity','opportunity','quote'].includes(kind)) throw new Error('客户关系类型无效')
      return { method: 'GET', path: `/api/v1/crm/records/${kind}/${positiveId(payload,'id')}${action==='crmChanges' ? '/changes' : ''}` }
    }
    case 'saveCrmContact':
    case 'saveCrmOpportunity':
    case 'createCrmActivity':
    case 'saveCrmQuote': {
      const source = payload as Record<string, unknown>
      const fields = action==='saveCrmContact' ? ['customer_id','name','job_title','phone','email','note','is_active']
        : action==='saveCrmOpportunity' ? ['customer_id','contact_id','title','owner_id','stage','estimated_amount','probability_percent','expected_close_date','note']
        : action==='createCrmActivity' ? ['customer_id','contact_id','opportunity_id','subject','owner_id','due_date','note']
        : ['opportunity_id','contact_id','reference','valid_until','terms']
      const body: Record<string, unknown> = Object.fromEntries(fields.map(key=>[key,source[key]]))
      for (const field of ['customer_id','owner_id','opportunity_id','contact_id']) {
        if (fields.includes(field) && (source[field] != null || ['customer_id','owner_id'].includes(field))) body[field]=positiveId(payload,field)
      }
      if (action==='saveCrmOpportunity' && source.probability_percent !== undefined) {
        if (source.probability_percent !== null && (!Number.isSafeInteger(source.probability_percent)
          || (source.probability_percent as number) < 0 || (source.probability_percent as number) > 100)) throw new Error('成交概率须为 0 至 100 的整数')
      }
      if (action==='saveCrmQuote') {
        if (!Array.isArray(source.lines) || source.lines.length < 1 || source.lines.length > 100) throw new Error('报价明细无效')
        body.lines = source.lines.map(row=>({ material_id: positiveId(row,'material_id'), quantity: row.quantity, unit_price: row.unit_price }))
      }
      const resource = action==='saveCrmContact' ? 'contacts' : action==='saveCrmOpportunity' ? 'opportunities' : action==='createCrmActivity' ? 'activities' : 'quotes'
      const edit = action !== 'createCrmActivity' && source.id !== undefined
      if (edit) { body.version = positiveId(payload,'version'); body.reason = source.reason }
      return { method: edit ? 'PUT' : 'POST', path: `/api/v1/crm/${resource}${edit ? '/'+positiveId(payload,'id') : ''}`, body }
    }
    case 'closeCrmActivity':
    case 'changeCrmQuote':
    case 'reopenCrmOpportunity':
    case 'convertCrmQuote': {
      const source = payload as Record<string, unknown>
      const command = action==='reopenCrmOpportunity' ? 'reopen' : action==='convertCrmQuote' ? 'convert' : source.action
      const allowed = action==='closeCrmActivity' ? ['complete','cancel'] : action==='changeCrmQuote' ? ['submit','approve','reject','cancel'] : ['reopen','convert']
      if (typeof command !== 'string' || !allowed.includes(command)) throw new Error('不允许的客户关系操作')
      const body: Record<string, unknown> = { version: positiveId(payload,'version'), reason: source.reason }
      if (action==='convertCrmQuote') {
        body.opportunity_version=positiveId(payload,'opportunity_version');body.acceptance_reference=source.acceptance_reference
      }
      const resource = action==='closeCrmActivity' ? 'activities' : action==='reopenCrmOpportunity' ? 'opportunities' : 'quotes'
      return { method:'POST',path:`/api/v1/crm/${resource}/${positiveId(payload,'id')}/${command}`,body }
    }
    case 'mrpOptions': return { method: 'GET', path: '/api/v1/production/mrp/options' }
    case 'mrpPlans': return { method: 'GET', path: '/api/v1/production/mrp/plans' }
    case 'mrpDetail': return { method: 'GET', path: `/api/v1/production/mrp/plans/${positiveId(payload, 'id')}` }
    case 'mrpCheck': return { method: 'GET', path: `/api/v1/production/mrp/plans/${positiveId(payload, 'id')}/check` }
    case 'mrpChanges': return { method: 'GET', path: `/api/v1/production/mrp/plans/${positiveId(payload, 'id')}/changes` }
    case 'mrpPolicyChanges': return { method: 'GET', path: `/api/v1/production/mrp/policies/${positiveId(payload, 'id')}/changes` }
    case 'saveMrpPolicy': {
      const { version, supply_mode, lead_time_days, safety_stock, minimum_quantity, multiple_quantity, reason } = payload as ErpOperations['saveMrpPolicy']['input']
      if (!Number.isSafeInteger(version) || version < 0 || !Number.isSafeInteger(lead_time_days)
        || lead_time_days < 0 || lead_time_days > 365 || !['auto','buy','make'].includes(supply_mode)) throw new Error('计划参数无效')
      return { method: 'PUT', path: `/api/v1/production/mrp/policies/${positiveId(payload, 'id')}`,
        body: { version, supply_mode, lead_time_days, safety_stock, minimum_quantity, multiple_quantity, reason } }
    }
    case 'createMrpPlan': {
      const { reference, start_date, demand_dates, supply_dates, manual_demands, reason } = payload as ErpOperations['createMrpPlan']['input']
      if (!Array.isArray(demand_dates) || demand_dates.length > 2000 || !Array.isArray(supply_dates) || supply_dates.length > 2000
        || !Array.isArray(manual_demands) || manual_demands.length > 500) throw new Error('计划来源明细无效')
      return { method: 'POST', path: '/api/v1/production/mrp/plans', body: { reference, start_date, reason,
        demand_dates: demand_dates.map(({ key, due_date }) => ({ key, due_date })),
        supply_dates: supply_dates.map(({ key, due_date }) => ({ key, due_date })),
        manual_demands: manual_demands.map(row => ({ material_id: positiveId(row, 'material_id'),
          quantity: row.quantity, due_date: row.due_date, reference: row.reference })) } }
    }
    case 'changeMrpStatus': {
      const { action: command, reason } = payload as ErpOperations['changeMrpStatus']['input']
      if (!['submit','approve','reject','cancel'].includes(command)) throw new Error('不允许的计划状态操作')
      return { method: 'POST', path: `/api/v1/production/mrp/plans/${positiveId(payload, 'id')}/${command}`,
        body: { version: positiveId(payload, 'version'), reason } }
    }
    case 'convertMrpSuggestion': {
      const { suggestion_key, warehouse_id, reference, reason } = payload as ErpOperations['convertMrpSuggestion']['input']
      return { method: 'POST', path: `/api/v1/production/mrp/plans/${positiveId(payload, 'id')}/convert`,
        body: { version: positiveId(payload, 'version'), suggestion_key,
          warehouse_id: warehouse_id == null ? null : positiveId(payload, 'warehouse_id'), reference, reason } }
    }
    case 'bootstrap': return { method: 'POST', path: '/api/v1/setup/admin', body: payload }
    case 'login': return { method: 'POST', path: '/api/v1/auth/login', body: payload }
    case 'logout': return { method: 'POST', path: '/api/v1/auth/logout' }
    case 'me': return { method: 'GET', path: '/api/v1/auth/me' }
    case 'changePassword': return { method: 'POST', path: '/api/v1/auth/change-password', body: payload }
    // 使用固定地址，菜单标识和图标由服务端白名单再次校验。
    case 'menuIcons': return { method: 'GET', path: '/api/v1/menu-icons' }
    case 'saveMenuIcon': return { method: 'PUT', path: '/api/v1/menu-icons', body: payload }
    case 'permissions': return { method: 'GET', path: '/api/v1/permissions' }
    case 'updatePermissionLabel': return {
      method: 'PUT', path: `/api/v1/permissions/${permissionCode(payload)}/label`,
      body: { label: (payload as { label: unknown }).label }
    }
    case 'roles': return { method: 'GET', path: '/api/v1/roles' }
    case 'createRole': return { method: 'POST', path: '/api/v1/roles', body: payload }
    case 'updateRole': return {
      method: 'PUT', path: `/api/v1/roles/${roleCode(payload)}`,
      body: { label: (payload as { label: unknown }).label, permissions: (payload as { permissions: unknown }).permissions }
    }
    case 'users': return { method: 'GET', path: '/api/v1/users' }
    case 'createUser': return { method: 'POST', path: '/api/v1/users', body: payload }
    // 路径只能使用经过校验的用户编号，业务字段由后端再次校验。
    case 'updateUser': return { method: 'PUT', path: `/api/v1/users/${positiveId(payload, 'userId')}`, body: payload }
    case 'setUserRoles': return {
      method: 'PUT', path: `/api/v1/users/${positiveId(payload, 'userId')}/roles`,
      body: { roles: (payload as { roles: unknown }).roles }
    }
    case 'setUserStatus': return {
      method: 'PUT', path: `/api/v1/users/${positiveId(payload, 'userId')}/status`,
      body: { is_active: (payload as { is_active: unknown }).is_active }
    }
    case 'resetUserPassword': return {
      method: 'POST', path: `/api/v1/users/${positiveId(payload, 'userId')}/reset-password`,
      body: { password: (payload as { password: unknown }).password }
    }
    case 'updateMaterial': return { method: 'PUT', path: `/api/v1/materials/${positiveId(payload, 'id')}`, body: materialBody(payload, true) }
    case 'deleteMaterial': return { method: 'DELETE', path: `/api/v1/materials/${positiveId(payload, 'id')}` }
    case 'supplierDetail': return { method: 'GET', path: `/api/v1/suppliers/${positiveId(payload, 'id')}` }
    case 'supplierChanges': return { method: 'GET', path: `/api/v1/suppliers/${positiveId(payload, 'id')}/changes` }
    case 'recentSupplierChanges': return { method: 'GET', path: `/api/v1/supplier-changes${payload && typeof payload==='object' && 'before_id' in payload ? '?before_id='+positiveId(payload,'before_id') : ''}` }
    case 'updateSupplier': return { method: 'PUT', path: `/api/v1/suppliers/${positiveId(payload, 'id')}`, body: masterDataEdit(payload, false) }
    case 'deleteSupplier': return { method: 'DELETE', path: `/api/v1/suppliers/${positiveId(payload, 'id')}?version=${positiveId(payload, 'version')}` }
    case 'warehouseDetail': return { method: 'GET', path: `/api/v1/warehouses/${positiveId(payload, 'id')}` }
    case 'warehouseChanges': return { method: 'GET', path: `/api/v1/warehouses/${positiveId(payload, 'id')}/changes` }
    case 'recentWarehouseChanges': return { method: 'GET', path: `/api/v1/warehouse-changes${payload && typeof payload==='object' && 'before_id' in payload ? '?before_id='+positiveId(payload,'before_id') : ''}` }
    case 'updateWarehouse': return { method: 'PUT', path: `/api/v1/warehouses/${positiveId(payload, 'id')}`, body: masterDataEdit(payload, true) }
    case 'deleteWarehouse': return { method: 'DELETE', path: `/api/v1/warehouses/${positiveId(payload, 'id')}?version=${positiveId(payload, 'version')}` }
    // 只允许固定分类目录地址，客户端不能指定外部资源。
    case 'materialCategories': return { method: 'GET', path: '/api/v1/material-categories' }
    case 'materialDetail': return { method: 'GET', path: `/api/v1/materials/${positiveId(payload, 'id')}` }
    case 'supplierMaterials': return { method: 'GET', path: '/api/v1/supplier-materials' }
    case 'bindSupplierMaterial': return { method: 'PUT', path: `/api/v1/suppliers/${positiveId(payload, 'supplierId')}/materials/${positiveId(payload, 'materialId')}` }
    case 'unbindSupplierMaterial': return { method: 'DELETE', path: `/api/v1/suppliers/${positiveId(payload, 'supplierId')}/materials/${positiveId(payload, 'materialId')}` }
    // 分页搜索经由受限 IPC 转发，权限和参数范围由服务端再次校验。
    case 'querySuppliers': return { method: 'POST', path: '/api/v1/suppliers/query', body: payload }
    case 'suppliers': return { method: 'GET', path: '/api/v1/suppliers' }
    case 'createSupplier': return { method: 'POST', path: '/api/v1/suppliers', body: payload }
    case 'customers': return { method: 'GET', path: '/api/v1/customers' }
    case 'customerDuplicateCandidates': {
      const name = payload && typeof payload === 'object' && !Array.isArray(payload)
        ? (payload as Record<string, unknown>).name : undefined
      if (typeof name !== 'string' || !name.trim() || name.trim().length > 120) throw new Error('客户名称无效')
      return { method: 'POST', path: '/api/v1/customers/duplicate-candidates', body: { name: name.trim() } }
    }
    case 'customerImportPreview': return { method: 'POST', path: '/api/v1/customers/import-preview',
      body: { names: customerImportNames(payload) } }
    case 'importCustomers': {
      const names = customerImportNames(payload)
      const source = payload as Record<string, unknown>
      if (typeof source.reason !== 'string' || !source.reason.trim() || source.reason.trim().length > 200
        || typeof source.allow_similar !== 'boolean') throw new Error('客户导入依据或相似名称确认无效')
      return { method: 'POST', path: '/api/v1/customers/import',
        body: { names, reason: source.reason.trim(), allow_similar: source.allow_similar } }
    }
    case 'createCustomer': return { method: 'POST', path: '/api/v1/customers', body: payload }
    case 'materials': return { method: 'GET', path: '/api/v1/materials' }
    case 'createMaterial': return { method: 'POST', path: '/api/v1/materials', body: materialBody(payload, false) }
    case 'warehouses': return { method: 'GET', path: '/api/v1/warehouses' }
    case 'otherInbounds': return { method: 'GET', path: '/api/v1/warehouse-inbounds' }
    case 'createOtherInbound': return { method: 'POST', path: '/api/v1/warehouse-inbounds', body: payload }
    case 'postOtherInbound': {
      const inboundId = positiveId(payload, 'inboundId')
      const source = payload as ErpOperations['postOtherInbound']['input']
      return {method: 'POST', path: `/api/v1/warehouse-inbounds/${inboundId}/post`,
        ...(source.lines === undefined ? {} : {body: inboundLotBody({lines: source.lines})})}
    }
    case 'cancelOtherInbound': return { method: 'POST', path: `/api/v1/warehouse-inbounds/${positiveId(payload, 'inboundId')}/cancel` }
    case 'reverseOtherInbound': {
      const inboundId = positiveId(payload, 'inboundId')
      const fields = payload as ErpOperations['reverseOtherInbound']['input']
      return { method: 'POST', path: `/api/v1/warehouse-inbounds/${inboundId}/reverse`, body: { reason: fields.reason } }
    }
    case 'warehouseOutbounds': return { method: 'GET', path: '/api/v1/warehouse-outbounds' }
    case 'createOtherOutbound': return { method: 'POST', path: '/api/v1/warehouse-outbounds', body: payload }
    case 'availableOutboundLots': return {method: 'GET',
      path: `/api/v1/warehouse-outbounds/${positiveId(payload, 'outboundId')}/available-lots`}
    case 'postWarehouseOutbound': {
      const outboundId = positiveId(payload, 'outboundId')
      const source = payload as ErpOperations['postWarehouseOutbound']['input']
      return {method: 'POST', path: `/api/v1/warehouse-outbounds/${outboundId}/post`,
        ...(source.lines === undefined ? {} : {body: outboundLotBody({lines: source.lines})})}
    }
    case 'cancelOtherOutbound': return { method: 'POST', path: `/api/v1/warehouse-outbounds/${positiveId(payload, 'outboundId')}/cancel` }
    case 'reverseOtherOutbound': {
      const outboundId = positiveId(payload, 'outboundId')
      const fields = payload as ErpOperations['reverseOtherOutbound']['input']
      return { method: 'POST', path: `/api/v1/warehouse-outbounds/${outboundId}/reverse`, body: { reason: fields.reason } }
    }
    case 'stockAdjustments': return { method: 'GET', path: '/api/v1/stock-adjustments' }
    case 'createStockAdjustment': return { method: 'POST', path: '/api/v1/stock-adjustments', body: payload }
    case 'submitStockAdjustment': return { method: 'POST', path: `/api/v1/stock-adjustments/${positiveId(payload, 'adjustmentId')}/submit` }
    case 'approveStockAdjustment': return { method: 'POST', path: `/api/v1/stock-adjustments/${positiveId(payload, 'adjustmentId')}/approve` }
    case 'rejectStockAdjustment': {
      const adjustmentId = positiveId(payload, 'adjustmentId')
      const fields = payload as ErpOperations['rejectStockAdjustment']['input']
      return { method: 'POST', path: `/api/v1/stock-adjustments/${adjustmentId}/reject`, body: { reason: fields.reason } }
    }
    case 'cancelStockAdjustment': return { method: 'POST', path: `/api/v1/stock-adjustments/${positiveId(payload, 'adjustmentId')}/cancel` }
    case 'availableAdjustmentLots': return {method: 'GET',
      path: `/api/v1/stock-adjustments/${positiveId(payload, 'adjustmentId')}/available-lots`}
    case 'postStockAdjustment': {
      const adjustmentId = positiveId(payload, 'adjustmentId')
      const source = payload as ErpOperations['postStockAdjustment']['input']
      return {method: 'POST', path: `/api/v1/stock-adjustments/${adjustmentId}/post`,
        ...(source.lines === undefined ? {} : {body: adjustmentLotBody({lines: source.lines})})}
    }
    case 'reverseStockAdjustment': {
      const adjustmentId = positiveId(payload, 'adjustmentId')
      const fields = payload as ErpOperations['reverseStockAdjustment']['input']
      return { method: 'POST', path: `/api/v1/stock-adjustments/${adjustmentId}/reverse`, body: { reason: fields.reason } }
    }
    case 'createWarehouse': return { method: 'POST', path: '/api/v1/warehouses', body: payload }
    case 'receipts': return { method: 'GET', path: '/api/v1/receipts' }
    case 'goodsReceipts': return { method: 'GET', path: '/api/v1/purchase-goods-receipts' }
    case 'createGoodsReceipt': return { method: 'POST', path: '/api/v1/purchase-goods-receipts', body: payload }
    case 'confirmGoodsReceipt': return { method: 'POST', path: `/api/v1/purchase-goods-receipts/${positiveId(payload, 'goodsReceiptId')}/confirm` }
    case 'cancelGoodsReceipt': return { method: 'POST', path: `/api/v1/purchase-goods-receipts/${positiveId(payload, 'goodsReceiptId')}/cancel` }
    case 'createReceipt': return { method: 'POST', path: '/api/v1/receipts', body: payload }
    case 'postReceipt': {
      const receiptId = positiveId(payload, 'receiptId')
      const source = payload as ErpOperations['postReceipt']['input']
      return {method: 'POST', path: `/api/v1/receipts/${receiptId}/post`,
        ...(source.lines === undefined ? {} : {body: receiptLotBody({lines: source.lines})})}
    }
    case 'reverseReceipt': {
      const receiptId = positiveId(payload, 'receiptId')
      const fields = payload as ErpOperations['reverseReceipt']['input']
      return { method: 'POST', path: `/api/v1/receipts/${receiptId}/reverse`, body: { reason: fields.reason } }
    }
    // 采购退货单编号只能通过正整数校验后进入固定路径。
    case 'purchaseReturns': return { method: 'GET', path: '/api/v1/purchase-returns' }
    case 'receivablesPayables': return { method: 'GET', path: '/api/v1/finance/receivables-payables' }
    case 'financeOverview': return { method: 'GET', path: '/api/v1/finance/overview' }
    case 'inventoryValuation': return { method: 'GET', path: '/api/v1/inventory/valuation' }
    case 'inventoryCostInputs': return { method: 'GET', path: '/api/v1/inventory/valuation/inputs' }
    case 'recordInventoryCost': return { method: 'POST', path: '/api/v1/inventory/valuation/inputs', body: payload }
    case 'financeAccounts': return { method: 'GET', path: '/api/v1/finance/accounts' }
    case 'ledgerAccounts': return { method: 'GET', path: '/api/v1/finance/ledger-accounts' }
    case 'createLedgerAccount': return { method: 'POST', path: '/api/v1/finance/ledger-accounts', body: payload }
    case 'ledgerAccountChanges': return { method: 'GET', path: `/api/v1/finance/ledger-accounts/${positiveId(payload, 'id')}/changes` }
    case 'updateLedgerAccount': {
      const id = positiveId(payload, 'id')
      const fields = payload as ErpOperations['updateLedgerAccount']['input']
      return { method: 'PUT', path: `/api/v1/finance/ledger-accounts/${id}`,
        body: { name: fields.name, is_active: fields.is_active, version: fields.version, reason: fields.reason } }
    }
    case 'accountingPeriods': return { method: 'GET', path: '/api/v1/finance/accounting-periods' }
    case 'createAccountingPeriod': return { method: 'POST', path: '/api/v1/finance/accounting-periods', body: payload }
    case 'accountingPeriodChanges': return { method: 'GET', path: `/api/v1/finance/accounting-periods/${positiveId(payload, 'id')}/changes` }
    case 'periodClosingCheck': return { method: 'GET', path: `/api/v1/finance/accounting-periods/${positiveId(payload, 'id')}/closing-check` }
    case 'periodClosingHistory': return { method: 'GET', path: `/api/v1/finance/accounting-periods/${positiveId(payload, 'id')}/closings` }
    case 'changePeriodClosingStatus': {
      const id = positiveId(payload, 'id')
      const fields = payload as ErpOperations['changePeriodClosingStatus']['input']
      if (!['close', 'reopen'].includes(fields.action)) throw new Error('结账操作无效。')
      return { method: 'POST', path: `/api/v1/finance/accounting-periods/${id}/${fields.action}`,
        body: { version: fields.version, reason: fields.reason } }
    }
    case 'updateAccountingPeriod': {
      const id = positiveId(payload, 'id')
      const fields = payload as ErpOperations['updateAccountingPeriod']['input']
      return { method: 'PUT', path: `/api/v1/finance/accounting-periods/${id}`,
        body: { name: fields.name, version: fields.version, reason: fields.reason } }
    }
    case 'journals': return { method: 'GET', path: '/api/v1/finance/journals' }
    case 'businessJournalSources': return { method: 'GET', path: '/api/v1/finance/business-journals' }
    case 'auxiliaryOptions': return { method: 'GET', path: '/api/v1/finance/auxiliary/options' }
    case 'auxiliaryChanges': return { method: 'GET', path: '/api/v1/finance/auxiliary/changes' }
    case 'createAuxiliaryItem': {
      const { kind, code, name, reason } = payload as ErpOperations['createAuxiliaryItem']['input']
      return { method: 'POST', path: '/api/v1/finance/auxiliary/items', body: { kind, code, name, reason } }
    }
    case 'updateAuxiliaryItem': {
      const { version, name, is_active, reason } = payload as ErpOperations['updateAuxiliaryItem']['input']
      return { method: 'PUT', path: `/api/v1/finance/auxiliary/items/${positiveId(payload, 'id')}`, body: { version, name, is_active, reason } }
    }
    case 'saveAuxiliaryPolicy': {
      const { version, start_date, required_kinds, reason } = payload as ErpOperations['saveAuxiliaryPolicy']['input']
      return { method: 'PUT', path: `/api/v1/finance/auxiliary/policies/${positiveId(payload, 'account_id')}`, body: { version, start_date, required_kinds, reason } }
    }
    case 'queryAuxiliary': {
      const { account_id, kind, from_date, to_date, entity_id } = payload as ErpOperations['queryAuxiliary']['input']
      return { method: 'POST', path: '/api/v1/finance/auxiliary/query', body: { account_id, kind, from_date, to_date, entity_id } }
    }
    case 'profitTransferOptions': return { method: 'GET', path: '/api/v1/finance/profit-transfers/policy' }
    case 'statementOptions': return { method: 'GET', path: '/api/v1/finance/statements/options' }
    case 'statementPolicyChanges': return { method: 'GET', path: '/api/v1/finance/statements/policy/changes' }
    case 'statementArchives': return { method: 'GET', path: '/api/v1/finance/statements/archives' }
    case 'statementArchiveDetail': return { method: 'GET', path: `/api/v1/finance/statements/archives/${positiveId(payload, 'id')}` }
    case 'saveStatementPolicy': {
      const { version, lines, allocations, manual_transfer_ids, reason } = payload as ErpOperations['saveStatementPolicy']['input']
      if (!Array.isArray(lines) || !Array.isArray(allocations) || !Array.isArray(manual_transfer_ids)) throw new Error('报表配置列表无效。')
      return { method: 'PUT', path: '/api/v1/finance/statements/policy', body: { version, reason, manual_transfer_ids,
        lines: lines.map(({ code, name, group }) => ({ code, name, group })),
        allocations: allocations.map(({ account_id, line_code }) => ({ account_id, line_code })) } }
    }
    case 'queryStatement': {
      const { from_date, to_date } = payload as ErpOperations['queryStatement']['input']
      return { method: 'POST', path: '/api/v1/finance/statements/query', body: { from_date, to_date } }
    }
    case 'archiveStatement': {
      const { from_date, to_date, policy_version, fingerprint, reason } = payload as ErpOperations['archiveStatement']['input']
      return { method: 'POST', path: '/api/v1/finance/statements/archive', body: { from_date, to_date, policy_version, fingerprint, reason } }
    }
    case 'profitTransferPolicyChanges': return { method: 'GET', path: '/api/v1/finance/profit-transfers/policy/changes' }
    case 'profitTransferPreview': return { method: 'GET', path: `/api/v1/finance/profit-transfers/periods/${positiveId(payload, 'id')}` }
    case 'saveProfitTransferPolicy': {
      const { version, start_date, target_account_id, cost_account_ids, reason } = payload as ErpOperations['saveProfitTransferPolicy']['input']
      return { method: 'PUT', path: '/api/v1/finance/profit-transfers/policy', body: { version, start_date, target_account_id, cost_account_ids, reason } }
    }
    case 'generateProfitTransfer': {
      const { period_id, period_version, policy_version, fingerprint, reference, reason } = payload as ErpOperations['generateProfitTransfer']['input']
      return { method: 'POST', path: '/api/v1/finance/profit-transfers/generate', body: { period_id, period_version, policy_version, fingerprint, reference, reason } }
    }
    case 'businessJournalOptions': return { method: 'GET', path: '/api/v1/finance/business-journals/policy' }
    case 'businessJournalPolicyChanges': return { method: 'GET', path: '/api/v1/finance/business-journals/policy/changes' }
    case 'saveBusinessJournalPolicy': {
      const { version, start_date, mapping, reason } = payload as ErpOperations['saveBusinessJournalPolicy']['input']
      return { method: 'PUT', path: '/api/v1/finance/business-journals/policy', body: { version, start_date, mapping, reason } }
    }
    case 'generateBusinessJournal': {
      const { source_key, fingerprint, policy_version, reference, journal_date, reason, auxiliary_by_role } = payload as ErpOperations['generateBusinessJournal']['input']
      const auxiliary = auxiliary_by_role === undefined ? {} : { auxiliary_by_role: Object.fromEntries(
        Object.entries(auxiliary_by_role).map(([role, items]) => {
          if (!Array.isArray(items)) throw new Error('辅助信息须为列表。')
          return [role, items.map(({ kind, id }) => ({ kind, id }))]
        })) }
      return { method: 'POST', path: '/api/v1/finance/business-journals/generate', body: { source_key, fingerprint, policy_version, reference, journal_date, reason, ...auxiliary } }
    }
    case 'openingBalances': return { method: 'GET', path: '/api/v1/finance/opening-balances' }
    case 'subledgerOpenings': return { method: 'GET', path: '/api/v1/finance/subledger-openings' }
    case 'subledgerOptions': return { method: 'GET', path: '/api/v1/finance/subledger-openings/options' }
    case 'subledgerPayments': return { method: 'GET', path: '/api/v1/finance/subledger-openings/payments' }
    case 'subledgerChanges': return { method: 'GET', path: `/api/v1/finance/subledger-openings/${positiveId(payload, 'id')}/changes` }
    case 'subledgerCheck': return { method: 'GET', path: `/api/v1/finance/subledger-openings/${positiveId(payload, 'id')}/check` }
    case 'createSubledgerOpening':
    case 'updateSubledgerOpening': {
      const fields = payload as ErpOperations['updateSubledgerOpening']['input']
      const { reference, note, reason, control_accounts, lines } = fields
      if (!Array.isArray(control_accounts) || control_accounts.length < 1 || control_accounts.length > 2
        || !Array.isArray(lines) || lines.length > 500) throw new Error('分户明细或控制科目无效')
      const body = { reference, note, reason, opening_balance_id: positiveId(payload, 'opening_balance_id'),
        opening_version: positiveId(payload, 'opening_version'),
        control_accounts: control_accounts.map(item => ({ kind: item.kind, account_id: positiveId(item, 'account_id') })),
        lines: lines.map(item => {
          if (!Array.isArray(item.auxiliary) || item.auxiliary.length > 2) throw new Error('分户辅助信息无效')
          return { kind: item.kind, account_id: positiveId(item, 'account_id'), party_id: positiveId(item, 'party_id'),
            document_reference: item.document_reference, document_date: item.document_date, debit: item.debit, credit: item.credit,
            auxiliary: item.auxiliary.map(value => ({ kind: value.kind, id: positiveId(value, 'id') })) }
        }) }
      const path = '/api/v1/finance/subledger-openings'
      return action === 'createSubledgerOpening' ? { method: 'POST', path, body }
        : { method: 'PUT', path: `${path}/${positiveId(payload, 'id')}`, body: { ...body, version: positiveId(payload, 'version') } }
    }
    case 'changeSubledgerStatus': {
      const { action: command, reason } = payload as ErpOperations['changeSubledgerStatus']['input']
      if (!['submit','approve','reject','confirm','cancel','reverse'].includes(command)) throw new Error('不允许的分户状态操作')
      return { method: 'POST', path: `/api/v1/finance/subledger-openings/${positiveId(payload, 'id')}/${command}`,
        body: { version: positiveId(payload, 'version'), reason } }
    }
    case 'querySubledger': {
      const { to_date, kind, party_id } = payload as ErpOperations['querySubledger']['input']
      return { method: 'POST', path: '/api/v1/finance/subledger-openings/query', body: { to_date, kind, party_id } }
    }
    case 'createSubledgerPayment': {
      const { action: command, amount, reference, reason } = payload as ErpOperations['createSubledgerPayment']['input']
      return { method: 'POST', path: `/api/v1/finance/subledger-openings/lines/${positiveId(payload, 'line_id')}/payments`,
        body: { action: command, amount, reference, reason } }
    }
    case 'reverseSubledgerPayment': return { method: 'POST', path: `/api/v1/finance/subledger-openings/payments/${positiveId(payload, 'id')}/reverse`,
      body: { reason: (payload as ErpOperations['reverseSubledgerPayment']['input']).reason } }
    case 'openingBalanceOptions': return { method: 'GET', path: '/api/v1/finance/opening-balances/options' }
    case 'openingBalanceChanges': return { method: 'GET', path: `/api/v1/finance/opening-balances/${positiveId(payload, 'id')}/changes` }
    case 'createOpeningBalance':
    case 'updateOpeningBalance': {
      const { reference, effective_date, note, reason, lines, ...rest } = payload as ErpOperations['updateOpeningBalance']['input']
      const path = '/api/v1/finance/opening-balances'
      return action === 'createOpeningBalance'
        ? { method: 'POST', path, body: { reference, effective_date, note, reason, lines } }
        : { method: 'PUT', path: `${path}/${positiveId(payload, 'id')}`, body: { version: rest.version, reference, effective_date, note, reason, lines } }
    }
    case 'changeOpeningBalanceStatus': {
      const { action: command, version, reason } = payload as ErpOperations['changeOpeningBalanceStatus']['input']
      if (!['submit','approve','reject','confirm','cancel','reverse'].includes(command)) throw new Error('不允许的期初状态操作')
      return { method: 'POST', path: `/api/v1/finance/opening-balances/${positiveId(payload, 'id')}/${command}`, body: { version, reason } }
    }
    case 'journalDetail': return { method: 'GET', path: `/api/v1/finance/journals/${positiveId(payload, 'id')}` }
    case 'ledgerReportOptions': return { method: 'GET', path: '/api/v1/finance/ledger-reports/options' }
    case 'queryLedgerReport': {
      const { kind, from_date, to_date, account_id } = payload as ErpOperations['queryLedgerReport']['input']
      return { method: 'POST', path: '/api/v1/finance/ledger-reports/query', body: { kind, from_date, to_date, account_id } }
    }
    case 'journalOptions': return { method: 'GET', path: '/api/v1/finance/journals/options' }
    case 'journalChanges': return { method: 'GET', path: `/api/v1/finance/journals/${positiveId(payload, 'id')}/changes` }
    case 'journalAttachments': return { method: 'GET', path: `/api/v1/finance/journals/${positiveId(payload, 'id')}/attachments` }
    case 'addJournalAttachment': return { method: 'POST', path: `/api/v1/finance/journals/${positiveId(payload, 'id')}/attachments`,
      body: attachmentBody(payload) }
    case 'reverseJournalAttachment': {
      const reason = bankText((payload as ErpOperations['reverseJournalAttachment']['input']).reason, '撤销原因', 200)
      return { method: 'POST', path: `/api/v1/finance/journals/${positiveId(payload, 'journalId')}/attachments/${positiveId(payload, 'attachmentId')}/reverse`,
        body: { reason } }
    }
    case 'createJournal': return { method: 'POST', path: '/api/v1/finance/journals', body: payload }
    case 'updateJournal': {
      const id = positiveId(payload, 'id')
      const { version, reference, journal_date, note, reason, lines } = payload as ErpOperations['updateJournal']['input']
      return { method: 'PUT', path: `/api/v1/finance/journals/${id}`, body: { version, reference, journal_date, note, reason, lines } }
    }
    case 'changeJournalStatus': {
      const id = positiveId(payload, 'id')
      const { action, version, reason } = payload as ErpOperations['changeJournalStatus']['input']
      if (!['submit', 'approve', 'reject', 'post', 'cancel'].includes(action)) throw new Error('不允许的凭证状态操作')
      return { method: 'POST', path: `/api/v1/finance/journals/${id}/${action}`, body: { version, reason } }
    }
    case 'reverseJournal': {
      const id = positiveId(payload, 'id')
      const { version, reference, journal_date, reason } = payload as ErpOperations['reverseJournal']['input']
      return { method: 'POST', path: `/api/v1/finance/journals/${id}/reverse`, body: { version, reference, journal_date, reason } }
    }
    case 'paymentRecords': return { method: 'GET', path: '/api/v1/finance/payment-records' }
    case 'orderSettlements': return { method: 'GET', path: '/api/v1/finance/order-settlements' }
    case 'bankReconciliationOverview': return { method: 'GET', path: '/api/v1/finance/bank-reconciliation/overview' }
    case 'createBankAccount': return { method: 'POST', path: '/api/v1/finance/bank-reconciliation/accounts', body: bankBody(payload, 'account') }
    case 'importBankLines': return { method: 'POST', path: '/api/v1/finance/bank-reconciliation/lines/import', body: bankBody(payload, 'lines') }
    case 'previewBankCsv': return { method: 'POST', path: '/api/v1/finance/bank-reconciliation/imports/csv/preview', body: bankCsvBody(payload) }
    case 'importBankCsv': return { method: 'POST', path: '/api/v1/finance/bank-reconciliation/imports/csv', body: bankCsvBody(payload) }
    case 'matchBankLine': return { method: 'POST', path: '/api/v1/finance/bank-reconciliation/matches', body: bankBody(payload, 'match') }
    case 'reverseBankMatch': return { method: 'POST', path: `/api/v1/finance/bank-reconciliation/matches/${positiveId(payload, 'matchId')}/reverse`, body: bankBody(payload, 'reverse') }
    case 'bankBalanceOverview': return { method: 'GET', path: '/api/v1/finance/bank-balance/overview' }
    case 'bindBankLedgerAccount': return { method: 'POST', path: `/api/v1/finance/bank-balance/accounts/${positiveId(payload, 'accountId')}/binding`, body: bankBalanceBody(payload, 'binding') }
    case 'clearBankOpeningItem': return { method: 'POST', path: `/api/v1/finance/bank-balance/opening-items/${positiveId(payload, 'openingItemId')}/clearances`, body: bankBalanceBody(payload, 'opening-clearance') }
    case 'reverseBankOpeningClearance': return { method: 'POST', path: `/api/v1/finance/bank-balance/opening-clearances/${positiveId(payload, 'clearanceId')}/reverse`, body: bankBalanceBody(payload, 'reason') }
    case 'previewBankBalance': return { method: 'POST', path: '/api/v1/finance/bank-balance/preview', body: bankBalanceBody(payload, 'preview') }
    case 'matchBankLedger': return { method: 'POST', path: '/api/v1/finance/bank-balance/ledger-matches', body: bankBalanceBody(payload, 'match') }
    case 'reverseBankLedgerMatch': return { method: 'POST', path: `/api/v1/finance/bank-balance/ledger-matches/${positiveId(payload, 'groupId')}/reverse`, body: bankBalanceBody(payload, 'reason') }
    case 'createBankBalanceReport': return { method: 'POST', path: '/api/v1/finance/bank-balance/reports', body: bankBalanceBody(payload, 'report') }
    case 'decideBankBalanceReport': return { method: 'POST', path: `/api/v1/finance/bank-balance/reports/${positiveId(payload, 'reportId')}/decision`, body: bankBalanceBody(payload, 'decision') }
    case 'createPaymentRecord': return { method: 'POST', path: '/api/v1/finance/payment-records', body: payload }
    case 'reversePaymentRecord': return {
      method: 'POST', path: `/api/v1/finance/payment-records/${positiveId(payload, 'paymentId')}/reverse`,
      body: { reason: (payload as { reason: unknown }).reason }
    }
    case 'createOrderSettlement': return { method: 'POST', path: '/api/v1/finance/order-settlements', body: payload }
    case 'reverseOrderSettlement': return {
      method: 'POST', path: `/api/v1/finance/order-settlements/${positiveId(payload, 'transferId')}/reverse`,
      body: { reason: (payload as { reason: unknown }).reason }
    }
    // BOM 的生命周期操作只接受经校验的单据编号。
    case 'boms': return { method: 'GET', path: '/api/v1/boms' }
    case 'createBom': return { method: 'POST', path: '/api/v1/boms', body: payload }
    case 'activateBom': return { method: 'POST', path: `/api/v1/boms/${positiveId(payload, 'bomId')}/activate` }
    case 'retireBom': return { method: 'POST', path: `/api/v1/boms/${positiveId(payload, 'bomId')}/retire` }
    case 'cancelBom': return { method: 'POST', path: `/api/v1/boms/${positiveId(payload, 'bomId')}/cancel` }
    case 'workOrders': return { method: 'GET', path: '/api/v1/work-orders' }
    case 'createWorkOrder': return { method: 'POST', path: '/api/v1/work-orders', body: payload }
    case 'releaseWorkOrder': return { method: 'POST', path: `/api/v1/work-orders/${positiveId(payload, 'orderId')}/release` }
    case 'cancelWorkOrder': return { method: 'POST', path: `/api/v1/work-orders/${positiveId(payload, 'orderId')}/cancel` }
    case 'materialIssues': return { method: 'GET', path: '/api/v1/material-issues' }
    case 'createMaterialIssue': return { method: 'POST', path: '/api/v1/material-issues', body: payload }
    case 'availableMaterialIssueLots': return {method: 'GET',
      path: `/api/v1/material-issues/${positiveId(payload, 'issueId')}/available-lots`}
    case 'postMaterialIssue': {
      const source = payload as ErpOperations['postMaterialIssue']['input']
      return {method: 'POST', path: `/api/v1/material-issues/${positiveId(payload, 'issueId')}/post`,
        ...(source.lines === undefined ? {} : {body: materialIssueLotBody({lines: source.lines})})}
    }
    case 'cancelMaterialIssue': return { method: 'POST', path: `/api/v1/material-issues/${positiveId(payload, 'issueId')}/cancel` }
    case 'reverseMaterialIssue': {
      const issueId = positiveId(payload, 'issueId')
      const fields = payload as ErpOperations['reverseMaterialIssue']['input']
      if (typeof fields.reason !== 'string' || !fields.reason.trim()
        || fields.reason.trim().length > 200 || /[\x00-\x1f]/.test(fields.reason))
        throw Error('生产领料冲销原因无效')
      return { method: 'POST', path: `/api/v1/material-issues/${issueId}/reverse`,
        body: { reason: fields.reason.trim() } }
    }
    case 'materialReturns': return { method: 'GET', path: '/api/v1/material-returns' }
    case 'createMaterialReturn': return { method: 'POST', path: '/api/v1/material-returns', body: payload }
    case 'availableMaterialReturnLots': return {method: 'GET',
      path: `/api/v1/material-returns/${positiveId(payload, 'returnId')}/available-lots`}
    case 'postMaterialReturn': {
      const source = payload as ErpOperations['postMaterialReturn']['input']
      return {method: 'POST', path: `/api/v1/material-returns/${positiveId(payload, 'returnId')}/post`,
        ...(source.lines === undefined ? {} : {body: materialReturnLotBody({lines: source.lines})})}
    }
    case 'cancelMaterialReturn': return { method: 'POST', path: `/api/v1/material-returns/${positiveId(payload, 'returnId')}/cancel` }
    case 'reverseMaterialReturn': {
      const returnId = positiveId(payload, 'returnId')
      const fields = payload as ErpOperations['reverseMaterialReturn']['input']
      if (typeof fields.reason !== 'string' || !fields.reason.trim()
        || fields.reason.trim().length > 200 || /[\x00-\x1f]/.test(fields.reason))
        throw Error('生产退料冲销原因无效')
      return {method: 'POST', path: `/api/v1/material-returns/${returnId}/reverse`,
        body: {reason: fields.reason.trim()}}
    }
    case 'productionCompletions': return { method: 'GET', path: '/api/v1/production-completions' }
    case 'createProductionCompletion': return { method: 'POST', path: '/api/v1/production-completions', body: payload }
    case 'inspectProductionCompletion': {
      const completionId = positiveId(payload, 'completionId')
      const fields = payload as ErpOperations['inspectProductionCompletion']['input']
      // 路径编号只用于定位单据，请求体仅发送质检接口确认的正式字段。
      return { method: 'POST', path: `/api/v1/production-completions/${completionId}/inspect`,
        body: { accepted_quantity: fields.accepted_quantity, qc_note: fields.qc_note } }
    }
    case 'postProductionCompletion': {
      const completionId = positiveId(payload, 'completionId')
      const source = payload as ErpOperations['postProductionCompletion']['input']
      return { method: 'POST', path: `/api/v1/production-completions/${completionId}/post`,
        ...(source.lots === undefined ? {} : {body: completionLotBody({lots: source.lots})}) }
    }
    case 'cancelProductionCompletion': return { method: 'POST', path: `/api/v1/production-completions/${positiveId(payload, 'completionId')}/cancel` }
    case 'reverseProductionCompletion': {
      const completionId = positiveId(payload, 'completionId')
      const fields = payload as ErpOperations['reverseProductionCompletion']['input']
      // 单据编号只用于受限路径，请求体只传冲销原因。
      return { method: 'POST', path: `/api/v1/production-completions/${completionId}/reverse`,
        body: { reason: fields.reason } }
    }
    case 'productionCosts': return { method: 'GET', path: '/api/v1/production-costs' }
    case 'productionCostSettlements': return { method: 'GET', path: '/api/v1/production-costs/settlements' }
    case 'settleProductionCost': return { method: 'POST', path: '/api/v1/production-costs/settlements', body: payload }
    case 'reverseProductionSettlement': {
      const settlementId = positiveId(payload, 'settlementId')
      const fields = payload as ErpOperations['reverseProductionSettlement']['input']
      return { method: 'POST', path: `/api/v1/production-costs/settlements/${settlementId}/reverse`, body: { reason: fields.reason } }
    }
    case 'recordMaterialValuation': return { method: 'POST', path: '/api/v1/production-costs/material-valuations', body: payload }
    case 'recordProductionCharge': return { method: 'POST', path: '/api/v1/production-costs/charges', body: payload }
    case 'reverseProductionCost': {
      const entryId = positiveId(payload, 'entryId')
      const fields = payload as ErpOperations['reverseProductionCost']['input']
      // 记录编号只进入固定路径，请求体仅包含冲销原因。
      return { method: 'POST', path: `/api/v1/production-costs/${entryId}/reverse`, body: { reason: fields.reason } }
    }
    case 'createPurchaseReturn': return { method: 'POST', path: '/api/v1/purchase-returns', body: payload }
    case 'submitPurchaseReturn': return { method: 'POST', path: `/api/v1/purchase-returns/${positiveId(payload, 'returnId')}/submit` }
    case 'postPurchaseReturn': return { method: 'POST', path: `/api/v1/purchase-returns/${positiveId(payload, 'returnId')}/post` }
    case 'cancelPurchaseReturn': return { method: 'POST', path: `/api/v1/purchase-returns/${positiveId(payload, 'returnId')}/cancel` }
    case 'reversePurchaseReturn': {
      const returnId = positiveId(payload, 'returnId')
      const fields = payload as ErpOperations['reversePurchaseReturn']['input']
      return { method: 'POST', path: `/api/v1/purchase-returns/${returnId}/reverse`, body: { reason: fields.reason } }
    }
    case 'purchaseOrders': return { method: 'GET', path: '/api/v1/purchase-orders' }
    case 'purchaseRequests': return { method: 'GET', path: '/api/v1/purchase-requests' }
    case 'createPurchaseRequest': return { method: 'POST', path: '/api/v1/purchase-requests', body: payload }
    case 'updatePurchaseRequest': {
      const requestId = positiveId(payload, 'requestId')
      const fields = payload as ErpOperations['updatePurchaseRequest']['input']
      return { method: 'PUT', path: `/api/v1/purchase-requests/${requestId}`,
        body: { reference: fields.reference, note: fields.note, lines: fields.lines } }
    }
    case 'submitPurchaseRequest': return { method: 'POST', path: `/api/v1/purchase-requests/${positiveId(payload, 'requestId')}/submit` }
    case 'approvePurchaseRequest': return { method: 'POST', path: `/api/v1/purchase-requests/${positiveId(payload, 'requestId')}/approve` }
    case 'rejectPurchaseRequest': {
      const requestId = positiveId(payload, 'requestId')
      const fields = payload as ErpOperations['rejectPurchaseRequest']['input']
      return { method: 'POST', path: `/api/v1/purchase-requests/${requestId}/reject`, body: { reason: fields.reason } }
    }
    case 'cancelPurchaseRequest': return { method: 'POST', path: `/api/v1/purchase-requests/${positiveId(payload, 'requestId')}/cancel` }
    case 'createPurchaseOrder': return { method: 'POST', path: '/api/v1/purchase-orders', body: payload }
    case 'confirmPurchaseOrder': return { method: 'POST', path: `/api/v1/purchase-orders/${positiveId(payload, 'orderId')}/confirm` }
    case 'cancelPurchaseOrder': return { method: 'POST', path: `/api/v1/purchase-orders/${positiveId(payload, 'orderId')}/cancel` }
    case 'salesOrders': return { method: 'GET', path: '/api/v1/sales-orders' }
    case 'salesOrderContract': return {method:'GET',path:`/api/v1/sales-orders/${positiveId(payload,'orderId')}/contract`}
    case 'salesContractAttachments': return {method:'GET',path:`/api/v1/sales-orders/${positiveId(payload,'orderId')}/contract/revisions/${positiveId(payload,'revisionId')}/attachments`}
    case 'addSalesContractAttachment': return {method:'POST',path:`/api/v1/sales-orders/${positiveId(payload,'orderId')}/contract/revisions/${positiveId(payload,'revisionId')}/attachments`,
      body:attachmentBody(payload)}
    case 'reverseSalesContractAttachment': {
      const source=payload as ErpOperations['reverseSalesContractAttachment']['input']
      const reason=bankText(source.reason,'撤销原因',200)
      return {method:'POST',path:`/api/v1/sales-orders/${positiveId(source,'orderId')}/contract/revisions/${positiveId(source,'revisionId')}/attachments/${positiveId(source,'attachmentId')}/reverse`,
        body:{reason}}
    }
    case 'reviseSalesOrderContract': {
      const source=payload as ErpOperations['reviseSalesOrderContract']['input']
      const orderId=positiveId(source,'orderId')
      if(!Number.isInteger(source.expected_version) || source.expected_version<0 ||
        typeof source.body!=='string' || !source.body.trim() || source.body.length>20000 ||
        typeof source.acceptance_reference!=='string' || !source.acceptance_reference.trim() || source.acceptance_reference.length>400 ||
        typeof source.reason!=='string' || !source.reason.trim() || source.reason.length>200)
        throw new Error('合同正文、客户确认依据或版本无效')
      return {method:'POST',path:`/api/v1/sales-orders/${orderId}/contract`,body:{
        expected_version:source.expected_version,body:source.body.trim(),
        acceptance_reference:source.acceptance_reference.trim(),reason:source.reason.trim()}}
    }
    case 'createSalesOrder': {
      const source=payload as ErpOperations['createSalesOrder']['input']
      if(!source || typeof source.reference!=='string' || source.reference.length>100 ||
        !Array.isArray(source.lines) || source.lines.length<1 || source.lines.length>100)
        throw new Error('销售订单输入无效')
      const lines=source.lines.map(line=>{
        if(!line || typeof line.quantity!=='string' || typeof line.unit_price!=='string')
          throw new Error('销售订单明细无效')
        const days=line.warranty_days??null,basis=line.warranty_basis??''
        if(days!==null && (typeof days!=='number' || !Number.isInteger(days) || days<1 || days>36500))
          throw new Error('保修天数无效')
        if(typeof basis!=='string' || basis.length>400 || (days===null)!==(basis.trim()===''))
          throw new Error('保修依据无效')
        return {material_id:positiveId(line,'material_id'),quantity:line.quantity,unit_price:line.unit_price,
          warranty_days:days,warranty_basis:basis.trim()}
      })
      return {method:'POST',path:'/api/v1/sales-orders',body:{customer_id:positiveId(source,'customer_id'),
        reference:source.reference,lines}}
    }
    case 'confirmSalesOrder': return { method: 'POST', path: `/api/v1/sales-orders/${positiveId(payload, 'orderId')}/confirm` }
    case 'cancelSalesOrder': return { method: 'POST', path: `/api/v1/sales-orders/${positiveId(payload, 'orderId')}/cancel` }
    case 'shipments': return { method: 'GET', path: '/api/v1/shipments' }
    case 'availableShipmentLots': return {method: 'GET',
      path: `/api/v1/shipments/${positiveId(payload, 'shipmentId')}/available-lots`}
    case 'createShipment': return { method: 'POST', path: '/api/v1/shipments', body: payload }
    case 'postShipment': {
      const shipmentId=positiveId(payload,'shipmentId')
      const source=payload as ErpOperations['postShipment']['input']
      return {method:'POST',path:`/api/v1/shipments/${shipmentId}/post`,
        ...(source.lines===undefined?{}:{body:shipmentLotBody({lines:source.lines})})}
    }
    case 'cancelShipment': return { method: 'POST', path: `/api/v1/shipments/${positiveId(payload, 'shipmentId')}/cancel` }
    case 'reverseShipment': {
      const shipmentId = positiveId(payload, 'shipmentId')
      const fields = payload as ErpOperations['reverseShipment']['input']
      return { method: 'POST', path: `/api/v1/shipments/${shipmentId}/reverse`, body: { reason: fields.reason } }
    }
    // 退货只能调用固定路径，单据编号先校验再拼接，避免渲染层指定任意 URL。
    case 'salesReturns': return { method: 'GET', path: '/api/v1/sales-returns' }
    case 'createSalesReturn': return { method: 'POST', path: '/api/v1/sales-returns', body: payload }
    case 'availableSalesReturnLots': return {method: 'GET',
      path: `/api/v1/sales-returns/${positiveId(payload, 'returnId')}/available-lots`}
    case 'postSalesReturn': {
      const returnId = positiveId(payload, 'returnId')
      const source = payload as ErpOperations['postSalesReturn']['input']
      return {method: 'POST', path: `/api/v1/sales-returns/${returnId}/post`,
        ...(source.lines === undefined ? {} : {body: salesReturnLotBody({lines: source.lines})})}
    }
    case 'cancelSalesReturn': return { method: 'POST', path: `/api/v1/sales-returns/${positiveId(payload, 'returnId')}/cancel` }
    case 'reverseSalesReturn': {
      const returnId = positiveId(payload, 'returnId')
      const fields = payload as ErpOperations['reverseSalesReturn']['input']
      return { method: 'POST', path: `/api/v1/sales-returns/${returnId}/reverse`, body: { reason: fields.reason } }
    }
    case 'transfers': return { method: 'GET', path: '/api/v1/transfers' }
    case 'createTransfer': return { method: 'POST', path: '/api/v1/transfers', body: payload }
    case 'availableTransferLots': return {method: 'GET',
      path: `/api/v1/transfers/${positiveId(payload, 'transferId')}/available-lots`}
    case 'postTransfer': {
      const transferId = positiveId(payload, 'transferId')
      const source = payload as ErpOperations['postTransfer']['input']
      return {method: 'POST', path: `/api/v1/transfers/${transferId}/post`,
        ...(source.lines === undefined ? {} : {body: transferLotBody({lines: source.lines})})}
    }
    case 'reverseTransfer': {
      const transferId = positiveId(payload, 'transferId')
      const fields = payload as ErpOperations['reverseTransfer']['input']
      // 调拨冲销只接收原因，目标路径固定且单据编号必须为正整数。
      return { method: 'POST', path: `/api/v1/transfers/${transferId}/reverse`, body: { reason: fields.reason } }
    }
    case 'stocktakes': return { method: 'GET', path: '/api/v1/stocktakes' }
    case 'createStocktake': return { method: 'POST', path: '/api/v1/stocktakes', body: payload }
    case 'availableStocktakeLots': return {method: 'GET',
      path: `/api/v1/stocktakes/${positiveId(payload, 'stocktakeId')}/available-lots`}
    case 'postStocktake': {
      const stocktakeId = positiveId(payload, 'stocktakeId')
      const source = payload as ErpOperations['postStocktake']['input']
      return {method: 'POST', path: `/api/v1/stocktakes/${stocktakeId}/post`,
        ...(source.lines === undefined ? {} : {body: stocktakeLotBody({lines: source.lines})})}
    }
    case 'cancelStocktake': return { method: 'POST', path: `/api/v1/stocktakes/${positiveId(payload, 'stocktakeId')}/cancel` }
    case 'reverseStocktake': {
      const stocktakeId = positiveId(payload, 'stocktakeId')
      const fields = payload as ErpOperations['reverseStocktake']['input']
      // 冲销只允许发送原因，单据编号由主进程校验后拼接到固定路径。
      return { method: 'POST', path: `/api/v1/stocktakes/${stocktakeId}/reverse`, body: { reason: fields.reason } }
    }
    case 'stock': return { method: 'GET', path: payload && typeof payload === 'object' && 'warehouseId' in payload && payload.warehouseId !== undefined
      ? `/api/v1/stock?warehouse_id=${positiveId(payload, 'warehouseId')}` : '/api/v1/stock' }
    case 'movements': return { method: 'GET', path: '/api/v1/movements' }
    case 'inventoryLedger': return { method: 'POST', path: '/api/v1/inventory-ledger/query', body: payload }
    case 'queryReport': return { method: 'POST', path: '/api/v1/reports/query', body: payload }
    default: throw new Error('不允许的业务操作')
  }
}

export async function callBackend(action: keyof ErpOperations, payload: unknown): Promise<unknown> {
  const request = operation(action, payload)
  const publicAction = action === 'setupStatus' || action === 'bootstrap' || action === 'login'
  if (!publicAction && !sessionToken) throw new Error('请先登录')
  const activeToken = sessionToken
  // 即使本地服务暂时不可达，退出时也立刻丢弃桌面进程持有的令牌。
  if (action === 'logout') setSessionToken(null)
  let response: Response
  try {
    response = await sendRequest(request.path, request.method, {
        ...(request.body === undefined ? {} : { 'Content-Type': 'application/json' }),
        ...(publicAction ? {} : { Authorization: `Bearer ${activeToken}` })
      }, request.body, action === 'addJournalAttachment' || action === 'addAfterSalesAttachment'
        || action === 'addCrmQuoteAttachment' || action === 'addCrmRecordAttachment' || action === 'addEquipmentAttachment'
        || action === 'addSalesContractAttachment' ? 30000 : 10000)
  } catch {
    throw new Error('无法连接服务端，请检查网络、服务状态和证书。')
  }
  const data: unknown = response.status === 204 ? undefined : await response.json().catch(() => undefined)
  if (!response.ok) {
    if (response.status === 401 && !publicAction && sessionToken === activeToken) setSessionToken(null)
    const detail = data && typeof data === 'object' && 'detail' in data ? data.detail : undefined
    // FastAPI 的默认 404 文案没有操作语境，提示用户核对桌面端与服务端版本。
    if (response.status === 404 && detail === 'Not Found') {
      throw new Error('服务端未找到此功能（HTTP 404）。请确认桌面端与服务端版本一致。')
    }
    throw new Error(typeof detail === 'string' ? detail : `请求失败（HTTP ${response.status}）`)
  }
  if (action === 'login') {
    if (!data || typeof data !== 'object' || !('token' in data) || typeof data.token !== 'string'
      || !('user' in data) || !data.user) throw new Error('登录响应格式不匹配')
    setSessionToken(data.token, true)
    return data.user
  }
  if (action === 'logout' || action === 'changePassword') setSessionToken(null)
  if (action === 'dashboard') validateDashboardResult(data,(payload as ErpOperations['dashboard']['input']).period)
  if (action === 'customerImportPreview') validateCustomerImportPreview(data,
    customerImportNames(payload))
  if (action === 'importCustomers') validateCustomerImportResult(data,
    customerImportNames(payload))
  if (action === 'contactImportPreview') validateContactImportPreview(data,
    contactImportRows(payload))
  if (action === 'importContacts') validateContactImportResult(data,
    contactImportRows(payload))
  if (action === 'opportunityImportPreview') validateOpportunityImportPreview(data,
    opportunityImportRows(payload))
  if (action === 'importOpportunities') validateOpportunityImportResult(data,
    opportunityImportRows(payload))
  if (action === 'crmForecast') validateCrmForecast(data)
  if (action === 'postReceipt') {
    const request = payload as ErpOperations['postReceipt']['input']
    if (request.lines) validatePostedReceiptLots(data, request.receiptId, receiptLotBody({lines: request.lines}).lines)
  }
  if (action === 'postOtherInbound') {
    const request = payload as ErpOperations['postOtherInbound']['input']
    if (request.lines) validatePostedInboundLots(data, request.inboundId,
      inboundLotBody({lines: request.lines}).lines)
  }
  if (action === 'availableOutboundLots') {
    validateOutboundLotOptions(data, (payload as ErpOperations['availableOutboundLots']['input']).outboundId)
  }
  if (action === 'postWarehouseOutbound') {
    const request = payload as ErpOperations['postWarehouseOutbound']['input']
    if (request.lines) validatePostedOutboundLots(data, request.outboundId,
      outboundLotBody({lines: request.lines}).lines)
  }
  if (action === 'availableShipmentLots') {
    validateShipmentLotOptions(data, (payload as ErpOperations['availableShipmentLots']['input']).shipmentId)
  }
  if (action === 'availableMaterialIssueLots') {
    validateMaterialIssueLotOptions(data,
      (payload as ErpOperations['availableMaterialIssueLots']['input']).issueId)
  }
  if (action === 'availableMaterialReturnLots') {
    validateMaterialReturnLotOptions(data,
      (payload as ErpOperations['availableMaterialReturnLots']['input']).returnId)
  }
  if (action === 'postMaterialReturn') {
    const request = payload as ErpOperations['postMaterialReturn']['input']
    if (request.lines) validatePostedMaterialReturnLots(data, request.returnId,
      materialReturnLotBody({lines: request.lines}).lines)
  }
  if (action === 'postMaterialIssue') {
    const request = payload as ErpOperations['postMaterialIssue']['input']
    if (request.lines) validatePostedMaterialIssueLots(data, request.issueId,
      materialIssueLotBody({lines: request.lines}).lines)
  }
  if (action === 'postShipment') {
    const request = payload as ErpOperations['postShipment']['input']
    if (request.lines) validatePostedShipmentLots(data, request.shipmentId,
      shipmentLotBody({lines: request.lines}).lines)
  }
  if (action === 'availableTransferLots') {
    validateTransferLotOptions(data, (payload as ErpOperations['availableTransferLots']['input']).transferId)
  }
  if (action === 'postTransfer') {
    const request = payload as ErpOperations['postTransfer']['input']
    if (request.lines) validatePostedTransferLots(data, request.transferId,
      transferLotBody({lines: request.lines}).lines)
  }
  if (action === 'availableStocktakeLots') {
    validateStocktakeLotOptions(data, (payload as ErpOperations['availableStocktakeLots']['input']).stocktakeId)
  }
  if (action === 'postStocktake') {
    const request = payload as ErpOperations['postStocktake']['input']
    if (request.lines) validatePostedStocktakeLots(data, request.stocktakeId,
      stocktakeLotBody({lines: request.lines}).lines)
  }
  if (action === 'availableAdjustmentLots') {
    validateAdjustmentLotOptions(data, (payload as ErpOperations['availableAdjustmentLots']['input']).adjustmentId)
  }
  if (action === 'postStockAdjustment') {
    const request = payload as ErpOperations['postStockAdjustment']['input']
    if (request.lines) validatePostedAdjustmentLots(data, request.adjustmentId,
      adjustmentLotBody({lines: request.lines}).lines)
  }
  if (action === 'availableSalesReturnLots') {
    validateSalesReturnLotOptions(data,
      (payload as ErpOperations['availableSalesReturnLots']['input']).returnId)
  }
  if (action === 'postSalesReturn') {
    const request = payload as ErpOperations['postSalesReturn']['input']
    if (request.lines) validatePostedSalesReturnLots(data, request.returnId,
      salesReturnLotBody({lines: request.lines}).lines)
  }
  if (action === 'postProductionCompletion') {
    const request = payload as ErpOperations['postProductionCompletion']['input']
    if (request.lots) validatePostedCompletionLots(data, request.completionId,
      completionLotBody({lots: request.lots}).lots)
  }
  validateInventoryWarningResult(action,data)
  validatePhysicalLotResult(action,data)
  validateEquipmentResult(action,data)
  validateMaterialResult(action, data)
  if (action === 'journalAttachments' || action === 'addJournalAttachment' || action === 'reverseJournalAttachment') {
    validateJournalAttachmentResult(action, data,
      positiveId(payload, action === 'reverseJournalAttachment' ? 'journalId' : 'id'))
  }
  if (action === 'afterSalesAttachments' || action === 'addAfterSalesAttachment' || action === 'reverseAfterSalesAttachment') {
    validateAfterSalesAttachmentResult(action, data,
      positiveId(payload, action === 'reverseAfterSalesAttachment' ? 'caseId' : 'id'))
  }
  if (action === 'crmQuoteAttachments' || action === 'addCrmQuoteAttachment' || action === 'reverseCrmQuoteAttachment') {
    validateCrmQuoteAttachmentResult(action, data,
      positiveId(payload, action === 'reverseCrmQuoteAttachment' ? 'quoteId' : 'id'))
  }
  if (action === 'salesContractAttachments' || action === 'addSalesContractAttachment' || action === 'reverseSalesContractAttachment') {
    validateSalesContractAttachmentResult(action, data,
      positiveId(payload, 'orderId'), positiveId(payload, 'revisionId'))
  }
  if (action === 'crmRecordAttachments' || action === 'addCrmRecordAttachment' || action === 'reverseCrmRecordAttachment') {
    validateCrmRecordAttachmentResult(action, data,
      crmRecordKind((payload as ErpOperations[typeof action]['input']).kind), positiveId(payload, 'id'))
  }
  if (action === 'equipmentAttachments' || action === 'addEquipmentAttachment' || action === 'reverseEquipmentAttachment') {
    validateEquipmentAttachmentResult(action, data,
      equipmentAttachmentKind((payload as ErpOperations[typeof action]['input']).kind), positiveId(payload, 'id'))
  }
  return data
}

export async function getBackendHealth(): Promise<BackendHealth> {
  try {
    // 地址只由主进程环境配置，页面不能传入任意 URL。
    const response = await sendRequest('/api/v1/health', 'GET', {}, undefined, 5000)
    if (!response.ok) {
      return { connected: false, message: `后端返回 HTTP ${response.status}，请检查服务后重试。` }
    }
    const data: unknown = await response.json()
    if (!data || typeof data !== 'object' || !('status' in data) || data.status !== 'ok'
      || !('service' in data) || data.service !== 'nexora-api'
      || !('version' in data) || typeof data.version !== 'string' || !data.version.trim()) {
      return { connected: false, message: '后端响应格式不匹配，请确认运行的是 Nexora API。' }
    }
    return { connected: true, version: data.version }
  } catch (error) {
    return { connected: false, message: error instanceof Error && error.message.includes('配置无效')
      ? error.message : '无法连接后端，请确认服务已启动、地址正确，然后重试。' }
  }
}
