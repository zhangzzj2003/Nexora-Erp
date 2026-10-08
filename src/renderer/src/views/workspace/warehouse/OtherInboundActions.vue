<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { NDropdown } from 'naive-ui'
import type { OtherInbound } from '../../../../../shared/erp-api'
import AppButton from '../../../components/app/AppButton.vue'
import { visibleRowActionCount } from '../../../utils/row-action-layout'
import { otherInboundActions, otherInboundRowActions, type OtherInboundAction, type OtherInboundPermissions } from './other-inbound-actions'

const props = defineProps<{ inbound: OtherInbound; permissions: OtherInboundPermissions; disabled: boolean; compact?: boolean }>()
const emit = defineEmits<{ action: [action: OtherInboundAction] }>()
const actions = computed(() => otherInboundActions(props.inbound, props.permissions))
const rowActions = computed(() => otherInboundRowActions(props.inbound, props.permissions))
const rowItems = computed(() => [rowActions.value.primary, ...rowActions.value.more])
const actionRoot = ref<HTMLElement | null>(null)
const measureRoot = ref<HTMLElement | null>(null)
const mounted = ref(false)
const availableWidth = ref(0)
const buttonWidths = ref<number[]>([])
const moreWidth = ref(52)
// 首次测量前沿用主操作与菜单；测量完成后根据列内真实空间展开，极窄列可全部收进菜单。
const visibleCount = computed(() => buttonWidths.value.length === rowItems.value.length
  ? visibleRowActionCount(buttonWidths.value, availableWidth.value, moreWidth.value)
  : 1)
const visibleItems = computed(() => rowItems.value.slice(0, visibleCount.value))
const overflowItems = computed(() => rowItems.value.slice(visibleCount.value))
let resizeObserver: ResizeObserver | undefined
function measureActions(): void {
  if (!actionRoot.value || !measureRoot.value) return
  availableWidth.value = actionRoot.value.getBoundingClientRect().width
  const widths = Array.from(measureRoot.value.querySelectorAll<HTMLElement>('[data-measure-action]'),
    button => button.getBoundingClientRect().width)
  // 测量真实公共按钮，避免按字符估宽在字体、主题和长文案下判断错误。
  if (widths.some((width, index) => width !== buttonWidths.value[index]) || widths.length !== buttonWidths.value.length) {
    buttonWidths.value = widths
  }
  moreWidth.value = measureRoot.value.querySelector<HTMLElement>('[data-measure-more]')?.getBoundingClientRect().width ?? 52
}
watch([actionRoot, measureRoot, rowItems], () => {
  resizeObserver?.disconnect()
  if (!actionRoot.value || !measureRoot.value) return
  measureActions()
  if (typeof ResizeObserver === 'undefined') return
  resizeObserver = new ResizeObserver(measureActions)
  resizeObserver.observe(actionRoot.value)
  // 同时观察测量按钮，字体或操作文案变化时也能重新计算，不依赖窗口缩放。
  for (const button of measureRoot.value.querySelectorAll<HTMLElement>('button')) resizeObserver.observe(button)
}, { flush: 'post' })
onMounted(() => { mounted.value = true })
onUnmounted(() => { resizeObserver?.disconnect() })
const menuOpen = ref(false)
const menuOptions = computed(() => overflowItems.value.map(item => ({
  key: item.key, label: item.label, disabled: props.disabled
})))
// 刷新、权限撤销或开始处理时收起旧菜单，选择回调仍会再次检查当前可用操作。
watch(() => `${props.inbound.id}:${props.disabled}:${actions.value.map(item => item.key).join(',')}`, () => { menuOpen.value = false })
// 调宽后菜单内容可能直接移到行内，及时关闭旧弹层，避免保留过期入口。
watch(() => menuOptions.value.map(item => item.key).join(','), () => { menuOpen.value = false })
function selectMore(key: string | number): void {
  const selected = overflowItems.value.find(item => item.key === key)
  menuOpen.value = false
  if (selected) run(selected.key)
}
function run(action: OtherInboundAction): void {
  // 事件层也复核禁用与可用状态，防止旧按钮回调绕过权限或正在处理的限制。
  if (!props.disabled && actions.value.some(item => item.key === action)) emit('action', action)
}
</script>

<template>
  <div v-if="compact" ref="actionRoot" class="inbound-row-actions" role="group" aria-label="单据操作">
    <!-- 通过公共按钮封装使用 Naive UI 语义色与浅底样式，业务页面只负责排列。 -->
    <AppButton v-for="item in visibleItems" :key="item.key" :data-action="item.key"
      :class="item.key === rowActions.primary.key ? 'inbound-row-primary' : 'inbound-row-extra'" type="button" size="small"
      :secondary="item.key === rowActions.primary.key" :quaternary="item.key !== rowActions.primary.key"
      :tone="item.key === rowActions.primary.key ? (item.key === 'post' ? 'success' : item.key === 'reopen' ? 'primary' : 'info') : 'default'"
      :disabled="disabled" @click="run(item.key)">{{ item.label }}</AppButton>
    <template v-if="menuOptions.length">
      <NDropdown v-model:show="menuOpen" trigger="click" placement="bottom-end" :disabled="disabled"
        :options="menuOptions" @select="selectMore">
        <AppButton class="inbound-row-more" type="button" size="small" tone="default" quaternary :disabled="disabled"
          aria-label="更多单据操作" aria-haspopup="menu" :aria-expanded="menuOpen">更多</AppButton>
      </NDropdown>
    </template>
    <!-- 测量副本仅在浏览器挂载后生成，不可点击、聚焦或被读屏重复朗读。 -->
    <div v-if="mounted" ref="measureRoot" class="inbound-action-measure" aria-hidden="true" inert>
      <AppButton v-for="item in rowItems" :key="item.key" data-measure-action type="button" size="small" disabled
        :class="item.key === rowActions.primary.key ? 'inbound-row-primary' : 'inbound-row-extra'"
        :secondary="item.key === rowActions.primary.key" :quaternary="item.key !== rowActions.primary.key"
        :tone="item.key === rowActions.primary.key ? (item.key === 'post' ? 'success' : item.key === 'reopen' ? 'primary' : 'info') : 'default'">{{ item.label }}</AppButton>
      <AppButton data-measure-more class="inbound-row-more" type="button" size="small" tone="default" quaternary disabled>更多</AppButton>
    </div>
  </div>
  <div v-else class="inbound-actions" role="group" aria-label="单据操作">
    <AppButton v-for="item in actions" :key="item.key" type="button" size="small"
      :variant="item.variant" :disabled="disabled" @click="run(item.key)">{{ item.label }}</AppButton>
  </div>
</template>

<style scoped>
/* 根据可用宽度展开展示，按钮的颜色、圆角、悬停和焦点均沿用 Naive UI。 */
.inbound-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.inbound-row-actions { position: relative; display: flex; width: 100%; min-width: 0; justify-content: center; align-items: center; gap: 8px; white-space: nowrap; }
.inbound-row-primary { width: 104px; }
.inbound-row-extra { min-width: 52px; }
.inbound-row-more { width: 52px; max-width: 100%; }
/* 零高容器裁切测量副本，不扩大表格滚动范围；子按钮仍保留自然宽度供测量。 */
.inbound-action-measure { position: absolute; top: 0; left: 0; display: flex; width: 100%; height: 0; overflow: hidden; visibility: hidden; pointer-events: none; gap: 8px; }
</style>
