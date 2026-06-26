#!/usr/bin/env python3
"""
local_llm_judge.py — Use local Codex CLI as LLM judge (replaces owner decisions).

Wraps `codex exec` with a stable JSON-friendly contract for the autoresearch
plan-rescue daemon. Designed to be called from cron / launchd / rescue
daemon when plan engine pauses, verifier rejects, or owner-decision is
pending.

Defaults to gpt-5.5 + xhigh reasoning (matches user's $HOME/.codex/config.toml).
Falls back gracefully on ChatGPT-account restrictions.

Exit codes:
  0 — success, model output written to --out-file (or stdout)
  1 — invalid arguments
  2 — codex not found
  3 — codex call failed (timeout / auth / model error)
  4 — output parsing failed

Usage:
  local_llm_judge.py --prompt "..." --model gpt-5.5 --reasoning-effort xhigh
  local_llm_judge.py --prompt-file /tmp/prompt.txt --out-file /tmp/decision.json
  local_llm_judge.py --system "You are a senior ICRA reviewer." --prompt "..."
  echo '{"verdict":"accept"}' | local_llm_judge.py --stdin --json-mode
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

CODEX_BIN = os.environ.get("CODEX_BIN")  # override via env var if set
CODEX_FALLBACK_BIN = "codex"  # PATH fallback
DEFAULT_MODEL = "gpt-5.5"
DEFAULT_REASONING_EFFORT = "xhigh"
DEFAULT_TIMEOUT_SEC = 600
MAX_RETRIES = 2


def find_codex() -> str:
    # Honor explicit override first (e.g. CODEX_BIN=/custom/path/codex)
    if CODEX_BIN:
        candidate = Path(CODEX_BIN)
        if candidate.exists() and os.access(CODEX_BIN, os.X_OK):
            return str(candidate)
        print(
            f"WARN: CODEX_BIN env var set to {CODEX_BIN!r} but not executable; "
            f"falling back to PATH lookup",
            file=sys.stderr,
        )
    found = shutil.which(CODEX_FALLBACK_BIN)
    if found:
        return found
    print("ERROR: codex CLI not found in PATH; set CODEX_BIN env var to override", file=sys.stderr)
    sys.exit(2)


def call_codex(
    prompt: str,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    system: Optional[str] = None,
    workdir: Optional[str] = None,
) -> tuple[int, str, str]:
    """Call codex exec and return (exit_code, stdout, stderr)."""
    codex = find_codex()

    cmd = [
        codex, "exec",
        "-m", model,
        "-c", f"model_reasoning_effort={reasoning_effort}",
        "--output-last-message", "/tmp/_local_llm_judge_out.txt",
    ]
    if system:
        # Codex doesn't have a direct --system flag, prepend to prompt.
        prompt = f"[SYSTEM]\n{system}\n\n[USER]\n{prompt}"

    cmd.append(prompt)

    last_err = ""
    for attempt in range(MAX_RETRIES + 1):
        try:
            proc = subprocess.run(
                cmd,
                cwd=workdir,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
            out_file = Path("/tmp/_local_llm_judge_out.txt")
            stdout = out_file.read_text() if out_file.exists() else proc.stdout
            stderr = proc.stderr
            if proc.returncode == 0 and stdout.strip():
                return 0, stdout.strip(), stderr
            last_err = stderr or proc.stdout or "empty output"
            # If model not supported (ChatGPT account), try gpt-5.5 fallback
            if "not supported when using Codex with a ChatGPT account" in (stderr + stdout):
                if model != DEFAULT_MODEL:
                    print(f"WARN: model {model} unsupported, falling back to {DEFAULT_MODEL}", file=sys.stderr)
                    cmd[cmd.index(model)] = DEFAULT_MODEL
                    model = DEFAULT_MODEL
                    continue
                else:
                    return 3, "", f"FATAL: {model} also unsupported on this account"
            if attempt < MAX_RETRIES:
                time.sleep(2 ** attempt)
        except subprocess.TimeoutExpired:
            last_err = f"timeout after {timeout_sec}s"
            if attempt < MAX_RETRIES:
                time.sleep(2 ** attempt)
                continue
            return 3, "", last_err

    return 3, "", last_err


def parse_output(raw: str, json_mode: bool) -> str:
    if not json_mode:
        return raw
    # Try to extract JSON object/array from the output
    raw = raw.strip()
    # Look for fenced ```json ... ``` blocks first
    if "```json" in raw:
        start = raw.find("```json") + len("```json")
        end = raw.find("```", start)
        if end > start:
            return raw[start:end].strip()
    # Try direct parse
    try:
        obj = json.loads(raw)
        return json.dumps(obj, indent=2)
    except json.JSONDecodeError:
        pass
    # Try first { ... } or [ ... ] block
    for opener, closer in [("{", "}"), ("[", "]")]:
        s = raw.find(opener)
        if s < 0:
            continue
        depth = 0
        for i in range(s, len(raw)):
            if raw[i] == opener:
                depth += 1
            elif raw[i] == closer:
                depth -= 1
                if depth == 0:
                    candidate = raw[s:i + 1]
                    try:
                        json.loads(candidate)
                        return candidate
                    except json.JSONDecodeError:
                        break
    # Fallback: return raw with warning
    print("WARN: json_mode=True but no parseable JSON found; returning raw", file=sys.stderr)
    return raw


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--prompt", help="prompt text (or use --prompt-file / --stdin)")
    p.add_argument("--prompt-file", help="read prompt from file")
    p.add_argument("--stdin", action="store_true", help="read prompt from stdin")
    p.add_argument("--system", help="optional system prompt")
    p.add_argument("--model", default=DEFAULT_MODEL, help=f"model name (default: {DEFAULT_MODEL})")
    p.add_argument("--reasoning-effort", default=DEFAULT_REASONING_EFFORT,
                   choices=["low", "medium", "high", "xhigh"],
                   help=f"reasoning effort (default: {DEFAULT_REASONING_EFFORT})")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SEC,
                   help=f"timeout seconds (default: {DEFAULT_TIMEOUT_SEC})")
    p.add_argument("--workdir", help="codex exec cwd (default: current dir)")
    p.add_argument("--out-file", help="write output to file (default: stdout)")
    p.add_argument("--json-mode", action="store_true",
                   help="expect/parse JSON output (fenced or raw)")
    p.add_argument("--quiet", action="store_true", help="suppress stderr metadata")
    args = p.parse_args()

    # Resolve prompt
    if args.prompt:
        prompt = args.prompt
    elif args.prompt_file:
        prompt = Path(args.prompt_file).read_text()
    elif args.stdin:
        prompt = sys.stdin.read()
    else:
        print("ERROR: must specify --prompt / --prompt-file / --stdin", file=sys.stderr)
        return 1

    if not args.quiet:
        print(f"[local_llm_judge] model={args.model} effort={args.reasoning_effort} "
              f"timeout={args.timeout}s prompt_len={len(prompt)}", file=sys.stderr)

    code, stdout, stderr = call_codex(
        prompt=prompt,
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        timeout_sec=args.timeout,
        system=args.system,
        workdir=args.workdir,
    )

    if code != 0:
        print(f"ERROR: codex call failed (exit={code}): {stderr[:500]}", file=sys.stderr)
        return code

    output = parse_output(stdout, args.json_mode)

    if args.out_file:
        Path(args.out_file).write_text(output)
        if not args.quiet:
            print(f"[local_llm_judge] wrote {len(output)} chars to {args.out_file}", file=sys.stderr)
    else:
        print(output)

    return 0


if __name__ == "__main__":
    sys.exit(main())