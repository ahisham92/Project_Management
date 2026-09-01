// Progress, schedule and earned-value calculations.
//
// These mirror the measurement rules used in the source control workbook:
//   weight %        = weight points / total weight points
//   elapsed months  = (data date - NTP) / days per month
//   planned %       = linear ramp between start and finish month; a line whose
//                     finish <= start is a milestone and steps 0% -> 100% on its date
//   earned progress = weight % x actual % complete
//   variance        = earned - planned
// All percentages are held as fractions (0..1).

export const MS_PER_DAY = 86400000;

export function parseDate(value) {
  if (value instanceof Date) return value;
  const d = new Date(`${String(value).slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) throw new Error(`Invalid date: ${value}`);
  return d;
}

export function toISODate(date) {
  return parseDate(date).toISOString().slice(0, 10);
}

export function addMonths(ntp, months, daysPerMonth) {
  return new Date(parseDate(ntp).getTime() + months * daysPerMonth * MS_PER_DAY);
}

export function daysBetween(from, to) {
  return Math.round((parseDate(to).getTime() - parseDate(from).getTime()) / MS_PER_DAY);
}

/**
 * Elapsed months since NTP.
 *
 * `dayOffset` decides how the NTP day itself is counted. With 0 (the default)
 * elapsed time is zero on the NTP date, which is the convention the schedule
 * columns assume ("month 0 = NTP") and the one the late/due day counts use.
 * With 1 the NTP day counts as a day worked, reproducing spreadsheets that
 * measure elapsed time as `data date - NTP + 1`.
 */
export function elapsedMonths(ntp, dataDate, daysPerMonth, dayOffset = 0) {
  return (daysBetween(ntp, dataDate) + dayOffset) / daysPerMonth;
}

const clamp01 = (n) => Math.min(1, Math.max(0, n));

/** Planned % complete for one task at a given elapsed-month position. */
export function plannedPct(task, elapsed) {
  const start = Number(task.start_month) || 0;
  const finish = Number(task.finish_month) || 0;
  if (finish <= start) return elapsed >= finish ? 1 : 0; // milestone
  return clamp01((elapsed - start) / (finish - start));
}

export function statusOf(actualPct) {
  if (actualPct >= 1) return 'Complete';
  if (actualPct > 0) return 'In Progress';
  return 'Not Started';
}

/**
 * Compute every derived figure for one project.
 *
 * @param {object}   project      project row
 * @param {object[]} tasks        task rows, each optionally carrying `allocations` {trade_id: pct}
 * @param {object[]} trades       trade rows
 * @param {string}   dataDate     YYYY-MM-DD progress cut-off
 * @param {object}   options      { horizonDays, spentByTrade }
 */
export function computeProject(project, tasks, trades = [], dataDate, options = {}) {
  const { horizonDays = 30, spentByTrade = {} } = options;
  const daysPerMonth = Number(project.days_per_month) || 30.4375;
  const hoursPerMonth = Number(project.hours_per_month) || 176;
  const dayOffset = Number(project.elapsed_day_offset) || 0;
  const elapsed = elapsedMonths(project.ntp_date, dataDate, daysPerMonth, dayOffset);
  const totalPoints = tasks.reduce((sum, t) => sum + (Number(t.weight_points) || 0), 0);

  const cutoff = parseDate(dataDate);
  const horizonEnd = new Date(cutoff.getTime() + horizonDays * MS_PER_DAY);

  const rows = tasks.map((task) => {
    const points = Number(task.weight_points) || 0;
    const weightPct = totalPoints > 0 ? points / totalPoints : 0;
    const actual = clamp01(Number(task.actual_pct) || 0);
    const planned = plannedPct(task, elapsed);
    const earned = weightPct * actual;
    const plannedProgress = weightPct * planned;

    const plannedStart = addMonths(project.ntp_date, Number(task.start_month) || 0, daysPerMonth);
    const dueDate = addMonths(project.ntp_date, Number(task.finish_month) || 0, daysPerMonth);
    const daysToDue = daysBetween(cutoff, dueDate);
    const isComplete = actual >= 1;
    const isLate = !isComplete && dueDate < cutoff;

    return {
      ...task,
      weight_pct: weightPct,
      actual_pct: actual,
      planned_pct: planned,
      earned_progress: earned,
      planned_progress: plannedProgress,
      variance: earned - plannedProgress,
      status: statusOf(actual),
      planned_start: toISODate(plannedStart),
      due_date: toISODate(dueDate),
      days_to_due: daysToDue,
      is_complete: isComplete,
      is_late: isLate,
      days_late: isLate ? -daysToDue : 0,
      is_upcoming: !isComplete && !isLate && dueDate <= horizonEnd,
      is_behind: !isComplete && actual < planned - 1e-9,
      is_milestone: (Number(task.finish_month) || 0) <= (Number(task.start_month) || 0),
    };
  });

  const earnedTotal = rows.reduce((s, r) => s + r.earned_progress, 0);
  const plannedTotal = rows.reduce((s, r) => s + r.planned_progress, 0);

  const tradeRows = trades.map((trade) => {
    let scopeWeight = 0;
    let earnedContrib = 0;
    let plannedContrib = 0;
    for (const row of rows) {
      const share = Number(row.allocations?.[trade.id] ?? 0);
      if (!share) continue;
      scopeWeight += row.weight_pct * share;
      earnedContrib += row.earned_progress * share;
      plannedContrib += row.planned_progress * share;
    }
    // Percent complete *of that trade's own scope*, as in the workbook's budget control tab.
    const earnedOfTrade = scopeWeight > 0 ? earnedContrib / scopeWeight : 0;
    const plannedOfTrade = scopeWeight > 0 ? plannedContrib / scopeWeight : 0;

    const budgetHours = Number(trade.budget_hours) || 0;
    const spentHours = Number(spentByTrade[trade.id] || 0);
    const earnedHours = budgetHours * earnedOfTrade;
    const cpi = spentHours > 0 ? earnedHours / spentHours : null;
    const eac = cpi && cpi > 0 ? budgetHours / cpi : budgetHours;

    return {
      id: trade.id,
      key: trade.key,
      name: trade.name,
      color: trade.color,
      sort_order: trade.sort_order,
      scope_weight_pct: scopeWeight,
      earned_contribution: earnedContrib,
      planned_contribution: plannedContrib,
      earned_pct_of_trade: earnedOfTrade,
      planned_pct_of_trade: plannedOfTrade,
      schedule_variance_pct: earnedOfTrade - plannedOfTrade,
      budget_hours: budgetHours,
      budget_months: hoursPerMonth > 0 ? budgetHours / hoursPerMonth : 0,
      spent_hours: spentHours,
      hours_used_pct: budgetHours > 0 ? spentHours / budgetHours : 0,
      earned_hours: earnedHours,
      hours_over_under: spentHours - earnedHours, // positive = burning more hours than progress earned
      remaining_hours: budgetHours - spentHours,
      cpi,
      eac_hours: eac,
      vac_hours: budgetHours - eac,
      budget_status: budgetStatus({ spentHours, budgetHours, cpi }),
    };
  });

  const budgetHours = tradeRows.reduce((s, t) => s + t.budget_hours, 0);
  const spentHours = tradeRows.reduce((s, t) => s + t.spent_hours, 0);
  const earnedHours = tradeRows.reduce((s, t) => s + t.earned_hours, 0);
  const projectCpi = spentHours > 0 ? earnedHours / spentHours : null;
  const eacHours = projectCpi && projectCpi > 0 ? budgetHours / projectCpi : budgetHours;

  const late = rows.filter((r) => r.is_late);
  const upcoming = rows.filter((r) => r.is_upcoming);
  const behind = rows.filter((r) => r.is_behind);

  return {
    data_date: toISODate(dataDate),
    ntp_date: toISODate(project.ntp_date),
    elapsed_months: elapsed,
    duration_months: Number(project.duration_months) || 0,
    time_elapsed_pct: project.duration_months > 0 ? clamp01(elapsed / project.duration_months) : 0,
    total_weight_points: totalPoints,
    horizon_days: horizonDays,
    totals: {
      planned_progress: plannedTotal,
      earned_progress: earnedTotal,
      variance: earnedTotal - plannedTotal,
      spi: plannedTotal > 0 ? earnedTotal / plannedTotal : null,
      task_count: rows.length,
      weighted_count: rows.filter((r) => (Number(r.weight_points) || 0) > 0).length,
      complete_count: rows.filter((r) => r.is_complete).length,
      in_progress_count: rows.filter((r) => !r.is_complete && r.actual_pct > 0).length,
      not_started_count: rows.filter((r) => r.actual_pct <= 0).length,
      late_count: late.length,
      upcoming_count: upcoming.length,
      behind_count: behind.length,
      weight_at_risk: late.reduce((s, r) => s + r.weight_pct, 0),
    },
    budget: {
      hours_per_month: hoursPerMonth,
      budget_hours: budgetHours,
      spent_hours: spentHours,
      earned_hours: earnedHours,
      remaining_hours: budgetHours - spentHours,
      hours_used_pct: budgetHours > 0 ? spentHours / budgetHours : 0,
      hours_over_under: spentHours - earnedHours,
      cpi: projectCpi,
      eac_hours: eacHours,
      vac_hours: budgetHours - eacHours,
      budget_status: budgetStatus({ spentHours, budgetHours, cpi: projectCpi }),
    },
    tasks: rows,
    trades: tradeRows,
  };
}

function budgetStatus({ spentHours, budgetHours, cpi }) {
  if (!spentHours) return 'No spend booked';
  if (spentHours > budgetHours) return 'Over budget';
  if (cpi === null) return 'No spend booked';
  if (cpi >= 1) return 'Under / on budget';
  if (cpi >= 0.9) return 'Slightly over-burning';
  return 'Over-burning';
}

/**
 * Planned and earned cumulative curves over the life of the project (the S-curve).
 * Planned comes from the schedule; earned is reconstructed from the progress history
 * so the curve shows what was actually reported at each point in time.
 */
export function buildSCurve(project, tasks, progressHistory, dataDate, steps = 40) {
  const daysPerMonth = Number(project.days_per_month) || 30.4375;
  const duration = Number(project.duration_months) || 12;
  const totalPoints = tasks.reduce((s, t) => s + (Number(t.weight_points) || 0), 0);
  const weightOf = (t) => (totalPoints > 0 ? (Number(t.weight_points) || 0) / totalPoints : 0);

  const ntp = parseDate(project.ntp_date);
  const cutoff = parseDate(dataDate);
  const dayOffset = Number(project.elapsed_day_offset) || 0;
  const endMonths = Math.max(duration, elapsedMonths(project.ntp_date, dataDate, daysPerMonth, dayOffset));

  // Progress history sorted oldest first, so we can replay it date by date.
  const history = [...progressHistory].sort((a, b) => a.data_date.localeCompare(b.data_date));

  // Sample evenly across the programme, but always include the data date itself
  // so the earned curve ends exactly on the reported progress.
  // Month positions map to dates the same way deliverable due dates do
  // (month 0 = NTP); the data date is added as its own sample so the earned
  // curve ends exactly on the reported progress.
  const samples = [];
  for (let i = 0; i <= steps; i++) {
    const month = (endMonths * i) / steps;
    samples.push({ month, date: toISODate(new Date(ntp.getTime() + month * daysPerMonth * MS_PER_DAY)) });
  }
  const cutoffMonth = elapsedMonths(project.ntp_date, dataDate, daysPerMonth, dayOffset);
  if (cutoffMonth >= 0 && cutoffMonth <= endMonths) {
    samples.push({ month: cutoffMonth, date: toISODate(dataDate) });
  }
  samples.sort((a, b) => a.month - b.month || a.date.localeCompare(b.date));

  const points = [];
  let previous = null;
  for (const { month, date } of samples) {
    if (previous !== null && Math.abs(month - previous) < 1e-9) continue; // de-duplicate
    previous = month;
    const planned = tasks.reduce((s, t) => s + weightOf(t) * plannedPct(t, month), 0);

    let earned = null;
    if (date <= toISODate(cutoff)) {
      const stateAt = new Map();
      for (const h of history) {
        if (h.data_date > date) break;
        stateAt.set(h.task_id, clamp01(Number(h.actual_pct) || 0));
      }
      earned = tasks.reduce((s, t) => s + weightOf(t) * (stateAt.get(t.id) ?? 0), 0);
    }

    points.push({ month: Number(month.toFixed(3)), date, planned, earned });
  }
  return points;
}

/** Progress gained between two dates, per task and in total (the period report). */
export function buildPeriodReport(project, tasks, trades, progressHistory, from, to) {
  const fromISO = toISODate(from);
  const toISO = toISODate(to);
  const totalPoints = tasks.reduce((s, t) => s + (Number(t.weight_points) || 0), 0);
  const history = [...progressHistory].sort((a, b) => a.data_date.localeCompare(b.data_date));

  const atStart = new Map();
  const atEnd = new Map();
  for (const h of history) {
    const pct = clamp01(Number(h.actual_pct) || 0);
    if (h.data_date < fromISO) atStart.set(h.task_id, pct);
    if (h.data_date <= toISO) atEnd.set(h.task_id, pct);
  }

  const rows = tasks.map((task) => {
    const weightPct = totalPoints > 0 ? (Number(task.weight_points) || 0) / totalPoints : 0;
    const startPct = atStart.get(task.id) ?? 0;
    // If a task has no history at all, fall back to its live value at period end.
    const endPct = atEnd.has(task.id) ? atEnd.get(task.id) : (atStart.has(task.id) ? startPct : clamp01(Number(task.actual_pct) || 0));
    const delta = endPct - startPct;
    const trade_earned = {};
    for (const trade of trades) {
      const share = Number(task.allocations?.[trade.id] ?? 0);
      if (share) trade_earned[trade.id] = weightPct * delta * share;
    }
    return {
      id: task.id,
      wbs: task.wbs,
      name: task.name,
      section_id: task.section_id,
      weight_pct: weightPct,
      actual_start: startPct,
      actual_end: endPct,
      delta_actual: delta,
      earned_start: weightPct * startPct,
      earned_end: weightPct * endPct,
      earned_in_period: weightPct * delta,
      trade_earned,
      period_status: delta > 1e-9 ? (endPct >= 1 ? 'Completed in period' : 'Advanced in period')
        : (endPct >= 1 ? 'Already complete' : startPct > 0 ? 'No change – in progress' : 'No change – not started'),
    };
  });

  const daysPerMonth = Number(project.days_per_month) || 30.4375;
  const plannedAtEnd = tasks.reduce((s, t) => {
    const w = totalPoints > 0 ? (Number(t.weight_points) || 0) / totalPoints : 0;
    return s + w * plannedPct(t, elapsedMonths(project.ntp_date, toISO, daysPerMonth, Number(project.elapsed_day_offset) || 0));
  }, 0);

  return {
    from: fromISO,
    to: toISO,
    days_in_period: daysBetween(fromISO, toISO) + 1,
    earned_at_start: rows.reduce((s, r) => s + r.earned_start, 0),
    earned_at_end: rows.reduce((s, r) => s + r.earned_end, 0),
    earned_in_period: rows.reduce((s, r) => s + r.earned_in_period, 0),
    planned_at_end: plannedAtEnd,
    trade_earned_in_period: trades.map((t) => ({
      id: t.id,
      name: t.name,
      color: t.color,
      earned_in_period: rows.reduce((s, r) => s + (r.trade_earned[t.id] || 0), 0),
    })),
    tasks: rows,
  };
}
