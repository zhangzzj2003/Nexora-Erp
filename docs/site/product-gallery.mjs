// 图片失败只替换说明，不移除原图链接；脚本失效时链接仍能独立打开图片。
export function watchImage(image, fallback, onReady = () => {}) {
  const update = failed => {
    image.hidden = failed
    fallback.hidden = !failed
    onReady(!failed)
  }
  image.addEventListener('error', () => update(true))
  image.addEventListener('load', () => update(false))
  if (image.complete) update(image.naturalWidth === 0)
}

export function mountProductGallery(root = document) {
  const dialog = root.querySelector('.product-lightbox')
  const links = [...root.querySelectorAll('[data-product-image]')]
  for (const link of links) {
    const image = link.querySelector('img')
    // 行内关联只在原图加载成功后显示；普通截图也保留同一失败提示路径。
    link.dataset.imageReady = String(image.complete && image.naturalWidth > 0)
    watchImage(image, link.querySelector('.image-error'), ready => { link.dataset.imageReady = String(ready) })
  }
  if (!dialog || typeof dialog.showModal !== 'function') return
  const image = dialog.querySelector('img')
  const title = dialog.querySelector('h2')
  const original = dialog.querySelector('.lightbox-original')
  const closeButton = dialog.querySelector('button')
  watchImage(image, dialog.querySelector('.lightbox-error'))
  let opener = null
  for (const link of links) link.addEventListener('click', event => {
    // 修饰键和非主键保留浏览器原有打开方式，不截获另开标签操作。
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
    event.preventDefault()
    opener = link
    title.textContent = link.dataset?.imageTitle || link.closest('figure')?.querySelector('h3')?.textContent || link.querySelector('img').alt
    image.alt = link.querySelector('img').alt
    image.hidden = false
    dialog.querySelector('.lightbox-error').hidden = true
    image.src = link.href
    original.href = link.href
    dialog.showModal()
  })
  dialog.addEventListener('click', event => {
    // 只有点击弹窗边界外才关闭，点击图片和弹窗内部不会误关。
    const bounds = dialog.getBoundingClientRect()
    if (event.target === dialog && (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom)) dialog.close()
  })
  dialog.addEventListener('close', () => opener?.focus({ preventScroll: true }))
  dialog.addEventListener('keydown', event => {
    // 显式循环首尾入口，避免浏览器把 Tab 焦点移到工具栏后让页面暂时失去焦点。
    if (event.key !== 'Tab') return
    const active = dialog.ownerDocument.activeElement
    if (event.shiftKey && active === closeButton) {
      event.preventDefault(); original.focus()
    } else if (!event.shiftKey && active === original) {
      event.preventDefault(); closeButton.focus()
    }
  })
}

if (typeof document !== 'undefined') mountProductGallery()
