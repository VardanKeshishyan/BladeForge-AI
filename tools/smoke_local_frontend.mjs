// Read-only browser smoke check against an already running frontend/backend.
// Uses a separate headless Chrome profile; never signs in or submits render jobs.
import { spawn } from 'node:child_process'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import assert from 'node:assert/strict'

const origin = process.env.UI_TEST_ORIGIN || 'http://127.0.0.1:3000'
const artifacts = resolve('.next/ui-checks')
await mkdir(artifacts, { recursive: true })
const browser = spawn('C:/Program Files/Google/Chrome/Application/chrome.exe', [
  '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  '--remote-debugging-port=9228', `--user-data-dir=${artifacts}/chrome-profile`, 'about:blank',
], { windowsHide: true, stdio: 'ignore' })
let browserError
browser.on('error', error => { browserError = error })
let socket
try {
  let tab
  for (let attempt = 0; attempt < 60; attempt++) {
    if (browserError) throw browserError
    try {
      tab = await (await fetch('http://127.0.0.1:9228/json/new?about:blank', { method: 'PUT' })).json()
      break
    } catch { await new Promise(resolve => setTimeout(resolve, 250)) }
  }
  assert.ok(tab, 'Headless browser did not start')
  socket = new WebSocket(tab.webSocketDebuggerUrl)
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject })
  const pending = new Map()
  let sequence = 0
  socket.onmessage = ({ data }) => {
    const message = JSON.parse(data)
    if (message.id && pending.has(message.id)) {
      const { resolve, reject, timer } = pending.get(message.id)
      clearTimeout(timer)
      pending.delete(message.id)
      if (message.error) reject(new Error(JSON.stringify(message.error)))
      else resolve(message.result)
    }
  }
  function command(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = ++sequence
      const timer = setTimeout(() => { pending.delete(id); reject(new Error(`Timeout: ${method}`)) }, 30000)
      pending.set(id, { resolve, reject, timer })
      socket.send(JSON.stringify({ id, method, params }))
    })
  }
  async function evaluate(expression) {
    const result = await command('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
    if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails))
    return result.result.value
  }
  async function visit(path, expected) {
    await command('Page.navigate', { url: origin + path })
    let text = ''
    for (let attempt = 0; attempt < 120; attempt++) {
      text = await evaluate('document.body?.innerText || ""')
      if (text.includes(expected)) break
      await new Promise(resolve => setTimeout(resolve, 250))
    }
    assert.ok(text.includes(expected), `${path}: expected ${expected}; got ${text.slice(0, 450)}`)
    assert.ok(!text.includes('Couldn’t load this workspace page'), `${path}: workspace error`)
    const nav = await evaluate('Array.from(document.querySelectorAll("aside nav a")).map(a=>a.textContent.trim())')
    assert.ok(!nav.some(label => ['Team', 'Docs', 'Defect Library', 'API Keys'].includes(label)))
    assert.ok(!await evaluate(`!!document.querySelector('button[aria-label="User menu"]')`))
    console.log(`PASS ${path}`)
    return text
  }
  await command('Page.enable')
  await command('Runtime.enable')
  await command('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false })
  const home = await visit('/', 'Turbine inspection data.')
  assert.ok(!/Sign in|Request access|Pricing/.test(home))
  assert.equal(await evaluate(`Array.from(document.querySelectorAll('a[href^="#"]')).every(a => document.querySelector(a.getAttribute('href')))`), true)
  await writeFile(`${artifacts}/home-desktop.png`, Buffer.from((await command('Page.captureScreenshot', { format: 'png' })).data, 'base64'))
  await visit('/app/overview', 'Your workspace')
  await visit('/app/jobs', 'Generation jobs')
  await writeFile(`${artifacts}/workspace-desktop.png`, Buffer.from((await command('Page.captureScreenshot', { format: 'png' })).data, 'base64'))
  const jobHref = await evaluate(`document.querySelector('main a[href^="/app/jobs/"]')?.getAttribute('href')`)
  if (jobHref) await visit(jobHref, 'Back to jobs')
  await visit('/app/datasets', 'datasets')
  const datasetHref = await evaluate(`document.querySelector('main a[href^="/app/datasets/"]')?.getAttribute('href')`)
  if (datasetHref) await visit(datasetHref, 'Back to datasets')
  await visit('/app/usage', 'Generation activity')
  await visit('/app/settings', 'Workspace settings')
  assert.ok((await evaluate('document.body.innerText')).includes('Connected'))
  await visit('/app/generate', 'Job configuration')
  for (const path of ['/auth/sign-in', '/auth/sign-up', '/onboarding']) {
    const response = await fetch(origin + path, { redirect: 'manual' })
    assert.equal(new URL(response.headers.get('location')).pathname, '/app/generate')
    console.log(`PASS redirect ${path}`)
  }
  await command('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true })
  await visit('/', 'Turbine inspection data.')
  assert.equal(await evaluate('document.documentElement.scrollWidth <= window.innerWidth'), true)
  await writeFile(`${artifacts}/home-mobile.png`, Buffer.from((await command('Page.captureScreenshot', { format: 'png' })).data, 'base64'))
  console.log(`Screenshots: ${artifacts}`)
} finally {
  socket?.close()
  browser.kill()
}
