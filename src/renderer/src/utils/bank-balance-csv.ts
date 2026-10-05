import type { BankBalanceReport } from '../../../shared/erp-api'

type CsvValue = string | number | boolean

function cell(value: CsvValue, amount = false): string {
  const text = String(value)
  // 银行导入的交易号、往来单位等可能由外部文件提供，导出时避免被表格软件当作公式。
  const safe = !amount && /^[\s\u0000-\u001f]*[=+\-@]/.test(text) ? `'${text}` : text
  return `"${safe.replaceAll('"', '""')}"`
}

function row(...values: CsvValue[]): string {
  return values.map(value => cell(value)).join(',')
}

function amountCell(value: string): string {
  if (!/^-?(?:0|[1-9]\d*)(?:\.\d{1,2})?$/.test(value)) throw new Error('银行调节表金额无效')
  return cell(value, true)
}

function moneyRow(section: string, label: string, amount: string, note = ''): string {
  return [cell(section), cell(label), cell(''), cell(''), cell(''), amountCell(amount), cell(note)].join(',')
}

export function bankBalanceReportCsv(report: BankBalanceReport): string {
  const snapshot = report.snapshot
  if (snapshot.account_id !== report.account_id || snapshot.as_of_date !== report.as_of_date
    || snapshot.bank_closing_declared !== report.declared_bank_closing
    || snapshot.fingerprint !== report.fingerprint) {
    throw new Error('银行调节表快照与报表记录不一致')
  }
  const status = { draft: '待复核', approved: '已复核', rejected: '已驳回', superseded: '已由新表取代' }
  const decision = { approve: '复核通过', reject: '驳回', supersede: '由新表取代' }
  const rows = [
    row('类别', '项目', '日期', '来源编号', '凭据/交易号', '金额(元)', '说明'),
    row('报表', '报表编号', '', report.id, '', '', ''),
    row('报表', '银行账户', '', snapshot.account_code, '', '', ''),
    row('报表', '总账科目', '', snapshot.ledger_code, '', '', ''),
    row('报表', '启用日', snapshot.effective_date, '', '', '', ''),
    row('报表', '截止日', report.as_of_date, '', '', '', ''),
    row('报表', '状态', '', status[report.status], '', '', report.stale ? '来源已变化' : '来源未变化'),
    row('报表', '编制人', report.created_at, report.created_by, '', '', report.created_by_name),
    row('报表', '编制依据', '', '', '', '', report.reason),
    row('报表', '来源指纹', '', report.fingerprint, '', '', ''),
    moneyRow('汇总', '银行期初', snapshot.bank_opening),
    moneyRow('汇总', '银行流水净额', snapshot.bank_movements),
    moneyRow('汇总', '银行系统期末', snapshot.bank_closing_computed),
    moneyRow('汇总', '银行凭据期末', snapshot.bank_closing_declared,
      snapshot.bank_statement_balanced ? '与系统流水相符' : '与系统流水不符'),
    moneyRow('汇总', '总账期初', snapshot.book_opening),
    moneyRow('汇总', '总账分录净额', snapshot.book_movements),
    moneyRow('汇总', '总账期末', snapshot.book_closing),
    moneyRow('汇总', '调整后银行', snapshot.adjusted_bank),
    moneyRow('汇总', '调整后账面', snapshot.adjusted_book,
      snapshot.balanced ? '编制时两侧相符' : '编制时两侧不符')
  ]
  for (const item of snapshot.bank_unmatched) rows.push([
    cell('银行未勾对'), cell('银行流水'), cell(item.occurred_on ?? ''), cell(item.id),
    cell(item.transaction_id ?? ''), amountCell(item.amount), cell(item.counterparty ?? '')
  ].join(','))
  for (const item of snapshot.book_unmatched) rows.push([
    cell('总账未勾对'), cell('总账分录'), cell(item.journal_date ?? ''), cell(item.journal_id ?? item.id),
    cell(item.reference ?? ''), amountCell(item.amount), cell(item.summary ?? '')
  ].join(','))
  for (const item of [...snapshot.bank_opening_unmatched, ...snapshot.book_opening_unmatched]) rows.push([
    cell('期初未达'), cell(item.side === 'bank' ? '银行已记' : '企业已记'), cell(item.occurred_on),
    cell(item.id), cell(item.reference), amountCell(item.amount), cell(item.description)
  ].join(','))
  for (const item of snapshot.matched_evidence) rows.push(row('已勾对来源', '分组', '', item.group_id, '', '',
    `银行流水 #${item.bank_line_ids.join('、')}；总账分录 #${item.journal_line_ids.join('、')}`))
  for (const item of snapshot.clearance_evidence) rows.push(row('期初核销来源', '核销', '', item.clearance_id,
    item.opening_item_id, '', `来源 #${item.source_ids.join('、')}`))
  for (const item of report.decisions) rows.push(row('复核记录', decision[item.action], item.created_at,
    item.created_by, item.id, '', `${item.created_by_name} · ${item.reason}`))
  return `\ufeff${rows.join('\r\n')}\r\n`
}
