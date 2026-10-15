# pytest-scope

Two pytest guards for the Bash and PowerShell tools, written as function hooks. Each is off until its option
is set, and every failure path (a missing file, a failed stat, no git, an unreadable state store) passes the
call through unchanged.

## Install

```
/plugin install pytest-scope --marketplace t968rs/operator-straps
```

## Options

Set at install: `/plugin` opens a dialog for unset options, and `claude plugin install` takes
`--config KEY=VALUE`. Change later with `/plugin configure pytest-scope@operator-straps` or `/config`.

| Option | Type | Default | Meaning |
|---|---|---|---|
| `python` | file | unset | Absolute path of the interpreter bare `pytest` runs under |
| `require_test_file` | boolean | `false` | Deny pytest calls that name no test file |

## 1. Interpreter rewrite (`hooks/interpreter.ts`)

A bare `pytest` resolves to whatever Python is first on PATH, often one without the project's test
dependencies. With `python` set, a bare pytest invocation that opens a simple Bash command runs under it:

| Written | Runs as |
|---|---|
| `pytest a.py -q`, `py.test a.py`, `pytest.exe a.py` | `"<python>" -m pytest a.py -q` |
| `python` / `python3` / `python.exe` / `py` `-m pytest a.py` | `"<python>" -m pytest a.py` |

- The rewrite applies after `;`, `&&`, `||`, `|` and a newline. Words inside quotes, arguments
  (`echo pytest`) and qualified names (`/usr/bin/python`, `python3.11`) stay as written.
- Commands whose structure is uncertain (`$(...)`, backticks, subshells, an unclosed quote or heredoc) are
  never rewritten. Neither are `python -c`, scripts, other modules, or commands led by an assignment
  (`PYTHONPATH=... pytest`), a keyword or a redirection.
- `python` must be absolute and name an existing file; backslashes are written as forward slashes. A
  relative path, or one holding `"`, `$` or a backtick, turns the rewrite off.
- The model sees a one-line `[pytest-scope] bare pytest rewritten ...` note beside the result.
- Only the Bash tool is rewritten.

**Permissions.** `tool.call` runs before the permission rules, so the rules judge the rewritten text. With
the `harness` plugin installed, its `bash_allow_shapes` hook approves `"<python>" -m pytest ARGS` when
`<python>` is this option's value and the bare form (`pytest ARGS`, `python -m pytest ARGS`) matches an
existing `Bash(...)` allow rule, so the rewrite never needs a wider rule than the bare call had. Without the
harness, allow the rewritten form in the project's settings, for example
`Bash("C:/path/to/env/python.exe" -m pytest *)`, or every rewritten call prompts.

## 2. Test-file requirement (`hooks/scope.ts`)

With `require_test_file` on, a pytest call on Bash or PowerShell with no test path, or with a directory as a
test path, is denied: a directory path is never the unit; a file or a node-id is. The message lists up to
15 test files (`test_*.py`, `*_test.py`) git knows under that directory, tracked or untracked.

- Recognised: `pytest`, `py.test`, `python -m pytest`, a quoted interpreter path `-m pytest`, rewritten
  commands, and wrappers such as `env`, `timeout`, `nohup`, `conda run` and `uv run`.
- Files and node-ids always run. `--collect-only`, `--version`, `--help` and runner scripts are never denied.
- Heredoc bodies and comments are data, not commands.
- A relative path resolves against the session cwd (which follows an earlier `cd`) and against the root:
  the git top level of the cwd, else of `CLAUDE_PROJECT_DIR`, else the cwd itself.
- `/pytest-broad-ok` arms a one-shot override for the next broad call. Meant for the developer.

## State

`$.state['pytest-scope']` (contract: `types/index.d.ts`): `rewrites` (number) and `broadOk` (boolean).

## Known limitations

- Commands nested inside `bash -c "..."`, `xargs` or `$(...)` are neither rewritten nor judged.
- A `cd` inside the same command (`cd tests && pytest unit/`) is not followed.
- `pytest --cov tests/test_x.py` names no test path (`--cov` consumes the next word, as pytest-cov's
  argparse option does), so it is denied as a whole-suite run. Write `--cov=<src>`.
- PowerShell commands are parsed with the Bash tokenizer; PowerShell backtick escapes are not understood.

## Checks

```
claude plugin validate --strict plugins/pytest-scope
claude plugin test plugins/pytest-scope
```

Source and import history: `docs/PROVENANCE.md` at the marketplace root.
