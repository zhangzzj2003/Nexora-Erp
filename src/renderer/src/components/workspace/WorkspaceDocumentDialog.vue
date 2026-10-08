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
  // 来源单据只允许处理已有明细；复用表格时隐藏自由新增入口。
  showAdd?: boolean
  addLabel?: string
  linesTitle?: string
  emptyText?: string
}>(), {
  busy: false, disabled: false, submitDisabled: false, addDisabled: false, readOnly: false,
  submitLabel: '保存草稿', hint: '', minTableWidth: 760, showAdd: true,
  addLabel: '添加物料', linesTitle: '物料明细',
  emptyText: '尚未添加物料，请点击“添加物料”新增一行，再在表格内搜索选择。'
})
const emit = defineEmits<{
  'update:show': [show: boolean]
  submit: []
  addMaterial: []
}>()
defineSlots<{
  basicInfo: () => unknown
  // 只读字段与单据操作分离，业务页面可在明细标题右侧提供自己的状态操作。
  documentActions?: () => unknown
  materialPicker?: () => unknown
  [name: `cell-${string}`]: (props: { row: TRow }) => unknown
}>()
function updateShow(show: boolean): void {
  // 保存中禁止关闭，避免用户误以为操作已取消；断线时仍允许收起并保留草稿。
  if (!props.busy) emit('update:show', show)
}
function addMaterial(): void {
  if (props.showAdd && !props.readOnly && !props.busy && !props.disabled && !props.addDisabled) emit('addMaterial')
}
function submit(): void {
  // 详情模式同时拦截事件，避免隐藏按钮后仍可通过表单提交触发业务写入。
  if (!props.readOnly && !props.busy && !props.disabled && !props.submitDisabled) emit('submit')
}
</script>

<template>
  <!-- 单据编辑与详情统一加宽，宽屏多展示物料信息，窄屏仍在两侧各留 16px。 -->
  <NModal :show="show" @update:show="updateShow" preset="card" :title="title"
    class="workspace-document-dialog" :mask-closable="!busy" :close-on-esc="!busy" :closable="!busy"
    :style="{ width: 'min(1280px, calc(100vw - 32px))', maxHeight: 'calc(100vh - 48px)' }">
    <form class="document-form" @submit.prevent="submit">
      <div class="document-body">
        <!-- 详情插槽使用纯文本，不禁用整个字段集，保留表格滚动和分页等查看交互。 -->
        <fieldset :disabled="busy || disabled" class="document-fields">
          <section class="document-basic" :class="{ 'document-basic--readonly': readOnly }" aria-label="基础信息">
            <h3>基础信息</h3>
            <div class="form-grid document-basic-grid"><slot name="basicInfo" /></div>
          </section>
          <!-- 分隔线明确区分单据头与物料明细，避免两类信息混在同一张表单中。 -->
          <hr class="document-divider" />
          <WorkspaceTable :title="linesTitle" :data="data" :columns="columns" :min-table-width="minTableWidth" stretch-columns
            :empty-text="readOnly ? '此单据暂无物料明细。' : emptyText" class="document-lines">
            <template #heading><h3>{{ linesTitle }} <span class="document-count">{{ data.length }} 项</span></h3></template>
            <template v-if="!readOnly || $slots.documentActions" #actions>
              <slot name="documentActions" />
              <AppButton v-if="!readOnly && showAdd" type="button" :disabled="busy || disabled || addDisabled"
                @click="addMaterial" variant="secondary">＋ {{ addLabel }}</AppButton>
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
.document-form { display: flex; flex-direction: column; min-height: 0; max-height: calc(100dvh - 172px); }
.document-body { min-height: 0; overflow-y: auto; }
.document-basic-grid :deep(> .document-basic-extra) { grid-column: 1 / -1; }
.document-fields { display: block; min-width: 0; margin: 0; padding: 0; border: 0; }
.document-basic h3, .document-lines h3 { margin: 0 0 18px; font-size: 15px; }
/* 基础信息独立成柔和面板，详情使用三列提高密度，编辑表单保留原两列。 */
.document-basic { padding: 20px; border: 1px solid var(--workspace-field-border);
  border-radius: 14px; background: var(--app-modal-surface); }
.document-basic--readonly .document-basic-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 22px 24px; }
.document-basic h3 { display: flex; align-items: center; gap: 9px; }
.document-basic h3::before { content: ''; width: 3px; height: 14px; border-radius: 3px; background: var(--workspace-field-accent); }
.document-divider { margin: 22px 0; border: 0; }
.document-lines { padding: 0; border: 0; border-radius: 0; background: transparent; box-shadow: none; }
/* 覆盖旧版暗色卡片背景，保持标题区与弹窗底色一致，表格仍使用自己的主题。 */
:root[data-theme='dark'] .document-lines { background: transparent; box-shadow: none; }
.document-lines h3 { margin: 0; }
.document-count { display: inline-block; margin-left: 8px; padding: 2px 8px; border-radius: 7px;
  color: var(--workspace-field-accent); background: var(--app-accent-tint); font-size: 12px; font-weight: 500; }
.document-footer { display: flex; flex-shrink: 0; align-items: center; justify-content: space-between; gap: 18px;
  margin-top: 24px; padding-top: 18px; border-top: 1px solid var(--workspace-field-border); }
.document-footer p { margin: 0; font-size: 12px; line-height: 1.6; }
.document-actions { display: flex; justify-content: flex-end; gap: 10px; margin-left: auto; }
@media (max-width: 850px) {
  .document-basic--readonly .document-basic-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 650px) {
  .document-basic { padding: 16px; }
  .document-basic .form-grid { grid-template-columns: 1fr; }
  .document-footer { flex-direction: column; align-items: stretch; gap: 12px; }
  .document-actions { margin-left: 0; }
}
</style>

<style>
/* Naive UI 卡片内容允许收缩，弹窗高度由视口限制，不让页脚滚出屏幕。 */
.n-modal.n-card.workspace-document-dialog > .n-card-content { min-height: 0; overflow: clip; }
</style>
