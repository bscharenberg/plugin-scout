/* Plugin Scout dashboard tab. Plain JavaScript using the dashboard's own SDK: no build step,
   no bundled libraries. All text is rendered as text (never as HTML). */
(function () {
  "use strict";
  var SDK = window.__HERMES_PLUGIN_SDK__;
  var React = SDK.React;
  var h = React.createElement;
  var useState = SDK.hooks.useState, useEffect = SDK.hooks.useEffect;
  var C = SDK.components;
  var API = "/api/plugins/plugin-scout";

  var muted = { color: "var(--muted-foreground, #888)", fontSize: "0.85rem" };
  var row = { display: "flex", flexWrap: "wrap", gap: "0.5rem", alignItems: "center" };
  var stack = { display: "flex", flexDirection: "column", gap: "1rem" };

  function post(path, body) {
    return SDK.fetchJSON(API + path, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body)
    });
  }

  function Section(props) {
    return h(C.Card, null,
      h(C.CardHeader, null, h(C.CardTitle, null, props.title),
        props.hint ? h("p", { style: muted }, props.hint) : null),
      h(C.CardContent, null, props.children));
  }

  function Line(props) {
    if (!props.text) return null;
    return h("p", { style: Object.assign({ margin: "0.25rem 0", fontSize: "0.9rem" }, props.style || {}) },
      h("strong", null, props.label + ": "), props.text);
  }

  function CopyCommand(props) {
    var s = useState(false), copied = s[0], setCopied = s[1];
    return h("div", { style: Object.assign({ marginTop: "0.5rem" }, row) },
      h("code", { style: { padding: "0.3rem 0.6rem", borderRadius: "0.375rem", color: "inherit",
                           background: "rgba(127,127,127,0.18)", border: "1px solid rgba(127,127,127,0.35)",
                           fontSize: "0.85rem", userSelect: "all" } }, props.command),
      h(C.Button, { size: "sm", variant: "outline", onClick: function () {
        try { navigator.clipboard.writeText(props.command); setCopied(true); setTimeout(function () { setCopied(false); }, 1500); }
        catch (e) { /* clipboard unavailable: the command is visible to copy by hand */ }
      } }, copied ? "Copied" : "Copy"),
      props.onDismiss ? h(C.Button, { size: "sm", variant: "ghost", onClick: props.onDismiss }, "Not for me") : null);
  }

  function Pick(props) {
    var p = props.pick;
    var strong = p.confidence === "strong match";
    return h("div", { style: { padding: "0.9rem 1rem", borderRadius: "0.5rem",
                               border: "1px solid var(--border, rgba(127,127,127,0.3))" } },
      h("div", { style: row },
        h("span", { style: { fontWeight: 600, fontSize: "1rem" } }, p.rank + ". " + p.title),
        p.tier === "official" || p.tier === "verified" ? h(C.Badge, { variant: "secondary" }, p.tier) : null,
        h(C.Badge, { variant: strong ? "default" : "outline" }, p.confidence || "")),
      h(Line, { label: "What it does", text: p.what }),
      h(Line, { label: "For you", text: (p.why ? [p.why] : []).concat(p.for_you || []).slice(0, 2)
        .map(function (r) { return r.replace(/\.+$/, ""); }).join(". ") + "." }),
      h(Line, { label: "Before you install", text: p.before_install,
                style: { borderLeft: "4px solid #d97706", paddingLeft: "0.6rem" } }),
      h(Line, { label: "Heads up", text: p.heads_up }),
      h(CopyCommand, { command: p.install, onDismiss: function () { props.onDismiss(p.name); } }));
  }

  function Jobs(props) {
    var s = useState(props.selected || []), chosen = s[0], setChosen = s[1];
    var b = useState(false), saving = b[0], setSaving = b[1];
    useEffect(function () { setChosen(props.selected || []); }, [JSON.stringify(props.selected || [])]);
    function toggle(n) {
      setChosen(chosen.indexOf(n) >= 0 ? chosen.filter(function (x) { return x !== n; }) : chosen.concat([n]));
    }
    return h("div", null,
      h("div", { style: row }, props.jobs.map(function (job, i) {
        var n = i + 1, on = chosen.indexOf(n) >= 0;
        // the theme draws button variants alike, so mark the chosen ones explicitly
        return h(C.Button, { key: n, size: "sm", variant: on ? "default" : "outline", "aria-pressed": on,
                             style: on ? { outline: "2px solid #d97706", outlineOffset: "1px", fontWeight: 700 }
                                       : { opacity: 0.75 },
                             onClick: function () { toggle(n); } }, (on ? "\u2713 " : "") + job);
      })),
      h("div", { style: Object.assign({ marginTop: "0.75rem" }, row) },
        h(C.Button, { size: "sm", disabled: saving, onClick: function () {
          setSaving(true);
          props.onSave(chosen).finally(function () { setSaving(false); });
        } }, saving ? "Updating picks..." : "Update my picks"),
        h("span", { style: muted }, "Pick two to four for the sharpest results.")));
  }

  function Finding(props) {
    var f = props.f;
    return h("div", { style: { marginBottom: "0.6rem" } },
      h("div", { style: row }, h(C.Badge, { variant: f.severity >= 2 ? "destructive" : "outline" }, f.label),
        h("span", { style: { fontWeight: 500 } }, f.title)),
      f.evidence.map(function (e, i) { return h("p", { key: i, style: Object.assign({ margin: "0.2rem 0 0 0.5rem" }, muted) }, e); }));
  }

  function PluginScoutPage() {
    var s = useState(null), data = s[0], setData = s[1];
    var e = useState(null), error = e[0], setError = e[1];
    function load(promise) {
      return promise.then(function (d) { setData(d); setError(d && d.error ? String(d.error) : null); })
        .catch(function (err) { setError(String(err && err.message || err)); });
    }
    useEffect(function () { load(SDK.fetchJSON(API + "/overview")); }, []);

    if (!data && !error) return h("p", { style: muted }, "Reading how you use Hermes...");
    if (!data) return h(Section, { title: "Plugin Scout" }, h("p", null, "Could not load: " + error));

    var serious = data.findings.filter(function (f) { return f.severity >= 2; });
    return h("div", { style: Object.assign({ maxWidth: "60rem" }, stack) },
      h("div", null,
        h("h1", { style: { fontSize: "1.5rem", fontWeight: 700, margin: 0 } }, "Plugin Scout"),
        h("p", { style: muted }, "Plugins that fit how you use Hermes, what each one does with your data, and a check of your setup. " +
          "Counted on this computer; your messages never leave it. It recommends only and never installs anything.")),
      h(Section, { title: "What do you want Hermes to handle for you?" },
        h(Jobs, { jobs: data.jobs, selected: data.selected_jobs,
                  onSave: function (jobs) { return load(post("/interests", { jobs: jobs })); } })),
      h(Section, { title: "Plugins you may find useful", hint: "Available now in the Hermes plugin catalog, best fit first." },
        data.picks.length ? h("div", { style: stack }, data.picks.map(function (p) {
          return h(Pick, { key: p.name, pick: p, onDismiss: function (name) { load(post("/dismiss", { name: name })); } });
        })) : h("p", { style: muted }, "Nothing stands out yet. Choose what you want Hermes to handle above.")),
      h(Section, { title: "Your likely interests", hint: data.sources ? "Based on " + data.sources + "." : null },
        data.topics.length ? data.topics.map(function (t) {
          return h("div", { key: t.topic, style: Object.assign({ marginBottom: "0.4rem" }, row) },
            h("span", { style: { fontWeight: 500, minWidth: "11rem" } }, t.topic),
            h(C.Badge, { variant: t.signal === "strong signal" ? "default" : "outline" }, t.signal),
            h("span", { style: muted }, t.why.join("; ")));
        }) : h("p", { style: muted }, "Nothing to go on yet. Use Hermes for a few days, or choose above.")),
      h(Section, { title: "Your setup", hint: data.enabled_plugins + " other plugin" + (data.enabled_plugins === 1 ? "" : "s") + " enabled." },
        serious.length ? serious.map(function (f, i) { return h(Finding, { key: i, f: f }); })
          : h("p", null, data.enabled_plugins ? "All clear: nothing clashing, no settings problems." :
                           "No other plugins enabled yet, so nothing can clash.")),
      error ? h("p", { style: muted }, "Note: " + error) : null);
  }

  window.__HERMES_PLUGINS__.register("plugin-scout", PluginScoutPage);
})();
