import json
import sys
import click


@click.command()
@click.argument("log_file", default=".logs/conversations.json")
@click.option("--thread-id", default=None, help="Filter to a single session by thread ID.")
def main(log_file, thread_id):
    """Read a conversations JSON log and print a plaintext Q&A dialog."""
    entries = []
    with open(log_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if thread_id and entry.get("thread_id") != thread_id:
                continue
            entries.append(entry)

    if not entries:
        click.echo("No conversation entries found.")
        sys.exit(0)

    current_thread = None
    for entry in entries:
        t = entry.get("thread_id", "")
        if t != current_thread:
            current_thread = t
            click.echo(f"\n=== Session: {t} ===")

        role = entry.get("role", "unknown")
        content = entry.get("content", entry.get("message", "")).strip()
        if role == "user":
            click.echo(f"\nUser: {content}")
        elif role == "assistant":
            click.echo(f"Assistant: {content}")
        else:
            click.echo(f"[{role}]: {content}")


if __name__ == "__main__":
    main()
