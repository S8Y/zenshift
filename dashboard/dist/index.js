(function () {
  "use strict";

  var SDK = window.__HERMES_PLUGIN_SDK__;
  var React = SDK.React;
  var hooks = SDK.hooks;
  var components = SDK.components;
  var Card = components.Card;
  var CardHeader = components.CardHeader;
  var CardTitle = components.CardTitle;
  var CardContent = components.CardContent;
  var Badge = components.Badge;
  var Button = components.Button;
  var Input = components.Input;
  var Select = components.Select;
  var useState = hooks.useState;
  var useEffect = hooks.useEffect;
  var useRef = hooks.useRef;
  var e = React.createElement;

  var API_BASE = "/api/plugins/zenshift";

  function masked(val) {
    if (!val || val === "(none)") return "(none)";
    if (val.length > 12) return val.slice(0, 8) + "..." + val.slice(-4);
    return val;
  }

  function fmtTime(seconds) {
    if (seconds == null) return "\u2014";
    if (seconds < 60) return seconds + "s";
    if (seconds < 3600) return Math.floor(seconds / 60) + "m " + (seconds % 60) + "s";
    var h = Math.floor(seconds / 3600);
    var m = Math.floor((seconds % 3600) / 60);
    return h + "h " + m + "m";
  }

  function classNames() {
    return Array.prototype.slice.call(arguments).filter(Boolean).join(" ");
  }

  function ErrorBox(props) {
    if (!props.error) return null;
    return e("div", { className: "zenshift-error" }, props.error);
  }

  function SuccessBox(props) {
    if (!props.msg) return null;
    return e("div", { className: "zenshift-success" }, props.msg);
  }

  function ZenShiftPage() {
    var _useState = useState(null);
    var status = _useState[0];
    var setStatus = _useState[1];
    var _useState2 = useState(null);
    var keysList = _useState2[0];
    var setKeysList = _useState2[1];
    var _useState3 = useState("");
    var keysText = _useState3[0];
    var setKeysText = _useState3[1];
    var _useState4 = useState("session");
    var strategy = _useState4[0];
    var setStrategy = _useState4[1];
    var _useState5 = useState(600);
    var interval = _useState5[0];
    var setInterval = _useState5[1];
    var _useState6 = useState(1);
    var apiCalls = _useState6[0];
    var setApiCalls = _useState6[1];
    var _useState7 = useState(false);
    var loading = _useState7[0];
    var setLoading = _useState7[1];
    var _useState8 = useState(null);
    var error = _useState8[0];
    var setError = _useState8[1];
    var _useState9 = useState(null);
    var success = _useState9[0];
    var setSuccess = _useState9[1];
    var _useState10 = useState(null);
    var reportError = _useState10[0];
    var setReportError = _useState10[1];

    var pollingRef = useRef(null);

    function fetchAll() {
      setLoading(true);
      setError(null);
      Promise.all([
        SDK.fetchJSON(API_BASE + "/status"),
        SDK.fetchJSON(API_BASE + "/keys")
      ])
        .then(function (results) {
          setStatus(results[0]);
          setKeysList(results[1]);
          setStrategy(results[0].strategy || "session");
          setInterval(results[0].interval_seconds || 600);
          setApiCalls(results[0].api_calls_before_rotate || 1);
        })
        .catch(function (err) {
          setError(err && err.message ? err.message : String(err));
        })
        .finally(function () { setLoading(false); });
    }

    useEffect(function () { fetchAll(); }, []);

    useEffect(function () {
      if (strategy !== "timed") {
        if (pollingRef.current) { clearInterval(pollingRef.current); pollingRef.current = null; }
        return;
      }
      pollingRef.current = setInterval(function () {
        SDK.fetchJSON(API_BASE + "/check-timed").then(function (data) {
          if (data.status === "rotated") {
            fetchAll();
            setSuccess("Timed rotation: swapped to next key");
          }
        }).catch(function () {});
      }, 5000);
      return function () {
        if (pollingRef.current) { clearInterval(pollingRef.current); }
      };
    }, [strategy]);

    function handleSaveKeys() {
      var lines = keysText.split("\n").map(function (l) { return l.trim(); }).filter(Boolean);
      if (lines.length === 0) {
        setError("Enter at least one API key.");
        return;
      }
      setLoading(true);
      setError(null);
      setSuccess(null);
      SDK.fetchJSON(API_BASE + "/keys", {
        method: "POST",
        body: JSON.stringify({ keys: lines }),
        headers: { "Content-Type": "application/json" }
      })
        .then(function (data) {
          if (data.error) { setError(data.error); return; }
          setSuccess("Saved " + data.count + " key(s). Rotating to first key...");
          return SDK.fetchJSON(API_BASE + "/rotate", { method: "POST" });
        })
        .then(function () { return fetchAll(); })
        .catch(function (err) {
          setError(err && err.message ? err.message : String(err));
        })
        .finally(function () { setLoading(false); });
    }

    function handleSaveConfig() {
      setLoading(true);
      setError(null);
      setSuccess(null);
      var body = { strategy: strategy };
      if (strategy === "timed") body.interval_seconds = interval;
      if (strategy === "api_call") body.api_calls_before_rotate = apiCalls;
      SDK.fetchJSON(API_BASE + "/config", {
        method: "POST",
        body: JSON.stringify(body),
        headers: { "Content-Type": "application/json" }
      })
        .then(function (data) {
          if (data.error) { setError(data.error); return; }
          setSuccess("Configuration updated.");
          return fetchAll();
        })
        .catch(function (err) {
          setError(err && err.message ? err.message : String(err));
        })
        .finally(function () { setLoading(false); });
    }

    function handleForceRotate() {
      setLoading(true);
      setError(null);
      SDK.fetchJSON(API_BASE + "/rotate", { method: "POST" })
        .then(function (data) {
          if (data.status === "no_keys") {
            setError("No keys configured. Add keys first.");
            return;
          }
          setSuccess("Rotated to key #" + data.new_key_index);
          return fetchAll();
        })
        .catch(function (err) {
          setError(err && err.message ? err.message : String(err));
        })
        .finally(function () { setLoading(false); });
    }

    function handleReportError() {
      var errText = reportError && reportError.trim ? reportError.trim() : "";
      if (!errText) { setError("Enter an error message to report."); return; }
      setLoading(true);
      setError(null);
      setSuccess(null);
      SDK.fetchJSON(API_BASE + "/report-error", {
        method: "POST",
        body: JSON.stringify({ error: errText }),
        headers: { "Content-Type": "application/json" }
      })
        .then(function (data) {
          setSuccess("Action: " + data.action + " \u2014 " + (data.reason || ""));
          setReportError("");
          return fetchAll();
        })
        .catch(function (err) {
          setError(err && err.message ? err.message : String(err));
        })
        .finally(function () { setLoading(false); });
    }

    return e("div", { className: "zenshift-page" },

      e("div", { className: "zenshift-header" },
        e("div", null,
          e("h1", null, "ZenShift"),
          e("p", { className: "zenshift-subtitle" }, "OpenCode Zen API Key Rotation Manager")
        ),
        e("div", { className: "zenshift-header-actions" },
          e(Button, { onClick: fetchAll, disabled: loading, size: "sm", outlined: true }, loading ? "Loading..." : "Refresh"),
          e(Button, { onClick: handleForceRotate, disabled: loading, size: "sm" }, "Force Rotate")
        )
      ),

      e(ErrorBox, { error: error }),
      e(SuccessBox, { msg: success }),

      status ? e(Card, null,
        e(CardContent, null,
          e("div", { className: "zenshift-status-grid" },
            e("div", { className: "zenshift-stat-card" },
              e("span", { className: "zenshift-stat-card-label" }, "Active Key"),
              e("span", { className: "zenshift-stat-card-value zenshift-mono" }, masked(status.active_key)),
              e("span", { className: "zenshift-stat-card-hint" }, "Index #" + status.active_key_index)
            ),
            e("div", { className: "zenshift-stat-card" },
              e("span", { className: "zenshift-stat-card-label" }, "Keys"),
              e("span", { className: "zenshift-stat-card-value" }, status.valid_keys + " / " + status.total_keys),
              e("span", { className: "zenshift-stat-card-hint" }, status.blacklisted_count + " blacklisted")
            ),
            e("div", { className: "zenshift-stat-card" },
              e("span", { className: "zenshift-stat-card-label" }, "Strategy"),
              e("span", { className: "zenshift-stat-card-value" }, status.strategy),
              e("span", { className: "zenshift-stat-card-hint" }, status.strategy === "timed" ? "every " + fmtTime(status.interval_seconds) : status.strategy === "api_call" ? "every " + status.api_calls_before_rotate + " call(s)" : "per session")
            ),
            e("div", { className: "zenshift-stat-card" },
              e("span", { className: "zenshift-stat-card-label" }, "Rotations"),
              e("span", { className: "zenshift-stat-card-value" }, status.total_rotations),
              e("span", { className: "zenshift-stat-card-hint" }, "Last: " + fmtTime(status.last_rotate_seconds_ago) + " ago")
            )
          )
        )
      ) : null,

      keysList && keysList.keys && keysList.keys.length > 0 ? e(Card, null,
        e(CardHeader, null,
          e(CardTitle, { className: "text-base" }, "Registered Keys"),
          e(Badge, { tone: "outline" }, keysList.total + " total")
        ),
        e(CardContent, null,
          e("div", { className: "zenshift-key-list" },
            keysList.keys.map(function (k) {
              return e("div", {
                key: k.index,
                className: classNames("zenshift-key-row", k.active && "zenshift-key-active", k.blacklisted && "zenshift-key-blacklisted")
              },
                e("span", { className: "zenshift-key-index" }, "#" + k.index),
                e("span", { className: classNames("zenshift-key-value", "zenshift-mono") }, k.masked),
                k.active ? e(Badge, { tone: "primary", size: "sm" }, "ACTIVE") : null,
                k.blacklisted ? e(Badge, { tone: "destructive", size: "sm" }, "BLACKLISTED " + fmtTime(k.blacklist_remaining_seconds)) : null
              );
            })
          )
        )
      ) : null,

      e(Card, null,
        e(CardHeader, null,
          e(CardTitle, { className: "text-base" }, "API Keys"),
          e("p", { className: "zenshift-card-desc" }, "Paste one OpenCode Zen API key per line. Keys are stored in ~/.hermes/.env and rotated based on the strategy below.")
        ),
        e(CardContent, null,
          e("div", { className: "zenshift-control" },
            e("label", null, "API Keys (one per line)"),
            e("textarea", {
              className: "zenshift-textarea",
              rows: 8,
              placeholder: "sk-zen-abc123...\nsk-zen-def456...\nsk-zen-ghi789...",
              value: keysText,
              onChange: function (ev) { setKeysText(ev.target.value); }
            })
          ),
          e("div", { className: "zenshift-actions" },
            e(Button, { onClick: handleSaveKeys, disabled: loading || !keysText.trim() }, "Save Keys & Rotate")
          )
        )
      ),

      e(Card, null,
        e(CardHeader, null,
          e(CardTitle, { className: "text-base" }, "Rotation Strategy"),
          e("p", { className: "zenshift-card-desc" }, "Choose how and when ZenShift rotates your active API key.")
        ),
        e(CardContent, null,
          e("div", { className: "zenshift-config-grid" },
            e("div", { className: "zenshift-control" },
              e("label", null, "Strategy"),
              e("select", {
                className: "zenshift-select",
                value: strategy,
                onChange: function (ev) { setStrategy(ev.target.value); }
              },
                e("option", { value: "session" }, "Per Session \u2014 rotate on every new session"),
                e("option", { value: "api_call" }, "Per API Call \u2014 rotate every N calls"),
                e("option", { value: "timed" }, "Timed \u2014 rotate every N seconds")
              )
            ),
            strategy === "timed" ? e("div", { className: "zenshift-control" },
              e("label", null, "Interval (seconds)"),
              e(Input, {
                type: "number",
                min: 30,
                step: 30,
                value: interval,
                onChange: function (ev) { setInterval(parseInt(ev.target.value, 10) || 600); }
              })
            ) : null,
            strategy === "api_call" ? e("div", { className: "zenshift-control" },
              e("label", null, "Calls Between Rotations"),
              e(Input, {
                type: "number",
                min: 1,
                step: 1,
                value: apiCalls,
                onChange: function (ev) { setApiCalls(parseInt(ev.target.value, 10) || 1); }
              })
            ) : null
          ),
          e("div", { className: "zenshift-actions", style: { marginTop: "1rem" } },
            e(Button, { onClick: handleSaveConfig, disabled: loading }, "Update Strategy")
          )
        )
      ),

      e(Card, null,
        e(CardHeader, null,
          e(CardTitle, { className: "text-base" }, "Error Detection & Auto-Rotation"),
          e("p", { className: "zenshift-card-desc" }, "Manually test an error to see how ZenShift handles it. Use this to verify blacklist behavior."),
          e(Badge, { tone: "outline" }, "Rate-limit \u2192 rotate \u00b7 Dead key \u2192 blacklist 24h + rotate")
        ),
        e(CardContent, null,
          e("div", { className: "zenshift-test-section" },
            e("div", { className: "zenshift-control" },
              e("label", null, "Simulate an API error"),
              e("textarea", {
                className: "zenshift-textarea zenshift-textarea-sm",
                rows: 3,
                placeholder: 'e.g. "rate limit exceeded" or "invalid API key"',
                value: reportError || "",
                onChange: function (ev) { setReportError(ev.target.value); }
              })
            ),
            e("div", { className: "zenshift-actions" },
              e(Button, { onClick: handleReportError, disabled: loading || !reportError, outlined: true }, "Report Error")
            )
          )
        )
      ),

      e(Card, null,
        e(CardContent, null,
          e("div", { className: "zenshift-info" },
            e("p", null, "How it works:"),
            e("ul", null,
              e("li", null, "API keys are stored in ~/.hermes/.env as ", e("code", null, "OPENCODE_ZEN_API_KEY")),
              e("li", null, "On rotation, the env var is updated in the running process and persisted to .env"),
              e("li", null, "Rate-limit errors (429, quota exceeded) trigger an immediate key swap"),
              e("li", null, "Dead/invalid key errors blacklist the key for 24 hours before rotating"),
              e("li", null, "Blacklisted keys are skipped during rotation until the cooldown expires")
            )
          )
        )
      )
    );
  }

  window.__HERMES_PLUGINS__.register("zenshift", ZenShiftPage);
})();
