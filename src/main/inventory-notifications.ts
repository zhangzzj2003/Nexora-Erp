import { inventoryWarningNoticeBody, validateInventoryWarningNotice } from '../shared/inventory-warning-notification.ts'

interface NativeNotice {
  on(event: 'click', listener: () => void): void
  show(): void
}

export function showInventoryWarningNotification(
  payload: unknown,
  focused: boolean,
  supported: boolean,
  create: (title: string, body: string) => NativeNotice,
  open: () => void
): boolean {
  const notice = validateInventoryWarningNotice(payload)
  if (focused || !supported) return false
  const nativeNotice = create('Nexora ERP 库存预警', inventoryWarningNoticeBody(notice))
  nativeNotice.on('click', open)
  nativeNotice.show()
  return true
}
