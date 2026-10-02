import { build } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import Icons from 'unplugin-icons/vite'
import { fileURLToPath } from 'node:url'
import { readFileSync,writeFileSync,readdirSync } from 'node:fs'
import { resolve } from 'node:path'
import { createHash } from 'node:crypto'

// 使用相对资源路径，GitHub Pages 子目录与本地预览均加载同一真实组件包。
export async function buildLivePreview(output) {
  await build({ configFile:false, root:fileURLToPath(new URL('./site-preview',import.meta.url)), base:'./',
    plugins:[vue(),tailwindcss(),Icons({compiler:'vue3'})], resolve:{dedupe:['vue']},
    build:{outDir:output,emptyOutDir:true,rollupOptions:{input:fileURLToPath(new URL('./site-preview/stage.html',import.meta.url))}} })
  // 在入口解析时提前下载共用 App、表格及样式，减少动态导入造成的串行等待。
  const assets=readdirSync(resolve(output,'assets')).sort()
  const warm=assets.filter(file=>/^(main-|WorkspaceTable-).*(?:\.js|\.css)$/.test(file))
  const path=resolve(output,'stage.html'),html=readFileSync(path,'utf8')
  writeFileSync(path,html.replace('</head>',warm.map(file=>`<link rel="${file.endsWith('.css')?'stylesheet':'modulepreload'}" href="./assets/${file}"${file.endsWith('.js')?' crossorigin':''}>`).join('')+'</head>'))
  // HTML 入口也携带组件包版本，旧缓存不会继续引用已替换的分包文件。
  const hash=createHash('sha256')
  for(const file of assets) hash.update(readFileSync(resolve(output,'assets',file)))
  return hash.digest('hex').slice(0,12)
}
