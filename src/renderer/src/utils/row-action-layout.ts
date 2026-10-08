// 优先按原顺序直接展示按钮；有溢出时为“更多”及间距预留位置，不能挤丢隐藏操作入口。
export function visibleRowActionCount(widths: readonly number[], availableWidth: number, moreWidth: number, gap = 8): number {
  if (!widths.length) return 0
  if (!Number.isFinite(availableWidth) || availableWidth <= 0 || !Number.isFinite(moreWidth) || moreWidth <= 0
    || !Number.isFinite(gap) || gap < 0 || widths.some(width => !Number.isFinite(width) || width <= 0)) return 0
  const total = widths.reduce((sum, width) => sum + width, 0) + gap * (widths.length - 1)
  // 全部按钮可放下时，不额外保留菜单位，即使最后只剩一个次要操作也直接展示。
  if (total <= availableWidth) return widths.length
  let used = moreWidth
  let count = 0
  for (const width of widths) {
    used += gap + width
    if (used > availableWidth) break
    ++count
  }
  return count
}
