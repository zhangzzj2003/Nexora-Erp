<script setup lang="ts">
import CheckIcon from '~icons/ri/check-line'
import AppButton from './AppButton.vue'

// 步骤只负责展示进度和返回已完成的阶段，前进与保存由业务表单校验。
withDefaults(defineProps<{ steps: readonly string[]; current: number; disabled?: boolean; label: string }>(), { disabled: false })
const emit = defineEmits<{ select: [step: number] }>()
</script>

<template>
  <nav class="app-stepper" :aria-label="label">
    <ol>
      <li v-for="(label, index) in steps" :key="index" :class="{ completed: index < current, active: index === current }"
        :aria-current="index === current ? 'step' : undefined">
        <AppButton class="step-button" variant="plain" type="button" :disabled="disabled || index >= current" :aria-label="label"
          :aria-current="index === current ? 'step' : undefined" @click="emit('select', index)">
          <span class="step-circle" aria-hidden="true"><CheckIcon v-if="index < current" /><span v-else>{{ index + 1 }}</span></span>
          <span class="step-label">{{ label }}</span>
        </AppButton>
        <span v-if="index < steps.length - 1" class="step-connector" aria-hidden="true"><span /></span>
      </li>
    </ol>
  </nav>
</template>

<style scoped>
/* 连线填充与完成标记表达真实进度；窄窗口保留步骤名称和键盘返回入口。 */
.app-stepper ol { display: flex; list-style: none; margin: 0; padding: 0; }
.app-stepper li { display: flex; position: relative; flex: 1; min-width: 0; }
.app-stepper li:last-child { flex: none; }
.step-button { display: flex; flex-direction: column; align-items: center; gap: 9px; width: auto; min-width: 70px; padding: 0; border: 0; color: var(--workspace-field-muted); background: none; font: inherit; }
.step-button:disabled { cursor: default; opacity: 1; }
.step-button:focus-visible { outline: 2px solid var(--workspace-field-accent); outline-offset: 5px; border-radius: 8px; }
.step-circle { display: grid; place-items: center; width: 34px; height: 34px; border: 1px solid var(--workspace-field-border); border-radius: 50%; background: var(--workspace-field-disabled); font-size: 13px; font-weight: 700; transition: background .2s ease, border-color .2s ease, box-shadow .2s ease; }
.step-circle svg { width: 20px; height: 20px; }
.active .step-circle, .completed .step-circle { color: #fff; background: var(--app-button-primary); border-color: var(--app-button-primary); }
.active .step-circle { box-shadow: 0 0 0 5px var(--app-accent-tint); }
.active .step-label { color: var(--workspace-field-accent); font-weight: 700; }
.completed .step-label { color: var(--workspace-field-text); }
.step-label { font-size: 12px; line-height: 1.4; text-align: center; }
.step-connector { height: 2px; flex: 1; margin: 16px 12px 0; background: var(--workspace-field-border); overflow: hidden; }
.step-connector > span { display: block; height: 100%; background: var(--app-button-primary); transform: scaleX(0); transform-origin: left; transition: transform .25s ease; }
.completed .step-connector > span { transform: scaleX(1); }
@media (max-width: 420px) { .step-button { min-width: 60px; } .step-connector { margin-inline: 8px; } .step-label { font-size: 11px; } }
@media (prefers-reduced-motion: reduce) { .step-circle, .step-connector > span { transition: none; } }
</style>
