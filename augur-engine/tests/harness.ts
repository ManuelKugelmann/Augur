/**
 * Minimal test harness — no external deps.
 * Runs tests, reports results, exits with appropriate code.
 */

let currentSuite = '';
let passed = 0;
let failed = 0;
const failures: Array<{ suite: string; test: string; error: string }> = [];

export function describe(name: string, fn: () => void): void {
  currentSuite = name;
  fn();
}

export function it(name: string, fn: () => void): void {
  try {
    fn();
    passed++;
    console.log(`  ✓ ${currentSuite} > ${name}`);
  } catch (err) {
    failed++;
    const msg = err instanceof Error ? err.message : String(err);
    console.log(`  ✗ ${currentSuite} > ${name}`);
    console.log(`    ${msg}`);
    failures.push({ suite: currentSuite, test: name, error: msg });
  }
}

export const expect = (actual: unknown) => ({
  toBe(expected: unknown) {
    if (actual !== expected) {
      throw new Error(`Expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
    }
  },
  toEqual(expected: unknown) {
    const a = JSON.stringify(actual);
    const b = JSON.stringify(expected);
    if (a !== b) {
      throw new Error(`Expected ${b}, got ${a}`);
    }
  },
  toBeTruthy() {
    if (!actual) {
      throw new Error(`Expected truthy, got ${JSON.stringify(actual)}`);
    }
  },
  toBeUndefined() {
    if (actual !== undefined) {
      throw new Error(`Expected undefined, got ${JSON.stringify(actual)}`);
    }
  },
  toContain(expected: unknown) {
    if (Array.isArray(actual)) {
      if (!actual.includes(expected)) {
        throw new Error(`Expected array containing ${JSON.stringify(expected)}, got: ${JSON.stringify(actual)}`);
      }
    } else if (typeof actual === 'string') {
      if (!actual.includes(expected as string)) {
        throw new Error(`Expected string containing "${expected}", got: ${(actual as string).slice(0, 200)}...`);
      }
    } else {
      throw new Error(`toContain requires string or array, got ${typeof actual}`);
    }
  },
  not: {
    toContain(expected: unknown) {
      if (Array.isArray(actual)) {
        if (actual.includes(expected)) {
          throw new Error(`Expected array NOT containing ${JSON.stringify(expected)}`);
        }
      } else if (typeof actual === 'string') {
        if (actual.includes(expected as string)) {
          throw new Error(`Expected string NOT containing "${expected}"`);
        }
      }
    },
  },
  toMatch(regex: RegExp) {
    if (typeof actual !== 'string' || !regex.test(actual)) {
      throw new Error(`Expected ${JSON.stringify(actual)} to match ${regex}`);
    }
  },
  toBeGreaterThan(expected: number) {
    if (typeof actual !== 'number' || actual <= expected) {
      throw new Error(`Expected ${actual} > ${expected}`);
    }
  },
  toBeGreaterThanOrEqual(expected: number) {
    if (typeof actual !== 'number' || actual < expected) {
      throw new Error(`Expected ${actual} >= ${expected}`);
    }
  },
  toBeLessThanOrEqual(expected: number) {
    if (typeof actual !== 'number' || actual > expected) {
      throw new Error(`Expected ${actual} <= ${expected}`);
    }
  },
});

/** Call at end of test file to report results */
export function report(): void {
  console.log(`\n${passed + failed} tests: ${passed} passed, ${failed} failed`);
  if (failures.length > 0) {
    console.log('\nFailures:');
    for (const f of failures) {
      console.log(`  ${f.suite} > ${f.test}: ${f.error}`);
    }
  }
}

/** Get exit code (0 = all pass, 1 = failures) */
export function exitCode(): number {
  return failed > 0 ? 1 : 0;
}
