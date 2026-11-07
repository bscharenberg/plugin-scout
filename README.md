# Plugin Scout

New Hermes plugins land every week, faster than anyone can read the catalog.

Plugin Scout is like the veteran coworker who knows your job, notices how you work, and leans over to say "there's a free tool for that," or "heads up, that one needs a setting you don't have." It reads how you actually use Hermes, reads the whole catalog, and tells you what fits:

1. **Plugins that fit you.** Picks based on the tools you use and the topics you ask about, each with the evidence behind it.
2. **Heads-ups.** A plugin whose own warnings apply to your settings, an update waiting, known issues, or a plugin pulled from the catalog (that one always comes first).
3. **Clashes.** If you stack plugins that step in on the same tool, such as two guards on `terminal` or `memory`, it says so before they trip over each other.
4. **What is new for you.** A weekly note that stays quiet unless something matters to you.

It recommends. It never installs, enables or changes anything. Every suggestion ends with the command for you to run yourself.

## Install

```bash
hermes plugins install plugin-scout
hermes plugins enable plugin-scout
```

## Use

| Command | What it does |
|---|---|
| `/scout` | Overview: plugins that fit you, heads-ups, then any clashes |
| `/scout picks` | Plugins that fit how you use Hermes |
| `/scout picks ai` | A shorter, smarter shortlist with a reason for each |
| `/scout check` | Full check of your plugins: clashes, settings, updates, known issues |
| `/scout check ai` | Same, with an AI second opinion on likely clashes |
| `/scout dismiss <name>` | Stop suggesting a plugin |
| `/scout week` | This week's note: only what matters to you |
| `/scout new` | Everything that changed in the catalog since you last looked |
| `/scout seen` | Mark catalog changes as seen |
| `/scout refresh` | Download the catalog again now |

You can also just ask Hermes ("what plugins should I try?", "do my plugins conflict?"). The agent has five tools: `scout_conflicts`, `scout_picks`, `scout_weekly`, `scout_whats_new` and `scout_dismiss`.

**Weekly note.** Open `/blueprint` and pick **Weekly plugin scout** to get it every Monday at a time you choose, in the chat it came from. Nothing is scheduled until you set it up.

### Example

```
Cloudflare Web Search
  Why: In the last 30 days you mentioned web 1 time in 1 session and you used web_search 2 times.
  Heads up: It needs web.cache_enabled: false. Yours is true.
  Install: hermes plugins install cloudflare-web-search   Not for you: /scout dismiss cloudflare-web-search
```

```
Spotify [official]
  Why: In the last 30 days you mentioned music 3 times in 2 sessions.
  Install: hermes plugins install spotify   Not for you: /scout dismiss spotify
```

```
Plugin Scout: 3 enabled plugin(s) checked. 1 to look at.

[CAUTION] Memory Shield and Provenance Gate both step in on `memory`
  - Both register `pre_tool_call`.
  - Both descriptions say they act on `memory`.
  - When both are on, either can block or change the call before the other sees it.
[KNOWN ISSUE] memory-shield: 5 known issues
  - Needs plugins.isolation: in_process (the default). Under plugins.isolation: host the plugin cannot see the current chat, sender or Hermes' review marker, so...
  - 4 more: hermes plugins info memory-shield
```

The last one is from `/scout check`, the full plugin check.

## How it decides

**Picks** come from counts, not from reading your conversations with a model. On your machine, Plugin Scout counts which tools you used and matches about 20 everyday topics (calendar, email, music, coding and so on) against fixed keyword lists in your own messages over the last 30 days. Catalog plugins are scored against those counts. Official and verified plugins get a small boost, plugins with known issues a small penalty.

**Settings** come from each plugin's own known issues. Many name a Hermes setting ("Needs plugins.isolation: in_process", "Set web.cache_enabled: false"). Plugin Scout reads those settings in your config and speaks up only when the warning applies to you, on installed plugins and on picks alike. Tested against every plugin in the catalog on a typical setup, it flagged only the one warning that truly applied.

**Clashes** are uncommon: only a few dozen catalog plugins step in on Hermes's built-in tools, so this mostly matters once you stack guard or safety plugins, most often on `terminal` and `write_file`. They come from what each plugin declares (its tools, hooks and middleware) plus its catalog description. Many plugins use the same hooks, so a shared hook alone is not a conflict. A caution needs both a shared tool-level hook and the same tool named in both descriptions. These are labelled "likely", not proven. `/scout ai` asks your model for a second opinion and downgrades the ones it judges harmless.

## Privacy and what it touches

What a careful user would want to know before installing:

- **Network.** One download only: the public catalog index from `hermes-agent.nousresearch.com`, which redirects to Nous's GitHub Pages site `nousresearch.github.io/hermes-agent` (about 1.7 MB), cached for 6 hours. It refuses any other address or redirect. No telemetry, no analytics, no other servers.
- **Reads outside its own data (read-only).**
  - Your Hermes session history, last 30 days, up to 200 sessions, opened read-only. Used only to count tools and topic keywords.
  - `config.yaml`: the list of enabled plugins, the memory provider, and any setting a plugin's known issues name (to check whether the warning applies to you).
  - Other installed plugins' `plugin.yaml` files and Hermes's install record (`plugins/.install-metadata.json`), to see what you have and which version.
- **Writes.** Only its own plugin data folder (the catalog cache) and its own plugin state (the "last looked" snapshot and your dismissed list).
- **Model calls.** Only when you ask for `ai` (or the agent sets `ai_rank` / `ai_check`). They go to the model you already use, through Hermes. What is sent: topic counts (for example `{"music": {"mentions": 3}}`) and public catalog descriptions. **Your message text is never sent.** A test plants a fake PIN in a chat and fails if it ever reaches a prompt. With a small model this costs a fraction of a cent per run.
- **Never.** No shell commands, no background processes, no credentials, no installs, no changes to other plugins or your config, no overrides of Hermes internals.

## Security

Catalog text, other plugins' manifests and model replies are treated as untrusted: cleaned of escape codes and invisible characters, length-capped, and fenced off as data in AI prompts. The model can add an opinion but can never hide a finding. See [SECURITY.md](SECURITY.md) for the threat model and how to report a problem.

## Development

Standard library only. Tests (including hostile-input tests) run on every push in GitHub Actions:

```bash
python3 -I -m unittest discover -s tests
```

Catalog check:

```bash
hermes plugins validate .
```

## License

MIT
