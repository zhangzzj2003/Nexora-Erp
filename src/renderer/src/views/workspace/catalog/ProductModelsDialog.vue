<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { usePiniaAppStore } from '../../../store/app-store'
import WorkspaceDocumentDialog from '../../../components/workspace/WorkspaceDocumentDialog.vue'
import AppInput from '../../../components/app/AppInput.vue'
import AppButton from '../../../components/app/AppButton.vue'
defineProps<{show: boolean}>()
const emit = defineEmits<{'update:show':[value:boolean]}>()
const store = usePiniaAppStore()
const {productModels, productModelForm: form, productModelChanges, busy, connectionLost} = storeToRefs(store)
const columns = [{key:'code',title:'产品系列编码',width:'180'},{key:'name',title:'产品系列名称'},{key:'notes',title:'说明'},{key:'actions',title:'操作',width:'90'}]
function clear(): void {
  // 主动选择新增时才清空产品系列草稿，关闭弹窗后重开仍保留未保存的修改。
  if (busy.value) return
  form.value = {id:0,version:0,code:'',name:'',notes:'',reason:''}; productModelChanges.value = []
}
</script>
<template>
  <WorkspaceDocumentDialog :show="show" :title="form.id ? '编辑产品系列' : '产品系列管理'" :data="productModels" :columns="columns"
    :show-add="false" lines-title="产品系列目录" :busy="busy" :disabled="connectionLost || !store.can('catalog.manage')"
    :submit-disabled="!form.code.trim() || !form.name.trim() || (!!form.id && !form.reason.trim())"
    submit-label="保存产品系列" hint="产品系列只作归组，不记库存；修改不会覆盖产品编码与规格。"
    @submit="store.saveProductModel" @update:show="emit('update:show',$event)" @invalidated="emit('update:show',false)">
    <template #basicInfo>
      <label>产品系列编码<AppInput v-model.trim="form.code" required maxlength="40" /></label>
      <label>产品系列名称<AppInput v-model.trim="form.name" required maxlength="120" /></label>
      <label>说明<AppInput v-model.trim="form.notes" maxlength="500" /></label>
      <label v-if="form.id">修改原因<AppInput v-model.trim="form.reason" required maxlength="500" /></label>
      <AppButton v-if="form.id" :disabled="busy" @click="clear">新增另一产品系列</AppButton>
    </template>
    <template #cell-code="{row}">{{ row.code }}</template><template #cell-name="{row}">{{ row.name }}</template><template #cell-notes="{row}">{{ row.notes || '—' }}</template>
    <template #cell-actions="{row}"><AppButton size="small" :disabled="busy || connectionLost || !store.can('catalog.manage')" @click="store.editProductModel(row.id)">编辑</AppButton></template>
    <template #afterLines><section v-if="productModelChanges.length"><h3>产品系列变更记录</h3><p v-for="change in productModelChanges" :key="change.id">{{ store.localTime(change.created_at) }} · {{ change.changed_by_name }} · {{ change.reason }}</p></section></template>
  </WorkspaceDocumentDialog>
</template>
