#!/usr/bin/env node

/**
 * augur-engine CLI
 *
 * Commands:
 *   cycle   --brand=<key> --horizon=<key>   Generate predictions for a brand/horizon
 *   post                                     Process social posting queue
 *   scorecard                                Update outcome tracking
 */

import { BRANDS } from './config/brands.js';
import type { BrandKey, HorizonKey } from './config/types.js';

function usage(): void {
  console.log(`
augur-engine — AI prediction pipeline

Commands:
  cycle     --brand=<the|der|financial|finanz> --horizon=<tomorrow|soon|future>
  post      Process pending social posts
  scorecard Update prediction outcomes

Options:
  --dry-run   Print output without writing files or pushing
  --help      Show this help
`);
}

function parseArgs(args: string[]): { command: string; flags: Record<string, string> } {
  const command = args[0] ?? 'help';
  const flags: Record<string, string> = {};

  for (const arg of args.slice(1)) {
    const match = arg.match(/^--(\w[\w-]*)(?:=(.+))?$/);
    if (match) {
      flags[match[1]] = match[2] ?? 'true';
    }
  }

  return { command, flags };
}

async function main(): Promise<void> {
  const { command, flags } = parseArgs(process.argv.slice(2));

  if (command === 'help' || flags['help']) {
    usage();
    return;
  }

  switch (command) {
    case 'cycle': {
      const brandKey = flags['brand'] as BrandKey | undefined;
      const horizonKey = flags['horizon'] as HorizonKey | undefined;

      if (!brandKey || !BRANDS[brandKey]) {
        console.error(`Error: --brand must be one of: ${Object.keys(BRANDS).join(', ')}`);
        process.exit(1);
      }
      if (!horizonKey || !['tomorrow', 'soon', 'future'].includes(horizonKey)) {
        console.error('Error: --horizon must be one of: tomorrow, soon, future');
        process.exit(1);
      }

      const brand = BRANDS[brandKey];
      const dryRun = flags['dry-run'] === 'true';

      console.log(`[augur] cycle: ${brand.name} / ${horizonKey}${dryRun ? ' (dry-run)' : ''}`);
      console.log('[augur] step 1: collect signals — not yet implemented');
      console.log('[augur] step 2: extrapolate — not yet implemented');
      console.log('[augur] step 3: generate assets — not yet implemented');
      console.log('[augur] step 4: publish — not yet implemented');
      console.log('[augur] step 5: notify — not yet implemented');
      break;
    }

    case 'post': {
      console.log('[augur] post: processing social queue — not yet implemented');
      break;
    }

    case 'scorecard': {
      console.log('[augur] scorecard: updating outcomes — not yet implemented');
      break;
    }

    default:
      console.error(`Unknown command: ${command}`);
      usage();
      process.exit(1);
  }
}

main().catch((err) => {
  console.error('[augur] fatal:', err);
  process.exit(1);
});
