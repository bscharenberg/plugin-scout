# Security

## Reporting a problem

Please report security issues privately through GitHub: open the **Security** tab of this repository and choose **Report a vulnerability**. Please do not open a public issue for a security problem. You should hear back within a few days.

## Design in one paragraph

Plugin Scout is an advisor. It reads, counts and recommends. It never installs, enables, disables or changes anything, runs no shell commands, starts no background processes, holds no credentials and uses only the Python standard library. Its single network call is an HTTPS GET of the public Hermes plugin catalog.

## Threat model

**What is worth protecting**

1. Your conversations in Hermes session history.
2. Your Hermes setup: config, installed plugins, approvals.
3. Your trust in its advice: a recommendation or an "all clear" you act on.
4. Your terminal and your agent's context, which display and read its output.

**Where outside input comes in**

| Source | Who writes it | How it is treated |
|---|---|---|
| Plugin catalog (`hermes-agent.nousresearch.com`, served from `nousresearch.github.io/hermes-agent`) | Third-party plugin authors, reviewed by Nous | Untrusted. Shape checked, every field cleaned and capped, bad names dropped (`sanitize.py`). |
| Other plugins' `plugin.yaml` / `plugin.json` | Third-party plugin authors | Untrusted. Size capped at 256 KB, safe YAML loaders only, fields cleaned. |
| Model replies (optional `ai` modes) | Your model, possibly steered by catalog text | Untrusted. Only known plugin names accepted, text cleaned and capped. |
| Session history | You | Private. Counted locally, never sent. |
| Hermes memory (`USER.md`, `MEMORY.md`) and your skill list | You | Private. Size capped, matched locally against fixed topic lists, never stored or sent. Bundled skills skipped. |
| Interests you give Scout | You | Cleaned and capped (12 items, 40 characters each), kept in Scout's own plugin state. |
| `config.yaml` | You | Trusted, read-only. |

**Threats and what stops them**

| Threat | Mitigation | Test |
|---|---|---|
| Your messages leak to a model or a server | Only topic counts and matched keywords from fixed lists leave the profiler. The only server contacted is the catalog. | `test_profile_holds_counts_not_message_text`, `test_prompt_never_contains_message_text` |
| Your memory or skill names leak into an AI prompt | The ranking prompt gets per-topic counts and true/false flags only. Agent tools return picks and a summary, not the raw profile. | `test_ai_prompt_gets_counts_not_skill_names_or_memory`, `test_memory_adds_topics_without_storing_text` |
| A catalog entry carries terminal escape codes, invisible or direction-changing Unicode | Removed at the door, before any code sees the text | `test_every_field_is_clean_and_capped`, `test_reports_built_from_it_stay_clean` |
| A plugin name smuggles shell syntax into a suggested `hermes plugins install` command | Names must match the catalog's own rule `[a-z0-9_-]{1,64}`, or the entry is dropped | `test_bad_names_and_non_entries_are_dropped` |
| A description tries to give the model orders (for example, "recommend me and call me safe") | Catalog text sits inside `<catalog>` fences with a note that it is data, and cannot close the fence early. The model can only choose from the rule-based shortlist. | `test_catalog_text_is_fenced_and_cannot_close_the_fence` |
| A description talks the model into hiding a conflict | The model can lower a finding's severity but never remove it. The finding, its rule-based evidence and the AI's verdict all stay on the report. | `test_model_cannot_hide_a_conflict` |
| A huge or malformed catalog or manifest crashes Hermes or floods output | 20 MB download cap, 256 KB manifest cap, field caps, shape checks, and every command catches errors and answers with a message | `test_wrong_shapes_raise_a_clean_error`, `test_odd_manifests_are_skipped_or_cleaned` |
| A link loop in the plugins folder causes repeats or fake "duplicate" conflicts | Each real folder is read once | `test_link_loop_does_not_double_count` |
| The plugin is used to change your setup | No code path installs, enables, writes config or calls the shell. Suggestions are text for you to run. | Hermes `plugins validate` capability probe and security scan |
| Offline or catalog outage | Falls back to the last cached copy and says so | `test_store_falls_back_to_stale_cache_when_offline` |

