#!/usr/bin/env python3
import sys, json, os, glob, time
from datetime import datetime

data = json.load(sys.stdin)
sid = data.get('session_id', 'unknown')
ts = datetime.now().strftime('%Y%m%dT%H%M%S')
d = f'.claude-history/{sid}'
os.makedirs(d, exist_ok=True)
proj = '-Users-nailbiter-Documents-forgithub-20260301-tasklist-agent'
transcript_dir = os.path.expanduser(f'~/.claude/projects/{proj}')
time.sleep(3)
msgs = []
if os.path.isdir(transcript_dir):
    for f in glob.glob(f'{transcript_dir}/*.jsonl'):
        for line in open(f):
            try:
                obj = json.loads(line)
                if obj.get('sessionId') == sid and obj.get('type') == 'assistant':
                    content = obj.get('message', {}).get('content', [])
                    text = ''.join(
                        b.get('text', '')
                        for b in content
                        if isinstance(b, dict) and b.get('type') == 'text'
                    )
                    if text:
                        msgs.append((obj.get('timestamp', ''), text))
            except Exception:
                pass
if msgs:
    msgs.sort(key=lambda x: x[0])
    open(f'{d}/{ts}-reply.md', 'w').write(msgs[-1][1])
