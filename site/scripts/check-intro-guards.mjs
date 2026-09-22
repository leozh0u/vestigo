// Exercise failure paths with a fake key and a fetch stub. No network requests.
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const scripts = path.dirname(fileURLToPath(import.meta.url));
const cwd = await fs.mkdtemp(path.join(os.tmpdir(), "vestigo-guards-"));
try {
  const stitch = spawnSync(process.execPath, [path.join(scripts, "stitch-intro.mjs")], { cwd, encoding: "utf8" });
  assert.equal(stitch.status, 1);
  assert.match(stitch.stderr, /Missing required footage: media\/earth.mp4, media\/descent.mp4, media\/room.mp4/);
  await assert.rejects(fs.stat(path.join(cwd, "public")));

  await fs.writeFile(path.join(cwd, ".env.local"), "ELEVENLABS_API_KEY=local-test-key\n");
  for (const [label, status, body, expected] of [
    ["unreadable balance", 403, {}, /Cannot verify the credit balance/],
    ["malformed balance", 200, { character_limit: 50000 }, /Cannot verify the credit balance/],
    ["exhausted balance", 200, { character_count: 49000, character_limit: 50000 }, /under the 15,000 floor/],
  ]) {
    const mock = path.join(cwd, "fetch-stub.mjs");
    await fs.writeFile(mock, `globalThis.fetch = async (url, options) => {
      if (url !== "https://api.elevenlabs.io/v1/user/subscription" || options.method === "POST")
        throw new Error("Unexpected generation request");
      return new Response(${JSON.stringify(JSON.stringify(body))}, {status: ${status}});
    };`);
    const run = spawnSync(process.execPath,
      ["--import", mock, path.join(scripts, "make-video.mjs"), "through"], { cwd, encoding: "utf8" });
    assert.equal(run.status, 1, label);
    assert.match(run.stderr + run.stdout, expected, label);
    assert.doesNotMatch(run.stderr + run.stdout, /Unexpected generation request/, label);
    console.log(`PASS: ${label} stops before generation`);
  }
  console.log("PASS: missing footage cannot replace the opening manifest");
} finally {
  await fs.rm(cwd, { recursive: true, force: true });
}
