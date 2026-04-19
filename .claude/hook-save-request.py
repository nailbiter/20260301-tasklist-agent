#!/usr/bin/env python3
import sys, json, os
from datetime import datetime

data = json.load(sys.stdin)
sid = data.get('session_id', 'unknown')
prompt = data.get('prompt', '')
ts = datetime.now().strftime('%Y%m%dT%H%M%S')
d = f'.claude-history/{sid}'
os.makedirs(d, exist_ok=True)
open(f'{d}/{ts}-request.md', 'w').write(prompt)
