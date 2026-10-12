<script setup lang="ts">
import AppInlineNumber from '../app/AppInlineNumber.vue'
import { editPurchasePrice } from '../../utils/purchase-pricing'
import type { PurchasePriceDraft } from '../../utils/purchase-pricing'

// 两个价格单元格共享原行对象；最后编辑的字段决定数量变化时如何联动。
const props = defineProps<{ line: PurchasePriceDraft; field: 'unit_price' | 'line_total'; disabled?: boolean; required?: boolean }>()
let original: Pick<PurchasePriceDraft, 'unit_price' | 'line_total' | 'pricing_mode'> | null = null
function update(value: string): void {
  if (!props.disabled) editPurchasePrice(props.line, props.field, value)
}
function remember(): void {
  original = { unit_price: props.line.unit_price, line_total: props.line.line_total, pricing_mode: props.line.pricing_mode }
}
function cancel(): void {
  // Escape 恢复金额及原计算依据，避免取消总价编辑后悄悄改变后续数量联动。
  if (original && !props.disabled) Object.assign(props.line, original)
}
</script>
<template>
  <AppInlineNumber :model-value="line[field]" :disabled="disabled"
    :label="field === 'unit_price' ? '单价（元）' : '总价（元）'"
    :max="field === 'unit_price' ? '1000000000' : '1000000000000000'"
    :step="field === 'line_total' ? '0.01' : line.pricing_mode === 'total' ? 'any' : '0.0001'"
    :required="required" @update:model-value="update" @edit-start="remember" @edit-cancel="cancel" />
</template>
