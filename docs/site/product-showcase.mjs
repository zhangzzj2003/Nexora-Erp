import { sourceDetails, detailImageStyle, detailTargetStyle, detailSource, detailMoney } from './source-details.mjs'

// 截图标题与优势说明集中维护；中英文网站使用同一批中文应用界面素材。
export const showcaseImages = [
  { key: 'home', file: 'home.png', zh: ['工作台首页', '从业务净额、库存与待办，看清当前经营状态。'], en: ['Workspace overview', 'Review business amounts, inventory and current tasks together.'] },
  { key: 'materials', file: 'materials.png', zh: ['电子生产物料', '分类、规格、封装与制造商料号，让物料档案贴近生产。'], en: ['Electronic materials', 'Categories, specifications, packages and manufacturer part numbers in one record.'] },
  { key: 'inventory', file: 'inventory.png', zh: ['库存台账与来源', '按仓库和物料核对每笔变动，保留单据来源与期初期末。'], en: ['Inventory and origins', 'Reconcile movements by warehouse and material, with source documents and opening and closing quantities.'] },
  { key: 'production', file: 'production.png', zh: ['生产成本归集', '材料、人工与制造费用分别归集，查看工单成本及领料来源。'], en: ['Production costs', 'Review material, labor and overhead costs by work order, with material issue origins.'] },
  { key: 'journals', file: 'journals.png', zh: ['业务与总账衔接', '从业务来源生成凭证草稿，独立审核后过账，保留原始依据。'], en: ['Business and ledger', 'Generate journal drafts from business sources, independently review them, then post with the original evidence preserved.'] },
]

// 三窗复用同一套真实截图；不把静态界面描述成可编辑应用。
export const sourceImages = [
  { key: 'receipt', file: 'receipts.png', highRes: 'receipts@3x.png', zh: ['采购入库', '确认原料进入电子原料仓'], en: ['Purchase receipts', 'Confirmed materials in the electronics warehouse'] },
  { key: 'stock', file: 'inventory.png', highRes: 'inventory@3x.png', zh: ['库存台账', '数量变动保留采购入库来源'], en: ['Inventory ledger', 'Movements preserve the purchase receipt origin'] },
  { key: 'finance', file: 'sources.png', highRes: 'sources@3x.png', zh: ['应收应付来源', '同一入库形成 4,800 元应付来源'], en: ['Financial origins', 'The same receipt creates a CNY 4,800 payable source'] },
]

export function sourcePreviewMarkup(item, language) {
  const en = language === 'en', [title] = item[en ? 'en' : 'zh']
  const detail = sourceDetails[0]
  const label = en ? {receipt:'Received quantity',stock:'Inventory movement',finance:'Payable amount'}[item.key] : {receipt:'入库数量',stock:'库存变动',finance:'应付金额'}[item.key]
  const value = item.key === 'finance' ? detailMoney(detail.amount) : `${item.key === 'stock' ? '+' : ''}${detail.quantity} ${en ? 'units' : '个'}`
  // 完整工作台作为底图，真实明细只在原工作区内放大；导航、标签和侧栏始终保留。
  const image = item.highRes
  return `<div class="real-interface" data-detail-key="${item.key}"><div class="real-app-shell" aria-hidden="true" style="background-image:url('../assets/screenshots/${image}')"></div><div class="real-workspace-mask" aria-hidden="true"></div><a class="product-image-link real-detail-image" data-image-ready="false" style="${detailImageStyle(item.key,detail)}" href="../assets/screenshots/${image}" data-product-image data-image-title="${title}" aria-label="${en ? 'View full image' : '查看大图'}: ${title}"><img src="../assets/screenshots/${image}" alt="${title} · ${en ? 'Current interface preview · Sample data' : '当前界面预览 · 示例数据'}" width="5400" height="3600" loading="lazy" decoding="async"><span class="real-item-target" data-real-anchor="${item.key}" data-source-id="${detailSource(detail)}" style="${detailTargetStyle(item.key,detail)}">${en ? detail.en : detail.zh} · ${detail.sku} · ${en ? 'Purchase receipt' : '采购入库'} #101</span><span class="image-error" role="status" hidden>${en ? 'Image unavailable. Open the original image or reload.' : '图片暂时无法加载，请打开原图或刷新页面。'}</span><span class="image-enlarge">${en ? 'Full interface' : '完整界面'} ↗</span></a><div class="real-source-caption"><div><strong data-detail-name>${en ? detail.en : detail.zh}</strong><span data-detail-sku>${detail.sku}</span></div><div><span>${label}</span><strong data-detail-value>${value}</strong></div></div><p class="real-preview-note">${en ? 'Current interface preview · Sample data · Detail enlarged' : '当前界面预览 · 示例数据 · 工作区明细放大'}</p></div>`
}

export function showcaseMarkup(language) {
  const en = language === 'en'
  const badge = en ? 'Current interface preview · Sample data' : '当前界面预览 · 示例数据'
  const heading = en ? 'A workspace built around your business.' : '让业务有联系，也让工作有全貌。'
  const intro = en ? 'Current application components, shown with a fictional control-board example. The application interface is currently Chinese.' : '当前项目真实组件，搭配虚构的控制板业务示例。看见日常工作，也看见每一笔记录的来源。'
  const enlarge = en ? 'View full image' : '查看大图'
  const failed = en ? 'Image unavailable. Open the original image or reload the page.' : '图片暂时无法加载，请打开原图或刷新页面。'
  const figures = showcaseImages.map((item, index) => {
    const [title, description] = item[en ? 'en' : 'zh']
    return `<figure class="product-shot${index === 0 ? ' product-shot-main' : ''}" data-orbit-card id="preview-${item.key}"><a class="product-image-link" href="../assets/screenshots/${item.file}" data-product-image aria-label="${en ? `View full image: ${title}` : `查看大图：${title}`}"><img src="../assets/screenshots/${item.file}" alt="${title} · ${badge}" width="1800" height="1200" loading="lazy" decoding="async"><span class="image-error" role="status" hidden>${failed}</span><span class="image-enlarge">${enlarge} <span aria-hidden="true">↗</span></span></a><figcaption><span class="orbit-step" data-orbit-node>${String(index + 1).padStart(2, '0')}</span><span class="product-shot-badge">${badge}</span><h3>${title}</h3><p>${description}</p></figcaption></figure>`
  }).join('')
  // 原图链接在无脚本时仍有效，增强脚本使用原生 dialog 管理焦点和键盘关闭。
  return `<section class="product-showcase" id="product-preview" aria-labelledby="product-preview-title"><div class="product-showcase-heading"><p class="product-eyebrow">${en ? 'INSIDE NEXORA' : 'NEXORA 工作空间'}</p><h2 id="product-preview-title">${heading}</h2><p>${intro}</p></div><div class="product-shots">${figures}</div></section><dialog class="product-lightbox" aria-labelledby="product-lightbox-title"><div class="lightbox-bar"><div><h2 id="product-lightbox-title"></h2><p>${badge}</p></div><form method="dialog"><button type="submit" autofocus>${en ? 'Close image' : '关闭大图'} <span aria-hidden="true">×</span></button></form></div><div class="lightbox-image"><img alt="" width="1800" height="1200"><p class="lightbox-error" role="status" hidden>${failed}</p></div><a class="lightbox-original" href="">${en ? 'Open original image' : '打开原图'} ↗</a></dialog>`
}
