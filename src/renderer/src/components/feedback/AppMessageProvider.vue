<script setup lang="ts">
import { NMessageProvider } from 'naive-ui'
import AppMessageBridge from './AppMessageBridge.vue'
import { titleBarHeight, usesIntegratedTitleBar } from '../../../../shared/window-chrome'

// 桌面通知从融合标题栏下方留出 12px 间距，避免遮住设置、主题和原生窗口按钮。
// 偏移直接交给传送到 body 的通知容器，所有堆叠消息都在同一安全区域内。
const messageContainerStyle = usesIntegratedTitleBar(typeof window === 'undefined' ? undefined : window.nexora?.platform)
  ? { top: `${titleBarHeight + 12}px` }
  : undefined
</script>

<template>
  <!-- 提供器覆盖引导、登录和工作台；传送到顶层的消息不占据页面内容高度。 -->
  <NMessageProvider placement="top-right" :container-style="messageContainerStyle" :duration="4000" closable keep-alive-on-hover>
    <AppMessageBridge />
    <slot />
  </NMessageProvider>
</template>
