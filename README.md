# SkillSense

SkillSense is a local live HUD for agent skill evidence. Start it with `skillsense serve`, leave the dashboard open, and watch each agent turn update from local logs.

It tracks `loaded`, `read`, `invoked`, `suggested`, and `not detected` states without calling an LLM or sending your chat anywhere.

SkillSense 的重点很简单：实时看每一轮 Agent 的 skill 证据状态。它默认本地运行，不需要 API key，也不会把状态塞进每轮聊天正文。

## Try It In 60 Seconds

```bash
git clone <your-fork-or-repo-url>
cd SkillSense
pip install -e .
skillsense scan
skillsense serve --interval 2
```

Open:

```text
http://127.0.0.1:8765/dashboard.html
```

`127.0.0.1` means localhost. It is the user's own machine, not the project author's IP address, and it is not exposed to the internet by default.

Use the HTTP dashboard for live updates. Opening `.skillsense/dashboard.html` directly with `file://` gives you a static report.

Network metadata is off by default. The live monitor, scan, report, and generic evidence adapter all work locally.

## Product Preview

![SkillSense statusline](assets/skillsense-statusline.png)

![SkillSense dashboard](assets/skillsense-dashboard.png)

These are normal PNG files under `assets/`. GitHub will render them when the `assets/` directory is included in the repository. They are only preview images; the CLI does not need them to run.

## What You See

| State | Meaning |
| --- | --- |
| `loaded` | The platform made a skill visible to the agent. Useful, but still just availability. |
| `read` | Local logs show a `SKILL.md` was opened. Stronger evidence than `loaded`. |
| `invoked` | The platform logged an explicit skill invocation event. This is the strongest signal. |
| `inferred` | SkillSense can only guess from traces such as commands, output, or file changes. |
| `suggested` | SkillSense thinks the skill may fit the prompt. This is a hint, not usage proof. |
| `not detected` | No local evidence was found. SkillSense leaves it unknown. |

## Accuracy Notice

If the platform does not expose real skill invocation logs, SkillSense cannot know with 100% certainty whether a skill was used. It separates confirmed evidence from inferred evidence.

如果平台不暴露真实 skill 调用日志，SkillSense 不能 100% 确认某个 skill 是否真的被使用。它会明确区分“已确认使用”和“疑似使用”。

## Live Skill Monitor

`skillsense serve --interval 2` serves the dashboard from `http://127.0.0.1:8765/dashboard.html`. That address is local to whoever runs the command. The page polls lightly, so opening panels, selecting text, scrolling, and changing language should not be interrupted by refreshes.

The monitor is the main product surface. It shows recent turns, evidence tied to those turns, and a folded `Trigger Diagnostics` area for each turn. That diagnostic area uses the local skill index and existing evidence only; it does not call an LLM.

The dashboard supports English, Chinese, Japanese, Korean, Spanish, and French. English mode stays English-only. Other languages show translated UI copy with English kept where accuracy is useful. Timestamps render in the browser’s local timezone.

Dashboard hierarchy:

| Layer | Dashboard area |
| --- | --- |
| Core | `Live Skill Monitor` |
| Review | `Evidence Timeline`, `Intervention Queue` |
| Supporting | `Suggested`, `Recommended`, `Project Conflicts` |
| Reference | `Local Skill Index` |
| Advanced | policy and privacy settings |

`Suggested` and `Recommended` are supporting signals. They help explain what might be useful, but the live evidence stream is the main promise.

## Install And Run

```bash
pip install -e .
skillsense scan
skillsense serve --interval 2
```

For quick CLI checks:

```bash
python -m skillsense.cli scan
python -m skillsense.cli list
python -m skillsense.cli suggest "帮我检查 README 能不能跑"
python -m skillsense.cli evidence
python -m skillsense.cli status
python -m skillsense.cli report
python -m skillsense.cli diagnose
```

## CLI Commands

