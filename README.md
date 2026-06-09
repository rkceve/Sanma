# Sanma (秋刀魚)

> Claude Code that doesn't forget. Persistent project memory across sessions, compactions, and restarts.
>  Persistent, structured conversation memory for Claude Code. A Stop hook
> (Sonnet 4.6) distills each exchange into a per-chat knowledge tree on disk;
> a lightweight index injected each turn lets the main model pull stored
> facts verbatim, on demand — keeping long-running discussions coherent
> across compactions, restarts, and project switches.

---

## 1. Why this exists

Long-running conversations with Claude Code share three failure modes:

- When a session grows past the context window, automatic compaction silently
  discards earlier turns, and the underlying premise of the discussion starts
  drifting.
- Switching to a new session forces you to re-explain decisions you already
  made yesterday.
- Important technical commitments — the architecture you chose, the option
  you rejected, the open question you flagged — get buried in the chat
  history and become unrecoverable.

Sanma distills each turn into a **structured correlation map** on local
disk, shows the main model a one-glance index of what is stored, and lets
it pull the exact facts it needs — verbatim, the moment they matter.

---

## 2. What it does

Two hooks are registered in your Claude Code `settings.json` and fire
automatically every turn, plus one on-demand search command.

| Component | When it fires | What it does | Model |
|---|---|---|---|
| `Stop` hook | Right after Claude finishes a response | Reads the latest exchange and emits **diff operations** (add / replace / delete facts); code validates and applies them to the map | Claude Sonnet 4.6 |
| `UserPromptSubmit` hook | The moment you submit a new prompt | Injects a compact **topic index** of this chat's map (titles only) — **no model call**, ~0 latency | — |
| `search_map.py` | When the main model decides it needs a stored fact | Selects matching satellites for an explicit query; their texts are returned **verbatim** | Claude Haiku 4.5 |

This is a pull architecture (v0.2). Earlier versions pushed a model-written
summary of the map into every turn; in practice that summary accumulated
stale facts and editorial opinions, and the main model wasted effort
arguing with it. Now the main model — the only party that knows what it
needs — sees the table of contents and pulls the verbatim facts on demand.

---

## 3. The correlation map