**Known limits**

- The advice is only as good as the catalog. If a plugin's description or declared capabilities are wrong, Plugin Scout can miss a conflict or flag a harmless pair. Conflicts are labelled "likely", with the evidence, for that reason.
- A model can still be persuaded by text it reads. That is why its role is limited to choosing among the rule-based shortlist and adding an opinion, never deciding what is shown.
- Anyone who can already write to your `~/.hermes` folder is out of scope: they could change Hermes itself.

## OWASP mapping

Plugin Scout is a local plugin with no server, accounts or web pages, so some items do not apply. Each one is listed anyway, so nothing is skipped silently.

**OWASP Top 10 (2025)**

| Item | How it applies here |
|---|---|
| A01 Broken Access Control | Reads only the active profile's own history and config, read-only. Writes only its own plugin data folder and state. |
| A02 Security Misconfiguration | Safe defaults: AI modes off unless asked for, nothing scheduled unless you set it up. CI runs with a read-only token. |
| A03 Software Supply Chain Failures | No dependencies (standard library only). CI actions pinned to exact commits and kept current by Dependabot. Catalog entry pins an exact commit. No binaries, bytecode or symlinks, checked in CI. |
| A04 Cryptographic Failures | HTTPS only, with Python's default certificate checks. No secrets stored. |
| A05 Injection | No shell, no SQL strings (Hermes's read-only session API), safe YAML loaders. Plugin names must match the catalog rule before they appear in a suggested command. Terminal escape codes removed. |
| A06 Insecure Design | Threat model above. Advisor by design: no code path installs or changes anything. |
| A07 Authentication Failures | Not applicable: no accounts, logins or credentials. |
| A08 Software or Data Integrity Failures | Catalog fetched only from its two official addresses; any other address or redirect is refused. Every field checked and cleaned. Cache written atomically. |
| A09 Logging and Alerting Failures | Failures are logged to the Hermes log with details; chat shows a plain message. No message text is logged. |
| A10 Mishandling of Exceptional Conditions | Every command catches errors and fails safe: an error never reads as "all clear", and an old catalog copy is always labelled as old. |

**OWASP Top 10 for LLM Applications (2025)**

| Item | How it applies here |
|---|---|
| LLM01 Prompt Injection | Catalog text fenced as data and unable to close the fence. The model chooses only from the rule-based shortlist. Tested with a hostile entry. |
| LLM02 Sensitive Information Disclosure | Your messages never reach a prompt: only topic counts and matched keywords from fixed lists. Tested with a planted PIN. Error text in chat carries no paths or internals. |
| LLM03 Supply Chain | Uses the model you already configured in Hermes, through Hermes. No other model or service. |
| LLM04 Data and Model Poisoning | A poisoned catalog entry can at most change a suggestion or a note. Conflicts rest on declared capabilities and are labelled "likely" with evidence. |
| LLM05 Improper Output Handling | Model replies cleaned and capped; only known plugin names accepted; the model never decides what code runs. |
| LLM06 Excessive Agency | All five tools are read-only. The weekly note is told to relay text and never install. |
| LLM07 System Prompt Leakage | Prompts hold no secrets, only public catalog text and counts. |
| LLM08 Vector and Embedding Weaknesses | Not applicable: no embeddings or vector store. |
| LLM09 Misinformation | Every finding and pick shows its evidence. AI opinions are labelled "AI check" and can never remove a finding. |
| LLM10 Unbounded Consumption | At most 5 AI conflict checks and 15 ranking candidates per run, with capped text in each prompt. History reads capped at 200 sessions. |

## Development practice

- Standard library only, so there are no dependencies to audit.
- Every change runs the full test suite in GitHub Actions, including the hostile-input tests in `tests/test_hostile.py`.
- Before each catalog release: `hermes plugins validate .` (capability probe, security scan, no core overrides), a check that no compiled files or binaries are committed, and a scan for secrets and personal paths.
- The catalog entry pins an exact commit, so what you install is what was reviewed.
