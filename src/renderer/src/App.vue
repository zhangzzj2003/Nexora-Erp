<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { NConfigProvider, darkTheme, dateZhCN, zhCN } from 'naive-ui'
import { storeToRefs } from 'pinia'
// 控件配色集中维护，主题切换由根样式变量与 Naive UI 共同驱动。
import { naiveThemeOverrides } from './utils/app-theme'
import { useAppStore } from './store/app-store'
import { useThemeStore } from './store/theme-store'
import OnboardingView from './views/OnboardingView.vue'
import WorkspaceShell from './views/WorkspaceShell.vue'
import AppMessageProvider from './components/feedback/AppMessageProvider.vue'
import AppTitleBar from './components/app/AppTitleBar.vue'
import WorkspaceTabs from './components/workspace/WorkspaceTabs.vue'
import { usesIntegratedTitleBar } from '../../shared/window-chrome'

// 根组件统一启动和释放桌面连接资源；页面状态仍由 Pinia store 管理。
const { screen, initialize, dispose } = useAppStore()
const { isDarkTheme } = storeToRefs(useThemeStore())
// 原生标题栏与页面共用一层外壳，确保登录、引导和工作台都有可拖动的顶部。
const platform = window.nexora?.platform ?? ''
const integratedTitleBar = usesIntegratedTitleBar(platform)
onMounted(() => {
  void initialize()
})
onUnmounted(dispose)
</script>

<template>
  <NConfigProvider
    :locale="zhCN"
    :date-locale="dateZhCN"
    :theme="isDarkTheme ? darkTheme : null"
    :theme-overrides="naiveThemeOverrides"
  >
    <AppMessageProvider>
      <div :class="{ 'desktop-shell': integratedTitleBar }">
        <AppTitleBar v-if="integratedTitleBar" :platform="platform">
          <WorkspaceTabs v-if="screen === 'app'" />
        </AppTitleBar>
        <OnboardingView v-if="screen !== 'app' && screen !== 'login' && screen !== 'setup'" />
        <WorkspaceShell v-else />
      </div>
    </AppMessageProvider>
  </NConfigProvider>
</template>

<style>
/* 可用高度扣除融合顶部栏，侧栏与底栏都保持在窗口内；浏览器预览不受影响。 */
.desktop-shell { height: 100vh; display: flex; flex-direction: column; overflow: hidden; }
.desktop-shell > .app-shell, .desktop-shell > .onboarding { flex: 1; min-height: 0; height: calc(100vh - 48px); }
.desktop-shell .sidebar, .desktop-shell .content { height: calc(100vh - 48px); }
/* 引导页品牌已进入顶部栏，避免出现两层相同的品牌标题。 */
.desktop-shell .onboard-top { display: none; }
</style>
