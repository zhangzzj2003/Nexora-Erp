<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { NSelect } from 'naive-ui'
import type { Supplier } from '../../../../shared/supplier-api'
import { useThemeStore } from '../../store/theme-store'
import { workspaceSelectTheme } from '../../utils/workspace-select'
import { newSupplierOption, supplierOption, supplierSelectionInput } from '../../utils/supplier-selection'

// 公共封装承接多选、搜索和新名称草稿；组件本身不调用接口创建供应商。
const props = withDefaults(defineProps<{
  modelValue: string[]; suppliers: readonly Supplier[]; disabled?: boolean
}>(), { disabled: false })
const emit = defineEmits<{ 'update:modelValue': [value: string[]] }>()
const { isDarkTheme, colorPalette } = storeToRefs(useThemeStore())
const theme = computed(() => workspaceSelectTheme(isDarkTheme.value, colorPalette.value))
const options = computed(() => [
  ...props.suppliers.map(supplierOption),
  // 重新渲染时也保留未保存的新名称标签，不依赖下拉组件的临时内部状态。
  ...props.modelValue.filter(value => value.startsWith('new:'))
    .map(value => ({ value, label: `新建“${value.slice(4)}”（待完善供应商）` }))
].map(option => ({ ...option, disabled: props.modelValue.length >= 20 && !props.modelValue.includes(option.value) })))
function createOption(name: string) {
  // 搜索有匹配结果时只展示已有档案，避免按 Enter 把搜索词误建成新供应商。
  const match = props.suppliers.find(item => item.name.toLowerCase().includes(name.trim().toLowerCase()))
  if (match) return supplierOption(match)
  const option = newSupplierOption(name, props.suppliers)
  const duplicate = props.modelValue.find(value => value.startsWith('new:')
    && value.slice(4).toLowerCase() === name.trim().toLowerCase())
  if (duplicate) return { value: duplicate, label: `新建“${duplicate.slice(4)}”（待完善供应商）` }
  return { ...option, disabled: option.disabled || props.modelValue.length >= 20 }
}
function update(value: string[]): void {
  if (props.disabled || value.length > 20) return
  supplierSelectionInput(value)
  emit('update:modelValue', value)
}
</script>

<template>
  <!-- Enter 用于确认下拉选项；阻止冒泡到外层表单，避免搜索时意外保存物料。 -->
  <div class="workspace-supplier-select" @keydown.enter.prevent>
    <NSelect multiple filterable tag clearable to="body"
      :value="modelValue" :options="options" :disabled="disabled"
      :on-create="createOption"
      :theme-overrides="theme" :fallback-option="false"
      placeholder="搜索已有供应商，或输入新名称后按 Enter 添加"
      :input-props="{ 'aria-label': '供应商绑定', maxlength: 120 }"
      @update:value="update">
      <template #empty>输入供应商名称即可创建待完善档案</template>
    </NSelect>
  </div>
</template>

<style scoped>
/* 下拉菜单传送到 body，弹窗滚动时不裁切；搜索输入沿用现有选择框外观。 */
.workspace-supplier-select { width: 100%; min-width: 0; font-weight: 400; }
.workspace-supplier-select :deep(input.n-base-selection-input) {
  min-height: 0; border: 0; border-radius: 0; padding: 0;
  background: transparent; outline: none; box-shadow: none;
}
</style>
