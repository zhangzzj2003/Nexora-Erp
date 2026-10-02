import { sourceImages, sourcePreviewMarkup } from './product-showcase.mjs'
import { catalog, initialState, transition, restoreState, total, lineTotal, sources, movements, balances } from './sandbox.mjs'

const escape = value => String(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])
export const money = value => `¥${BigInt(value) / 100n}.${String(BigInt(value) % 100n).padStart(2, '0')}`
const quantity = value => `${BigInt(value) / 1000n}.${String(BigInt(value) % 1000n).padStart(3, '0')}`.replace(/\.?0+$/, '') || '0'
const t = (lang, zh, en) => lang === 'en' ? en : zh
const label = (id, lang) => {
  const names = { 'SUP-A': ['供应商 A', 'Supplier A'], 'SUP-B': ['供应商 B', 'Supplier B'], 'WH-A': ['主仓库', 'Main warehouse'], 'WH-B': ['备料仓', 'Materials warehouse'], 'MAT-A': ['物料 A · 铝合金支架', 'Material A · Bracket'], 'MAT-B': ['物料 B · 紧固件', 'Material B · Fastener'], 'MAT-C': ['物料 C · 电机', 'Material C · Motor'], 'MAT-D': ['物料 D · 包装箱', 'Material D · Carton'] }
  return names[id]?.[lang === 'en' ? 1 : 0] || id
}
const icon = name => {
  const paths = { receipt: '<path d="M3 3h2l2 12h11l3-9H6M9 20h.01M18 20h.01"/>', stock: '<path d="m12 3 9 5v9l-9 5-9-5V8l9-5Zm0 9 9-4M12 12 3 8m9 4v10M7 6l10 5"/>', sales: '<path d="M4 10V5l8-3 8 3v5M4 10l8-3 8 3v11H4V10Zm5 11v-7h6v7"/>', production: '<path d="M3 21V9l6 3V6l6 6V9l6 3v9H3Zm3-5h2m3 0h2m3 0h2M15 4V2h3v6"/>', system: '<path d="m9 3 1-2h4l1 2 3 2 2 1v4l-2 1v4l2 1v4l-2 1-3 2-1 2h-4l-1-2-3-2-2-1v-4l2-1v-4L4 10V6l2-1 3-2Z"/><circle cx="12" cy="12" r="3"/>', finance: '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M15 8h-4a2 2 0 0 0 0 4h2a2 2 0 0 1 0 4H9m3-10v12"/>', expand: '<path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/>', reset: '<path d="M3 10a9 9 0 1 1 1 7M3 4v6h6"/>', plus: '<path d="M12 5v14M5 12h14"/>', arrow: '<path d="M5 12h14m-6-6 6 6-6 6"/>', trash: '<path d="M4 6h16M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7m4-7v7"/>' }
  return `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.arrow}</svg>`
}
const options = (ids, selected, lang, all = '') => `${all ? `<option value="">${all}</option>` : ''}${ids.map(id => `<option value="${escape(id)}" ${id === selected ? 'selected' : ''}>${escape(label(id, lang))}</option>`).join('')}`
const button = (action, text, extra = '') => `<button type="button" data-action="${action}" ${extra}>${text}</button>`
const noRows = (cols, lang) => `<tr><td colspan="${cols}" class="empty-state">${t(lang, '暂无匹配记录，试试调整筛选条件。', 'No matching records. Try adjusting the filters.')}</td></tr>`
const field = (title, html, key = '') => `<label class="demo-field">${title}${html}${key ? `<span class="field-error" data-error="${key}"></span>` : ''}</label>`
const attempt = fn => { try { return money(fn()) } catch { return '—' } }
const pageSizes = { receipt: 2, stock: 4, balance: 3, source: 2, payment: 3 }
export function pageItems(items, requested = 0, size = 2) {
  if (!Number.isSafeInteger(size) || size < 1) throw new RangeError('Invalid page size')
  const count = Math.max(1, Math.ceil(items.length / size))
  const page = Math.max(0, Math.min(count - 1, Number.isFinite(requested) ? Math.trunc(requested) : 0))
  const start = page * size
  return { page, count, total: items.length, rows: items.slice(start, start + size).map((item, index) => ({ item, index: start + index })) }
}
const pagination = (group, view, lang) => {
  if (view.count === 1) return ''
  const title = { receipt: ['物料明细', 'Materials'], stock: ['库存流水', 'Stock movements'], balance: ['库存余额', 'Stock balances'], source: ['应付明细', 'Payable details'], payment: ['付款记录', 'Payment history'] }[group][lang === 'en' ? 1 : 0]
  const control = (step, text) => `<button type="button" data-page-group="${group}" data-page="${view.page + step}" data-page-direction="${step}" aria-label="${text} ${title}" ${(step < 0 ? view.page === 0 : view.page === view.count - 1) ? 'disabled' : ''}>${text}</button>`
  return `<nav class="demo-pagination" aria-label="${title} ${t(lang, '分页', 'pages')}"><span>${view.page + 1} / ${view.count} · ${view.total} ${t(lang, '条', 'rows')}</span><span>${control(-1, t(lang, '上一页', 'Previous'))}${control(1, t(lang, '下一页', 'Next'))}</span></nav>`
}
export const names = lang => [t(lang, '采购入库', 'Purchase receipt'), t(lang, '库存流水', 'Stock movements'), t(lang, '应付来源', 'Payable sources')]

