import { shallowRef, watch } from 'vue'

// 只管理页面的资料展示，不写入 Pinia 草稿；用真实行对象避免删行后按序号展开错料。
export function useDocumentMaterialDetails<TLine extends object>(lines: () => readonly TLine[]) {
  // 展示状态只依赖行对象，兼容实盘数量和 BOM 组件等不同草稿字段。
  const activeLine = shallowRef<TLine | null>(lines().at(-1) ?? null)
  watch(() => lines().slice(), (current, previous) => {
    // 新增行统一收起旧资料卡，页面无需再复制一套添加后的展示联动。
    const added = current.filter(line => !previous.includes(line)).at(-1)
    if (added) activeLine.value = added
    // 移除当前行或保存清空时同步展示状态，其他行的数量与物料选择不受影响。
    if (activeLine.value && !current.includes(activeLine.value)) activeLine.value = current.at(-1) ?? null
  }, { flush: 'sync' })
  function showLine(line: TLine): void {
    if (lines().includes(line)) activeLine.value = line
  }
  function setCompact(line: TLine, compact: boolean): void {
    if (!compact) showLine(line)
    else if (activeLine.value === line) activeLine.value = null
  }
  return { activeLine, showLine, setCompact }
}
