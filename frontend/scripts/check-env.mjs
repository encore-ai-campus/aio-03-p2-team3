import assert from "node:assert/strict"
import { mkdtemp, rm, writeFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import { resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { build, resolveConfig } from "vite"
import createConfig from "../vite.config.js"

const frontend = fileURLToPath(new URL("..", import.meta.url))
const directory = await mkdtemp(resolve(tmpdir(), "trademate-env-"))
const values = {
  SUPABASE_URL: "https://env-check.supabase.example",
  SUPABASE_PUBLISHABLE_KEY: "sb_publishable_fake_env_check",
  SUPABASE_SECRET_KEY: "sb_secret_fake_must_stay_on_server",
  DATABASE_URL: "postgresql://fake_db_only@localhost/example",
  TOKEN_ENCRYPTION_KEY: "fake_server_encryption_setting",
}
const previous = Object.fromEntries(Object.keys(values).map((key) => [key, process.env[key]]))
const previousPort = process.env.FRONTEND_PORT
try {
  process.env.FRONTEND_PORT = ""
  const config = createConfig({ mode: "development" })
  assert.equal(resolve(config.envDir), resolve(frontend, ".."))
  assert.equal(config.server.port, 5174)
  assert.equal(config.server.strictPort, true)
  process.env.FRONTEND_PORT = "3000"
  assert.equal(createConfig({ mode: "development" }).server.port, 3000)
  for (const invalid of ["invalid", "0", "65536", "1.5"]) {
    process.env.FRONTEND_PORT = invalid
    assert.throws(() => createConfig({ mode: "development" }), /FRONTEND_PORT/)
  }
  process.env.FRONTEND_PORT = "3000"
  for (const key of Object.keys(values)) delete process.env[key]
  await writeFile(resolve(directory, ".env"), Object.entries(values).map(([key,value]) => `${key}=${value}`).join("\n"))
  const options = { ...config, configFile: false, root: frontend, envDir: directory, logLevel: "silent" }
  const resolved = await resolveConfig(options, "build")
  assert.equal(resolved.env.SUPABASE_URL, values.SUPABASE_URL)
  assert.equal(resolved.env.SUPABASE_PUBLISHABLE_KEY, values.SUPABASE_PUBLISHABLE_KEY)
  assert.equal(resolved.env.FRONTEND_PORT, undefined)
  const result = await build({ ...options, build: { write: false, minify: false } })
  const bundle = result.output.map((file) => file.code ?? String(file.source ?? "")).join("\n")
  for (const [key,value] of Object.entries(values)) {
    const isPublic = key === "SUPABASE_URL" || key === "SUPABASE_PUBLISHABLE_KEY"
    assert.equal(bundle.includes(value), isPublic, `${key}의 브라우저 공개 범위를 확인하세요`)
    if (!isPublic) assert.equal(resolved.env[key], undefined)
  }
  console.log("통과: 기본 5174·지정 3000·잘못된 포트 거부, 공개 URL·키 전달, 서버 비밀값 빌드 제외")
} finally {
  if (previousPort === undefined) delete process.env.FRONTEND_PORT
  else process.env.FRONTEND_PORT = previousPort
  for (const [key,value] of Object.entries(previous)) {
    if (value === undefined) delete process.env[key]
    else process.env[key] = value
  }
  await rm(directory, { recursive: true, force: true })
}
