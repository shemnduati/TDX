# CI/CD (GitHub Actions)

Pushes to **`main`** run tests, then deploy to the production server at `/opt/tdx`.

Workflow file: [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)

## Pipeline

1. **test** — `pytest`, then `frontend` TypeScript build (`npm ci && npm run build`)
2. **deploy** (main only, after tests pass) — SSH to the server, `git pull`, `deploy/deploy.sh`, restart `tdx-api`

Pull requests run **test** only (no deploy).

## One-time GitHub setup

### 1. Repository secrets

In GitHub: **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Example | Description |
|--------|---------|-------------|
| `DEPLOY_HOST` | `72.61.19.150` | Server IP or hostname |
| `DEPLOY_USER` | `root` | SSH user (same as manual deploy) |
| `DEPLOY_SSH_KEY` | *(private key)* | Full PEM contents of an SSH **private** key that can log in as `DEPLOY_USER` |
| `DEPLOY_PORT` | `22` | Optional; omit to use 22 |

**Recommended:** create a dedicated deploy key (do not paste your personal laptop key into GitHub unless you accept that risk):

```bash
ssh-keygen -t ed25519 -C "github-actions-tdx" -f ~/.ssh/tdx_deploy -N ""
ssh root@YOUR_SERVER "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys" < ~/.ssh/tdx_deploy.pub
```

Put the contents of `~/.ssh/tdx_deploy` (private) into **`DEPLOY_SSH_KEY`**.

**Paste the whole private key** (including `BEGIN` / `END` lines). Do not use a passphrase on this key (`-N ""`). Do not paste the `.pub` file.

Because the workflow uses `environment: production`, add these secrets either as **repository secrets** (available to all jobs) **or** under **Settings → Environments → production → Environment secrets**. If deploy fails before SSH connects, the **Validate deploy secrets** step will say which name is empty.

Verify from your machine before relying on CI:

```bash
ssh -i ~/.ssh/tdx_deploy -o BatchMode=yes root@72.61.19.150 "echo ok"
```

### 2. GitHub Environment (optional but recommended)

**Settings → Environments → New environment → `production`**

Add the same secrets there, or use environment protection rules (required reviewers) before deploy runs.

The workflow references `environment: production`.

### 3. Server prerequisites

Already done if you followed [DEPLOY.md](DEPLOY.md):

- Repo cloned at `/opt/tdx`, tracking `origin/main`
- `venv`, `tdx-api` systemd unit, nginx `tdx` site

Ensure `git` can pull without a password (public repo is fine; for private repos, configure a deploy key on the **server** for GitHub).

## Manual deploy (same as CI)

```bash
ssh root@YOUR_SERVER
cd /opt/tdx
git fetch origin main && git reset --hard origin/main
bash deploy/deploy.sh
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Deploy job skipped | Only runs on **push to main** after tests pass |
| `ssh: unable to authenticate ... publickey` | Secrets missing/wrong, or public key not in server `~/.ssh/authorized_keys` for `DEPLOY_USER`. Re-run the `ssh-keygen` + `authorized_keys` steps above; confirm `DEPLOY_USER` matches (usually `root`). |
| `Permission denied (publickey)` | Same as above |
| Missing secret in **Validate deploy secrets** | Create the secret in GitHub (repo or `production` environment) and re-run the workflow |
| `pytest` fails in CI | Fix tests locally; deploy will not run |
| `pip` / `coincurve` on server | `deploy.sh` skips `coincurve` on Python ≥ 3.14 automatically |