```bash
skillsense scan
skillsense list
skillsense suggest "<user prompt>"
skillsense evidence
skillsense status
skillsense watch --interval 2
skillsense serve --interval 2
skillsense reset-state
skillsense report
skillsense diagnose
skillsense interventions
skillsense propose-fix <intervention-id>
skillsense apply-fix <intervention-id> --yes
skillsense dismiss <intervention-id>
skillsense why-not <skill-name> "<user prompt>"
skillsense rewrite-description <skill-name>
skillsense mute <skill-name>
skillsense unmute <skill-name>
skillsense prefer <skill-name>
skillsense unprefer <skill-name>
skillsense ask-before <skill-name>
skillsense no-ask-before <skill-name>
skillsense config get
skillsense config set language zh-CN
skillsense config set network.enabled true
skillsense config set network.enabled false
skillsense config set privacy.store_turn_text true
skillsense config set privacy.store_turn_text false
skillsense config set privacy.show_turn_text true
skillsense config set privacy.show_turn_text false
```

## Other Agent Platforms

Codex and Claude Code adapters read their local logs directly. Other tools can write newline-delimited JSON into:

```text
.skillsense/evidence/*.jsonl
```

Example:

```json
{"platform":"cursor","turn_id":"turn-1","timestamp":"2026-05-14T10:00:00Z","user_message":"check README","assistant_summary":"opened docs skill"}
{"platform":"cursor","turn_id":"turn-1","skill_name":"readme-runner","event_type":"read","certainty":"confirmed","source":"generic_jsonl","snippet":"SKILL.md opened"}
```

Use `invoked` only when the platform exposes a real invocation event. For schema details and Cursor / VS Code / custom agent examples, see [docs/generic-evidence-adapter.md](docs/generic-evidence-adapter.md). Sample files live in [examples/generic_evidence](examples/generic_evidence).

## Evidence Files

SkillSense writes generated state under `.skillsense/`:

```text
.skillsense/skills_index.json
.skillsense/state.json
.skillsense/interventions.json
.skillsense/report.md
.skillsense/dashboard.html
.skillsense/config.json
.skillsense/metadata_cache.json
```

`.skillsense/` is ignored by Git. A fresh clone can regenerate it with `skillsense scan` and `skillsense report`.

## Privacy

Generated state hides turn text by default:

```json
{
  "privacy": {
    "store_turn_text": false,
    "show_turn_text": false
  }
}
```

The timeline can still show evidence without storing chat text. Enable text storage only when you need local debugging.

## Intervention Queue

`skillsense diagnose` creates `.skillsense/interventions.json` and fills the dashboard `Intervention Queue`.

Interventions are review items. They can point out trigger overlap, a missed suggested skill, a possibly wrong `SKILL.md` read, broad descriptions, narrow descriptions, or error-like assistant output when local turn text is available.

SkillSense proposes changes; it does not quietly edit `SKILL.md`.

```bash
skillsense propose-fix <intervention-id>
skillsense apply-fix <intervention-id> --yes
```

The dashboard has the same review flow with `View proposal`, `Apply after review`, and `Dismiss`.

## Network

SkillSense runs offline by default:

```json
{
  "network": {
    "enabled": false
  }
}
```

Turning network on allows optional GitHub metadata enrichment for skills with a `repo_url`, such as stars and maintenance status. If metadata cannot be fetched, the dashboard shows `unknown`.

## Scan Locations

```text
./.claude/skills/
~/.claude/skills/
./.codex/skills/
~/.codex/skills/
./skills/
./examples/
```

`./examples/` is included so a fresh checkout can demonstrate `skillsense scan` immediately.

## Adapter Strategy

| Adapter | Status |
| --- | --- |
| Generic local scan and JSONL evidence | shipped |
| Codex session logs | shipped |
| Claude Code project logs | shipped |
| Cursor / VS Code sidebar | later |
| Platform-level blocking | later, only if a platform exposes the hook |
