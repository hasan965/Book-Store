Immediate steps
1) Revoke/rotate the leaked key in Stripe NOW.
2) Ensure settings.py no longer contains the key (use STRIPE_SECRET_KEY from env).
3) Remove secrets from git history, then force-push cleaned repo.
4) Tell all collaborators to reclone.

Recommended: git-filter-repo (fast)
# Example (replace EXACT_SECRET with the leaked key)
git clone --mirror https://github.com/hasan965/Book_Store.git repo-mirror.git
cd repo-mirror.git
# create replacements.txt with a line: EXACT_SECRET==>REDACTED
git filter-repo --replace-text ../replacements.txt
git reflog expire --expire=now --all
git gc --prune=now --aggressive
git push --force --all
git push --force --tags

Alternative: BFG Repo-Cleaner
git clone --mirror https://github.com/hasan965/Book_Store.git repo-bfg.git
# create secrets.txt (one secret per line)
java -jar bfg.jar --replace-text secrets.txt repo-bfg.git
cd repo-bfg.git
git reflog expire --expire=now --all && git gc --prune=now --aggressive
git push --force --all
git push --force --tags

Important notes
- Revoking the Stripe key is mandatory; cleaning git history does NOT revoke the leaked key.
- After force-push, every contributor must delete local clones and clone again.
- Do NOT click GitHub "unblock" link unless you intentionally allow the secret in history.
