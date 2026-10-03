<script setup lang="ts">
import { onUnmounted, watch } from 'vue'
import { useAppStore } from '../../store/app-store'
import { useAppMessage } from '../../composables/use-app-message'
import { observeAppMessageFeedback } from '../../utils/app-message-feedback'

const { notice, error, warningAlert } = useAppStore()
const message = useAppMessage()

// 桥接现有业务状态，所有页面的成功与失败反馈都复用同一个右上角通知层。
const stop = observeAppMessageFeedback({ notice, error }, (tone, content) => {
  message[tone](content)
})
const stopWarning = watch(warningAlert, (alert) => {
  if (alert) message.warning(alert.content)
}, { flush: 'sync' })
onUnmounted(() => { stop(); stopWarning() })
</script>

<template></template>
