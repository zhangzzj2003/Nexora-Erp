// 只接受一个客户名称列，避免把联系方式或归属字段误当作可自动导入的主数据。
function csvField(line: string): string {
  if (line.startsWith('"')) {
    if (!line.endsWith('"') || line.length < 2) throw new Error('CSV 引号未闭合')
    const inner = line.slice(1, -1)
    if (inner.replace(/""/g, '').includes('"')) throw new Error('CSV 引号格式无效')
    return inner.replace(/""/g, '"')
  }
  if (line.includes(',') || line.includes('"')) throw new Error('CSV 只能包含客户名称一列')
  return line
}

export function parseCustomerCsv(text: string): string[] {
  if (text.length > 256 * 1024) throw new Error('CSV 文件不能超过 256 KiB')
  const lines = text.replace(/^\uFEFF/, '').split(/\r\n|\n|\r/)
  while (lines.length && !lines[lines.length - 1].trim()) lines.pop()
  if (!lines.length || !['name', '客户名称'].includes(csvField(lines[0].trim()).trim())) {
    throw new Error('请使用 UTF-8 CSV，首行须为“客户名称”或 name')
  }
  if (lines.length < 2 || lines.length > 101) throw new Error('每次须导入 1 至 100 位客户')
  return lines.slice(1).map((line, index) => {
    const name = csvField(line.trim()).trim()
    if (!name || name.length > 120 || /[\x00-\x1f]/.test(name)) {
      throw new Error(`第 ${index + 2} 行客户名称无效`)
    }
    return name
  })
}
