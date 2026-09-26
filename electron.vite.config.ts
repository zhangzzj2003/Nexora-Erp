import { defineConfig } from 'electron-vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import Icons from 'unplugin-icons/vite'

// 主进程、预加载脚本和 Vue 页面分别构建，避免桌面权限泄露到渲染进程。
export default defineConfig({
  main: {},
  preload: {},
  renderer: {
    // Tailwind 只处理 Vue 渲染页面，不参与 Electron 主进程和预加载脚本。
    // Remix Icon 在构建时转成 Vue SVG 组件，桌面端离线也能显示。
    plugins: [vue(), tailwindcss(), Icons({ compiler: 'vue3' })]
  }
})
