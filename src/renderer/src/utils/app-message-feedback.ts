import { watch } from 'vue'
import type { Ref, WatchStopHandle } from 'vue'

export type AppMessageTone = 'success' | 'error' | 'warning'

// 只把非空的新反馈送往通知层；清空状态用于下一次同文案操作重新提示。
export function observeAppMessageFeedback(
  feedback: { notice: Ref<string>; error: Ref<string>; warning?: Ref<string> },
  show: (tone: AppMessageTone, content: string) => void
): WatchStopHandle {
  const stopNotice = watch(
    feedback.notice,
    (content) => {
      if (content) show('success', content)
    },
    { flush: 'sync' }
  )
  const stopError = watch(
    feedback.error,
    (content) => {
      if (content) show('error', content)
    },
    { flush: 'sync' }
  )
  // 刷新告警与保存失败使用不同颜色；旧调用方未提供 warning 时保持原行为。
  const stopWarning = feedback.warning ? watch(feedback.warning, (content) => {
    if (content) show('warning', content)
  }, { flush: 'sync' }) : undefined
  return () => {
    stopNotice()
    stopError()
    stopWarning?.()
  }
}
