// 库存与单据保留简要物料契约，详细参数由物料管理接口提供。
export interface MaterialSummary { id: number; sku: string; name: string; unit: string }
export interface MaterialDetails {
  category_code: string
  specification: string
  package: string
  brand: string
  manufacturer_part_number: string
  electrical_value: string
  tolerance: string
  rated_voltage: string
  rated_power: string
  temperature_range: string
  compliance: string
  notes: string
}
export interface Material extends MaterialSummary, MaterialDetails {
  version: number
  // 编辑专用详情同时返回绑定编号；列表及旧调用继续使用原有简要响应。
  supplier_ids?: number[]
}
export type MaterialSupplierInput = { supplier_id: number; name?: never } | { name: string; supplier_id?: never }
export interface MaterialCategory {
  code: string
  name: string
  children: { code: string; name: string }[]
}
// 新增省略 sku，编辑携带原编码和读取时的版本；可选字段兼容原有调用入口。
export interface MaterialInput extends Partial<MaterialDetails> {
  sku?: string
  name: string
  unit: string
  // 新客户端提交目录编号，服务端核对名称和启用状态；旧调用可省略。
  unit_id?: number
  version?: number
  reason?: string
  suppliers?: MaterialSupplierInput[]
}
