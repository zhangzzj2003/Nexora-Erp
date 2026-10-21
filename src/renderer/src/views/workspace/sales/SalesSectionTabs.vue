<script setup lang="ts" generic="T extends string">
import AppButton from '../../../components/app/AppButton.vue'
defineProps<{modelValue:T;options:readonly {key:T;label:string}[];disabled?:boolean;label:string}>()
const emit=defineEmits<{'update:modelValue':[value:T]}>()
</script>
<template>
  <!-- 继续使用真实按钮，Tab、Enter 和空格均可切换；选中态除下划线外也提供读屏状态。 -->
  <nav class="sales-section-tabs" :aria-label="label"><AppButton v-for="option in options" :key="option.key" variant="plain"
    :disabled="disabled" :aria-pressed="modelValue===option.key" :class="{'is-active':modelValue===option.key}"
    @click="emit('update:modelValue',option.key)">{{option.label}}</AppButton></nav>
</template>
<style scoped>
/* 使用现有强调色和按钮，线形导航与列表操作区分层，窄窗自然换行。 */
.sales-section-tabs{display:flex;flex-wrap:wrap;gap:24px;border-bottom:1px solid var(--workspace-field-border)}
.sales-section-tabs :deep(.app-button){padding:12px 0;height:auto;border-radius:0;border:0;border-bottom:2px solid transparent;background:transparent;color:var(--workspace-field-muted)}
.sales-section-tabs :deep(.is-active){color:var(--workspace-field-accent);border-bottom-color:var(--workspace-field-accent)}
</style>
