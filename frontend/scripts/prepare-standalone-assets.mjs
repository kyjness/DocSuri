import { copyFileSync, existsSync, mkdirSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

const root = process.cwd();
const standaloneRoot = join(root, '.next', 'standalone');
const staticSource = join(root, '.next', 'static');
const staticTarget = join(standaloneRoot, '.next', 'static');
const publicSource = join(root, 'public');
const publicTarget = join(standaloneRoot, 'public');

if (!existsSync(standaloneRoot)) {
  throw new Error('Next standalone output is missing. Run next build first.');
}

if (existsSync(staticSource)) {
  mkdirSync(join(standaloneRoot, '.next'), { recursive: true });
  copyDirectory(staticSource, staticTarget);
}

if (existsSync(publicSource)) {
  copyDirectory(publicSource, publicTarget);
}

function copyDirectory(source, target) {
  mkdirSync(target, { recursive: true });
  for (const entry of readdirSync(source)) {
    const from = join(source, entry);
    const to = join(target, entry);
    if (statSync(from).isDirectory()) {
      copyDirectory(from, to);
    } else {
      copyFileSync(from, to);
    }
  }
}
