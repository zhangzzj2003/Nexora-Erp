<script setup lang="ts" generic="TRow extends object">
import AppButton from '../../../components/app/AppButton.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import type { WorkspaceTableColumn } from '../../../utils/table-columns'
import { nextTick, onUnmounted, ref, watch } from 'vue'

// 首次建配方直接占用产品工作区；字段和行操作仍由共用 BOM 编辑器提供。
defineOptions({inheritAttrs: false})
const props = withDefaults(defineProps<{
  show: boolean; title: string; data: TRow[]; columns: readonly WorkspaceTableColumn[]
  busy?: boolean; disabled?: boolean; submitDisabled?: boolean; addDisabled?: boolean
  submitLabel?: string; hint?: string
}>(), {busy: false, disabled: false, submitDisabled: false, addDisabled: false, submitLabel: '保存 BOM 草稿', hint: ''})
const emit = defineEmits<{submit: []; addMaterial: []}>()
const formElement = ref<HTMLFormElement|null>(null)
const table = ref<{refreshLayout: () => Promise<void>}|null>(null)
let rowObserver: ResizeObserver|undefined
let contentObserver: MutationObserver|undefined
// 缓存行高可能限制表体本身的尺寸，直接观察物料组件的自然高度才能同时处理展开与收起。
watch(formElement, async element => {
  rowObserver?.disconnect()
  contentObserver?.disconnect()
  await nextTick()
  if (!element || element!==formElement.value) return
  const refresh = (): void => {if (element===formElement.value) void table.value?.refreshLayout()}
  rowObserver = new ResizeObserver(refresh)
  const observeMaterials = (): void => {
    if (element!==formElement.value) return
    rowObserver?.disconnect()
    element.querySelectorAll('.workspace-material-select').forEach(material => rowObserver?.observe(material))
  }
  // VXE 异步生成行，新增、删行和虚拟列重建后重新观察当前节点；不监听布局写回的样式。
  contentObserver = new MutationObserver(observeMaterials)
  contentObserver.observe(element, {childList:true,subtree:true})
  observeMaterials()
}, {flush:'post'})
onUnmounted(() => {rowObserver?.disconnect(); contentObserver?.disconnect()})
function submit(): void {
  // 表单回车和迟到点击与按钮共用保护，不能绕过草稿校验或断线状态。
  if (!props.busy && !props.disabled && !props.submitDisabled) emit('submit')
}
function addMaterial(): void {
  if (!props.busy && !props.disabled && !props.addDisabled) emit('addMaterial')
}
</script>

<template>
  <form v-if="show" ref="formElement" class="bom-inline-form" :aria-label="title" @submit.prevent="submit">
    <header class="bom-inline-heading"><h4>建立 BOM</h4><p>填写组件与用量，保存为首个版本草稿。</p></header>
    <fieldset :disabled="busy || disabled" class="bom-inline-fields">
      <div class="bom-inline-basic"><slot name="basicInfo" /></div>
      <WorkspaceTable ref="table" title="物料明细" :data="data" :columns="columns" :min-table-width="750" stretch-columns class="bom-inline-lines">
        <template #heading><h4>组成明细 <span>{{ data.length }} 项</span></h4></template>
        <template #actions>
          <slot name="documentActions" />
          <AppButton type="button" size="small" :disabled="busy || disabled || addDisabled" @click="addMaterial">＋ 添加物料</AppButton>
        </template>
        <template v-for="column in columns" :key="column.key" #[`cell-${column.key}`]="{row}">
          <slot :name="`cell-${column.key}`" :row="row" />
        </template>
      </WorkspaceTable>
    </fieldset>
    <footer class="bom-inline-footer">
      <p v-if="hint" class="muted">{{ hint }}</p>
      <AppButton type="submit" variant="primary" :loading="busy" :disabled="busy || disabled || submitDisabled">{{ submitLabel }}</AppButton>
    </footer>
  </form>
</template>

<style scoped>
/* 首建表单与版本组成共用右侧空间，不再嵌套大卡片或重复目标物料资料。 */
.bom-inline-form { display:grid; gap:20px; border-top:1px solid var(--workspace-field-border); padding-top:20px; }
.bom-inline-heading { display:flex; align-items:center; flex-wrap:wrap; gap:8px 16px; }
.bom-inline-heading h4,.bom-inline-heading p { margin:0; }
.bom-inline-heading h4 { font-size:15px; }
.bom-inline-heading p { color:var(--workspace-field-muted); font-size:12px; }
.bom-inline-fields { display:grid; gap:22px; min-width:0; margin:0; padding:0; border:0; }
.bom-inline-basic { display:grid; grid-template-columns:minmax(160px,220px) minmax(0,1fr); gap:16px; align-items:start; }
.bom-inline-basic :deep(> .document-basic-extra) { grid-column:1/-1; margin:0; font-size:12px; }
.bom-inline-lines { min-width:0; padding:0; border:0; border-radius:0; background:transparent; box-shadow:none; }
.bom-inline-lines h4 { margin:0; font-size:14px; }
.bom-inline-lines h4 span { margin-left:8px; font-weight:400; font-size:12px; color:var(--workspace-field-muted); }
.bom-inline-footer { display:flex; align-items:center; justify-content:space-between; gap:16px; border-top:1px solid var(--workspace-field-border); padding-top:16px; }
.bom-inline-footer p { margin:0; font-size:12px; }
.bom-inline-footer > .app-button { flex-shrink:0; margin-left:auto; }
@media(max-width:760px) { .bom-inline-basic { grid-template-columns:minmax(0,1fr); } .bom-inline-footer { flex-wrap:wrap; } }
</style>
