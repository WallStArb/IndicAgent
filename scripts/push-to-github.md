# Push IndicAgent to GitHub

**Repository:** [https://github.com/WallStArb/IndicAgent](https://github.com/WallStArb/IndicAgent)

Run these in Git Bash or a terminal where `git` is available (e.g. from "Git for Windows").

## Push local changes (e.g. updated README)

```bash
cd z:/indicagent

# Confirm remote points to WallStArb/IndicAgent
git remote -v
# Should show: origin  https://github.com/WallStArb/IndicAgent.git  (fetch/push)

# Commit and push
git add README.md
git commit -m "docs: update README to v4.6.0, I1-I8 complete, 45 plugins"
git push origin main
```

## If remote is missing or wrong

```bash
cd z:/indicagent

# Remove existing origin (if any)
git remote remove origin 2>nul

# Add correct remote
git remote add origin https://github.com/WallStArb/IndicAgent.git
# Or SSH: git remote add origin git@github.com:WallStArb/IndicAgent.git

git push -u origin main
```

## First-time Git setup (if needed)

If you never set your name/email for commits:

```bash
git config --global user.name "Your Name"
git config --global user.email "your.email@example.com"
```
