import { build } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import Icons from 'unplugin-icons/vite'
import { fileURLToPath } from 'node:url'

// 使用相对资源路径，GitHub Pages 子目录与本地预览均加载同一真实组件包。
export async function buildLivePreview(output) {
  await build({ configFile:false, root:fileURLToPath(new URL('./site-preview',import.meta.url)), base:'./',
    plugins:[vue(),tailwindcss(),Icons({compiler:'vue3'})], resolve:{dedupe:['vue']},
    build:{outDir:output,emptyOutDir:true,rollupOptions:{input:fileURLToPath(new URL('./site-preview/stage.html',import.meta.url))}} })
}
