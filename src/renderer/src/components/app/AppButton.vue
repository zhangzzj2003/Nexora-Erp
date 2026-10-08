<script setup lang="ts">
import { computed } from 'vue'
import { NButton } from 'naive-ui'
import type { GlobalThemeOverrides } from 'naive-ui'

// 按钮默认不提交表单；保存入口显式传 type="submit"，避免弹窗中的操作误触提交。
defineOptions({ inheritAttrs: false })
const props = withDefaults(
  defineProps<{
    // tone 对应 Naive UI 的语义色，type 仍保留原生表单按钮类型，避免破坏既有调用。
    tone?: 'default' | 'tertiary' | 'primary' | 'info' | 'success' | 'warning' | 'error'
    variant?: 'primary' | 'secondary' | 'text' | 'plain'
    type?: 'button' | 'submit' | 'reset'
    size?: 'small' | 'medium' | 'large'
    disabled?: boolean
    loading?: boolean
  }>(),
  { variant: 'secondary', type: 'button', size: 'medium', disabled: false, loading: false }
)
const theme = computed<NonNullable<GlobalThemeOverrides['Button']>>(() => ({
  // 配色通过 CSS 变量适配明暗主题和引导页，导航按钮保留各自的结构样式。
  heightMedium: props.variant === 'plain' ? 'auto' : '40px',
  heightSmall: props.variant === 'plain' ? 'auto' : '34px',
  heightLarge: '44px',
  // 页面、表格和弹窗共用更柔和的圆角，不再在业务页面单独覆盖按钮外观。
  borderRadiusMedium: '12px',
  borderRadiusSmall: '10px',
  borderRadiusLarge: '14px',
  fontSizeMedium: props.variant === 'plain' ? 'inherit' : '13px',
  fontSizeSmall: '13px',
  fontWeight: props.variant === 'plain' ? 'inherit' : '600',
  paddingMedium: '0 16px',
  paddingSmall: '0 10px',
  // 显式语义色交给 Naive UI 计算浅底/悬停色；CSS 变量不能直接参与它的颜色解析。
  ...(props.tone ? {} : {
    colorPrimary: 'var(--app-button-primary)',
    colorHoverPrimary: 'var(--app-button-primary-hover)',
    colorPressedPrimary: 'var(--app-button-primary-pressed)',
    colorFocusPrimary: 'var(--app-button-primary)',
    borderPrimary: '1px solid var(--app-button-primary)',
    borderHoverPrimary: '1px solid var(--app-button-primary-hover)',
    borderPressedPrimary: '1px solid var(--app-button-primary-pressed)',
    borderFocusPrimary: '1px solid var(--app-button-primary)',
    colorDisabledPrimary: 'var(--app-button-primary)',
    borderDisabledPrimary: '1px solid var(--app-button-primary)',
    textColorDisabledPrimary: '#ffffff',
    colorDisabled: 'var(--workspace-field-disabled)',
    borderDisabled: '1px solid var(--workspace-field-border)',
    textColorDisabled: 'var(--workspace-field-muted)',
    textColorPrimary: '#ffffff',
    textColorHoverPrimary: '#ffffff',
    textColorPressedPrimary: '#ffffff',
    textColorFocusPrimary: '#ffffff',
    color: 'var(--workspace-field-background)',
    colorHover: 'var(--app-button-secondary-hover)',
    colorPressed: 'var(--app-button-secondary-hover)',
    colorFocus: 'var(--workspace-field-background)',
    border: '1px solid var(--workspace-field-border)',
    borderHover: '1px solid var(--workspace-field-accent)',
    borderPressed: '1px solid var(--workspace-field-accent)',
    borderFocus: '1px solid var(--workspace-field-accent)',
    textColor: 'var(--app-button-secondary-text)',
    textColorHover: 'var(--workspace-field-accent)',
    textColorPressed: 'var(--workspace-field-accent)',
    textColorFocus: 'var(--workspace-field-accent)',
    textColorText: props.variant === 'plain' ? 'inherit' : 'var(--workspace-field-accent)',
    textColorTextHover: props.variant === 'plain' ? 'inherit' : 'var(--workspace-field-accent)',
    textColorTextPressed: props.variant === 'plain' ? 'inherit' : 'var(--workspace-field-accent)',
    textColorTextFocus: props.variant === 'plain' ? 'inherit' : 'var(--workspace-field-accent)'
  })
}))
</script>

<template>
  <NButton
    v-bind="$attrs"
    class="app-button"
    :class="`app-button--${variant}`"
    :type="tone ?? (variant === 'primary' ? 'primary' : 'default')"
    :text="variant === 'text' || variant === 'plain'"
    :attr-type="type"
    :size="size"
    :disabled="disabled || loading"
    :loading="loading"
    :theme-overrides="theme"
  >
    <template v-if="$slots.icon" #icon><slot name="icon" /></template>
    <slot />
  </NButton>
</template>

<style scoped>
/* 常规按钮保持单行，导航/标签/启动卡片用 plain 保留原有排版并复用 Naive UI 交互。 */
.app-button {
  flex-shrink: 0;
}
.app-button--text {
  height: auto;
  padding: 0;
}
.app-button--plain :deep(.n-button__content) {
  display: contents;
}
</style>
