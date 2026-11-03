// Pontoon — the calculations off the page's thread, so typing and the 3D view stay smooth.
import { analyse } from "../engine/analyse.js";
import { CHECKS, runCheck } from "../engine/verify.js";

self.onmessage = (ev) => {
  const { id, kind, project } = ev.data;
  try {
    if (kind === "analyse") {
      const t0 = performance.now();
      const r = analyse(project);
      self.postMessage({ id, kind: "done", result: JSON.parse(JSON.stringify(r, (k, v) => (typeof v === "function" ? undefined : v))), ms: performance.now() - t0 });
    } else if (kind === "verify") {
      CHECKS.forEach((c, i) => {
        let res;
        try { res = runCheck(c); } catch (e) { res = { name: c.name, ref: c.ref, rows: [], ok: false, error: String(e) }; }
        self.postMessage({ id, kind: "check", i, n: CHECKS.length, res });
      });
      self.postMessage({ id, kind: "verified" });
    }
  } catch (e) {
    self.postMessage({ id, kind: "error", message: String((e && e.message) || e), stack: String((e && e.stack) || "") });
  }
};
