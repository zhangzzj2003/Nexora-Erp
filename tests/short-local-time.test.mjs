import assert from 'node:assert/strict'
import { test } from 'node:test'
import { execFileSync } from 'node:child_process'

// 独立进程指定时区，避免测试依赖执行机器位置或污染其他测试的时区。
function formatInZone(zone, values) {
  const source = `import {shortLocalTime} from './src/renderer/src/utils/formatters.ts'; console.log(JSON.stringify(${JSON.stringify(values)}.map(shortLocalTime)))`
  return JSON.parse(execFileSync(process.execPath, ['--experimental-strip-types', '--input-type=module', '-e', source], {
    cwd: new URL('..', import.meta.url), env: { ...process.env, TZ: zone }, encoding: 'utf8'
  }))
}

test('列表短时间保留本地日期和时分，兼容 UTC、显式偏移、跨年与无效历史值', () => {
  assert.deepEqual(formatInZone('Asia/Shanghai', [
    '2026-10-08 03:02:59', '2026-10-08T03:02:01Z', '2026-10-08T11:02:27+08:00',
    '2026-12-31T16:05:59Z', '', '未知时间'
  ]), ['26/10/8 11:02', '26/10/8 11:02', '26/10/8 11:02', '27/1/1 00:05', '', '未知时间'])
  assert.deepEqual(formatInZone('America/New_York', ['2026-10-08T03:02:59Z']), ['26/10/7 23:02'])
})
