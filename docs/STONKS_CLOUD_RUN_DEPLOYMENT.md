# AgentOffice — secure Cloud Run deployment and verification

These are **operator-executed instructions**. This branch adds an IAP-only,
non-trading `/office/release` endpoint to distinguish actual deployments from
GitHub merges and Docker builds. No Google Cloud deployment was performed
by GitHub CI; Google Cloud authentication is required.

## Prerequisites

- The appropriate Google Cloud account can deploy Cloud Run to project
  `gen-lang-client-0756501827`, region `us-central1`.
- The existing `webull-paper-viewer` Cloud Run service must remain protected
  by **IAP and authentication** and retain its current Secret Manager mounts.
- Confirm that the current service's account-read-only credentials are for
  `api.sandbox.webull.com`, never a live brokerage endpoint.
- Set billing alerts and review the costs before running a source build.
- Do not paste Cloud IAM credentials, broker keys or account fingerprints
  in issue comments, GitHub workflow logs, chat or this repository.

## Deploy exact reviewed main branch from Google Cloud Shell

Open https://shell.cloud.google.com/?project=gen-lang-client-0756501827

```bash
set -euo pipefail
cd ~/webull-paper
git fetch origin main
git checkout main
git pull --ff-only origin main
test -z "$(git status --porcelain)" || {
  echo "STOP: modified local files; deployment not proven to match main"
  exit 1
}
test "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" || {
  echo "STOP: not on reviewed remote main"
  exit 1
}
RELEASE_SHA="$(git rev-parse HEAD)"
echo "Deploying reviewed main at $RELEASE_SHA"

gcloud run deploy webull-paper-viewer \
  --source dashboard \
  --project gen-lang-client-0756501827 \
  --region us-central1 \
  --no-allow-unauthenticated \
  --iap \
  --update-env-vars "STONKS_CODE_SHA=$RELEASE_SHA"

gcloud run services describe webull-paper-viewer \
  --project gen-lang-client-0756501827 \
  --region us-central1 \
  --format="value(status.latestReadyRevisionName)"
```

Do **not** add `--allow-unauthenticated`, `--set-secrets` with literal
credentials, or `--set-env-vars` replacing existing settings. A failed or
unauthorized deployment is **not** evidence of successful activation.
Google Cloud CLI flags may change; inspect `gcloud run deploy --help`
before applying in an updated environment.

## Verify exact deployed revision

1. Record the current commit printed by the Cloud Shell command.
2. Open the authenticated
   [release marker](https://webull-paper-viewer-955692373304.us-central1.run.app/office/release).
   It must show a valid **operator-declared** `declared_source_sha` matching
   the reviewed SHA. It is not by itself cryptographic provenance.
3. Independently compare the Cloud Run **ready revision** shown by
   `gcloud run services describe` with its deployment record/build provenance.
4. Open the
   [AgentOffice](https://webull-paper-viewer-955692373304.us-central1.run.app/office)
   and [status API](https://webull-paper-viewer-955692373304.us-central1.run.app/office/status)
   as the IAP-authorized owner.
5. Confirm unauthorized requests still return 401/403 at the Google/IAP
   layer; there must not be public dashboard, account or admin access.
6. Verify that `source=VERIFIED` is associated with real GitHub workflow
   metadata; roles in `WORKING` are genuinely active, not merely animated.
7. Check actual Webull SANDBOX order/position reconciliation **read-only**.
   Order/fill verification never follows from a GitHub workflow green check.

The latest actual deployed revision and Cloud Run IAM policy have **not**
been independently verified by this PR; these steps remain external.

## Rollback

Use Google Cloud Console > Cloud Run > webull-paper-viewer >
Revisions to route traffic to the prior known-good and IAP-protected
revision, after verifying its account isolation and permissions. The
`STONKS_CODE_SHA` marker is not an independent rollback authority.
Never disable authentication as a troubleshooting workaround.

## Automated offline UI tests

The repository's Python CI now runs pinned Playwright/Chromium against the
production Flask/Jinja template and JavaScript with a **loopback-only fixture**
that supplies synthetic research and replaces IAP access in that testing
process only. The fixture is in `tests/office_playwright_fixture.py` and
requires `STONKS_OFFICE_E2E=true`; it is **excluded from the deployed image**.
A passing Playwright test proves the test-rendered interface, not IAP
configuration, broker connectivity or the currently deployed Cloud Run
revision.
