// Recover the published presentation assets without rendering or inference.
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const publicDir = path.join(root, 'public');
const lock = JSON.parse(await fs.readFile(path.join(root, 'presentation-assets.json'), 'utf8'));
const download = process.argv.includes('--fetch');
if (process.argv.slice(2).some(arg => !['--fetch', '--check'].includes(arg))) {
  throw new Error('Use --check (offline) or --fetch (published static files only).');
}
if (!/^https:\/\/raw\.githubusercontent\.com\/leozh0u\/vestigo\/[a-f0-9]{40}\/$/.test(lock.source)) {
  throw new Error('Asset source must be a pinned commit in the Vestigo repository.');
}
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const missing = [];
for (const asset of lock.files) {
  if (!/^(textures|opening)\/[\w.-]+$/.test(asset.path)
      || !/^[a-f0-9]{64}$/.test(asset.sha256)
      || !Number.isSafeInteger(asset.bytes) || asset.bytes <= 0) {
    throw new Error('Invalid asset lock entry.');
  }
  const dest = path.join(publicDir, asset.path);
  let bytes = await fs.readFile(dest).catch(error => {
    if (error.code === 'ENOENT') return null;
    throw error;
  });
  if (bytes?.length === asset.bytes && sha(bytes) === asset.sha256) continue;
  if (!download) { missing.push(asset.path); continue; }
  const response = await fetch(new URL(asset.path, lock.source), {
    signal: AbortSignal.timeout(120_000),
  });
  if (!response.ok) throw new Error(`Asset fetch failed (${response.status}): ${asset.path}`);
  bytes = Buffer.from(await response.arrayBuffer());
  if (bytes.length !== asset.bytes || sha(bytes) !== asset.sha256) {
    throw new Error(`Asset checksum mismatch: ${asset.path}`);
  }
  await fs.mkdir(path.dirname(dest), { recursive: true });
  const temporary = `${dest}.${process.pid}.part`;
  try {
    await fs.writeFile(temporary, bytes, { flag: 'wx' });
    await fs.rename(temporary, dest);
  } finally {
    await fs.rm(temporary, { force: true });
  }
  console.log(`Restored ${asset.path}`);
}
if (missing.length) {
  throw new Error(`Missing or changed presentation assets: ${missing.join(', ')}. Run npm run assets:fetch to restore the pinned published copies.`);
}
const intro = JSON.parse(await fs.readFile(path.join(publicDir, 'opening/intro.json'), 'utf8'));
if (!lock.files.some(asset => `/${asset.path}` === intro.src)) {
  throw new Error('The opening manifest does not select a locked presentation asset.');
}
const entries = JSON.parse(await fs.readFile(path.join(publicDir, 'traces/index.json'), 'utf8'));
if (!Array.isArray(entries) || !entries.length) throw new Error('No recorded investigations.');
for (const entry of entries) {
  if (!/^[\w.-]+\.json$/.test(entry.file) || !/^\/photos\/[\w.-]+\.jpg$/.test(entry.photo)) {
    throw new Error('Invalid recorded-investigation path.');
  }
  const trace = JSON.parse(await fs.readFile(path.join(publicDir, 'traces', entry.file), 'utf8'));
  if (!Array.isArray(trace.steps) || !trace.steps.length || !trace.final) {
    throw new Error(`Incomplete recorded investigation: ${entry.file}`);
  }
  await fs.access(path.join(publicDir, entry.photo.slice(1)));
}
console.log(`${lock.files.length} presentation assets and ${entries.length} recorded investigations verified.`);
