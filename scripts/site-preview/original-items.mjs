// 在原页面查找同一来源的真实字段，坐标随字体、表格与布局重新测量。
export function findOriginalItem(root,key,detail) {
  if (key === 'receipt') {
    const span=[...root.querySelectorAll('.workspace-record-lines > span')].find(el=>el.textContent.includes(detail.zh))
    if (!span) return null
    // 用原文字的真实边界定位，避免把单元格剩余的空白也当作需要放大的内容。
    if (!span.ownerDocument?.createRange) return span
    const range=span.ownerDocument.createRange();range.selectNodeContents(span)
    return {getBoundingClientRect:()=>range.getBoundingClientRect()}
  }
  const table = root.querySelector('.workspace-vxe-table')
  const row = [...(table?.querySelectorAll('tr.vxe-body--row') ?? [])].find(el => el.textContent.includes(detail.sku) && el.textContent.includes('#101'))
  if (!row) return null
  const cells = [...row.querySelectorAll('td')], indexes = key === 'stock' ? [2,3,4] : [3,4,5]
  const rects = indexes.map(index => cells[index]?.getBoundingClientRect()).filter(Boolean)
  if (rects.length !== indexes.length) return null
  const left=Math.min(...rects.map(r=>r.left)),top=Math.min(...rects.map(r=>r.top)),right=Math.max(...rects.map(r=>r.right)),bottom=Math.max(...rects.map(r=>r.bottom))
  return { getBoundingClientRect:()=>({left,top,width:right-left,height:bottom-top}) }
}
