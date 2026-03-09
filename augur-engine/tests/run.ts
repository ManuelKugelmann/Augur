#!/usr/bin/env tsx

/**
 * Test runner — imports all test files and reports results.
 */

import { report, exitCode } from './harness.js';

// Import test suites (side effects run the tests)
import './config.test.js';
import './publish.test.js';
import './prompts.test.js';

report();
process.exit(exitCode());
