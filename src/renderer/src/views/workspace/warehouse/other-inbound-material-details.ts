import { shallowRef, watch } from 'vue'
import type { DocumentMaterialLine } from '../../../utils/document-material-lines.ts'

// 只管理页面的资料展示，不写入 Pinia 草稿；用真实行对象避免删行后按序号展开错料。
export function useOtherInboundMaterialDetails(lines: () => readonly DocumentMaterialLine[]) {
  const activeLine = shallowRef<DocumentMaterialLine | null>(lines().at(-1) ?? null)
  watch(() => lines().slice(), current => {
    // 移除当前行或保存清空时同步展示状态，其他行的数量与物料选择不受影响。
    if (activeLine.value && !current.includes(activeLine.value)) activeLine.value = current.at(-1) ?? null
  }, { flush: 'sync' })
  function showLine(line: DocumentMaterialLine): void {
    if (lines().includes(line)) activeLine.value = line
  }
  function setCompact(line: DocumentMaterialLine, compact: boolean): void {
    if (!compact) showLine(line)
    else if (activeLine.value === line) activeLine.value = null
  }
  return { activeLine, showLine, setCompact }
}
