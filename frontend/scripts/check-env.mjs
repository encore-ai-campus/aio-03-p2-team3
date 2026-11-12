import assert from "node:assert/strict"
import { mkdtemp, rm, writeFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import { resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { build, resolveConfig } from "vite"
import config from "../vite.config.js"

const frontend = fileURLToPath(new URL("..", import.meta.url))
assert.equal(resolve(frontend, config.envDir), resolve(frontend, ".."))
const directory = await mkdtemp(resolve(tmpdir(), "trademate-env-"))
const values = {
  SUPABASE_URL: "https://env-check.supabase.example",
  SUPABASE_PUBLISHABLE_KEY: "sb_publishable_fake_env_check",
  SUPABASE_SECRET_KEY: "sb_secret_fake_must_stay_on_server",
  DATABASE_URL: "postgresql://fake_db_only@localhost/example",
  TOKEN_ENCRYPTION_KEY: "fake_server_encryption_setting",
}
const previous = Object.fromEntries(Object.keys(values).map((key) => [key, process.env[key]]))
try {
  for (const key of Object.keys(values)) delete process.env[key]
  await writeFile(resolve(directory, ".env"), Object.entries(values).map(([key,value]) => `${key}=${value}`).join("\n"))
  const options = { ...config, configFile: false, root: frontend, envDir: directory, logLevel: "silent" }
  const resolved = await resolveConfig(options, "build")
  assert.equal(resolved.env.SUPABASE_URL, values.SUPABASE_URL)
  assert.equal(resolved.env.SUPABASE_PUBLISHABLE_KEY, values.SUPABASE_PUBLISHABLE_KEY)
  const result = await build({ ...options, build: { write: false, minify: false } })
  const bundle = result.output.map((file) => file.code ?? String(file.source ?? "")).join("\n")
  for (const [key,value] of Object.entries(values)) {
    const isPublic = key === "SUPABASE_URL" || key === "SUPABASE_PUBLISHABLE_KEY"
    assert.equal(bundle.includes(value), isPublic, `${key}의 브라우저 공개 범위를 확인하세요`)
    if (!isPublic) assert.equal(resolved.env[key], undefined)
  }
  console.log("통과: 루트 .env 공유, 공개 URL·키 전달, 서버 비밀값 빌드 제외")
} finally {
  for (const [key,value] of Object.entries(previous)) {
    if (value === undefined) delete process.env[key]
    else process.env[key] = value
  }
  await rm(directory, { recursive: true, force: true })
}
