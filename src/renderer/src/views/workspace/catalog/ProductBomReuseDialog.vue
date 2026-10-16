<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Bom } from '../../../../../shared/erp-api'
import WorkspaceDocumentDialog from '../../../components/workspace/WorkspaceDocumentDialog.vue'
import AppInput from '../../../components/app/AppInput.vue'
import AppButton from '../../../components/app/AppButton.vue'
const props = withDefaults(defineProps<{
  show:boolean; sources:Bom[]; targetName:string; busy:boolean; disconnected:boolean; allowBlank?:boolean
}>(), { allowBlank:false })
const emit = defineEmits<{'update:show':[value:boolean]; choose:[bom:Bom]; blank:[]}>()
const search = ref('')
// 来源目录来自完整 BOM 快照，不能仅使用当前子机型的版本；取消的来源不允许再复制。
const options = computed(()=>props.sources.filter(row=>row.status!=='cancelled'
  && `${row.product_sku} ${row.product_name} V${row.version}`.toLowerCase().includes(search.value.trim().toLowerCase())))
const columns=[{key:'product',title:'来源机型'},{key:'version',title:'BOM 版本',width:'130'},
  {key:'status',title:'状态',width:'100'},{key:'actions',title:'复用',width:'180'}]
function createBlank():void {
  // 禁用状态也在事件边界检查，断线或关闭后的迟到点击不能继续打开编辑流程。
  if (!props.show || !props.allowBlank || props.busy || props.disconnected) return
  emit('blank')
}
function chooseBom(bom:Bom):void {
  if (!props.show || props.busy || props.disconnected) return
  // 使用最新来源快照，列表更新后已取消、移除的版本不能被旧行事件再次选中。
  const source=props.sources.find(row=>row.id===bom.id && row.status!=='cancelled')
  if (source) emit('choose',source)
}
function close():void {
  if (!props.busy) emit('update:show',false)
}
</script>
<template>
  <WorkspaceDocumentDialog :show="show" read-only :title="allowBlank ? '新建 BOM 版本' : '选择要复用的 BOM'" lines-title="可复用版本" :show-lines="options.length > 0" :data="options" :columns="columns" :busy="busy"
    @update:show="emit('update:show',$event)" @invalidated="emit('update:show',false)">
    <template v-if="allowBlank" #beforeBasicInfo>
      <section class="blank-choice" aria-label="空白创建">
        <div><h3>从空白开始</h3><p class="muted">建立新版本草稿，自行添加组成物料；也可以在下方选择原版本或其他产品的 BOM 进行复用。</p></div>
        <AppButton variant="primary" :disabled="busy || disconnected" @click="createBlank">空白创建</AppButton>
      </section>
    </template>
    <template #basicInfo><div class="document-detail-field"><span>目标子机型</span><strong>{{ targetName }}</strong></div>
      <label>搜索来源<AppInput v-model.trim="search" maxlength="120" placeholder="来源机型、编码或版本" /></label>
    </template>
    <template #cell-product="{row}"><strong>{{ row.product_name }}</strong><small class="reuse-code">{{ row.product_sku }}</small></template>
    <template #cell-version="{row}">#{{ row.id }} · V{{ row.version }}</template>
    <template #cell-status="{row}">{{ {draft:'草稿',active:'已启用',retired:'已停用',cancelled:'已取消'}[row.status] }}</template>
    <template #cell-actions="{row}"><AppButton size="small" :disabled="busy || disconnected" @click="chooseBom(row)">复用到当前机型</AppButton></template>
    <template #afterLines><p v-if="!options.length" class="muted source-empty">{{ search ? '未找到匹配的可复用版本，请调整搜索条件。' : allowBlank ? '暂无可复用的 BOM，可选择空白创建。' : '暂无可复用的 BOM。' }}</p></template>
    <template #footer><p class="muted">复用会复制完整组成生成新草稿，保存前可调整用料，原 BOM 版本保持不变。</p><AppButton :disabled="busy" @click="close">取消</AppButton></template>
  </WorkspaceDocumentDialog>
</template>
<style scoped>
/* 来源编码辅助识别同名机型，不与目标身份混排。 */
.reuse-code { display:block; margin-top:6px; color:var(--workspace-field-muted); }
/* 创建入口与来源表分开，窄屏下按钮换行仍保持清晰的操作顺序。 */
.blank-choice { display:flex; align-items:center; justify-content:space-between; gap:20px; margin-bottom:20px; }
.blank-choice h3 { margin:0 0 8px; font-size:15px; }
.blank-choice p, .source-empty { margin:0; font-size:12px; line-height:1.7; }
.source-empty { margin-top:14px; }
@media (max-width:650px) { .blank-choice { align-items:flex-start; flex-direction:column; gap:12px; } }
</style>
