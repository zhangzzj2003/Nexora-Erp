import { sourceDetails, detailSource, detailMoney } from './source-details.mjs'

// 使用项目同款 Remix 图标的路径，不为展示启动图标库或应用运行时。
const icons = {"home-4-line":{"body":"<path fill=\"currentColor\" d=\"M19 21H5a1 1 0 0 1-1-1v-9H1l10.327-9.388a1 1 0 0 1 1.346 0L23 11h-3v9a1 1 0 0 1-1 1m-6-2h5V9.157l-6-5.454l-6 5.454V19h5v-6h2z\"/>"},"archive-line":{"body":"<path fill=\"currentColor\" d=\"M3 10H2V4.003C2 3.449 2.455 3 2.992 3h18.016A.99.99 0 0 1 22 4.003V10h-1v10.002a.996.996 0 0 1-.993.998H3.993A.996.996 0 0 1 3 20.002zm16 0H5v9h14zM4 5v3h16V5zm5 7h6v2H9z\"/>"},"file-list-3-line":{"body":"<path fill=\"currentColor\" d=\"M19 22H5a3 3 0 0 1-3-3V3a1 1 0 0 1 1-1h14a1 1 0 0 1 1 1v12h4v4a3 3 0 0 1-3 3m-1-5v2a1 1 0 1 0 2 0v-2zm-2 3V4H4v15a1 1 0 0 0 1 1zM6 7h8v2H6zm0 4h8v2H6zm0 4h5v2H6z\"/>"},"shopping-cart-line":{"body":"<path fill=\"currentColor\" d=\"M4.005 16V4h-2V2h3a1 1 0 0 1 1 1v12h12.438l2-8H8.005V5h13.72a1 1 0 0 1 .97 1.243l-2.5 10a1 1 0 0 1-.97.757H5.004a1 1 0 0 1-1-1m2 7a2 2 0 1 1 0-4a2 2 0 0 1 0 4m12 0a2 2 0 1 1 0-4a2 2 0 0 1 0 4\"/>"},"money-dollar-box-line":{"body":"<path fill=\"currentColor\" d=\"M3.005 3.003h18a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1h-18a1 1 0 0 1-1-1v-16a1 1 0 0 1 1-1m1 2v14h16v-14zm4.5 9h5.5a.5.5 0 1 0 0-1h-4a2.5 2.5 0 1 1 0-5h1v-2h2v2h2.5v2h-5.5a.5.5 0 0 0 0 1h4a2.5 2.5 0 0 1 0 5h-1v2h-2v-2h-2.5z\"/>"},"building-4-line":{"body":"<path fill=\"currentColor\" d=\"M21 20h2v2H1v-2h2V3a1 1 0 0 1 1-1h16a1 1 0 0 1 1 1zm-2 0V4H5v16zM8 11h3v2H8zm0-4h3v2H8zm0 8h3v2H8zm5 0h3v2h-3zm0-4h3v2h-3zm0-4h3v2h-3z\"/>"},"settings-3-line":{"body":"<path fill=\"currentColor\" d=\"M3.34 17a10 10 0 0 1-.979-2.326a3 3 0 0 0 .003-5.347a10 10 0 0 1 2.5-4.337a3 3 0 0 0 4.632-2.674a10 10 0 0 1 5.007.003a3 3 0 0 0 4.632 2.671a10.06 10.06 0 0 1 2.503 4.336a3 3 0 0 0-.002 5.347a10 10 0 0 1-2.501 4.337a3 3 0 0 0-4.632 2.674a10 10 0 0 1-5.007-.002a3 3 0 0 0-4.631-2.672A10 10 0 0 1 3.339 17m5.66.196a5 5 0 0 1 2.25 2.77q.75.07 1.499.002a5 5 0 0 1 2.25-2.772a5 5 0 0 1 3.526-.564q.435-.614.748-1.298A5 5 0 0 1 18 12c0-1.26.47-2.437 1.273-3.334a8 8 0 0 0-.75-1.298A5 5 0 0 1 15 6.804a5 5 0 0 1-2.25-2.77q-.75-.071-1.5-.001A5 5 0 0 1 9 6.804a5 5 0 0 1-3.526.564q-.436.614-.747 1.298A5 5 0 0 1 6 12c0 1.26-.471 2.437-1.273 3.334a8 8 0 0 0 .75 1.298A5 5 0 0 1 9 17.196M12 15a3 3 0 1 1 0-6a3 3 0 0 1 0 6m0-2a1 1 0 1 0 0-2a1 1 0 0 0 0 2\"/>"},"refresh-line":{"body":"<path fill=\"currentColor\" d=\"M5.463 4.433A9.96 9.96 0 0 1 12 2c5.523 0 10 4.477 10 10c0 2.136-.67 4.116-1.81 5.74L17 12h3A8 8 0 0 0 6.46 6.228zm13.074 15.134A9.96 9.96 0 0 1 12 22C6.477 22 2 17.523 2 12c0-2.136.67-4.116 1.81-5.74L7 12H4a8 8 0 0 0 13.54 5.772z\"/>"},"moon-line":{"body":"<path fill=\"currentColor\" d=\"M10 7a7 7 0 0 0 12 4.9v.1c0 5.523-4.477 10-10 10S2 17.523 2 12S6.477 2 12 2h.1A6.98 6.98 0 0 0 10 7m-6 5a8 8 0 0 0 15.062 3.762A9 9 0 0 1 8.238 4.938A8 8 0 0 0 4 12\"/>"},"arrow-down-s-line":{"body":"<path fill=\"currentColor\" d=\"m12 13.171l4.95-4.95l1.414 1.415L12 16L5.636 9.636L7.05 8.222z\"/>"}}
const icon = name => `<svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true">${icons[name].body}</svg>`
const surfaces = {
  receipt: { title:'采购入库', group:'采购管理', description:'采购收货生成待入库单，仓库确认后增加库存；错误记录可填写原因冲销。', menu:['采购申请','采购订单','采购收货','采购入库','采购报表','采购退货'] },
  stock: { title:'库存台账', group:'仓库管理', description:'按仓库和物料核对每笔变动，保留来源单据及期初期末数量。', menu:['其他入库','仓库出库','库存总览','库存台账','仓库调拨','库存调整','库存报表','库存盘点'] },
  finance: { title:'应收应付来源', group:'财务管理', description:'业务确认后记录应收应付来源，数量和金额保留原始单据依据。', menu:['应收应付来源','订单余额','手工收付款','总账凭证','科目明细','试算平衡'] }
}
const groups = [['工作台首页','home-4-line'],['仓库管理','archive-line'],['基础资料','file-list-3-line'],['采购管理','shopping-cart-line'],['销售管理','shopping-cart-line'],['财务管理','money-dollar-box-line'],['生产管理','building-4-line'],['系统管理','settings-3-line']]
const cell = (text, key = '') => `<td class="vxe-body--column"${key ? ` data-display-item="${key}"` : ''}><div class="vxe-cell">${text}</div></td>`
function table(headers, widths, rows) {
  return `<div class="workspace-vxe-table"><table><colgroup>${widths.map(width=>`<col style="width:${width}">`).join('')}</colgroup><thead><tr>${headers.map(text=>`<th class="vxe-header--column"><div class="vxe-cell">${text}</div></th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`
}
function filters(key) {
  const labels = key==='receipt' ? [['搜索采购入库','单号、名称或物料']] : key==='stock'
    ? [['仓库','全部仓库'],['物料','全部物料'],['开始日期','2026-09-25'],['结束日期','2026-10-01'],['来源','全部来源']]
    : [['类别','全部类别'],['往来单位','全部往来单位']]
  // 筛选框仅复现原组件外观；展示区域 inert，不暗示它能够操作业务。
  return `<div class="workspace-table-toolbar"><div class="workspace-table-filters">${labels.map(([label,value])=>`<label>${label}<span class="display-field">${value}</span></label>`).join('')}</div>${key==='stock'?'<span class="display-query">查询台账</span>':''}</div>`
}
function records(key) {
  if (key==='receipt') {
    const details = sourceDetails.map(item=>`<span data-display-item="${item.key}" data-display-source="${detailSource(item)}">${item.zh} × ${item.quantity} 个 · 已退 0</span>`).join('')
    return table(['单据','状态','业务明细','操作'],['28%','120px','auto','280px'],[
      `<tr>${cell('<strong>#101 · 示例电子供应商 · 电子原料仓</strong><p class="muted">2026/10/1 16:00:00 · 创建人 示例管理员 · 采购订单 #101 · DEMO-RCPT-101</p>')}${cell('<span class="pill posted">已入库</span>')}${cell(`<div class="workspace-record-lines">${details}</div>`)}${cell('')}</tr>`
    ])
  }
  const rows = sourceDetails.map(item=>{
    const source=`采购入库 #101<small>明细 #${item.line}</small>`
    const time='2026/10/1 16:00:00<small>示例仓管</small>'
    const cells = key==='stock'
      ? [cell(time),cell('电子原料仓'),cell(`${item.sku} · ${item.zh}`,item.key),cell(source,item.key),cell(`+${item.quantity} 个`,item.key),cell(`${item.quantity} 个`)]
      : [cell(time),cell('应付'),cell('示例电子供应商'),cell(source,item.key),cell(`${item.sku} × ${item.quantity}`,item.key),cell(detailMoney(item.amount),item.key),cell('示例仓管')]
    return `<tr data-display-source="${detailSource(item)}">${cells.join('')}</tr>`
  })
  return key==='stock'
    ? table(['时间','仓库','物料','来源单据','变动','筛选范围结余'],['16%','14%','28%','19%','11%','12%'],rows)
    : table(['确认时间','类别','往来单位','来源单据','物料','金额变动','操作人'],['16%','9%','17%','20%','20%','10%','8%'],rows)
}
export function displayMarkup(key) {
  const item=surfaces[key]
  if (!item) throw new Error('未知官网展示页面')
  const side = groups.map(([label,name])=>`<div class="nav-group">${label==='工作台首页'
    ? `<button class="nav-item nav-home" type="button">${icon(name)}${label}</button>`
    : `<button class="side-category${label===item.group?' current':''}" type="button" aria-expanded="${label===item.group}"><span class="display-category">${icon(name)}${label}</span>${icon('arrow-down-s-line')}</button>${label===item.group?`<div class="nav-panel expanded"><div class="nav-list">${item.menu.map(title=>`<button class="nav-item${title===item.title?' active':''}" type="button">${icon('file-list-3-line')}${title}</button>`).join('')}</div></div>`:''}`}</div>`).join('')
  const tabs=['工作台首页','物料管理','采购入库','库存台账','生产成本','应收应付来源','总账凭证'].map(title=>`<span class="workspace-tab${title===item.title?' active':''}"><button type="button" class="workspace-tab-link">${title}</button><button type="button" class="workspace-tab-close">×</button></span>`).join('')
  // 直接输出 HTML，首帧就有完整界面；后续镜头只移动这一份 DOM，不套截图或另开应用。
  return `<div class="erp-display" data-display-canvas data-theme="light" aria-hidden="true" inert><header class="app-titlebar"><div class="app-titlebar-safe-area"><div class="app-titlebar-brand"><img src="../assets/brand.png" alt=""><strong>NEXORA <span>ERP</span></strong></div><div class="display-title-tools">${icon('refresh-line')}${icon('home-4-line')}<span>${item.group} › ${item.title}</span></div><span class="display-moon">${icon('moon-line')}</span></div></header><div class="display-shell"><aside class="sidebar"><div class="brand"><span class="brand-mark"><img src="../assets/brand.png" alt=""></span><div><strong>NEXORA</strong><small>联光 ERP · 团队工作台</small></div></div><div class="side-group">${side}</div><div class="sidebar-bottom"><span class="sidebar-account-avatar">人</span><span><strong>示例管理员</strong><small>管理员</small></span></div></aside><div class="content"><div class="content-body"><div class="workspace-tabs">${tabs}</div><div class="topbar"><div><p class="eyebrow">NEXORA WORKSPACE</p><h1>${item.title}</h1><p class="muted">${item.description}</p></div></div><section class="card workspace-table">${filters(key)}${records(key)}</section>${key==='stock'?`<section class="card display-balances"><h2>期初期末</h2>${table(['仓库','物料','期初','期末'],['20%','50%','15%','15%'],sourceDetails.map(d=>`<tr>${cell('电子原料仓')}${cell(d.sku+' · '+d.zh)}${cell('0 个')}${cell(d.quantity+' 个')}</tr>`))}</section>`:''}</div><div class="display-footer"><span>界面展示 · 示例数据</span><span>只读展示</span></div></div></div></div>`
}

