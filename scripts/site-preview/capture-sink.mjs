import { writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

// 只接受三张规定素材的三倍像素 PNG，路径和大小均在边界校验，不开放任意文件写入。
export function validateCapture(path, bytes) {
  const allowed = ['receipts@3x.png', 'inventory@3x.png', 'sources@3x.png']
  const file = path?.replace('/__preview_capture/', '')
  if (!path?.startsWith('/__preview_capture/') || !allowed.includes(file)) throw new Error('不允许的取景文件')
  if (bytes.length < 24 || bytes.length > 20 * 1024 * 1024 || bytes.subarray(0, 8).toString('hex') !== '89504e470d0a1a0a' || bytes.readUInt32BE(16) !== 5400 || bytes.readUInt32BE(20) !== 3600) throw new Error('必须为 5400 × 3600 的高清 PNG')
  return file
}

export function captureSink(root) {
  return async (request, response, next) => {
    if (!request.url?.startsWith('/__preview_capture/')) return next()
    try {
      // 固定回环源，拒绝跨站页面向取景工具写图；正式应用与官网不存在此入口。
      if (request.method !== 'POST' || request.headers.origin !== 'http://127.0.0.1:8766') throw new Error('只接受本地预览导出')
      const chunks = []; let size = 0
      for await (const chunk of request) {
        size += chunk.length
        if (size > 20 * 1024 * 1024) throw new Error('取景文件过大')
        chunks.push(chunk)
      }
      const bytes = Buffer.concat(chunks), file = validateCapture(request.url, bytes)
      await writeFile(resolve(root, 'docs/site/screenshots', file), bytes)
      response.end('已保存高清 PNG')
    } catch (error) { response.statusCode = 400; response.end(error.message) }
  }
}
