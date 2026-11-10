/* Plugin Scout dashboard tab. Plain JavaScript on the dashboard's own SDK: no build step, no
   bundled libraries. Styling follows the Hermes dashboard (see style.css). All text is rendered
   as text, never as HTML. */
(function () {
  "use strict";
  var SDK = window.__HERMES_PLUGIN_SDK__;
  var React = SDK.React;
  var h = React.createElement;
  var useState = SDK.hooks.useState, useEffect = SDK.hooks.useEffect;
  var API = "/api/plugins/plugin-scout";

  function post(path, body) {
    return SDK.fetchJSON(API + path, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body)
    });
  }
  function plural(n, word) {
    if (n === 1) return n + " " + word;
    return n + " " + word + (/(ch|sh|s|x)$/.test(word) ? "es" : "s");
  }
  function plain(text) { return String(text || "").replace(/`/g, ""); }  // backticks are for the terminal
  function sentence(parts) {
    return parts.map(function (r) { return String(r).replace(/\.+$/, ""); }).join(". ") + ".";
  }

  function Stat(props) {
    return h("div", { className: "ps-stat" },
      h("div", { className: "ps-stat-label" }, props.label),
      h("div", { className: "ps-stat-value" }, props.value),
      h("div", { className: "ps-stat-hint" }, props.hint));
  }

  function Jobs(props) {
    var s = useState(props.selected || []), chosen = s[0], setChosen = s[1];
    var b = useState(false), saving = b[0], setSaving = b[1];
    useEffect(function () { setChosen(props.selected || []); }, [JSON.stringify(props.selected || [])]);
    function toggle(n) {
      setChosen(chosen.indexOf(n) >= 0 ? chosen.filter(function (x) { return x !== n; }) : chosen.concat([n]));
    }
    return h("div", { className: "ps-panel" },
      h("strong", { className: "ps-panel-title" }, "What should Hermes handle for you?"),
      h("p", { className: "ps-panel-hint" }, "Pick two to four. Picks follow what you choose and how you actually use Hermes."),
      h("div", { className: "ps-pills" }, props.jobs.map(function (job, i) {
        var n = i + 1, on = chosen.indexOf(n) >= 0;
        return h("button", { key: n, type: "button", className: on ? "active" : "", "aria-pressed": on,
                             onClick: function () { toggle(n); } }, job);
      })),
      h("div", { className: "ps-row", style: { marginTop: ".8rem" } },
        h("button", { type: "button", className: "ps-btn ps-tier-strong", disabled: saving, onClick: function () {
          setSaving(true);
          props.onSave(chosen).finally(function () { setSaving(false); });
        } }, saving ? "Scouting..." : "Update picks")));
  }

  function Pick(props) {
    var p = props.pick;
    var strong = p.confidence === "strong match";
    var s = useState(false), copied = s[0], setCopied = s[1];
    var reasons = (p.why ? [p.why] : []).concat(p.for_you || []).slice(0, 2);
    var tierName = p.tier === "official" || p.tier === "verified" ? p.tier : "community";
    return h("div", { className: "ps-card " + (strong ? "ps-tier-strong" : "ps-tier-guess") },
      h("div", { className: "ps-card-head" },
        h("div", { className: "ps-rank" }, String(p.rank)),
        h("div", null,
          h("div", { className: "ps-card-title" }, p.title),
          h("div", { className: "ps-card-sub" }, (p.interest ? "For " + p.interest + " \u00b7 " : "") + tierName)),
        h("div", { className: "ps-badges" },
          h("span", { className: "ps-badge" }, strong ? "Strong match" : "Early guess"),
          tierName !== "community" ? h("span", { className: "ps-badge ps-tier-official" }, tierName) : null)),
      p.what ? h("p", { className: "ps-desc" }, p.what) : null,
      reasons.length ? h("div", { className: "ps-why" },
        h("span", { className: "ps-label" }, "Why it fits"), h("p", null, sentence(reasons))) : null,
      p.before_install ? h("details", { className: "ps-risk", open: true },
        h("summary", null, "Before you install"), h("p", null, p.before_install)) : null,
      p.heads_up ? h("div", { className: "ps-headsup" }, "Heads up: " + p.heads_up) : null,
      h("div", { className: "ps-install" },
        h("code", null, p.install),
        h("button", { type: "button", className: "ps-btn", onClick: function () {
          try { navigator.clipboard.writeText(p.install); setCopied(true); setTimeout(function () { setCopied(false); }, 1500); }
          catch (e) { /* clipboard unavailable: the command stays visible to copy by hand */ }
        } }, copied ? "Copied" : "Copy"),
        h("button", { type: "button", className: "ps-btn ps-btn-quiet",
                      onClick: function () { props.onDismiss(p.name); } }, "Not for me")));
  }

  function Interests(props) {
    return h("div", { className: "ps-panel" },
      h("strong", { className: "ps-panel-title" }, "Likely interests"),
      props.sources ? h("p", { className: "ps-panel-hint" }, "Read from " + props.sources + ".") : null,
      h("div", { className: "ps-legend" },
        h("span", { className: "ps-chip ps-tier-guess" }, h("i"), "Early guess"),
        h("span", { className: "ps-arrow" }, "\u2192"),
        h("span", { className: "ps-chip ps-tier-strong" }, h("i"), "Strong signal")),
      props.topics.length ? props.topics.map(function (t) {
        var strong = t.signal === "strong signal";
        return h("div", { key: t.topic, className: "ps-interest" },
          h("strong", null, t.topic),
          h("span", { className: "ps-badge " + (strong ? "ps-tier-strong" : "ps-tier-guess") }, strong ? "Strong" : "Guess"),
          h("span", { className: "ps-interest-why" }, t.why.join("; ")));
      }) : h("p", { className: "ps-desc" }, "Nothing to go on yet. Choose above, or use Hermes for a few days."));
  }

  function Setup(props) {
    var serious = props.findings.filter(function (f) { return f.severity >= 2; });
    return h("div", { className: "ps-panel" },
      h("strong", { className: "ps-panel-title" }, "Your setup"),
      h("p", { className: "ps-panel-hint" }, plural(props.enabled, "other plugin") + " enabled."),
      serious.length ? serious.map(function (f, i) {
        return h("div", { key: i, className: "ps-finding" + (f.kind === "conflict" || f.kind === "pulled" ? " ps-tier-danger" : "") },
          h("div", { className: "ps-row" }, h("span", { className: "ps-badge" }, f.label), h("strong", null, plain(f.title))),
          f.evidence.slice(0, 2).map(function (e, j) { return h("p", { key: j }, plain(e)); }));
      }) : h("div", { className: "ps-row" },
        h("span", { className: "ps-badge ps-tier-clear" }, "All clear"),
        h("span", { className: "ps-desc" }, props.enabled ? "Nothing clashing, no settings problems." : "Nothing installed that could clash.")));
  }

  function PluginScoutPage() {
    var s = useState(null), data = s[0], setData = s[1];
    var e = useState(null), error = e[0], setError = e[1];
    var b = useState(false), busy = b[0], setBusy = b[1];
    function load(promise) {
      setBusy(true);
      return promise.then(function (d) { setData(d); setError(d && d.error ? String(d.error) : null); })
        .catch(function (err) { setError(String(err && err.message || err)); })
        .finally(function () { setBusy(false); });
    }
    useEffect(function () { load(SDK.fetchJSON(API + "/overview")); }, []);

    if (!data && !error) return h("div", { className: "ps-loading" }, "Scouting the catalog and your Hermes history...");
    if (!data) return h("div", { className: "ps-loading" }, "Could not load Plugin Scout: " + error);

    var strongCount = data.picks.filter(function (p) { return p.confidence === "strong match"; }).length;
    var serious = data.findings.filter(function (f) { return f.severity >= 2; }).length;
    return h("div", { className: "ps-page" },
      h("div", { className: "ps-hero" },
        h("div", null,
          h("div", { className: "ps-kicker" }, "Setup advisor"),
          h("h1", null, "Plugin Scout"),
          h("p", null, "Reads how you actually use Hermes and the whole plugin catalog, then shows what fits you, " +
            "what each plugin does with your data, and whether your plugins and settings conflict with each other. " +
            "It all runs on your own computer, and your conversations are never sent anywhere. " +
            "It recommends only and never installs.")),
        h("button", { type: "button", className: "ps-btn ps-hero-action", disabled: busy,
                      onClick: function () { load(SDK.fetchJSON(API + "/overview")); } }, busy ? "Scouting..." : "Rescan")),
      h("div", { className: "ps-stats" },
        h(Stat, { label: "Picks for you", value: String(data.picks.length), hint: plural(strongCount, "strong match") }),
        h(Stat, { label: "Catalog", value: (data.catalog_size || 0).toLocaleString(), hint: "plugins read" }),
        h(Stat, { label: "Your setup", value: serious ? plural(serious, "item") : "All clear",
                  hint: plural(data.enabled_plugins, "plugin") + " enabled" }),
        h(Stat, { label: "Signals", value: String(data.sessions), hint: "conversations read, last 30 days" }),
        h(Stat, { label: "Privacy", value: "Local", hint: "your messages never leave" })),
      h(Jobs, { jobs: data.jobs, selected: data.selected_jobs,
                onSave: function (jobs) { return load(post("/interests", { jobs: jobs })); } }),
      h("div", null,
        h("strong", { className: "ps-panel-title" }, "Plugins for you"),
        data.picks.length ? h("div", { className: "ps-grid" }, data.picks.map(function (p) {
          return h(Pick, { key: p.name, pick: p, onDismiss: function (name) { load(post("/dismiss", { name: name })); } });
        })) : h("div", { className: "ps-panel ps-desc" }, "Nothing stands out yet. Choose what Hermes should handle above.")),
      h("div", { className: "ps-split" },
        h(Interests, { topics: data.topics, sources: data.sources }),
        h(Setup, { findings: data.findings, enabled: data.enabled_plugins })),
      error ? h("div", { className: "ps-loading" }, "Note: " + error) : null);
  }

  window.__HERMES_PLUGINS__.register("plugin-scout", PluginScoutPage);
})();
