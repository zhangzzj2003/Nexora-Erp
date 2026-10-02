// 在浏览器内用真实 DOM 和当前计算样式取景；直接以三倍像素绘制，避免放大低分辨率图片。
export function captureFile(path) {
  return { '/workspace/receipts': 'receipts@3x.png', '/workspace/inventory-ledger': 'inventory@3x.png', '/workspace/financial-sources': 'sources@3x.png' }[path] ?? null
}

// SVG 的实际栅格化尺寸就是 5400×3600，viewBox 保持原排版；不是先生成小图再拉伸。
export function captureSvg(xml) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="5400" height="3600" viewBox="0 0 1800 1200"><foreignObject width="1800" height="1200">${xml}</foreignObject></svg>`
}

async function cloneAppearance(node) {
  const copy = node.cloneNode(false)
  if (node instanceof Element) {
    const style = getComputedStyle(node)
    copy.setAttribute('style', [...style].map(name => `${name}:${style.getPropertyValue(name)}`).join(';'))
    // 内联品牌资源，防止 SVG 导出过程中丢失图片或污染画布；不会访问正式服务。
    if (node instanceof HTMLImageElement) {
      const response = await fetch(node.currentSrc)
      if (!response.ok) throw new Error('品牌图片加载失败')
      const blob = await response.blob()
      const uri = await new Promise((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => resolve(reader.result)
        reader.onerror = reject
        reader.readAsDataURL(blob)
      })
      copy.setAttribute('src', uri)
      copy.removeAttribute('srcset')
    }
    if (node instanceof HTMLInputElement) copy.setAttribute('value', node.value)
  }
  for (const child of node.childNodes) copy.append(await cloneAppearance(child))
  return copy
}

export async function captureInterface(root) {
  await document.fonts.ready
  // 路由切换的侧栏/标签颜色过渡结束后再读取样式，避免把旧页面选中态取进新图。
  await new Promise(resolve => requestAnimationFrame(resolve))
  await Promise.all(root?.getAnimations({ subtree: true }).filter(animation => animation.effect?.getTiming().iterations !== Infinity).map(animation => animation.finished.catch(() => {})) ?? [])
  if (!root) throw new Error('真实工作台尚未加载')
  const rect = root.getBoundingClientRect()
  if (Math.abs(rect.width - 1800) > 1 || Math.abs(rect.height - 1200) > 1) throw new Error('请将取景窗口设为 1800 × 1200')
  const clone = await cloneAppearance(root)
  clone.setAttribute('xmlns', 'http://www.w3.org/1999/xhtml')
  const xml = new XMLSerializer().serializeToString(clone)
  const svg = captureSvg(xml)
  // data URI 使内联 foreignObject 保持可导出；blob URL 在部分 Chromium 版本会污染画布。
  const url = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
  const image = new Image()
  image.src = url
  await image.decode()
  if (image.naturalWidth !== 5400 || image.naturalHeight !== 3600) throw new Error('浏览器未按高清尺寸绘制')
  const canvas = document.createElement('canvas')
  canvas.width = 5400; canvas.height = 3600
  const context = canvas.getContext('2d')
  if (!context) throw new Error('浏览器无法创建取景画布')
  context.fillStyle = '#f4f6f9'; context.fillRect(0, 0, canvas.width, canvas.height)
  context.drawImage(image, 0, 0)
  return await new Promise((resolve, reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('高清图片导出失败')), 'image/png'))
}

export function mountCaptureTool() {
  const button = document.createElement('button')
  button.textContent = '导出当前界面高清 PNG'
  button.style.cssText = 'position:fixed;right:20px;bottom:40px;z-index:99999;padding:12px;background:white;border:1px solid #237d7a;border-radius:8px'
  button.onclick = async () => {
    const file = captureFile(location.hash.slice(1))
    if (!file) { button.textContent = '此页面不属于三窗取景范围'; return }
    button.disabled = true
    try {
      const blob = await captureInterface(document.querySelector('.desktop-shell'))
      const response = await fetch(`/__preview_capture/${file}`, { method: 'POST', body: blob })
      if (!response.ok) throw new Error(await response.text())
      button.textContent = `已保存 ${file}`
    } catch (error) { button.textContent = `取景失败：${error.message}` }
    finally { button.disabled = false }
  }
  document.body.append(button)
}
