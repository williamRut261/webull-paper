"""Webull PaperTrade sandbox account connectivity check (GET only).

Never calls order placement and never uses the production API hostname.
Credentials must be stored as GitHub Actions secrets, not in this repository.
"""
import os
import sys

SANDBOX_HOST = "api.sandbox.webull.com"

def main():
    key = os.environ.get("WEBULL_PAPER_APP_KEY", "").strip()
    secret = os.environ.get("WEBULL_PAPER_APP_SECRET", "").strip()
    if not key or not secret:
        missing = []
        if not key:
            missing.append("WEBULL_PAPER_APP_KEY")
        if not secret:
            missing.append("WEBULL_PAPER_APP_SECRET")
        print("MISSING_GITHUB_ACTIONS_SECRETS:", ", ".join(missing))
        # GitHub's vars are not secrets; print only booleans (never values).
        if os.getenv("WEBULL_PAPER_VAR_KEY_PRESENT", "") == "true" or os.getenv("WEBULL_PAPER_VAR_SECRET_PRESENT", "") == "true":
            print("DIAGNOSIS: matching Repository variables exist; use Repository secrets instead.")
        else:
            print("DIAGNOSIS: These secret names are not available to this GitHub Actions job.")
        return 2

    from webull.core.client import ApiClient
    from webull.trade.trade_client import TradeClient

    api = ApiClient(key, secret, "us")
    api.add_endpoint("us", SANDBOX_HOST)
    trade = TradeClient(api)

    # GET account list only. Do NOT print account IDs, balances, auth material,
    # or the response body. No request to api.webull.com can occur here.
    try:
        response = trade.account_v2.get_account_list()
        status = response.status_code
    except Exception as exc:
        print("WEBULL_PAPER_CONNECTION_ERROR:", type(exc).__name__)
        return 1

    if status == 200:
        print("WEBULL_PAPER_SANDBOX_CONNECTED: account-list GET returned HTTP 200; no orders submitted.")
        return 0

    print("WEBULL_PAPER_CONNECTION_REJECTED: HTTP", status,
          "; check paper-app keys and sandbox API permissions.")
    return 1

if __name__ == "__main__":
    sys.exit(main())
