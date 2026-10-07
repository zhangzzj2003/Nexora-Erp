<script setup lang="ts">
import { NModal } from 'naive-ui'
import AppButton from '../app/AppButton.vue'

// 各业务保留自己的草稿和确认操作，共享弹窗只负责标题、滚动区和操作保护。
const props = withDefaults(defineProps<{
  show: boolean
  title: string
  documentNumber: string
  hint: string
  submitLabel: string
  busy?: boolean
  disabled?: boolean
  loading?: boolean
  loadError?: string
  issue?: string
  loadingText?: string
}>(), { busy: false, disabled: false, loading: false, loadError: '', issue: '', loadingText: '正在读取可用批次…' })
const emit = defineEmits<{ 'update:show': [show: boolean]; submit: [] }>()
function updateShow(show: boolean): void {
  // 保存期间所有关闭途径保持一致，避免请求仍在执行时让用户误以为已取消。
  if (!props.busy) emit('update:show', show)
}
function submit(): void {
  if (!props.busy && !props.disabled && !props.loading && !props.loadError && !props.issue) emit('submit')
}
</script>

<template>
  <NModal :show="show" preset="card" :title="`${title} · ${documentNumber}`"
    class="workspace-lot-dialog" :mask-closable="!busy" :close-on-esc="!busy" :closable="!busy"
    :style="{ width: 'min(1120px, calc(100vw - 32px))', maxHeight: 'calc(100dvh - 48px)' }"
    @update:show="updateShow">
    <form class="lot-dialog-form" @submit.prevent="submit">
      <div class="lot-dialog-body">
        <p class="lot-dialog-hint">{{ hint }}</p>
        <p v-if="loading" role="status">{{ loadingText }}</p>
        <p v-if="loadError" class="lot-dialog-issue" role="alert">{{ loadError }}</p>
        <fieldset :disabled="busy || disabled || loading" class="lot-dialog-fields"><slot /></fieldset>
      </div>
      <!-- 页脚不跟随长明细滚动，数量错误及确认按钮始终可见。 -->
      <footer class="lot-dialog-footer">
        <p v-if="issue && !loading && !loadError" class="lot-dialog-issue" role="alert">{{ issue }}</p>
        <p v-else class="lot-dialog-hint">确认后按所选批次记录本次库存变动。</p>
        <div class="lot-dialog-actions">
          <AppButton type="button" :disabled="busy" @click="updateShow(false)">取消</AppButton>
          <AppButton type="submit" variant="primary" :loading="busy"
            :disabled="busy || disabled || loading || !!loadError || !!issue">{{ submitLabel }}</AppButton>
        </div>
      </footer>
    </form>
  </NModal>
</template>

<style scoped>
/* 标题由 Naive UI 固定，正文独立滚动，沿用现有单据弹窗的高度约束。 */
.lot-dialog-form { display: flex; flex-direction: column; min-height: 0; max-height: calc(100dvh - 168px); }
.lot-dialog-body { min-height: 0; min-width: 0; overflow-y: auto; overscroll-behavior: contain; }
/* 覆盖全局 fieldset 的换列规则，让宽表格在自己的容器滚动，不撑开物料标题。 */
.lot-dialog-fields { display: flex; flex-direction: column; flex-wrap: nowrap; gap: 22px; width: 100%; min-width: 0; border: 0; margin: 0; padding: 0; }
.lot-dialog-hint { margin: 0 0 18px; color: var(--workspace-field-muted); font-size: 13px; line-height: 1.7; }
.lot-dialog-footer { display: flex; flex-shrink: 0; align-items: center; justify-content: space-between; gap: 18px;
  margin-top: 22px; padding-top: 16px; border-top: 1px solid var(--workspace-field-border); }
.lot-dialog-footer p { margin: 0; font-size: 12px; line-height: 1.6; }
.lot-dialog-actions { display: flex; gap: 10px; flex-shrink: 0; margin-left: auto; }
.lot-dialog-issue { color: #b94438; }
:root[data-theme='dark'] .lot-dialog-issue { color: #ffaaa2; }
@media (max-width: 650px) {
  .lot-dialog-footer { flex-direction: column; align-items: stretch; gap: 12px; }
  .lot-dialog-actions { justify-content: flex-end; margin-left: 0; }
}
</style>

<style>
/* 内容区允许收缩，避免全局卡片滚动规则把页脚一起滚走。 */
.n-modal.n-card.workspace-lot-dialog > .n-card-content { min-height: 0; overflow: clip; }
</style>