function receiptBody(state, lang, pages) {
  const r = state.receipts.find(r => r.id === state.selectedId), locked = r.status === 'posted'
  const view = pageItems(r.lines, pages.receipt, pageSizes.receipt)
  return `<div class="window-heading"><div><p>${t(lang, '从一张单据开始', 'Start with a document')}</p><h2 tabindex="-1">${names(lang)[0]}</h2></div><span class="status-chip ${locked ? '' : 'draft'}">${locked ? t(lang, '已入库', 'Received') : t(lang, '草稿', 'Draft')}</span></div>
  <div class="demo-toolbar"><label>${t(lang, '单据', 'Document')}<select data-select-receipt aria-label="${t(lang, '选择入库单', 'Select receipt')}">${state.receipts.map(row => `<option value="${row.id}" ${row.id === r.id ? 'selected' : ''}>${row.id}${row.status === 'draft' ? t(lang, ' · 草稿', ' · Draft') : ''}</option>`).join('')}</select></label>${button('new', `${icon('plus')}${t(lang, '新建', 'New')}`)}${button('copy', t(lang, '复制为草稿', 'Copy as draft'))}</div>
  <form data-form="receipt" novalidate><div class="receipt-sheet" data-posted="${locked}"><div class="sheet-title"><h3>${t(lang, '单据信息', 'Document details')}</h3><strong data-anchor="receipt">${r.id}<i class="anchor-dot"></i></strong></div><div class="demo-fields">
  ${field(t(lang, '供应商', 'Supplier'), `<select name="supplier" data-edit="supplier" ${locked ? 'disabled' : ''}>${options(catalog.suppliers, r.supplier, lang)}</select>`, 'supplier')}
  ${field(t(lang, '入库仓库', 'Warehouse'), `<select name="warehouse" data-edit="warehouse" ${locked ? 'disabled' : ''}>${options(catalog.warehouses, r.warehouse, lang)}</select>`, 'warehouse')}
  ${field(t(lang, '单据日期', 'Document date'), `<input type="date" name="date" data-edit="date" value="${escape(r.date)}" ${locked ? 'readonly' : ''}>`, 'date')}
  ${field(t(lang, '单据状态', 'Status'), `<span class="readonly-value">${locked ? t(lang, '库存与应付已关联', 'Stock and payable linked') : t(lang, '确认后生成库存与应付', 'Confirm to update stock and payable')}</span>`)}
  </div><h3>${t(lang, '物料明细', 'Material details')}</h3><div class="demo-table-scroll"><table class="sandbox-table receipt-lines"><thead><tr><th scope="col">${t(lang, '物料', 'Material')}</th><th scope="col">${t(lang, '数量', 'Quantity')}</th><th scope="col">${t(lang, '单价', 'Unit price')}</th><th scope="col">${t(lang, '金额', 'Amount')}</th>${locked ? '' : `<th scope="col"><span class="visually-hidden">${t(lang, '操作', 'Actions')}</span></th>`}</tr></thead><tbody>${view.rows.map(({item: line, index}) => `<tr><td data-label="${t(lang, '物料', 'Material')}"><select data-edit="material" data-index="${index}" aria-label="${t(lang, '物料', 'Material')} ${index + 1}" ${locked ? 'disabled' : ''}>${options(catalog.materials, line.material, lang)}</select></td><td data-label="${t(lang, '数量', 'Quantity')}"><input inputmode="decimal" data-edit="quantity" data-index="${index}" aria-label="${t(lang, '数量', 'Quantity')} ${index + 1}" value="${escape(line.quantity)}" ${locked ? 'readonly' : ''}><span class="field-error" data-error="quantity-${index}"></span></td><td data-label="${t(lang, '单价', 'Unit price')}"><input inputmode="decimal" data-edit="price" data-index="${index}" aria-label="${t(lang, '单价', 'Unit price')} ${index + 1}" value="${escape(line.price)}" ${locked ? 'readonly' : ''}><span class="field-error" data-error="price-${index}"></span></td><td class="numeric" data-label="${t(lang, '金额', 'Amount')}" data-line-total="${index}">${attempt(() => lineTotal(line, index))}</td>${locked ? '' : `<td>${button('removeLine', icon('trash'), `data-index="${index}" aria-label="${t(lang, '删除物料', 'Remove material')} ${index + 1}" ${r.lines.length === 1 ? 'disabled' : ''}`)}</td>`}</tr>`).join('')}</tbody></table></div>${pagination('receipt', view, lang)}<span class="field-error" data-error="lines"></span>
  <div class="sheet-footer">${locked ? `<span>${t(lang, '已确认单据保留原始记录', 'Confirmed records are preserved')}</span>` : button('addLine', `${icon('plus')}${t(lang, '添加物料', 'Add material')}`)}<span>${t(lang, '合计', 'Total')} <strong data-receipt-total>${attempt(() => total(r))}</strong></span></div></div>
  <div class="form-actions"><p>${locked ? t(lang, '复制这张单据，体验库存和应付联动。', 'Copy this receipt to explore connected stock and payables.') : t(lang, '草稿暂不改变库存与应付。', 'Drafts do not change stock or payables.')}</p>${locked ? button('copy', `${t(lang, '试着开一张', 'Create your own')}${icon('arrow')}`, 'class="demo-primary"') : `<button type="submit" class="demo-primary">${t(lang, '确认入库', 'Confirm receipt')}${icon('arrow')}</button>`}</div></form>`
}
function stockBody(state, lang, filters, pages) {
  const rows = movements(state).filter(r => (!filters.warehouse || r.warehouse === filters.warehouse) && (!filters.material || r.material === filters.material) && r.receiptId.toLowerCase().includes(filters.source.toLowerCase()))
  const stock = balances(state).filter(r => (!filters.warehouse || r.warehouse === filters.warehouse) && (!filters.material || r.material === filters.material))
  const view = pageItems(rows, pages.stock, pageSizes.stock), stockView = pageItems(stock, pages.balance, pageSizes.balance)
  return `<div class="window-heading"><div><p>${t(lang, '每一次变化，都有来源', 'Every movement has a source')}</p><h2 tabindex="-1">${names(lang)[1]}</h2></div></div><div class="demo-filters">
  ${field(t(lang, '仓库', 'Warehouse'), `<select data-filter="warehouse" data-filter-group="stock">${options(catalog.warehouses, filters.warehouse, lang, t(lang, '全部仓库', 'All warehouses'))}</select>`)}
  ${field(t(lang, '物料', 'Material'), `<select data-filter="material" data-filter-group="stock">${options(catalog.materials, filters.material, lang, t(lang, '全部物料', 'All materials'))}</select>`)}
  ${field(t(lang, '来源单号', 'Source number'), `<input type="search" data-filter="source" data-filter-group="stock" value="${escape(filters.source)}" placeholder="DEMO-001">`)}</div>
  <div class="demo-table-scroll"><table class="sandbox-table movement-table"><thead><tr><th scope="col">${t(lang, '日期 / 物料', 'Date / material')}</th><th scope="col">${t(lang, '仓库', 'Warehouse')}</th><th scope="col">${t(lang, '变动', 'Change')}</th><th scope="col">${t(lang, '结存', 'Balance')}</th><th scope="col">${t(lang, '来源单据', 'Source')}</th></tr></thead><tbody>${view.rows.map(({item: r, index}) => `<tr class="${r.receiptId === state.selectedId ? 'linked-row' : ''}"><td data-label="${t(lang, '日期 / 物料', 'Date / material')}"><small>${r.date}</small>${escape(label(r.material, lang))}</td><td data-label="${t(lang, '仓库', 'Warehouse')}">${escape(label(r.warehouse, lang))}</td><td class="numeric positive" data-label="${t(lang, '变动', 'Change')}">+${quantity(r.quantity)}</td><td class="numeric" data-label="${t(lang, '结存', 'Balance')}">${quantity(r.balance)}</td><td data-label="${t(lang, '来源单据', 'Source')}"><button type="button" class="source-link-button" data-action="trace" data-id="${r.receiptId}" ${r.receiptId === state.selectedId && !view.rows.some(row => row.index < index && row.item.receiptId === state.selectedId) ? 'data-anchor="stock"' : ''}>${r.receiptId}${icon('arrow')}</button></td></tr>`).join('') || noRows(5, lang)}${rows.length ? Array.from({ length: Math.max(0, 6 - view.rows.length) }, () => `<tr class="movement-placeholder" aria-hidden="true">${Array.from({length: 5}, () => '<td><span></span></td>').join('')}</tr>`).join('') : ''}</tbody></table></div>${pagination('stock', view, lang)}
  <div class="stock-balances"><h3>${t(lang, '当前库存余额', 'Current stock balances')}</h3>${stock.length ? stockView.rows.map(({item: r}) => `<div><span>${escape(label(r.warehouse, lang))} · ${escape(label(r.material, lang))}</span><strong>${quantity(r.quantity)}</strong></div>`).join('') : `<p>${t(lang, '该条件下暂无库存。', 'No stock for these filters.')}</p>`}${pagination('balance', stockView, lang)}</div><p class="window-note">${t(lang, '演示期初为 0；库存余额按仓库和物料汇总。', 'Opening stock is 0. Balances are grouped by warehouse and material.')}</p>`
}
function financeBody(state, lang, filters, paymentId, pages) {
  const all = sources(state)
  const rows = all.filter(r => (!filters.supplier || r.supplier === filters.supplier) && (!filters.status || r.paymentStatus === filters.status) && r.id.toLowerCase().includes(filters.source.toLowerCase()))
  const selected = rows.find(r => r.id === paymentId) || rows.find(r => r.id === state.selectedId) || rows[0]
  const detailView = pageItems(selected?.lines || [], pages.source, pageSizes.source)
  const paymentView = pageItems(state.payments.filter(p => p.receiptId === selected?.id), pages.payment, pageSizes.payment)
  const statusName = status => ({ unpaid: t(lang, '未付', 'Unpaid'), partial: t(lang, '部分付款', 'Part paid'), paid: t(lang, '已结清', 'Paid') })[status]
  return `<div class="window-heading"><div><p>${t(lang, '业务发生，来源可查', 'Amounts with a traceable origin')}</p><h2 tabindex="-1">${names(lang)[2]}</h2></div></div><div class="demo-filters finance-filters">
  ${field(t(lang, '供应商', 'Supplier'), `<select data-filter="supplier" data-filter-group="finance">${options(catalog.suppliers, filters.supplier, lang, t(lang, '全部供应商', 'All suppliers'))}</select>`)}
  ${field(t(lang, '付款状态', 'Payment status'), `<select data-filter="status" data-filter-group="finance"><option value="">${t(lang, '全部状态', 'All statuses')}</option>${['unpaid', 'partial', 'paid'].map(status => `<option value="${status}" ${filters.status === status ? 'selected' : ''}>${statusName(status)}</option>`).join('')}</select>`)}
  ${field(t(lang, '来源单号', 'Source number'), `<input type="search" data-filter="source" data-filter-group="finance" value="${escape(filters.source)}" placeholder="DEMO-001">`)}</div>
  <label class="payable-picker">${t(lang, '应付单据', 'Payable document')}<select data-select-payable>${rows.map(r => `<option value="${r.id}" ${r.id === selected?.id ? 'selected' : ''}>${r.id} · ${statusName(r.paymentStatus)}</option>`).join('') || `<option value="">${t(lang, '暂无匹配单据', 'No matching document')}</option>`}</select></label>
  ${selected ? `<div class="payable-detail"><div class="payable-summary"><p>${t(lang, '来源单据', 'Source document')}</p><button class="source-link-button" type="button" data-action="trace" data-id="${selected.id}" data-anchor="finance">${selected.id}${icon('arrow')}</button><p>${escape(label(selected.supplier, lang))}</p><p class="payable-label">${t(lang, '应付金额', 'Payable amount')}</p><strong class="payable-amount">${money(selected.amount)}</strong><div class="payment-totals"><div><span>${t(lang, '已付', 'Paid')}</span><strong>${money(selected.paid)}</strong></div><div><span>${t(lang, '未付', 'Remaining')}</span><strong>${money(selected.remaining)}</strong></div></div><div class="overview-source-lines">${detailView.rows.map(({item: line}) => `<div class="source-detail-line"><span>${escape(label(line.material, lang).split(' · ')[0])}<small>${escape(line.quantity)} × ¥${escape(line.price)}</small></span><strong>${money(lineTotal(line))}</strong></div>`).join('')}</div><button type="button" data-focus="finance" class="overview-focus-action demo-primary">${t(lang, '登记模拟付款', 'Try a payment')}${icon('arrow')}</button><details data-detail="source"><summary>${t(lang, '查看物料明细', 'Material details')}</summary>${detailView.rows.map(({item: line}) => `<div class="source-detail-line"><span>${escape(label(line.material, lang))}<small>${escape(line.quantity)} × ¥${escape(line.price)}</small></span><strong>${money(lineTotal(line))}</strong></div>`).join('')}${pagination('source', detailView, lang)}</details></div><div class="payment-editor">
  <form data-form="payment" data-id="${selected.id}" novalidate>${field(t(lang, '模拟付款金额', 'Demo payment amount'), `<input name="payment" inputmode="decimal" placeholder="${money(selected.remaining).slice(1)}" ${selected.remaining === 0 ? 'disabled' : ''}>`, 'payment')}<div class="payment-actions">${button('payAll', t(lang, '付清剩余', 'Pay remaining'), `data-id="${selected.id}" ${selected.remaining === 0 ? 'disabled' : ''}`)}<button type="submit" class="demo-primary" ${selected.remaining === 0 ? 'disabled' : ''}>${t(lang, '登记付款', 'Record payment')}</button></div></form>
  <details class="payment-history" ${state.payments.some(p => p.receiptId === selected.id) ? 'open' : ''}><summary>${t(lang, '付款记录', 'Payment history')} (${state.payments.filter(p => p.receiptId === selected.id).length})</summary>${paymentView.rows.map(({item: p}) => `<div><span>${p.id}</span><strong>${money(p.amount)}</strong></div>`).join('') || `<p>${t(lang, '还没有模拟付款。', 'No demo payments yet.')}</p>`}${pagination('payment', paymentView, lang)}</details></div></div>` : `<div class="empty-state">${t(lang, '没有匹配的应付来源。确认入库或调整筛选后查看。', 'No payable source matches. Confirm a receipt or adjust filters.')}</div>`}`
}
const defaultFilters = () => ({ stock: { warehouse: '', material: '', source: '' }, finance: { supplier: '', status: '', source: '' } })
export function sandboxBody(key, state, lang, filters = defaultFilters(), paymentId = state.selectedId, pages = {}) {
  return key === 'receipt' ? receiptBody(state, lang, pages) : key === 'stock' ? stockBody(state, lang, filters.stock, pages) : financeBody(state, lang, filters.finance, paymentId, pages)
}
export function sandboxMarkup(lang = 'zh-CN') {
  const state = initialState(), keys = ['receipt', 'stock', 'finance']
  const sidebar = key => ['receipt', 'stock', 'sales', 'production', 'finance'].map(target => {
    const text = ({receipt: ['采购', 'Purchase'], stock: ['库存', 'Stock'], sales: ['销售', 'Sales'], production: ['生产', 'Production'], finance: ['财务', 'Finance']})[target][lang === 'en' ? 1 : 0]
    return keys.includes(target) ? `<button type="button" data-focus="${target}" aria-label="${text}" class="${target === key ? 'selected' : ''}">${icon(target)}<span>${text}</span></button>` : `<span class="sidebar-context">${icon(target)}<span>${text}</span></span>`
  }).join('')
  return keys.map((key, index) => `<section class="demo-window ${key}-panel" data-window="${key}" aria-label="${names(lang)[index]}"><div class="window-viewport">${sourcePreviewMarkup(sourceImages[index], lang)}<div class="window-chrome"><span class="traffic-lights" aria-hidden="true"><i></i><i></i><i></i></span><span>Nexora ERP</span><span class="window-demo-label">${t(lang, '交互演示', 'Interactive demo')}</span><button type="button" data-focus="${key}" aria-label="${t(lang, '放大操作', 'Expand')} ${names(lang)[index]}" title="${t(lang, '放大操作', 'Expand to interact')}">${icon('expand')}</button></div><div class="app-layout"><nav class="app-sidebar" aria-label="${names(lang)[index]} ${t(lang, '演示导航', 'demo navigation')}"><span class="app-logo"><img src="../assets/brand.png" alt="" width="28" height="28"><span>Nexora ERP</span></span>${sidebar(key)}<span class="sidebar-bottom">${icon('system')}<span>${t(lang, '系统', 'System')}</span></span></nav><div class="sandbox-content" data-content="${key}">${sandboxBody(key, state, lang, defaultFilters(), state.selectedId)}</div></div><div class="window-base" aria-hidden="true"></div></div></section>`).join('')
}
const errors = {
  number: ['请输入有效数字，数量最多 3 位小数，金额最多 2 位。', 'Enter a valid number: up to 3 decimals for quantity, 2 for money.'], positive: ['请输入大于 0 的数值。', 'Enter a value greater than zero.'], tooLarge: ['数值过大，请减小数值后重试。', 'Value is too large. Enter a smaller value.'], supplier: ['请选择供应商。', 'Select a supplier.'], warehouse: ['请选择仓库。', 'Select a warehouse.'], date: ['请输入有效日期。', 'Enter a valid date.'], lines: ['至少保留一行物料。', 'Keep at least one material line.'], material: ['请选择物料。', 'Select a material.'], missing: ['单据不存在，请重新选择。', 'Document not found. Select it again.'], draftPayment: ['请先确认入库。', 'Confirm the receipt first.'], overpayment: ['付款金额不能超过剩余未付金额。', 'Payment cannot exceed the remaining balance.'], locked: ['已确认单据不能修改，请复制为新草稿。', 'Confirmed receipts are read-only. Copy as a draft.']
}
export function mountSandbox(scene, lang = 'zh-CN') {
  let state = initialState(), filters = defaultFilters(), paymentId = state.selectedId
  const pages = { receipt: 0, stock: 0, balance: 0, source: 0, payment: 0 }
  const key = 'nexora-demo-language-transfer'
  const win = scene.ownerDocument.defaultView
  try {
    const transfer = JSON.parse(win.sessionStorage.getItem(key) || 'null')
    win.sessionStorage.removeItem(key)
    if (transfer?.language === lang && win.performance.getEntriesByType('navigation')[0]?.type === 'navigate') state = restoreState(transfer.state)
  } catch { /* 隐私模式或无效临时数据不影响演示。 */ }
  paymentId = state.selectedId
  const emit = (name, detail) => scene.dispatchEvent(new win.CustomEvent(name, { detail }))
  const status = scene.querySelector('[data-demo-status]')
  const notify = message => { status.textContent = message }
  const render = () => {
    const active = scene.ownerDocument.activeElement
    const content = active?.closest('[data-content]')?.dataset.content
    const marker = active?.dataset.edit ? `[data-edit="${active.dataset.edit}"]${active.dataset.index != null ? `[data-index="${active.dataset.index}"]` : ''}` : active?.dataset.filter ? `[data-filter="${active.dataset.filter}"]` : null
    const control = marker || (active?.matches('[data-select-receipt]') ? '[data-select-receipt]' : active?.matches('[data-select-payable]') ? '[data-select-payable]' : active?.dataset.action ? `[data-action="${active.dataset.action}"]${active.dataset.index != null ? `[data-index="${active.dataset.index}"]` : ''}` : active?.type === 'submit' ? `form[data-form="${active.closest('form').dataset.form}"] button[type="submit"]` : null)
    const selection = active?.selectionStart
    const sourceOpen = scene.querySelector('[data-content=finance] [data-detail=source]')?.open
    for (const el of scene.querySelectorAll('[data-content]')) el.innerHTML = sandboxBody(el.dataset.content, state, lang, filters, paymentId, pages)
    if (sourceOpen) { const detail = scene.querySelector('[data-content=finance] [data-detail=source]'); if (detail) detail.open = true }
    if (content && control) {
      let target = scene.querySelector(`[data-content="${content}"] ${control}`)
      if (!target || target.disabled) target = scene.querySelector(`[data-content="${content}"] h2`)
      target?.focus({ preventScroll: true })
      if (selection != null && target?.setSelectionRange) { try { target.setSelectionRange(selection, selection) } catch { /* 日期与下拉框没有文本光标。 */ } }
    }
    emit('sandbox:render', {})
  }
  const run = (action, message = '') => {
    try {
      state = transition(state, action)
      if (['new', 'copy', 'post', 'reset'].includes(action.type)) paymentId = state.selectedId
      if (['new', 'copy', 'select', 'post', 'reset'].includes(action.type)) {
        pages.receipt = 0; pages.source = 0; pages.payment = 0
        pages.stock = Math.max(0, Math.floor(movements(state).findIndex(r => r.receiptId === state.selectedId) / pageSizes.stock))
      }
      if (action.type === 'addLine') pages.receipt = Math.floor((state.receipts.find(r => r.id === state.selectedId).lines.length - 1) / pageSizes.receipt)
      if (action.type === 'pay') pages.payment = Math.floor((state.payments.filter(p => p.receiptId === (action.id || state.selectedId)).length - 1) / pageSizes.payment)
      render()
      notify(message)
      return true
    } catch (error) {
      const message = (errors[error.code] || [ '操作未完成，请检查输入。', 'Could not complete the action. Check your input.' ])[lang === 'en' ? 1 : 0]
      const rowError = /^(?:quantity|price|material)-(\d+)$/.exec(error.field)
      if (rowError) { pages.receipt = Math.floor(Number(rowError[1]) / pageSizes.receipt); render() }
      const target = scene.querySelector(`[data-error="${error.field}"]`)
      if (target) {
        target.textContent = message
        const input = target.parentElement.querySelector('input,select')
        input?.setAttribute('aria-invalid', 'true')
        target.id = `error-${error.field}`
        input?.setAttribute('aria-describedby', target.id)
        input?.focus({ preventScroll: true })
      }
      notify(message)
      emit('sandbox:render', {})
      return false
    }
  }
  const onInput = event => {
    const input = event.target
    if (input.dataset.edit) {
      state = transition(state, { type: 'edit', field: input.dataset.edit, index: Number(input.dataset.index), value: input.value })
      input.removeAttribute('aria-invalid')
      const r = state.receipts.find(r => r.id === state.selectedId)
      scene.querySelector('[data-receipt-total]').textContent = attempt(() => total(r))
      scene.querySelectorAll('[data-line-total]').forEach(el => { el.textContent = attempt(() => lineTotal(r.lines[Number(el.dataset.lineTotal)])) })
      const error = input.parentElement.querySelector('.field-error')
      if (error) error.textContent = ''
      emit('sandbox:render', {})
    }
    if (input.dataset.filter) {
      filters[input.dataset.filterGroup][input.dataset.filter] = input.value
      if (input.dataset.filterGroup === 'stock') { pages.stock = 0; pages.balance = 0 }
      else { pages.source = 0; pages.payment = 0 }
      render()
    }
  }
  const onChange = event => {
    const input = event.target
    if (input.matches('[data-select-receipt]')) { paymentId = input.value; run({ type: 'select', id: input.value }) }
    if (input.matches('[data-select-payable]')) { paymentId = input.value; pages.source = 0; pages.payment = 0; render() }
  }
  const onClick = event => {
    const pager = event.target.closest('[data-page-group]')
    if (pager) {
      const page = Number(pager.dataset.page), group = pager.dataset.pageGroup
      if (Object.hasOwn(pages, group) && Number.isSafeInteger(page) && page >= 0) {
        pages[group] = page; render()
        scene.querySelector(`[data-content="${group === 'receipt' ? 'receipt' : ['stock', 'balance'].includes(group) ? 'stock' : 'finance'}"] h2`)?.focus({ preventScroll: true })
      }
      return
    }
    const target = event.target.closest('[data-action]')
    if (!target) return
    const type = target.dataset.action
    if (type === 'trace') { run({ type: 'select', id: target.dataset.id }); emit('sandbox:focus', { key: 'receipt' }); return }
    if (type === 'reset') { filters = defaultFilters(); for (const group of Object.keys(pages)) pages[group] = 0; run({ type }, t(lang, '演示已重置。', 'Demo reset.')); return }
    if (type === 'payAll') {
      const source = sources(state).find(r => r.id === target.dataset.id)
      if (source) run({ type: 'pay', id: source.id, amount: money(source.remaining).slice(1) }, t(lang, '模拟付款已登记。', 'Demo payment recorded.'))
      return
    }
    run({ type, index: Number(target.dataset.index) })
    if (type === 'new' || type === 'copy') emit('sandbox:focus', { key: 'receipt' })
  }
  const onSubmit = event => {
    const form = event.target.closest('[data-form]')
    if (!form) return
    event.preventDefault()
    if (form.dataset.form === 'receipt') run({ type: 'post' }, t(lang, '已确认入库，库存与应付已同步。', 'Receipt confirmed. Stock and payable updated.'))
    else run({ type: 'pay', id: form.dataset.id, amount: form.elements.payment.value }, t(lang, '模拟付款已登记。', 'Demo payment recorded.'))
  }
  const onLanguage = event => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
    const link = event.target.closest('a.language')
    if (!link) return
    try { win.sessionStorage.setItem(key, JSON.stringify({ language: link.hreflang, state })) } catch { /* 存储不可用时仍允许语言导航。 */ }
  }
  scene.addEventListener('input', onInput)
  scene.addEventListener('change', onChange)
  scene.addEventListener('click', onClick)
  scene.addEventListener('submit', onSubmit)
  scene.ownerDocument.addEventListener('click', onLanguage)
  render()
  scene.classList.add('sandbox-ready')
  return { getState: () => structuredClone(state), destroy() {
    scene.removeEventListener('input', onInput); scene.removeEventListener('change', onChange); scene.removeEventListener('click', onClick); scene.removeEventListener('submit', onSubmit)
    scene.ownerDocument.removeEventListener('click', onLanguage)
  } }
}
