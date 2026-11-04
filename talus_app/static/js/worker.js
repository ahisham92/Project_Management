// Talus — calculations off the page's thread, so typing and the 3D view stay smooth.
import { analyse, seismicExtras, steepestSafe } from "../engine/analyse.js";
import { CHECKS, runCheck } from "../engine/verify.js";
import { probabilistic } from "../engine/prob.js";
import { femCase } from "../engine/fem.js";

self.onmessage = (ev) => {
  const { id, kind, project } = ev.data;
  try {
    if (kind === "analyse") {
      const t0 = performance.now();
      const r = analyse(project, { onCase: (c, i, n) => self.postMessage({ id, kind: "case", case: c, i, n }) });
      delete r._cases;
      self.postMessage({ id, kind: "done", result: r, ms: performance.now() - t0 });
      const s = seismicExtras(project);
      self.postMessage({ id, kind: "seismic", data: s });
    } else if (kind === "optimise") {
      const r = steepestSafe(project, { onStep: (cot, worst) => self.postMessage({ id, kind: "step", cot, worst }) });
      self.postMessage({ id, kind: "optimised", result: r });
    } else if (kind === "prob") {
      const pr = project.prob || {};
      const r = probabilistic(project, { caseKey: ev.data.caseKey, n: pr.n || 2000, cov: pr.cov || {}, seed: 1, onProgress: (d, n) => self.postMessage({ id, kind: "probStep", done: d, n }) });
      self.postMessage({ id, kind: "probDone", result: r });
    } else if (kind === "fem") {
      let k = 0;
      const r = femCase(project, { caseKey: ev.data.caseKey, guess: ev.data.guess, onRun: (srf, ok) => self.postMessage({ id, kind: "femStep", run: ++k, srf, ok }) });
      self.postMessage({ id, kind: "femDone", result: r });
    } else if (kind === "verify") {
      CHECKS.forEach((c, i) => {
        const t0 = performance.now();
        let rows;
        try { rows = runCheck(c); } catch (e) { rows = [{ label: "error", value: NaN, expected: NaN, error: NaN, pass: false, message: String(e) }]; }
        self.postMessage({ id, kind: "check", i, n: CHECKS.length, check: { id: c.id, group: c.group, title: c.title, source: c.source }, rows, ms: performance.now() - t0 });
      });
      self.postMessage({ id, kind: "verified" });
    }
  } catch (e) {
    self.postMessage({ id, kind: "error", message: String(e && e.message || e), stack: String(e && e.stack || "") });
  }
};
