# Private Webull PAPER portfolio viewer — Cloud Run preparation

**Status: source and offline tests prepared. NOT DEPLOYED.**

This isolated, GET-only viewer connects to the pinned Webull OpenAPI
SANDBOX hostname, api.sandbox.webull.com. It shows current paper
account equity, cash, positions and up to the latest 100 available
order records. The rows are orders, not necessarily executions.
Unavailable data is labeled unavailable, never filled in from logs.

## Security requirements

- Cloud Run MUST be protected by direct Google Identity-Aware Proxy
  (IAP) with authentication required. Never allow public access.
- The application additionally validates the Google-signed
  X-Goog-Iap-Jwt-Assertion, issuer, project/service audience, and a
  single allowlisted owner email. A text-only identity header is
  not sufficient.
- Webull SDK is pinned to version 3.0.3 and only its SANDBOX host.
- Only the known CASH account with a matching SHA-256 account
  fingerprint can be queried.
- Cloud Secret Manager must provide WEBULL_PAPER_APP_KEY,
  WEBULL_PAPER_APP_SECRET, and WEBULL_PAPER_ACCOUNT_SHA256.
  Use the existing sandbox-only credentials, never LIVE credentials.
- The Docker image contains only the dashboard files, not the bot
  strategies or order executor. No order methods exist in this viewer.
- Private no-store HTTP responses, non-root container user, min
  instances 0 and maximum 1. No background polling.

## First: protect the $300 Google Cloud credit

The welcome credit excludes Gemini API calls. Do not assume any
cloud service or usage is universally covered.

1. Open https://console.cloud.google.com/billing and select the
   correct Google Cloud billing account/project.
2. Select Budgets & alerts > Create budget.
3. If available, select Spend cap enforcement and make a $10/month
   cap scoped to this project and the Cloud Run service. A spend cap
   can suspend the viewer; it isn't instant and may allow overages.
4. Create a *separate* $5/month spend cap for Gemini API if desired:
   Google spend caps allow one eligible API/service per project.
5. Add alerts-only budgets for storage/build and other services;
   alerts alone do NOT restrict expenditure.
6. Check the credit remaining and expiration date under Billing.

## Private Cloud Run deployment (requires owner Google Cloud authorization)

1. Select the existing Google Cloud project and note its numeric
   project number (different from the project ID).
2. Enable required Cloud Run, Cloud Build, IAP and Secret Manager APIs.
3. Create the three Secret Manager entries named above. Do not print,
   share, or move secrets into git. Existing GitHub Actions secret
   values are not viewable; retrieve the original secure values.
   If the verified account SHA pin cannot be obtained, STOP.
4. In a Google Cloud Shell session scoped to the correct project,
   run the following from the checked-out repository root:

       gcloud run deploy webull-paper-viewer --source dashboard \
         --region us-central1 --no-allow-unauthenticated --iap \
         --min-instances 0 --max-instances 1 --memory 512Mi --timeout 60

   For first-time IAP in a personal project, Google may require
   choosing authentication through the Cloud Run console instead.
5. Map the GCP secrets to Cloud Run environment variables with the
   exact same names. Set additional environment variables:
   - WEBULL_PAPER_ACCOUNT_INDEX=0
   - DASHBOARD_ALLOWED_EMAIL=YOUR_GOOGLE_EMAIL_ADDRESS
   - IAP_AUDIENCE=/projects/PROJECT_NUMBER/locations/us-central1/services/webull-paper-viewer
6. Grant the IAP-secured Web App User role only to the owner Google
   identity. Configure IAP OAuth through the console if prompted.
   Give the dedicated Cloud Run runtime service account only the
   minimal Secret Manager Secret Accessor access it needs.
7. Verify anonymous/invalid-JWT requests are denied and the signed
   in user can view the right sandbox account. Check the rendered
   equity, cash, positions and order history against live broker
   read-only responses. Do not confuse with native Paper Trading.
8. Confirm no Alpaca or Webull trading workflows changed and delete
   the Cloud Run service when no longer needed.

## Offline tests

    python -m pip install -r dashboard/requirements.txt
    python -m unittest discover -s tests -p test_cloud_dashboard.py -v
    docker build -t paper-viewer -f dashboard/Dockerfile dashboard

No Google Cloud budget, IAP policy, service, Secret Manager credential,
or externally accessible URL has been created from this change alone.
No production or paper orders are ever placed by this viewer.
