<script setup lang="ts">
import { onMounted, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { nexoraLogo } from '../../assets/brand'
import { useThemeStore } from '../../store/theme-store'
import { usePiniaAppStore } from '../../store/app-store'
import WorkspaceTitleNavigation from '../workspace/WorkspaceTitleNavigation.vue'
import ThemeToggle from './ThemeToggle.vue'

defineProps<{ platform: string }>()
const { themeMode } = storeToRefs(useThemeStore())
const { screen } = storeToRefs(usePiniaAppStore())

function syncWindowTheme(): void {
  // 原生控件主题同步失败要保留诊断信息，不能阻止页面主题切换。
  void window.nexora?.setWindowTheme(themeMode.value).catch((error: unknown) => {
    console.error('同步窗口标题栏主题失败', error)
  })
}
onMounted(syncWindowTheme)
watch(themeMode, syncWindowTheme)
</script>

<template>
  <!-- 固定在窗口顶部，不随业务页面滚动；空白处负责原生窗口拖动。 -->
  <header class="app-titlebar" :class="{ 'app-titlebar--mac': platform === 'darwin' }">
    <div class="app-titlebar-safe-area">
      <div class="app-titlebar-brand">
        <img :src="nexoraLogo" alt="" />
        <strong>NEXORA <span>ERP</span></strong>
      </div>
      <!-- 工作台目录替代固定标语；引导与登录阶段保留可拖动空白。 -->
      <div class="app-titlebar-caption"><WorkspaceTitleNavigation v-if="screen === 'app'" /></div>
      <div class="app-titlebar-actions"><ThemeToggle /></div>
    </div>
  </header>
</template>

<style scoped>
/* 原生控件安全区由 Electron 提供，系统缩放、全屏和按钮位置变化时自动更新。 */
.app-titlebar { flex: none; height: 48px; background: #fff; color: #17213b; border-bottom: 1px solid #dfe6ed; -webkit-app-region: drag; user-select: none; }
.app-titlebar-safe-area { margin-left: env(titlebar-area-x, 0px); width: env(titlebar-area-width, calc(100% - 138px)); height: 100%; display: flex; align-items: center; gap: 16px; padding: 0 12px; }
.app-titlebar--mac .app-titlebar-safe-area { margin-left: env(titlebar-area-x, 88px); width: env(titlebar-area-width, calc(100% - 88px)); }
.app-titlebar-brand { display: flex; flex: none; align-items: center; gap: 9px; white-space: nowrap; font-size: 13px; letter-spacing: .05em; }
.app-titlebar-brand img { width: 27px; height: 27px; object-fit: contain; }
.app-titlebar-brand span { font-size: 11px; color: #237d7a; }
.app-titlebar-caption { flex: 1; min-width: 0; display: flex; }
/* 主题按钮不参与拖动；页面标签另占内容区的第二行。 */
.app-titlebar-actions { -webkit-app-region: no-drag; }
.app-titlebar-actions { flex: none; display: flex; align-items: center; }
:root[data-theme='dark'] .app-titlebar { background: #111d32; color: #e6edf8; border-color: #33445f; }
:root[data-theme='dark'] .app-titlebar-brand span { color: #68cbc2; }
@media (max-width: 900px) {
  .app-titlebar-safe-area { gap: 10px; }
  .app-titlebar-brand strong { display: none; }
}
</style>
