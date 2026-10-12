import type { ControlScopeChoice, ControlTransferInput, FundsScopeChoice } from './control-balance-api'

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw Error('往来组合参数或响应无效，请刷新核对。')
  return value as Record<string, unknown>
}
export function controlId(value: unknown): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value <= 0) throw Error('往来组合编号须为正整数。')
  return value
}
export function controlText(value: unknown, max: number): string {
  if (typeof value !== 'string' || !value.trim() || value.trim().length > max || /[\x00-\x1f]/.test(value)) throw Error(`依据必填，最多 ${max} 字。`)
  return value.trim()
}
export function controlDate(value: unknown): string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value) || !Number.isFinite(Date.parse(value + 'T00:00:00Z'))
    || new Date(value + 'T00:00:00Z').toISOString().slice(0, 10) !== value) throw Error('往来日期无效。')
  return value
}
function fingerprint(value: unknown): string {
  if (typeof value !== 'string' || !/^[a-f0-9]{64}$/.test(value)) throw Error('组合来源版本无效，请刷新核对。')
  return value
}
function auxiliary(value: unknown): FundsScopeChoice['auxiliary'] {
  if (!Array.isArray(value) || value.length < 1 || value.length > 4) throw Error('须选择完整辅助组合。')
  const kinds = new Set<string>()
  return value.map<FundsScopeChoice['auxiliary'][number]>(value => {
    const row = object(value), kind = row.kind
    if (kind !== 'customer' && kind !== 'supplier' && kind !== 'department' && kind !== 'project' || kinds.has(String(kind))) throw Error('辅助类别无效或重复。')
    kinds.add(kind)
    return { kind, id: controlId(row.id) }
  }).sort((a, b) => a.kind.localeCompare(b.kind))
}
export function fundsScopeBody(value: unknown): FundsScopeChoice {
  const row = object(value)
  return { account_id: controlId(row.account_id), auxiliary: auxiliary(row.auxiliary), fingerprint: fingerprint(row.fingerprint) }
}
function scopeBody(value: unknown, required: boolean): ControlScopeChoice {
  const row = object(value)
  if (row.source_type !== 'historical' && row.source_type !== 'order') throw Error('原单类别无效。')
  return { source_type: row.source_type, source_id: controlId(row.source_id), account_id: controlId(row.account_id), auxiliary: auxiliary(row.auxiliary),
    fingerprint: row.fingerprint == null && !required ? null : fingerprint(row.fingerprint) }
}
export function controlTransferBody(value: unknown): ControlTransferInput {
  const row = object(value)
  if (row.kind !== 'receivable' && row.kind !== 'payable' || row.operation !== 'reclassify' && row.operation !== 'allocate') throw Error('往来类别或转账用途无效。')
  if (typeof row.amount !== 'string' || !/^\d{1,13}(\.\d{1,2})?$/.test(row.amount) || !/[1-9]/.test(row.amount)) throw Error('转账金额须为正数，最多两位小数。')
  return { kind: row.kind, operation: row.operation, business_date: controlDate(row.business_date), from_scope: scopeBody(row.from_scope, true),
    to_scope: scopeBody(row.to_scope, row.operation === 'allocate'), amount: row.amount, reference: controlText(row.reference, 80), reason: controlText(row.reason, 200) }
}
function amount(value: unknown): bigint {
  if (typeof value !== 'string' || !/^-?\d{1,20}\.\d{2}$/.test(value)) throw Error('服务端往来金额格式无效。')
  return BigInt(value.replace('.', ''))
}
function identity(value: unknown): Record<string, unknown> {
  const row = object(value)
  if (row.kind !== 'receivable' && row.kind !== 'payable' || row.source_type !== 'historical' && row.source_type !== 'order') throw Error('服务端往来身份无效。')
  controlId(row.source_id); controlId(row.party_id); controlId(row.account_id)
  const refs = auxiliary(row.auxiliary), partner = row.kind === 'receivable' ? 'customer' : 'supplier'
  if (!refs.some(item => item.kind === partner && item.id === row.party_id)
    || refs.some(item => ['customer', 'supplier'].includes(item.kind) && (item.kind !== partner || item.id !== row.party_id))) throw Error('服务端组合的实际往来不一致。')
  return row
}
function group(value: unknown): Record<string, unknown> {
  const row = identity(value)
  amount(row.outstanding_amount); fingerprint(row.fingerprint)
  if (!Array.isArray(row.evidence) || !Array.isArray(row.blockers) || row.blockers.some(value => typeof value !== 'string')) throw Error('服务端组合依据无效。')
  row.evidence.forEach(evidence)
  return row
}
function evidence(value: unknown): void {
  const row = object(value)
  if (row.type === 'journal') {
    controlId(row.journal_id); controlId(row.journal_line_id); controlDate(row.journal_date); amount(row.amount)
    controlText(row.source_key, 120); fingerprint(row.fingerprint)
  } else if (row.type === 'opening') {
    controlId(row.line_id); controlId(row.opening_id); controlId(row.opening_version); controlDate(row.date)
    if (amount(row.debit) < 0n || amount(row.credit) < 0n) throw Error('期初依据金额无效。')
  } else if (row.type === 'historical_payment' || row.type === 'pending_payment') {
    controlId(row.payment_id); controlDate(row.date); amount(row.amount)
    if (row.type === 'historical_payment' && row.reverses_id !== null) controlId(row.reverses_id)
    if (row.journal_id !== undefined) { controlId(row.journal_id); controlDate(row.journal_date); fingerprint(row.fingerprint) }
  } else if (row.type === 'historical_settlement' || row.type === 'historical_order_settlement') {
    controlId(row.settlement_id); controlDate(row.date); amount(row.amount)
  } else if (row.type === 'order_settlement') {
    controlId(row.transfer_id); amount(row.amount)
    if (typeof row.executed_at !== 'string' || !Number.isFinite(Date.parse(row.executed_at))) throw Error('核销执行日期无效。')
  } else if (row.type === 'control_transfer') {
    controlId(row.transfer_id); controlId(row.journal_id); controlDate(row.date); amount(row.from_delta)
    if (row.reverses_id !== null) controlId(row.reverses_id)
  } else throw Error('服务端组合依据类型无效。')
}
function sameScope(a: Record<string, unknown>, b: Record<string, unknown>): boolean {
  return ['kind','source_type','source_id','party_id','account_id'].every(key => a[key] === b[key])
    && JSON.stringify(auxiliary(a.auxiliary)) === JSON.stringify(auxiliary(b.auxiliary))
}
function origin(value: unknown): Record<string, unknown> {
  const row = object(value)
  if (row.kind !== 'receivable' && row.kind !== 'payable' || row.source_type !== 'historical' && row.source_type !== 'order') throw Error('服务端原单身份无效。')
  controlId(row.source_id); controlId(row.party_id)
  controlText(row.party_name, 120)
  if (typeof row.reference !== 'string' || !Array.isArray(row.blockers) || row.blockers.some(value => typeof value !== 'string')
    || !Array.isArray(row.groups)) throw Error('服务端原单组合无效。')
  const seen = new Set<string>()
  let total = 0n
  for (const value of row.groups) {
    const part = group(value), key = `${part.account_id}:${JSON.stringify(auxiliary(part.auxiliary))}`
    if (['kind','source_type','source_id','party_id'].some(key => row[key] !== part[key]) || seen.has(key)) throw Error('服务端原单组合归属不一致。')
    seen.add(key); total += amount(part.outstanding_amount)
  }
  if (total !== amount(row.outstanding_amount)) throw Error('服务端原单总额与组合金额不一致。')
  return row
}
function transfer(value: unknown): Record<string, unknown> {
  const row = object(value)
  controlId(row.id); controlId(row.version); controlId(row.party_id); controlDate(row.business_date)
  const source = identity(row.from_scope), target = identity(row.to_scope)
  if (row.currency !== 'CNY' || !['draft','executed','cancelled'].includes(String(row.status))
    || !['reclassify','allocate'].includes(String(row.operation)) || amount(row.amount) <= 0n
    || [source, target].some(part => part.kind !== row.kind || part.party_id !== row.party_id)
    || ![-amount(row.amount), amount(row.amount)].includes(amount(row.from_delta))) throw Error('服务端转账状态、归属或金额无效。')
  const proofs = object(row.evidence)
  if (!sameScope(source, group(proofs.source)) || !sameScope(target, group(proofs.target))) throw Error('固定转账组合与来源依据不一致。')
  if (row.journal_id !== null) controlId(row.journal_id)
  if (row.status === 'executed' && (row.journal_id === null || row.journal_status !== 'posted')) throw Error('生效转账缺少已过账凭证。')
  return row
}
export function validateControlBalanceResult(action: string, value: unknown): void {
  if (action === 'controlBalanceTransfers') {
    if (!Array.isArray(value)) throw Error('转账列表响应无效。')
    value.forEach(transfer)
  } else if (action === 'controlBalanceOptions' || action === 'queryControlBalances') {
    const row = object(value)
    if (row.currency !== 'CNY' || !Array.isArray(row.origins)) throw Error('组合余额响应无效。')
    row.origins.forEach(origin)
    if (action === 'queryControlBalances') { controlDate(row.to_date); if (row.time_basis !== 'UTC') throw Error('截止日口径无效。') }
    else {
      if (!Array.isArray(row.accounts) || !Array.isArray(row.auxiliary_items) || !Array.isArray(row.auxiliary_policies) || !Array.isArray(row.control_accounts)) throw Error('组合选项响应无效。')
      const accounts = new Set(row.accounts.map(part => controlId(object(part).id))), seen = new Set<string>()
      for (const part of row.control_accounts) {
        const control = object(part), id = controlId(control.account_id), key = `${control.kind}:${id}`
        if (!['receivable','payable'].includes(String(control.kind)) || !accounts.has(id) || seen.has(key)) throw Error('可用控制科目归属无效。')
        seen.add(key)
      }
    }
  } else if (action === 'controlBalanceFundsOptions') {
    const row = object(value)
    if (row.currency !== 'CNY' || typeof row.required !== 'boolean') throw Error('资金组合响应无效。')
    if (row.accounts !== undefined) {
      if (!Array.isArray(row.accounts)) throw Error('资金控制科目响应无效。')
      for (const item of row.accounts) { const account = object(item); controlId(account.id); controlText(account.code, 32); controlText(account.name, 100) }
    }
    if (row.origin !== null) origin(row.origin)
    if (row.required && row.origin === null) throw Error('须选择组合的原单缺少来源。')
  } else if (action === 'controlBalanceChanges') {
    if (!Array.isArray(value)) throw Error('转账审计响应无效。')
    for (const part of value) { const row = object(part); controlId(row.id); transfer(row.snapshot) }
  } else if (action === 'generateControlBalanceJournal') {
    const row = object(value), parent = transfer(row.transfer), journal = object(row.journal)
    if (parent.journal_id !== journal.id || journal.journal_date !== parent.business_date || journal.currency !== 'CNY'
      || journal.status !== 'draft' || !Array.isArray(journal.lines) || journal.lines.length !== 2) throw Error('关联凭证归属无效。')
    // 固定两条分录与原单组合一致，防止异常响应把别的凭证当作本次转账。
    const delta = amount(parent.from_delta) * (parent.kind === 'receivable' ? 1n : -1n)
    for (const [index, frozen] of [parent.from_scope, parent.to_scope].entries()) {
      const line = object(journal.lines[index]), scope = object(frozen), expected = index === 0 ? delta : -delta
      if (line.account_id !== scope.account_id || JSON.stringify(auxiliary(line.auxiliary)) !== JSON.stringify(auxiliary(scope.auxiliary))
        || amount(line.debit) !== (expected > 0n ? expected : 0n) || amount(line.credit) !== (expected < 0n ? -expected : 0n)) throw Error('固定凭证分录与转账组合不一致。')
    }
  } else if (['controlBalanceDetail','createControlBalanceTransfer','reverseControlBalanceTransfer','cancelControlBalanceTransfer'].includes(action)) transfer(value)
}
