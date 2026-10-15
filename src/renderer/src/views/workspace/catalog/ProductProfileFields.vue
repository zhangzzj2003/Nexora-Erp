<script setup lang="ts">
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import AppInput from '../../../components/app/AppInput.vue'
import type { ProductFields, ProductModel } from '../../../../../shared/product-api'
import { productKindLabels, productKinds } from '../../../../../shared/product-api'
// 归组信息与物料参数分开保存，切换机型不会覆盖产品的规格或编码。
defineProps<{form: ProductFields; models: ProductModel[]; disabled: boolean}>()
</script>
<template>
  <label>产品类型<WorkspaceSelect v-model="form.kind" :options="productKinds.map(value => ({value, label: productKindLabels[value]}))" :disabled="disabled" required /></label>
  <label>所属机型（可选）<WorkspaceSelect v-model="form.model_id" :options="[{value: null, label: '不归属机型'}, ...models.map(row => ({value: row.id, label: `${row.code} · ${row.name}`}))]" :disabled="disabled" /></label>
  <label>配置名称（可选）<AppInput v-model.trim="form.configuration_name" maxlength="120" placeholder="如：标准版、长续航版" :disabled="disabled" /></label>
</template>
