import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import Icons from 'unplugin-icons/vite'
import { fileURLToPath } from 'node:url'
import { captureSink } from './site-preview/capture-sink.mjs'

// 截图预览只绑定回环地址，直接加载当前组件；不会连接或打包进正式桌面应用。
const root = fileURLToPath(new URL('..', import.meta.url))
const server = await createServer({
  configFile: false, root,
  plugins: [vue(), tailwindcss(), Icons({ compiler: 'vue3' }), { name: 'isolated-png-capture', configureServer(server) { server.middlewares.use(captureSink(root)) } }],
  resolve: { dedupe: ['vue', 'pinia', 'vue-router'] },
  optimizeDeps: { entries: ['scripts/site-preview/index.html'], include: ['vue', 'pinia', 'vue-router', 'naive-ui', 'vxe-table/es/table', 'vxe-table/es/column'] },
  server: { host: '127.0.0.1', port: 8766, strictPort: true },
})
await server.listen()
console.log('界面截图预览：http://127.0.0.1:8766/scripts/site-preview/index.html#/workspace/home')
for (const signal of ['SIGINT', 'SIGTERM']) process.once(signal, async () => { await server.close(); process.exit(0) })
