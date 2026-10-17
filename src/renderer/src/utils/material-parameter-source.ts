import type { MaterialChoice } from '../../../shared/material-api'

// 旧服务端未附带参数时，只按真实物料 ID 从当前已授权缓存回退；不靠名称或编号猜测。
export function materialParameterIndex(materials: readonly MaterialChoice[]): ReadonlyMap<number, MaterialChoice> {
  return new Map(materials.map(material => [material.id, material]))
}

export function materialParameterSource(
  materialId: number,
  embedded?: MaterialChoice | null,
  cached?: ReadonlyMap<number, MaterialChoice>,
): MaterialChoice | undefined {
  if (!Number.isSafeInteger(materialId) || materialId <= 0) return
  if (embedded?.id === materialId) return embedded
  const material = cached?.get(materialId)
  return material?.id === materialId ? material : undefined
}