The data model is a three-level tree, taken from the paper [*Geometric
Convergence for Conversational Context Management*](https://doi.org/10.5281/zenodo.19354705)
(DOI: `10.5281/zenodo.19354705`):

```
SUN: top-level topic
├── PLANET (mass=N): subtopic, depth N
│   ├── SAT: detail
│   └── SAT: detail
└── PLANET (mass=N): another subtopic
    └── SAT: ...
```

Each planet's **mass** grows as the conversation keeps returning to that
subtopic, which proxies how deeply the user has engaged with it. Mass is
shown in the injected topic index, so the main model can see at a glance
which subjects this chat has history on.

---

## 4. Per-turn lifecycle

```
[user submits prompt]
    │
    ↓
[UserPromptSubmit hook — no model call]
    │  renders the map's topic index (sun/planet titles + fact counts)
    ↓
[index injected as additionalContext, with the search command embedded]
    │
    ↓
[main model works on the response]
    │  if a stored fact would change the answer, it runs:
    │    python search_map.py --map <path> "<query>"
    │  Haiku 4.5 picks satellite numbers; texts are printed VERBATIM
    ↓
[main model finishes the response]
    │
    ↓
[Stop hook]
    │  Sonnet 4.6 reads the latest exchange, emits {"ops": [...]} —
    │  add_sat / replace_sat / delete_sat / add_planet / add_sun / inc_mass.
    │  Code validates each op (existing ids only, <=200 chars, <=10 ops)
    │  and applies the survivors. One retry with the validation errors.
    ↓
[correlation_map.json written atomically to disk]
```

The pre-turn injection is deterministic and adds no perceptible latency.
The Stop-hook model call runs after your response is already on screen.

---

## 5. Installation

### Requirements

- Python 3.11 or newer
- Claude Code CLI (the VS Code extension or the npm-installed CLI)
- An active Claude Pro / Max subscription, or an Anthropic API key (see §7)

### Steps

**Linux / macOS / Git Bash:**

```bash
git clone https://github.com/rkceve/claude-code-cms.git ~/.claude/hooks/cms
cd ~/.claude/hooks/cms
python3 install.py
```

**Windows (PowerShell):**

```powershell
git clone https://github.com/rkceve/claude-code-cms.git "$HOME\.claude\hooks\cms"
cd "$HOME\.claude\hooks\cms"
python install.py
```

The installer adds the two hook entries to `~/.claude/settings.json`
idempotently. Existing hooks are not overwritten.

### Verify

```bash
python install.py --status
```

If both hooks appear, you're done. The next Claude Code session will pick
them up automatically.

### Uninstall

```bash
python install.py --uninstall
```

This removes only the entries that point at the CMS scripts — other hooks
in your `settings.json` are left alone.

---

## 6. Usage

After installation, there is nothing to do. Just use Claude Code normally;
the correlation map populates itself.

### Where the map lives

```
~/.claude/projects/<cwd-slug>/memory/cms/chats/<session_id>/correlation_map.json
```

Each Claude Code session gets its own correlation map under a directory
keyed by both the project (cwd) and the session id. This per-chat layout
keeps individual maps small — the prompt sent to the lightweight update
model embeds the full current map, so a per-project map shared across all
historical conversations would balloon over time and push the model past
its timeout.

If you want to inspect maps from a previous session, look for the
`session_id` in `cms.log` or browse the `chats/` directory directly.

### Logs

```
~/.claude/hooks/cms/cms.log
```

Every hook invocation is recorded with a timestamp. The log auto-rotates
when it exceeds ~1 MB.

### Disabling for one session

```bash
CMS_DISABLE=1 claude
```

The hooks early-exit when this environment variable is set.

---

## 7. Configuration

### Numeric and structural settings (`cms.toml`)

Copy `cms.toml.example` to `cms.toml` and edit. All keys are optional;
unspecified ones fall back to defaults.

What you can override:

- The Haiku and Sonnet model IDs (e.g., to switch to other Anthropic models)
- Per-call timeouts and retry counts
- Glob patterns for project directories where the hooks should skip
- Soft cap on planet count (low-mass planets are pruned past this limit)
- Provider mode: `claude_code_cli` (default — uses your existing OAuth
  session via `claude -p`) or `anthropic_sdk` (uses the `anthropic` Python
  SDK directly; requires `ANTHROPIC_API_KEY`)

See the comments inside `cms.toml.example` for detail.

### Behavior tuning via prompts (`prompts/`)

The hook models (Haiku/Sonnet) do **not** read the user's `CLAUDE.md`.
Their **system prompts** are instead controlled by two markdown files
shipped with this repo:

```
prompts/
├── update.md     # Stop hook: what counts as a FACT + the diff-op rules
└── search.md     # search_map.py: how the selector picks satellite numbers
```

These are the editable equivalent of a `CLAUDE.md` for the hook models.
Edit them to tune model behavior without touching Python. Changes take
effect on the next hook fire; no restart needed.

Note that prompts are only the first of three constraint layers. The
other two live in code and hold regardless of what the model does:
every operation is validated before it is applied (unknown ids, texts
over 200 characters, and more than 10 ops per turn are rejected), and
the output formats make misbehavior structurally impossible — the
updater can only request operations (the map itself is assembled by
code), and the searcher can only pick numbers (fact texts are printed
verbatim, so it cannot rephrase or invent them).

If the prompt files are missing (e.g., a partial install), the hooks
fall back to a minimal hardcoded prompt embedded in the Python so the
system still runs.

---

## 8. Cost

Each turn fires one Sonnet call (the Stop hook, after your response is
done), plus a Haiku call only on the turns where the main model actually
searches the map. All calls run against your existing Claude Pro / Max
token allowance — no separate API key is needed unless you opt into the
SDK provider mode. To economize further, set exclusion patterns in
`cms.toml`, or prefix individual sessions with `CMS_DISABLE=1`.

---

## 9. Known limitations

### Sandbox-cwd workaround for a Claude Code CLI bug

Claude Code CLI v2.1.x silently ignores `--no-session-persistence` whenever
the system prompt is large, and writes a transcript file to the current
project directory anyway. Those transcripts surface as visible chat tabs
in the VS Code extension and pollute your workspace.

To avoid this, the hooks spawn the inner `claude -p` with cwd set to a
dedicated sandbox directory (`~/.claude/hooks/cms/_sandbox`), then delete
the transcript by `session_id` after the call returns. This is a workaround
that becomes unnecessary once Anthropic fixes the upstream bug.

### Rejected operations

The updater occasionally emits operations that fail validation (unknown
ids, overlong texts). Invalid ops are **rejected individually** and the
valid ones still apply; if every op fails, the hook retries once with
the validation errors attached, then leaves the map untouched for that
turn. Rejections are recorded in `cms.log` — check there if the map
seems to stop growing.

### Per-project isolation

Maps are keyed by current working directory. Starting work on the same
project from a different cwd gives you a fresh map. Be aware when you
switch the folder open in VS Code.

### SDK provider mode is unverified

The `provider.mode = "anthropic_sdk"` path is implemented but has not been
tested end-to-end against a real API key in the development environment.
Reports and pull requests welcome.

---

## 10. Privacy

The correlation map stores **summaries of your conversations as plain
JSON**. Treat it accordingly:

- Add `correlation_map.json` to `.gitignore` (it lives outside this repo,
  but you may end up checking the directory by accident)
- After conversations involving secrets — API keys, credentials, personal
  data — manually delete the relevant nodes or wipe the map and start
  fresh
- This project does not phone home; the only outbound network traffic is
  the Anthropic API calls the hooks themselves make

---

## 11. Author

**Ryosuke Kawai** — independent researcher, 

- X / Twitter: [@rkcevE](https://x.com/rkcevE)
- Contact: X DM, GitHub issues, or `ryosukekawai1224@gmail.com`

Active research areas:

- **Image compression** — hybrid pipeline using Structure Graph Data (SGD):
  edge vectors plus interior raster, with ONNX super-resolution
- **VR** — 3D Gaussian Splatting plus surface EMG (sEMG) for 6-DoF
  view-prediction; future-projection reprojection to mitigate VR sickness
- **LLM context management** — mass-aware attention bias for long-context
  coherence

---

## 12. Patent context

> ⚠️ **Patent pending — Japan, 2026.**
> Commercial use (productizing this code, hosting it as a paid service,
> redistributing it as part of a paid offering, and so on) requires a separate
> conversation. Please reach out via [@rkcevE](https://x.com/rkcevE) on X
> or open a GitHub issue first.
> **Personal use, freelance work, and internal use within an organization
> are not restricted.**

This repository is a reference implementation of techniques described in
[*Geometric Convergence for Conversational Context Management: A Distributed
Structured Memory Architecture Based on Correlation-Diagram Data*](https://doi.org/10.5281/zenodo.19354705)
(DOI: `10.5281/zenodo.19354705`), authored by the project author and made
available on Zenodo. A corresponding patent application is pending in Japan
(filed 2026).

### What this code implements

- Local-device creation and update of correlation-map data
- Tree structuring with sun / planet / satellite nodes
- A consistency-maintenance step (simplified here as schema validation)

### What this code does **not** implement

- The mass-aware attention bias (the `+wM` term in the paper). This
  modification operates inside the model's attention computation and
  cannot be implemented from outside the model — Claude API does not
  expose attention-score injection. That component lives in a separate
  Gemma + LoRA implementation outside this repository.

---

## 13. License

The source code in this repository is released under the **MIT License**
(see [LICENSE](./LICENSE)).

The technology this code implements is **patent pending in Japan**. The
MIT License grants rights to the source code only; it does **not** grant
a patent license.

| Use case | Restriction |
|---|---|
| Personal use, academic research, education | None |
| Freelance work for clients | None |
| Internal company use, employee productivity tooling | None |
| Productizing, SaaS hosting, redistributing as part of a paid offering | Please reach out first |

For commercial-use inquiries, contact [@rkcevE](https://x.com/rkcevE) on X
or open a GitHub issue.

---

## 14. Citation

If you use this in research or publications, citations are welcome.

To cite this implementation:

```bibtex
@misc{kawai2026cms,
  author    = {Kawai, Ryosuke},
  title     = {claude-code-cms: A reference implementation of structured
               conversation memory for Claude Code},
  year      = {2026},
  publisher = {GitHub},
  url       = {https://github.com/rkceve/claude-code-cms}
}
```

To cite the underlying paper:

```bibtex
@misc{kawai2026geometric,
  author    = {Kawai, Ryosuke},
  title     = {Geometric Convergence for Conversational Context Management:
               A Distributed Structured Memory Architecture Based on
               Correlation-Diagram Data},
  year      = {2026},
  publisher = {Zenodo},
  doi       = {10.5281/zenodo.19354705},
  url       = {https://doi.org/10.5281/zenodo.19354705}
}
```

---

## 15. Acknowledgements

- **Anthropic** — for Claude Code CLI and the Claude Sonnet / Haiku models
  this project depends on

---

## 16. Contributing

Issues and pull requests are welcome. Help is especially appreciated in
these areas:

- End-to-end verification of the `anthropic_sdk` provider mode against a
  real API key
- Linux and macOS testing (development happens on Windows)
- Industry collaboration on the underlying paper — please reach out if your
  organization is interested in joint research

  ## 17. Repository Name

  Named after sanma (秋刀魚, Pacific saury) — a fish known for being remembered fondly even after the season ends.
