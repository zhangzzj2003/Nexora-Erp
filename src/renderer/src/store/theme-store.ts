import { computed, nextTick, onScopeDispose, ref, watch } from 'vue'
import { defineStore } from 'pinia'
import { readThemePreference, saveThemePreference } from '../utils/theme-preference'
import type { ThemeMode } from '../utils/theme-preference'
import { createThemeTransition, themeToggleOrigin } from '../utils/theme-transition'

function availableStorage(): Storage | undefined {
  try {
    return typeof window === 'undefined' ? undefined : window.localStorage
  } catch {
    return undefined
  }
}

// 主题作为独立 Pinia store，根组件与账号区读取同一份设置。
export const useThemeStore = defineStore('theme', () => {
  const themeMode = ref<ThemeMode>(readThemePreference(availableStorage()))
  const isDarkTheme = computed(() => themeMode.value === 'dark')

  function setDarkTheme(enabled: boolean): void {
    themeMode.value = enabled ? 'dark' : 'light'
  }

  // 动画只负责主题切换时的画面快照，持久化和根节点配色继续由本 store 维护。
  const motion = createThemeTransition({
    isDark: () => isDarkTheme.value,
    setDark: setDarkTheme,
    flush: nextTick,
    environment: () => typeof document === 'undefined' ? undefined : {
      width: window.innerWidth,
      height: window.innerHeight,
      reducedMotion: window.matchMedia('(prefers-reduced-motion: reduce)').matches,
      root: document.documentElement,
      start: typeof document.startViewTransition === 'function'
        ? (update) => document.startViewTransition(update) : undefined
    }
  })
  function toggleTheme(event: MouseEvent): void {
    const target = event.currentTarget
    const origin = target instanceof HTMLElement ? themeToggleOrigin(event, target.getBoundingClientRect()) : undefined
    void motion.toggle(origin).catch((error: unknown) => console.error('切换主题失败', error))
  }
  onScopeDispose(motion.dispose)

  watch(themeMode, (mode) => {
    // 主题切换同步更新根节点与本地偏好，设置存储不可用时仍保留当前视觉状态。
    if (typeof document !== 'undefined') {
      document.documentElement.dataset.theme = mode
      document.documentElement.style.colorScheme = mode
    }
    saveThemePreference(availableStorage(), mode)
  }, { immediate: true })

  return { themeMode, isDarkTheme, setDarkTheme, toggleTheme }
})
