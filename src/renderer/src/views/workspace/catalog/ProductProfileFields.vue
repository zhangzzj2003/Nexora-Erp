<script setup lang="ts">
import { NCheckbox } from 'naive-ui'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import AppInput from '../../../components/app/AppInput.vue'
import type { ProductFields, ProductModel } from '../../../../../shared/product-api'
import { productKindLabels, productKinds } from '../../../../../shared/product-api'
// 归组信息与物料参数分开保存，切换机型不会覆盖产品的规格或编码。
defineProps<{form: ProductFields; models: ProductModel[]; disabled: boolean}>()
</script>
<template>
  <label>产品类型<WorkspaceSelect v-model="form.kind" :options="productKinds.map(value => ({value, label: productKindLabels[value]}))" :disabled="disabled" required /></label>
  <label>所属产品系列（可选）<WorkspaceSelect v-model="form.model_id" :options="[{value: null, label: '未归组'}, ...models.map(row => ({value: row.id, label: `${row.code} · ${row.name}`}))]" :disabled="disabled" /></label>
  <label>配置名称（可选）<AppInput v-model.trim="form.configuration_name" maxlength="120" placeholder="如：标准版、长续航版" :disabled="disabled" /></label>
  <div class="product-use-fields"><span>业务用途</span>
    <div><NCheckbox v-model:checked="form.can_sell" :disabled="disabled">允许销售</NCheckbox>
      <NCheckbox v-model:checked="form.can_purchase" :disabled="disabled">允许采购</NCheckbox>
      <NCheckbox v-model:checked="form.can_produce" :disabled="disabled">允许生产</NCheckbox></div>
    <small>用途独立设置，半成品也可销售。不能互换的硬件版本请使用不同物料编码。</small>
  </div>
</template>
<style scoped>
/* 用途并列呈现，避免产品类型与销售资格混为一谈。 */
.product-use-fields { grid-column:1/-1; display:grid; gap:10px; }
.product-use-fields>div { display:flex; flex-wrap:wrap; gap:20px; }
.product-use-fields small { color:var(--workspace-field-muted); font-weight:400; }
</style>
