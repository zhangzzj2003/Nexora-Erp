<script setup lang="ts" generic="TRow extends object">
import { NModal } from 'naive-ui'
import AppButton from '../app/AppButton.vue'
import WorkspaceTable from './WorkspaceTable.vue'

// 单据弹窗只统一布局和交互边界，基础字段、物料选择及保存业务仍由页面提供。
const props = withDefaults(defineProps<{
  show: boolean
  title: string
  data: TRow[]
  columns: readonly { key: string; title: string; width?: string }[]
  busy?: boolean
  disabled?: boolean
  submitDisabled?: boolean
  addDisabled?: boolean
  readOnly?: boolean
  submitLabel?: string
  hint?: string
  minTableWidth?: number
}>(), {
  busy: false, disabled: false, submitDisabled: false, addDisabled: false, readOnly: false,
  submitLabel: '保存草稿', hint: '', minTableWidth: 760
})
const emit = defineEmits<{
  'update:show': [show: boolean]
  submit: []
  addMaterial: []
}>()
defineSlots<{
  basicInfo: () => unknown
  materialPicker?: () => unknown
  [name: `cell-${string}`]: (props: { row: TRow }) => unknown
}>()
function updateShow(show: boolean): void {
  // 保存中禁止关闭，避免用户误以为操作已取消；断线时仍允许收起并保留草稿。
  if (!props.busy) emit('update:show', show)
}
function addMaterial(): void {
  if (!props.readOnly && !props.busy && !props.disabled && !props.addDisabled) emit('addMaterial')
}
function submit(): void {
  // 详情模式同时拦截事件，避免隐藏按钮后仍可通过表单提交触发业务写入。
  if (!props.readOnly && !props.busy && !props.disabled && !props.submitDisabled) emit('submit')
}
</script>

<template>
  <NModal :show="show" @update:show="updateShow" preset="card" :title="title"
    class="workspace-document-dialog" :mask-closable="!busy" :close-on-esc="!busy" :closable="!busy"
    :style="{ width: 'min(1040px, calc(100vw - 32px))', maxHeight: 'calc(100vh - 48px)' }">
    <form class="document-form" @submit.prevent="submit">
      <div class="document-body">
        <!-- 详情插槽使用纯文本，不禁用整个字段集，保留表格滚动和分页等查看交互。 -->
        <fieldset :disabled="busy || disabled" class="document-fields">
          <section class="document-basic" aria-label="基础信息">
            <h3>基础信息</h3>
            <div class="form-grid"><slot name="basicInfo" /></div>
          </section>
          <!-- 分隔线明确区分单据头与物料明细，避免两类信息混在同一张表单中。 -->
          <hr class="document-divider" />
          <WorkspaceTable title="物料明细" :data="data" :columns="columns" :min-table-width="minTableWidth"
            :empty-text="readOnly ? '此单据暂无物料明细。' : '尚未添加物料，请点击“添加物料”新增一行，再在表格内搜索选择。'" class="document-lines">
            <template #heading><h3>物料明细 <span class="document-count">{{ data.length }} 项</span></h3></template>
            <template v-if="!readOnly" #actions>
              <AppButton type="button" :disabled="busy || disabled || addDisabled"
                @click="addMaterial" variant="secondary">＋ 添加物料</AppButton>
            </template>
            <template v-if="$slots.materialPicker" #beforeTable><slot name="materialPicker" /></template>
            <!-- 继续透传类型明确的行插槽，数量、价格等不同业务字段无需写进公共组件。 -->
            <template v-for="column in columns" :key="column.key" #[`cell-${column.key}`]="{ row }">
              <slot :name="`cell-${column.key}`" :row="row" />
            </template>
          </WorkspaceTable>
        </fieldset>
      </div>
      <footer class="document-footer">
        <p v-if="hint" class="muted">{{ hint }}</p>
        <div class="document-actions">
          <AppButton type="button" :disabled="busy" @click="updateShow(false)">{{ readOnly ? '关闭' : '收起' }}</AppButton>
          <AppButton v-if="!readOnly" type="submit" variant="primary" :loading="busy"
            :disabled="busy || disabled || submitDisabled">{{ submitLabel }}</AppButton>
        </div>
      </footer>
    </form>
  </NModal>
</template>

<style scoped>
/* 只让内容区滚动，长明细和窄窗口下仍能直接访问保存、收起按钮。 */
.document-form { display: flex; flex-direction: column; min-height: 0; max-height: calc(100vh - 160px); }
.document-body { min-height: 0; overflow-y: auto; }
.document-fields { display: block; min-width: 0; margin: 0; padding: 0; border: 0; }
.document-basic h3, .document-lines h3 { margin: 0 0 18px; font-size: 15px; }
.document-basic { padding: 4px 0 8px; }
.document-divider { margin: 24px 0; border: 0; border-top: 1px solid var(--workspace-field-border); }
.document-lines { padding: 0; border: 0; border-radius: 0; background: transparent; box-shadow: none; }
/* 覆盖旧版暗色卡片背景，保持标题区与弹窗底色一致，表格仍使用自己的主题。 */
:root[data-theme='dark'] .document-lines { background: transparent; box-shadow: none; }
.document-lines h3 { margin: 0; }
.document-count { margin-left: 8px; color: var(--workspace-field-muted); font-size: 12px; font-weight: 400; }
.document-footer { display: flex; flex-shrink: 0; align-items: center; justify-content: space-between; gap: 18px;
  margin-top: 24px; padding-top: 18px; border-top: 1px solid var(--workspace-field-border); }
.document-footer p { margin: 0; font-size: 12px; line-height: 1.6; }
.document-actions { display: flex; justify-content: flex-end; gap: 10px; margin-left: auto; }
@media (max-width: 650px) {
  .document-basic .form-grid { grid-template-columns: 1fr; }
  .document-footer { flex-direction: column; align-items: stretch; gap: 12px; }
  .document-actions { margin-left: 0; }
}
</style>

<style>
/* Naive UI 卡片内容允许收缩，弹窗高度由视口限制，不让页脚滚出屏幕。 */
.workspace-document-dialog > .n-card__content { min-height: 0; }
</style>
