#!/usr/bin/env node
import {
  PiAuthStore,
  isExpired,
  loadCodexCredential,
  resolveAuthFile,
} from '@memgrafter/flatagents';

const DEFAULT_AUTH_FILE = '~/.agents/flatmachines/auth.json';

type Args = {
  authFile?: string;
  provider: string;
  requireCredential: boolean;
  help: boolean;
};

function parseArgs(argv: string[]): Args {
  const args: Args = {
    authFile: DEFAULT_AUTH_FILE,
    provider: 'openai-codex',
    requireCredential: false,
    help: false,
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--help' || arg === '-h') args.help = true;
    else if (arg === '--auth-file' && argv[i + 1]) args.authFile = argv[++i];
    else if (arg === '--provider' && argv[i + 1]) args.provider = argv[++i] ?? args.provider;
    else if (arg === '--require-credential') args.requireCredential = true;
    else throw new Error(`Unknown argument: ${arg}`);
  }

  return args;
}

function usage(): string {
  return [
    'OpenAI Codex OAuth diagnostics (JS)',
    '',
    'Usage:',
    '  node dist/openai_codex_oauth_example/main.js',
    '  node dist/openai_codex_oauth_example/main.js --auth-file ~/.agents/flatmachines/auth.json',
    '  node dist/openai_codex_oauth_example/main.js --require-credential',
  ].join('\n');
}

async function main(): Promise<void> {
  let args: Args;
  try {
    args = parseArgs(process.argv.slice(2));
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    console.error();
    console.error(usage());
    process.exit(2);
    return;
  }

  if (args.help) {
    console.log(usage());
    return;
  }

  const resolved = resolveAuthFile({ explicitPath: args.authFile });
  const store = new PiAuthStore(resolved);

  const output: Record<string, any> = {
    provider: args.provider,
    auth_file: resolved,
    credential_loaded: false,
    expired: null,
    account_id: null,
  };

  try {
    const cred = loadCodexCredential(store, args.provider);
    output.credential_loaded = true;
    output.expired = isExpired(cred.expires);
    output.account_id = cred.account_id;
  } catch (error) {
    output.error = error instanceof Error ? error.message : String(error);
  }

  console.log(JSON.stringify(output, null, 2));

  if (args.requireCredential && !output.credential_loaded) {
    process.exit(1);
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
