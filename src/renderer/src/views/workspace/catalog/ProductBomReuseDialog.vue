<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Bom } from '../../../../../shared/erp-api'
import WorkspaceDocumentDialog from '../../../components/workspace/WorkspaceDocumentDialog.vue'
import AppInput from '../../../components/app/AppInput.vue'
import AppButton from '../../../components/app/AppButton.vue'
const props = defineProps<{show:boolean; sources:Bom[]; targetName:string; busy:boolean; disconnected:boolean}>()
const emit = defineEmits<{'update:show':[value:boolean]; choose:[bom:Bom]}>()
const search = ref('')
// 来源目录来自完整 BOM 快照，不能仅使用当前子机型的版本；取消的来源不允许再复制。
const options = computed(()=>props.sources.filter(row=>row.status!=='cancelled'
  && `${row.product_sku} ${row.product_name} V${row.version}`.toLowerCase().includes(search.value.trim().toLowerCase())))
const columns=[{key:'product',title:'来源机型'},{key:'version',title:'BOM 版本',width:'130'},
  {key:'status',title:'状态',width:'100'},{key:'actions',title:'复用',width:'180'}]
</script>
<template>
  <WorkspaceDocumentDialog :show="show" read-only title="选择要复用的 BOM" lines-title="可复用版本" :data="options" :columns="columns" :busy="busy"
    @update:show="emit('update:show',$event)" @invalidated="emit('update:show',false)">
    <template #basicInfo><div class="document-detail-field"><span>目标子机型</span><strong>{{ targetName }}</strong></div>
      <label>搜索来源<AppInput v-model.trim="search" maxlength="120" placeholder="来源机型、编码或版本" /></label>
    </template>
    <template #cell-product="{row}"><strong>{{ row.product_name }}</strong><small class="reuse-code">{{ row.product_sku }}</small></template>
    <template #cell-version="{row}">#{{ row.id }} · V{{ row.version }}</template>
    <template #cell-status="{row}">{{ {draft:'草稿',active:'已启用',retired:'已停用',cancelled:'已取消'}[row.status] }}</template>
    <template #cell-actions="{row}"><AppButton size="small" :disabled="busy || disconnected" @click="emit('choose',row)">复用到当前机型</AppButton></template>
    <template #footer><p class="muted">复制后可调整完整用料，保存为目标子机型的新 BOM 草稿。</p><AppButton :disabled="busy" @click="emit('update:show',false)">取消</AppButton></template>
  </WorkspaceDocumentDialog>
</template>
<style scoped>
/* 来源编码辅助识别同名机型，不与目标身份混排。 */
.reuse-code { display:block; margin-top:6px; color:var(--workspace-field-muted); }
</style>
