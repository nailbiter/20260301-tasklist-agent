#!/usr/bin/env python3
import sys, json, os

# Current USD/JPY exchange rate (April 2026)
USD_JPY_RATE = 159.25
YEN_SIGN = "\u00A5"


def run():
    # 1. Read Claude's real-time session input from stdin
    try:
        claude = json.loads(sys.stdin.read())
    except:
        claude = {}

    # 2. Read your Monthly GCP Spend from your background puller
    cache_path = os.path.expanduser("~/.claude_spend.json")
    monthly_info = "?"
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r") as f:
                data = json.load(f)
                monthly_info = f"{int(data.get('costAmount', 0))}"
        except:
            monthly_info = "err"

    # 3. Process Claude's built-in metrics
    model = claude.get("model", {}).get("display_name", "Claude")

    # Context Usage
    ctx_pct = claude.get("context_window", {}).get("used_percentage", 0)
    ctx = f"{ctx_pct}%"

    # Session Cost: Convert USD to JPY
    usd_cost = claude.get("cost", {}).get("total_cost_usd", 0)
    jpy_session_cost = usd_cost * USD_JPY_RATE
    # We use .1f to show small spends like 2.5
    ses_cost = f"{jpy_session_cost:.1f}"

    # 4. Final Output Line
    # Format: [Model] | [Context] | Ses: [Session Cost] | Mo: [Monthly Total]
    print(
        f"{model} | ?? {ctx} | Ses: {ses_cost}{YEN_SIGN} | Mo: {monthly_info}{YEN_SIGN}"
    )


if __name__ == "__main__":
    run()
