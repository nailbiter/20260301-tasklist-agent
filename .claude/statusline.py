#!/usr/bin/env python3
import sys
import json
import os

def get_statusline():
    # 1. Read session data from Claude (piped into stdin)
    try:
        input_data = sys.stdin.read()
        claude = json.loads(input_data) if input_data else {}
    except:
        claude = {}

    # 2. Read your monthly GCP spend from your existing cache
    state_file = os.path.expanduser("~/.claude_spend.json")
    gcp_spend = "¥?"
    if os.path.exists(state_file):
        try:
            with open(state_file, 'r') as f:
                state = json.load(f)
                current = state.get("costAmount", 0)
                limit = state.get("budgetAmount", 0)
                # Format: ¥72 (4%)
                pct = f" ({(current/limit)*100:.0f}%)" if limit > 0 else ""
                gcp_spend = f"¥{current}{pct}"
        except:
            gcp_spend = "¥err"

    # 3. Extract built-in Claude metrics
    model = claude.get("model", {}).get("display_name", "Claude")
    context = claude.get("context_window", {}).get("used_percentage", 0)
    session_cost = claude.get("cost", {}).get("total_cost_usd", 0)

    # 4. Format the final line
    # Left: Model and Context | Right: Session Cost & Monthly GCP Spend
    line = f"🤖 {model} | 🧠 {context}% | 💰 Ses: ${session_cost:.2f} | 📈 Mo: {gcp_spend}"
    print(line)

if __name__ == "__main__":
    get_statusline()