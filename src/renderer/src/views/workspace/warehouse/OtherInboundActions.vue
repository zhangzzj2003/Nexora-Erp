<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NDropdown } from 'naive-ui'
import type { OtherInbound } from '../../../../../shared/erp-api'
import AppButton from '../../../components/app/AppButton.vue'
import { otherInboundActions, otherInboundRowActions, type OtherInboundAction, type OtherInboundPermissions } from './other-inbound-actions'

const props = defineProps<{ inbound: OtherInbound; permissions: OtherInboundPermissions; disabled: boolean; compact?: boolean }>()
const emit = defineEmits<{ action: [action: OtherInboundAction] }>()
const actions = computed(() => otherInboundActions(props.inbound, props.permissions))
const rowActions = computed(() => otherInboundRowActions(props.inbound, props.permissions))
const menuOpen = ref(false)
const menuOptions = computed(() => rowActions.value.more.map(item => ({
  key: item.key, label: item.label, disabled: props.disabled
})))
// 刷新、权限撤销或开始处理时收起旧菜单，选择回调仍会再次检查当前可用操作。
watch(() => `${props.inbound.id}:${props.disabled}:${actions.value.map(item => item.key).join(',')}`, () => { menuOpen.value = false })
function selectMore(key: string | number): void {
  const selected = rowActions.value.more.find(item => item.key === key)
  menuOpen.value = false
  if (selected) run(selected.key)
}
function run(action: OtherInboundAction): void {
  // 事件层也复核禁用与可用状态，防止旧按钮回调绕过权限或正在处理的限制。
  if (!props.disabled && actions.value.some(item => item.key === action)) emit('action', action)
}
</script>

<template>
  <div v-if="compact" class="inbound-row-actions" role="group" aria-label="单据操作">
    <!-- 通过公共按钮封装使用 Naive UI 语义色与浅底样式，业务页面只负责排列。 -->
    <AppButton class="inbound-row-primary" type="button" size="small" secondary
      :tone="rowActions.primary.key === 'post' ? 'success' : rowActions.primary.key === 'reopen' ? 'primary' : 'info'"
      :disabled="disabled" @click="run(rowActions.primary.key)">{{ rowActions.primary.label }}</AppButton>
    <template v-if="menuOptions.length">
      <NDropdown v-model:show="menuOpen" trigger="click" placement="bottom-end" :disabled="disabled"
        :options="menuOptions" @select="selectMore">
        <AppButton class="inbound-row-more" type="button" size="small" tone="default" quaternary :disabled="disabled"
          aria-label="更多单据操作" aria-haspopup="menu" :aria-expanded="menuOpen">更多</AppButton>
      </NDropdown>
    </template>
  </div>
  <div v-else class="inbound-actions" role="group" aria-label="单据操作">
    <AppButton v-for="item in actions" :key="item.key" type="button" size="small"
      :variant="item.variant" :disabled="disabled" @click="run(item.key)">{{ item.label }}</AppButton>
  </div>
</template>

<style scoped>
/* 列表使用等宽双列保持对齐；按钮的颜色、圆角、悬停和焦点均沿用 Naive UI。 */
.inbound-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.inbound-row-actions { display: grid; grid-template-columns: 104px 52px; align-items: center; gap: 8px; white-space: nowrap; }
.inbound-row-primary { width: 104px; }
.inbound-row-more { width: 52px; }
</style>
