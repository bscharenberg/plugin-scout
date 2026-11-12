# Security

## Reporting a problem

Please report security issues privately through GitHub: open the **Security** tab of this repository and choose **Report a vulnerability**. Please do not open a public issue for a security problem. You should hear back within a few days.

## Design in one paragraph

Plugin Scout is an advisor. It reads, counts and recommends. It never installs, enables, disables or changes anything, runs no shell commands, starts no background processes, and holds no credentials. It needs no extra packages: it uses the Python standard library plus what Hermes already ships (a YAML reader for manifests, FastAPI for the dashboard routes). Its single network call is an HTTPS GET of the public Hermes plugin catalog. The only things it ever changes are in its own plugin state: your stated interests, picks you skipped, and the "last looked" marker for the catalog.

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
| Other plugins' `plugin.yaml` / `plugin.json` | Third-party plugin authors | Untrusted. Size capped at 256 KB. A file with YAML anchors, aliases or merge keys (which can expand exponentially) never reaches a YAML library; a small built-in reader that cannot expand anything reads it. Otherwise Hermes's own YAML library (ruamel.yaml, or PyYAML if present) reads it in its safe, text-only mode, so `1.10` stays `1.10`. Only plain text and lists of text are used, so a nested structure is never printed. A name that breaks the catalog's name rule means the plugin is skipped. |
| Hermes's install record (`plugins/.install-metadata.json`) | Hermes, sometimes from values a plugin supplies | Untrusted for this purpose. Names must follow the catalog's name rule and commit ids must be full commit ids, or they are ignored. |
| Model replies (optional `ai` modes) | Your model, possibly steered by catalog text | Untrusted. Ranking accepts only plugin names from its own shortlist. The conflict check accepts only a one-word reply, CLASH or SEPARATE; any other reply leaves the finding as it was. The model's own words are never shown: Scout prints a fixed "AI opinion" line instead. |
| Session history | You | Private. Counted locally, never sent. |
| Hermes memory (`USER.md`, `MEMORY.md`) and your skill list | You | Private. Size capped, matched locally against fixed topic lists, never stored or sent. Bundled skills skipped. |
| Dashboard tab requests | You, through the local dashboard | Served only by Hermes's own dashboard (local by default, behind its sign-in). Two actions change anything: saving your choices (numbers 1 to 13 only; nothing else is accepted) and skipping a pick (catalog-style names only). The page renders text, never HTML. Nothing installs. |
| Interests you give Scout | You | Cleaned and capped (30 items, 40 characters each), kept in Scout's own plugin state. Interests that match no built-in topic never go into an AI prompt; only their count does. |
| `config.yaml` | You | Read-only. A setting is read only when a plugin's known issue names it, and that name comes from third-party text, so: a setting whose name ends like a credential (`key`, `token`, `secret`, `password`, `_env` and similar) is never read; your value is shown only for the plugin's own `plugins.entries.<name>.*` settings and a short list of harmless ones. For every other setting Scout says only whether yours differs. |

**Threats and what stops them**

