#!/usr/bin/env node
import { readdirSync, readFileSync, existsSync, statSync } from 'fs';
import { join, basename } from 'path';

const repoRoot = process.cwd();
const examplesRoot = join(repoRoot, 'sdk', 'examples');

function listDirs(path) {
  return readdirSync(path, { withFileTypes: true })
    .filter((d) => d.isDirectory())
    .map((d) => d.name);
}

function walkFiles(path, exts, out = []) {
  if (!existsSync(path)) return out;
  for (const dirent of readdirSync(path, { withFileTypes: true })) {
    const full = join(path, dirent.name);
    if (dirent.isDirectory()) {
      walkFiles(full, exts, out);
    } else if (exts.some((ext) => dirent.name.endsWith(ext))) {
      out.push(full);
    }
  }
  return out;
}

function read(path) {
  return readFileSync(path, 'utf8');
}

function extractPythonRunTarget(pyRunSh) {
  if (!existsSync(pyRunSh)) return { type: 'missing', target: null, raw: null };
  const text = read(pyRunSh);
  const moduleMatch = text.match(/-m\s+([A-Za-z0-9_.]+)/);
  if (moduleMatch) {
    const moduleName = moduleMatch[1];
    const rel = `${moduleName.replace(/\./g, '/')}.py`;
    return { type: 'module', target: rel, raw: moduleName };
  }
  if (/\bmain\.py\b/.test(text)) {
    return { type: 'script', target: 'main.py', raw: 'main.py' };
  }
  return { type: 'unknown', target: null, raw: null };
}

function extractJsRunTarget(jsRunSh) {
  if (!existsSync(jsRunSh)) return { type: 'missing', target: null, raw: null };
  const text = read(jsRunSh);
  const m = text.match(/node\s+dist\/([A-Za-z0-9_\-/]+)\.js/);
  if (!m) return { type: 'unknown', target: null, raw: null };
  return { type: 'dist', target: `src/${m[1]}.ts`, raw: `dist/${m[1]}.js` };
}

function hasToken(text, token) {
  return text.includes(token);
}

function detectPythonCapabilities(pyFiles) {
  let usesFlatmachines = false;
  let usesFlatagents = false;

  for (const file of pyFiles) {
    const text = read(file);
    if (/\bflatmachines\b/.test(text) || /\bFlatMachine\b/.test(text)) {
      usesFlatmachines = true;
    }
    if (/\bflatagents\b/.test(text) || /\bFlatAgent\b/.test(text)) {
      usesFlatagents = true;
    }
  }

  return { usesFlatmachines, usesFlatagents };
}

function detectJsCapabilities(jsFiles) {
  let usesFlatmachines = false;
  let usesFlatagents = false;
  let importsFlatmachinesPkg = false;
  let importsFlatagentsPkg = false;

  for (const file of jsFiles) {
    const text = read(file);
    if (text.includes('@memgrafter/flatmachines')) importsFlatmachinesPkg = true;
    if (text.includes('@memgrafter/flatagents')) importsFlatagentsPkg = true;

    if (/\bFlatMachine\b/.test(text)) usesFlatmachines = true;

    // Agent capability can come from either package.
    if (/\bFlatAgent\b/.test(text)) usesFlatagents = true;
  }

  return {
    usesFlatmachines,
    usesFlatagents,
    importsFlatmachinesPkg,
    importsFlatagentsPkg,
  };
}

function loadPackageDeps(packageJsonPath) {
  if (!existsSync(packageJsonPath)) return new Set();
  const pkg = JSON.parse(read(packageJsonPath));
  const deps = { ...(pkg.dependencies || {}), ...(pkg.devDependencies || {}) };
  return new Set(Object.keys(deps));
}

function checkRunShLocalPin(runShPath, pkgName) {
  if (!existsSync(runShPath)) return false;
  const text = read(runShPath);
  const escaped = pkgName.replace('/', '\\/');
  const re = new RegExp(`npm\\s+pkg\\s+set\\s+dependencies\\.${escaped}=`, 'm');
  return re.test(text);
}

