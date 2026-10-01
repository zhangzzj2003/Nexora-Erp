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
export interface Material extends MaterialSummary, MaterialDetails { version: number }
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
  version?: number
  reason?: string
}
