// 表格额外携带原始行索引，但不复制业务字段；编辑与删除仍作用于 Pinia 草稿。
export function documentRows<T extends object>(lines: readonly T[]): { line: T; index: number }[] {
  return lines.map((line, index) => ({ line, index }))
}
