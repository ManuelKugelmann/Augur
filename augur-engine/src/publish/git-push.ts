import { simpleGit } from 'simple-git';

/** Commit and push new content to the augur site repo/branch */
export async function commitAndPush(
  siteDir: string,
  message: string,
  branch?: string,
): Promise<void> {
  const targetBranch = branch ?? process.env['SITE_BRANCH'] ?? 'augur_news';
  const git = simpleGit(siteDir);

  // Ensure we're on the right branch
  const currentBranch = (await git.branchLocal()).current;
  if (currentBranch !== targetBranch) {
    try {
      await git.checkout(targetBranch);
    } catch {
      await git.checkoutLocalBranch(targetBranch);
    }
  }

  // Stage all changes
  await git.add('.');

  // Check if there are actual changes
  const status = await git.status();
  if (status.files.length === 0) {
    console.log('[git] no changes to commit');
    return;
  }

  // Commit
  await git.commit(message);
  console.log(`[git] committed: ${message} (${status.files.length} files)`);

  // Push with retry
  const maxRetries = 4;
  const backoff = [2000, 4000, 8000, 16000];

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      await git.push('origin', targetBranch, ['--set-upstream']);
      console.log(`[git] pushed to origin/${targetBranch}`);
      return;
    } catch (err) {
      if (attempt < maxRetries) {
        const delay = backoff[attempt];
        console.warn(`[git] push failed (attempt ${attempt + 1}/${maxRetries + 1}), retrying in ${delay}ms...`);
        await new Promise((r) => setTimeout(r, delay));
      } else {
        throw new Error(`[git] push failed after ${maxRetries + 1} attempts: ${err}`);
      }
    }
  }
}
