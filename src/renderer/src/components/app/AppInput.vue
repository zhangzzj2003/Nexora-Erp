<script setup lang="ts" generic="T extends string | number | null | undefined">
import { useAttrs } from 'vue'
import type { InputHTMLAttributes } from 'vue'
import { NInput } from 'naive-ui'
import { normalizeInputValue } from '../../utils/input-value'
import type { InputModifiers } from '../../utils/input-value'

// 复用 Naive UI 输入外观，同时把必填、长度、数字上下限等规则交给真实输入元素。
defineOptions({ inheritAttrs: false })
const props = withDefaults(
  defineProps<{
    modelValue: T
    modelModifiers?: InputModifiers
    type?: 'text' | 'password' | 'number' | 'tel' | 'search' | 'textarea'
    disabled?: boolean
  }>(),
  { type: 'text', disabled: false }
)
const emit = defineEmits<{ 'update:modelValue': [value: T] }>()
const attrs = useAttrs()
// useAttrs 不提供响应式依赖；每次渲染重新读取，订单切换后 min/max 等限制才能同步更新。
function nativeInputProps(): InputHTMLAttributes {
  const { class: _class, style: _style, ...native } = attrs
  // Naive UI 负责密码显示/隐藏；数字和电话仍保留浏览器校验及键盘语义。
  return {
    ...native,
    ...(props.type === 'number' || props.type === 'tel' || props.type === 'search'
      ? { type: props.type }
      : {})
  }
}
function update(value: string): void {
  // 泛型保证页面模型沿用原有声明；转换规则只依据模型类型和显式修饰符。
  emit('update:modelValue', normalizeInputValue(value, props.modelValue, props.modelModifiers) as T)
}
</script>

<template>
  <NInput
    class="app-input"
    :class="$attrs.class"
    :style="$attrs.style as string | undefined"
    :value="modelValue == null ? '' : String(modelValue)"
    :type="type === 'password' ? 'password' : type === 'textarea' ? 'textarea' : 'text'"
    :rows="$attrs.rows as number | undefined"
    :disabled="disabled"
    :input-props="nativeInputProps()"
    :placeholder="($attrs.placeholder as string | undefined) ?? ''"
    :maxlength="$attrs.maxlength as number | string | undefined"
    :show-password-on="type === 'password' ? 'click' : undefined"
    @update:value="update"
  />
</template>
