import { Plugin } from "@opencode/plugin"
import { spawn } from "node:child_process"
import { appendFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { dirname } from "node:path"

const BRIDGE_HOST = process.env.FS_BRIDGE_HOST || "127.0.0.1"
const BRIDGE_PORT = process.env.FS_BRIDGE_PORT || "8765"
const HEALTH_URL = `http://${BRIDGE_HOST}:${BRIDGE_PORT}/health`

// Optional trace of the instruction parts OpenCode assembles.
function trace(label: string, payload: unknown) {
  const target = process.env.FS_DEBUG_INSTRUCTIONS
  if (!target) return
  try {
    appendFileSync(target, JSON.stringify({ label, payload }) + "\n")
  } catch {}
}

// index.ts -> france-student-session -> plugins -> .opencode -> project root
function bridgeRoot(): string {
  const here = dirname(fileURLToPath(import.meta.url))
  return dirname(dirname(dirname(here)))
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

async function isBridgeUp(): Promise<boolean> {
  try {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 2000)
    const response = await fetch(HEALTH_URL, { signal: controller.signal })
    clearTimeout(timer)
    return response.ok
  } catch {
    return false
  }
}

function startBridge(root: string) {
  const python = process.env.FS_PYTHON || "python"
  try {
    const child = spawn(python, ["bridge_server.py"], {
      cwd: root,
      detached: true,
      stdio: "ignore",
      windowsHide: true,
    })
    child.unref()
    console.log(`[france-student] Pont demarre (${python} bridge_server.py)`)
  } catch (error) {
    console.error("[france-student] Demarrage du pont impossible:", error)
  }
}

// The bridge is started on demand, when a France Student request is made.
// It is never started at boot, and never started for another provider.
let starting: Promise<boolean> | undefined
let lastCheck = 0
let lastState = false

async function ensureBridge(root: string): Promise<boolean> {
  const now = Date.now()
  if (lastState && now - lastCheck < 10_000) return true
  lastCheck = now
  if (await isBridgeUp()) {
    lastState = true
    return true
  }
  lastState = false
  if (starting) return starting

  starting = (async () => {
    console.log("[france-student] Pont France Student absent, demarrage...")
    startBridge(root)
    for (let attempt = 0; attempt < 40; attempt++) {
      await sleep(500)
      if (await isBridgeUp()) {
        lastState = true
        lastCheck = Date.now()
        console.log("[france-student] Pont pret.")
        return true
      }
    }
    console.error("[france-student] Le pont n'a pas repondu a temps.")
    return false
  })().finally(() => {
    starting = undefined
  })
  return starting
}

export default Plugin.define({
  id: "france-student-bridge-session",
  async setup(ctx) {
    const root = bridgeRoot()

    // The bridge is started when OpenCode's server starts, which happens
    // when the user launches OpenCode. It is never started at boot.
    const ready = ensureBridge(root)

    await ctx.session.hook(
      "model.request",
      async (event) => {
        event.headers["x-opencode-session-id"] = event.sessionID
        event.headers["x-opencode-request-kind"] = event.kind
        // The agent name lets the bridge run its own agents (majfs) without
        // involving the model.
        const agent = (event as any).agent
        if (typeof agent === "string" && agent) {
          event.headers["x-opencode-agent"] = agent
        }
        trace("model.request", {
          kind: event.kind,
          session: event.sessionID,
          agent: (event as any).agent,
          keys: Object.keys(event as any),
        })
        // The working directory lets the bridge resolve the relative paths
        // the France Student models emit into absolute OpenCode paths.
        const directory = await resolveDirectory(ctx, event.sessionID)
        if (directory) {
          event.headers["x-opencode-directory"] = directory
        }
        // Safety net: the bridge may have been stopped since the server
        // started.
        await ready
      },
      { providerID: "france-student" },
    )

    // The upstream POST is stateful. A transport retry could create a second
    // FS chat or append the same message after an ambiguous timeout.
    await ctx.session.hook(
      "retry",
      (event) => {
        event.decision = { retry: false }
      },
      { providerID: "france-student" },
    )
  },
})

async function resolveDirectory(ctx: any, sessionID: string): Promise<string | undefined> {
  try {
    const session = await ctx.session.get({ sessionID })
    const directory = (session as any)?.directory
    if (typeof directory === "string" && directory) return directory
  } catch {
    // Fall through to the plugin location.
  }
  const location = (ctx as any)?.location?.directory
  return typeof location === "string" && location ? location : undefined
}