| Threat | Mitigation | Test |
|---|---|---|
| Your messages leak to a model or a server | Only topic counts and matched keywords from fixed lists leave the profiler. The only server contacted is the catalog. | `test_profile_holds_counts_not_message_text`, `test_prompt_never_contains_message_text` |
| Your memory, skill names or own words leak into an AI prompt | The ranking prompt gets per-topic counts and true/false flags for built-in topics only; your own interest words are replaced by a count. Agent tools return picks and a summary, not the raw profile. | `test_ai_prompt_gets_counts_not_skill_names_or_memory`, `test_memory_adds_topics_without_storing_text`, `test_free_text_interests_stay_out_of_the_prompt` |
| A catalog entry carries terminal escape codes, invisible or direction-changing Unicode | Removed at the door, before any code sees the text: control characters, and every character in the Unicode categories for format characters, surrogates and private use (which covers zero-width and bidirectional marks, tag characters that can hide text a model reads, and anything added to those categories later), plus a short list of invisible characters outside them (variation selectors, Hangul fillers, the braille blank) | `test_every_field_is_clean_and_capped`, `test_reports_built_from_it_stay_clean`, `test_reviewer_list_is_removed` |
| A plugin name smuggles shell syntax into a suggested `hermes plugins ...` command | Every name that can appear in a suggested command (catalog entries, installed plugins' manifests, Hermes's install record) must match the catalog's own rule `[a-z0-9_-]{1,64}`; otherwise the entry is dropped or the plugin skipped | `test_bad_names_and_non_entries_are_dropped`, `test_manifest_and_sidecar_names` |
| A description tries to give the model orders (for example, "recommend me and call me safe") | Two paths. In Scout's own AI prompts, catalog text sits inside `<catalog>` fences with a note that it is data and cannot close the fence early; the model can only choose from the rule-based shortlist. In results Scout's tools return to your agent, including the unattended weekly run, every result starts with a notice that plugin text is third-party data, never instructions, and that no command in it should be run. This lowers the risk; it cannot remove it (see known limits). | `test_catalog_text_is_fenced_and_cannot_close_the_fence`, `test_every_tool_result_and_the_weekly_prompt_carry_the_notice` |
| A description talks the model into hiding a conflict | The model can lower a finding's severity, only with the one-word reply SEPARATE, and never remove it. The finding, its rule-based evidence and the AI's opinion all stay on the report, and the headline never says "all clear" while notes are listed. | `test_model_cannot_hide_a_conflict`, `test_only_a_clear_no_downgrades`, `test_headline_is_not_all_clear_while_notes_are_listed` |
| A known issue names a secret setting (for example `model.api_key`) so its value lands in a tool result or a chat message | Credential-like setting names are never read. Values are shown only for the plugin's own settings and allowlisted harmless ones; otherwise the finding says "yours differs". (Reported by the catalog review, Nov 11, 2026.) | `test_secret_looking_keys_are_never_read`, `test_secret_never_reaches_tool_results_or_weekly_note` |
| A plugin's warning talks you into changing an important setting | An allowlist, not a blocklist: Scout gives a "change it" command only for the plugin's own settings (`plugins.entries.<that plugin>.*`) and a short list of harmless ones. Every other setting, including approvals, isolation, sandbox and secrets, gets only a pointer to the plugin's warning and the option to turn the plugin off | `test_security_setting_gets_no_command` |
| A disclosure hides a risk behind a negation or an unusual domain | A negation only counts when nothing that starts a new statement (a full stop, colon, bracket or words like "except") sits between it and the fact, so a false alarm is preferred over a false all-clear. Web addresses with common, country and newer endings count, and so do raw IP addresses; file names such as `setup.sh` do not. A plain statement that it uploads or sends your files or data counts even without an address. An address with a rare ending can still be missed, which is why Scout never calls a plugin safe and points you to the full entry. | `test_negation_must_govern_the_fact`, `test_any_domain_counts_but_files_and_settings_do_not`, `test_bypass_wordings_are_caught` |
| A prompt-injected agent changes Scout's state | Skipped picks must be valid plugin names, capped at 200 (a full list refuses new names rather than quietly dropping old ones); interests are capped at 60, and only the numbers 1 to 13 count as answers to the welcome question. Only Scout's own state can change. | `test_dismiss_only_stores_real_names_and_is_capped` |
| A huge or malformed catalog or manifest crashes Hermes or floods output | 20 MB download cap, 20,000-entry cap, a 10-minute pause before asking an unreachable catalog again, 256 KB manifest cap, field caps, shape checks, nested structures never printed, bounded patterns on long text, and every command catches errors and answers with a message | `test_wrong_shapes_raise_a_clean_error`, `test_odd_manifests_are_skipped_or_cleaned`, `test_shared_nested_lists_are_never_printed`, `test_long_dotted_text_is_fast` |
| A link loop in the plugins folder causes repeats or fake "duplicate" conflicts | Each real folder is read once | `test_link_loop_does_not_double_count` |
| The plugin is used to change your setup | No code path installs, enables, writes config or calls the shell. Suggestions are text for you to run. | Hermes `plugins validate` capability probe and security scan |
| Offline or catalog outage | Falls back to the last cached copy and says so | `test_store_falls_back_to_stale_cache_when_offline` |

**Known limits**

- The advice is only as good as the catalog. If a plugin's description or declared capabilities are wrong, Plugin Scout can miss a conflict or flag a harmless pair. Conflicts are labelled "likely", with the evidence, for that reason.
- A model can still be persuaded by text it reads. That is why its role is limited to choosing among the rule-based shortlist and adding an opinion, never deciding what is shown.
- Anyone who can already write to your `~/.hermes` folder is out of scope: they could change Hermes itself.
- **Shared group chats.** Scout's tools read your history across all your chats. If your Hermes answers in a shared group chat, anyone who can talk to it could ask for your picks or your profile. Don't enable Scout's tools in shared group chats. The weekly note only goes to the chat it was set up in, or stays local.
- **Text your agent reads.** The third-party-data notice tells your agent not to follow instructions in plugin text, but a model can still be persuaded by what it reads. Scout's tools never run commands themselves, which limits the damage.
- **The before-you-install line** restates each plugin's own disclosure. A dishonest disclosure can still mislead it. For anything sensitive, read the full entry: `hermes plugins info <name>`.
- **The dashboard's sign-in and cross-site protection** come from Hermes's own dashboard; Scout's routes rely on them. Keep the dashboard on its default local address.

