import { computed, ref } from 'vue'
import type { Ref } from 'vue'

// 本地步骤不写业务状态；只有确认页提交才调用原 Pinia 保存操作。
export function useNumberingSteps(initial: boolean, disabled: Ref<boolean>, valid: Ref<boolean>, save: () => Promise<void>) {
  const step = ref(0)
  const direction = ref<'next' | 'back'>('next')
  const canContinue = computed(() => !disabled.value && ((initial && step.value === 0) || valid.value))
  function back(target = step.value - 1): void {
    if (!initial || disabled.value || !Number.isInteger(target) || target < 0 || target >= step.value) return
    direction.value = 'back'
    step.value = target
  }
  async function submit(): Promise<void> {
    // 表单回车与按钮走相同边界，前两步不能意外保存或触发历史补号。
    if (!canContinue.value) return
    if (initial && step.value < 2) {
      direction.value = 'next'
      step.value += 1
      return
    }
    await save()
  }
  return { step, direction, canContinue, back, submit }
}