function extractConfigBasenamesFromText(text) {
  const out = new Set();
  let m;

  // JS join(configDir, 'machine.yml') and Python os.path.join(..., "config", "machine.yml")
  const joinRe = /join\([^\n]*config[^\n]*[,/]\s*['"]([^'"]+\.(?:yml|yaml|json))['"]/g;
  while ((m = joinRe.exec(text)) !== null) {
    out.add(basename(m[1]));
  }

  // Python Path / 'config' / 'machine.yml'
  const pathOpRe = /['"]config['"]\s*\/\s*['"]([^'"]+\.(?:yml|yaml|json))['"]/g;
  while ((m = pathOpRe.exec(text)) !== null) {
    out.add(basename(m[1]));
  }

  // Any explicit config/... path string
  const slashRe = /config\/(?:[^'"\s\/]+\/)*([^'"\s\/]+\.(?:yml|yaml|json))/g;
  while ((m = slashRe.exec(text)) !== null) {
    out.add(basename(m[1]));
  }

  return out;
}

function resolveTargetPath(baseDir, kind, targetRel) {
  if (!targetRel) return null;
  if (kind === 'python') {
    const candidateA = join(baseDir, 'src', targetRel);
    if (existsSync(candidateA)) return candidateA;
    const candidateB = join(baseDir, targetRel);
    if (existsSync(candidateB)) return candidateB;
    if (targetRel === 'main.py') {
      const direct = join(baseDir, 'main.py');
      if (existsSync(direct)) return direct;
    }
    return null;
  }

  if (kind === 'js') {
    const candidate = join(baseDir, targetRel);
    if (existsSync(candidate)) return candidate;
    return null;
  }

  return null;
}

const examples = listDirs(examplesRoot)
  .filter((name) => !name.startsWith('.'))
  .filter((name) => existsSync(join(examplesRoot, name, 'python')) && existsSync(join(examplesRoot, name, 'js')))
  .sort();

const rows = [];

for (const name of examples) {
  const base = join(examplesRoot, name);
  const pyDir = join(base, 'python');
  const jsDir = join(base, 'js');
  const pyRun = join(pyDir, 'run.sh');
  const jsRun = join(jsDir, 'run.sh');

  const pyTarget = extractPythonRunTarget(pyRun);
  const jsTarget = extractJsRunTarget(jsRun);

  const pyTargetFile = pyTarget.target ? resolveTargetPath(pyDir, 'python', pyTarget.target) : null;
  const jsTargetFile = jsTarget.target ? resolveTargetPath(jsDir, 'js', jsTarget.target) : null;

  const pyFiles = [
    ...walkFiles(join(pyDir, 'src'), ['.py']),
    ...(existsSync(join(pyDir, 'main.py')) ? [join(pyDir, 'main.py')] : []),
  ];
  const jsFiles = walkFiles(join(jsDir, 'src'), ['.ts', '.js', '.mjs', '.cjs']);

  const pyCap = detectPythonCapabilities(pyFiles);
  const jsCap = detectJsCapabilities(jsFiles);

  const pkgDeps = loadPackageDeps(join(jsDir, 'package.json'));

  const jsNeedsFlatmachinesPkg = jsCap.importsFlatmachinesPkg;
  const jsNeedsFlatagentsPkg = jsCap.importsFlatagentsPkg;

  const pkgMissing = [];
  if (jsNeedsFlatmachinesPkg && !pkgDeps.has('@memgrafter/flatmachines')) pkgMissing.push('@memgrafter/flatmachines');
  if (jsNeedsFlatagentsPkg && !pkgDeps.has('@memgrafter/flatagents')) pkgMissing.push('@memgrafter/flatagents');

  const localPinMissing = [];
  if (jsNeedsFlatmachinesPkg && !checkRunShLocalPin(jsRun, '@memgrafter/flatmachines')) {
    localPinMissing.push('@memgrafter/flatmachines');
  }
  if (jsNeedsFlatagentsPkg && !checkRunShLocalPin(jsRun, '@memgrafter/flatagents')) {
    localPinMissing.push('@memgrafter/flatagents');
  }

  const capMismatch = [];

  // Python flatmachines usage must map to JS flatmachines package usage.
  if (pyCap.usesFlatmachines && !jsCap.importsFlatmachinesPkg) {
    capMismatch.push('flatmachines');
  }

  // Python flatagents usage can map to either JS flatagents package OR flatmachines
  // (JS SDK allows FlatAgent usage through @memgrafter/flatmachines).
  if (pyCap.usesFlatagents && !(jsCap.importsFlatagentsPkg || jsCap.importsFlatmachinesPkg)) {
    capMismatch.push('flatagents');
  }

  let pyCfg = new Set();
  let jsCfg = new Set();
  if (pyTargetFile && existsSync(pyTargetFile)) pyCfg = extractConfigBasenamesFromText(read(pyTargetFile));
  if (jsTargetFile && existsSync(jsTargetFile)) jsCfg = extractConfigBasenamesFromText(read(jsTargetFile));

  const pyCfgArr = [...pyCfg].sort();
  const jsCfgArr = [...jsCfg].sort();

  // soft check: require overlap only when both sides have explicit config literals.
  const overlap = pyCfgArr.filter((x) => jsCfg.has(x));
  const cfgMismatch = pyCfgArr.length > 0 && jsCfgArr.length > 0 && overlap.length === 0;

  const issues = [];
  if (!pyTargetFile) issues.push('python_target_unresolved');
  if (!jsTargetFile) issues.push('js_target_unresolved');
  if (capMismatch.length) issues.push(`sdk_capability_mismatch:${capMismatch.join('+')}`);
  if (pkgMissing.length) issues.push(`package_missing:${pkgMissing.join('+')}`);
  if (localPinMissing.length) issues.push(`runsh_local_pin_missing:${localPinMissing.join('+')}`);
  if (cfgMismatch) issues.push(`config_ref_no_overlap:py=[${pyCfgArr.join(',')}] js=[${jsCfgArr.join(',')}]`);

  rows.push({
    example: name,
    status: issues.length ? 'FAIL' : 'PASS',
    issues,
    pyTarget: pyTarget.raw,
    jsTarget: jsTarget.raw,
    pyCaps: `M:${pyCap.usesFlatmachines ? 'Y' : 'N'} A:${pyCap.usesFlatagents ? 'Y' : 'N'}`,
    jsCaps: `M:${jsCap.usesFlatmachines ? 'Y' : 'N'} A:${jsCap.usesFlatagents ? 'Y' : 'N'}`,
  });
}

const pass = rows.filter((r) => r.status === 'PASS').length;
const fail = rows.length - pass;

console.log('JS/Python SDK parity audit');
console.log(`Examples checked: ${rows.length} | PASS: ${pass} | FAIL: ${fail}`);
console.log('');

for (const r of rows) {
  console.log(`${r.status.padEnd(4)}  ${r.example.padEnd(28)} py:${String(r.pyTarget).padEnd(24)} js:${String(r.jsTarget).padEnd(34)} caps(py ${r.pyCaps} | js ${r.jsCaps})`);
  if (r.issues.length) {
    for (const issue of r.issues) console.log(`      - ${issue}`);
  }
}

if (fail > 0) process.exitCode = 1;