## OWASP mapping

Plugin Scout is a local plugin with no server, accounts or web pages, so some items do not apply. Each one is listed anyway, so nothing is skipped silently.

**OWASP Top 10 (2025)**

| Item | How it applies here |
|---|---|
| A01 Broken Access Control | Reads only the active profile's own history and config, read-only. Writes only its own plugin data folder and state. |
| A02 Security Misconfiguration | Safe defaults: AI modes off unless asked for, nothing scheduled unless you set it up. CI runs with a read-only token. |
| A03 Software Supply Chain Failures | No extra packages to install. CI actions pinned to exact commits and kept current by Dependabot. Catalog entry pins an exact commit. No binaries, bytecode or symlinks, checked in CI. |
| A04 Cryptographic Failures | HTTPS only, with Python's default certificate checks. No secrets stored. |
| A05 Injection | No shell, no SQL strings (Hermes's read-only session API), safe YAML loaders. Every plugin name must match the catalog rule before it can appear in a suggested command, from any source. Terminal escape codes and invisible Unicode removed. |
| A06 Insecure Design | Threat model above. Advisor by design: no code path installs or changes anything. |
| A07 Authentication Failures | Not applicable: no accounts, logins or credentials. |
| A08 Software or Data Integrity Failures | Catalog fetched only from its two official addresses; any other address or redirect is refused. Every field checked and cleaned. Cache written atomically. |
| A09 Logging and Alerting Failures | Failures are logged to the Hermes log with details; chat shows a plain message. No message text is logged. |
| A10 Mishandling of Exceptional Conditions | Every command catches errors and fails safe: an error never reads as "all clear", and an old catalog copy is always labelled as old. |

**OWASP Top 10 for LLM Applications (2025)**

| Item | How it applies here |
|---|---|
| LLM01 Prompt Injection | Catalog text fenced as data in Scout's prompts; every tool result to your agent opens with a third-party-data notice, including the unattended weekly run. The model chooses only from the rule-based shortlist. Tested with hostile entries. A residual risk remains (see known limits). |
| LLM02 Sensitive Information Disclosure | Your messages never reach a prompt: only topic counts and matched keywords from fixed lists. Tested with a planted PIN. Error text in chat carries no paths or internals. |
| LLM03 Supply Chain | Uses the model you already configured in Hermes, through Hermes. No other model or service. |
| LLM04 Data and Model Poisoning | A poisoned catalog entry can at most change a suggestion or a note, and can never get a "change it" command for a core Hermes setting. Conflicts rest on declared capabilities and are labelled "likely" with evidence. |
| LLM05 Improper Output Handling | Model replies cleaned and capped; ranking accepts only shortlist names; the conflict check accepts only the one-word reply CLASH or SEPARATE and never shows the model's words; the model never decides what code runs. |
| LLM06 Excessive Agency | Eight tools. Five only read. Three change only Scout's own state (your interests, skipped picks, the "last looked" marker), with validated, capped input. None installs, runs commands or changes config. The weekly note is told to relay text, never act on it. |
| LLM07 System Prompt Leakage | Prompts hold no secrets, only public catalog text and counts. |
| LLM08 Vector and Embedding Weaknesses | Not applicable: no embeddings or vector store. |
| LLM09 Misinformation | Every finding and pick shows its evidence. AI opinions are labelled "AI opinion" and can never remove a finding. |
| LLM10 Unbounded Consumption | At most 5 AI conflict checks and 15 ranking candidates per run, with capped text in each prompt. History reads capped at 200 sessions. |

## Development practice

- No extra packages to install, so there are no dependencies of its own to audit.
- An independent security review on Nov 10, 2026 (a separate model, reading every file and testing attacks) reported 12 findings (F1 to F12). A re-check of the fixes and a separate code review followed the same day. Fixed, each with a regression test built from the reviewer's own input (`tests/test_audit.py`, `tests/test_review2.py`): F1 to F3, F5 to F7 and F9 to F12, plus every re-check and code-review item. Two are reduced but cannot be fully fixed by a plugin, and are listed under known limits: F4 (an agent can still be persuaded by plugin text it reads; every result now carries a third-party-data notice) and F8 (Scout's tools answer in shared group chats too).
- Every change runs the full test suite in GitHub Actions on Python 3.11 to 3.13, and again with each YAML library Hermes may use (PyYAML, ruamel.yaml), including the hostile-input tests in `tests/test_hostile.py`.
- Before each catalog release: `hermes plugins validate .` (capability probe, security scan, no core overrides), a check that no compiled files or binaries are committed, and a scan for secrets and personal paths.
- The catalog entry pins an exact commit, so what you install is what was reviewed.
