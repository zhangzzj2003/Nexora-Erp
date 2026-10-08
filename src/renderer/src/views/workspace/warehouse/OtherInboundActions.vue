<script setup lang="ts">
import { computed } from 'vue'
import type { OtherInbound } from '../../../../../shared/erp-api'
import AppButton from '../../../components/app/AppButton.vue'
import { otherInboundActions, type OtherInboundAction, type OtherInboundPermissions } from './other-inbound-actions'

const props = defineProps<{ inbound: OtherInbound; permissions: OtherInboundPermissions; disabled: boolean }>()
const emit = defineEmits<{ action: [action: OtherInboundAction] }>()
const actions = computed(() => otherInboundActions(props.inbound, props.permissions))
function run(action: OtherInboundAction): void {
  // 事件层也复核禁用与可用状态，防止旧按钮回调绕过权限或正在处理的限制。
  if (!props.disabled && actions.value.some(item => item.key === action)) emit('action', action)
}
</script>

<template>
  <div class="inbound-actions" role="group" aria-label="单据操作">
    <AppButton v-for="item in actions" :key="item.key" type="button" size="small"
      :variant="item.variant" :disabled="disabled" @click="run(item.key)">{{ item.label }}</AppButton>
  </div>
</template>

<style scoped>
/* 同一组操作适配列表窄列与详情右上角，空间不足时自然换行。 */
.inbound-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
</style>
