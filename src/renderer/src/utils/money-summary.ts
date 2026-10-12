// 金额统一按“分”累加，超过 Number 安全整数范围时也不丢失精度。
export function moneyCents(value: string | null | undefined): bigint | null {
  // 旧草稿可能没有金额字段，按待完善处理，不能让汇总中断整个弹窗渲染。
  if (typeof value !== 'string' || value.length > 30) return null
  const match = /^\+?(\d+(?:\.\d*)?|\.\d+)(?:[eE]([+-]?\d+))?$/.exec(value)
  if (!match) return null
  const [whole, fraction = ''] = match[1].split('.')
  const exponent = Number(match[2] ?? 0), shift = 2 + exponent - fraction.length
  if (!Number.isInteger(exponent) || Math.abs(exponent) > 25 || shift < 0) return null
  const cents = BigInt((whole || '0') + fraction) * 10n ** BigInt(shift)
  return cents <= 10n ** 19n ? cents : null // 最多 100 行、每行一千万亿元。
}
export function sumMoney(values: readonly (string | null | undefined)[]): string | null {
  let total = 0n
  for (const value of values) {
    const cents = moneyCents(value)
    // 尚未填写或非法的金额不视为零元，避免显示看似完整的合计。
    if (cents === null) return null
    total += cents
  }
  return `${total / 100n}.${(total % 100n).toString().padStart(2, '0')}`
}
const digits = '零壹贰叁肆伍陆柒捌玖'
function fourDigits(value: number): string {
  let result = '', pendingZero = false
  for (const [index, digit] of String(value).padStart(4, '0').split('').entries()) {
    const number = Number(digit)
    if (number === 0) { if (result) pendingZero = true; continue }
    if (pendingZero) result += '零'
    result += digits[number] + ['仟', '佰', '拾', ''][index]
    pendingZero = false
  }
  return result
}
export function uppercaseMoney(value: string | null): string {
  if (value === null) return '待完善'
  const cents = moneyCents(value)
  if (cents === null) return '待完善'
  let yuan = cents / 100n, integer = '', pendingZero = false
  const groups: number[] = []
  do { groups.push(Number(yuan % 10000n)); yuan /= 10000n } while (yuan > 0n)
  const units = ['', '万', '亿', '兆', '京', '垓', '秭', '穰']
  for (let index = groups.length - 1; index >= 0; index--) {
    const group = groups[index]
    if (!group) { if (integer) pendingZero = true; continue }
    if (integer && (pendingZero || group < 1000)) integer += '零'
    integer += fourDigits(group) + units[index]
    pendingZero = false
  }
  const jiao = Number(cents / 10n % 10n), fen = Number(cents % 10n)
  let result = (integer || '零') + '元'
  if (jiao) result += digits[jiao] + '角'
  if (fen) result += (!jiao && cents >= 100n ? '零' : '') + digits[fen] + '分'
  if (!jiao && !fen) result += '整'
  return result
}
