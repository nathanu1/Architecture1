// The research platform's views inside the town's inspector: decision records, the social
// network, behavior measures and beliefs. They read the same read-only research API as the
// other tabs and show recorded data only (docs/research_platform.md §6).

import { useEffect, useMemo, useState } from "react";
import { DEMO } from "../demo/flag";
import { circleLayout, colorFor, daysOf, familiarityWord, percent, recordSummary, TOM_LABELS, valenceWord, type DecisionRecord } from "../lib/research";
import { formatDayTime, formatDecimal, formatNumber, formatTime } from "../lib/time";
import { Card, Pill, Problem, SERVER_HINT, Stat, td, th, useQueryParam, useResearch, type Json } from "./inspectorShared";

const RECORDED_NOTE = "Recorded evidence only: engine events with the retrieval traces and model calls they cite. Nothing here is explained after the fact.";
const selectCls = "min-h-9 rounded-xl border-2 border-[var(--line)] bg-[var(--panel)] px-2 text-sm text-[var(--text)]";

function nameOf(agents: Json[]): (id: string) => string {
  const byId = new Map(agents.map((a) => [a.id, a.name as string]));
  return (id: string) => (id === "builder" ? "the town builder" : (byId.get(id) ?? id));
}

function colorOf(agents: Json[]): (id: string) => string {
  const byId = new Map(agents.map((a) => [a.id, a.color as string]));
  return (id: string) => byId.get(id) ?? "#625f75";
}

function Missing({ what, error }: { what: string; error: string }) {
  if (DEMO) return <p className="text-[var(--muted)]">This recording does not include {what}. Run <span className="font-semibold">ga play</span> on a town to see it live.</p>;
  return <Problem>{`Could not load ${what}: ${error}. ${SERVER_HINT}`}</Problem>;
}

// ------------------------------------------------------------------ decisions
export function Decisions({ agent, agents, refresh }: { agent: string; agents: Json[]; refresh: number }) {
  const { data, error, loading } = useResearch<{ records: DecisionRecord[]; traces: Record<string, Json>; calls: Record<string, Json>; note: string }>(agent ? `agent/${encodeURIComponent(agent)}/decisions?limit=400` : null, [refresh]);
  const [day, setDay] = useQueryParam("day");
  const [type, setType] = useQueryParam("type");
  const [openParam, setOpen] = useQueryParam("rec");
  const name = nameOf(agents);
  const records = data?.records ?? [];
  const days = useMemo(() => daysOf(records), [records]);
  const theDay = days.includes(day) ? day : (days[days.length - 1] ?? "");
  const shown = records.filter((r) => r.sim_time.slice(0, 10) === theDay && (!type || r.type === type));
  const open = shown.find((r) => String(r.id) === openParam) ?? shown[shown.length - 1];
  useEffect(() => setOpen(""), [agent]); // eslint-disable-line react-hooks/exhaustive-deps
  const types = [...new Set(records.map((r) => r.type))].sort();
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
      <Card
        title="Decision Records"
        aside={
          <div className="flex flex-wrap items-center gap-2">
            <label htmlFor="dec-day" className="sr-only">
              Day
            </label>
            <select id="dec-day" value={theDay} onChange={(e) => setDay(e.target.value)} className={selectCls}>
              {days.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
            <label htmlFor="dec-type" className="sr-only">
              Event type
            </label>
            <select id="dec-type" value={type} onChange={(e) => setType(e.target.value)} className={selectCls}>
              <option value="">All events</option>
              {types.map((t) => (
                <option key={t} value={t}>
                  {t.replace(/_/g, " ")}
                </option>
              ))}
            </select>
          </div>
        }
      >
        {error ? <Missing what="decision records" error={error} /> : null}
        {loading && !data ? <p className="text-[var(--muted)]">Loading…</p> : null}
        {data && !shown.length ? <p className="text-[var(--muted)]">No recorded decisions for this day yet.</p> : null}
        {shown.length ? (
          <ol className="space-y-1">
            {shown.map((r) => (
              <li key={r.id} className="[contain-intrinsic-size:auto_56px] [content-visibility:auto]">
                <button
                  type="button"
                  aria-pressed={open?.id === r.id}
                  onClick={() => setOpen(String(r.id))}
                  className={`flex w-full gap-3 rounded-xl px-3 py-2 text-left text-sm transition-colors ${open?.id === r.id ? "bg-sun/25" : "hover:bg-[var(--panel-hover)]"}`}
                >
                  <span className="w-16 shrink-0 tabular text-xs text-[var(--muted)]">
                    {formatTime(r.sim_time)}
                    <span className="block">step {formatNumber(r.step)}</span>
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="mr-1 inline-block size-2.5 rounded-full align-middle" style={{ background: colorFor(r.type) }} aria-hidden="true" />
                    <span className="font-display font-semibold">{r.type.replace(/_/g, " ")}</span>
                    {r.trace_ids.length ? <span className="ml-1.5 text-xs text-[var(--muted)]">{r.trace_ids.length} retrieval{r.trace_ids.length > 1 ? "s" : ""}</span> : null}
                    <span className="line-clamp-2 block text-[var(--muted)]">{recordSummary(r, name)}</span>
                  </span>
                </button>
              </li>
            ))}
          </ol>
        ) : null}
      </Card>
      <Card title="What the Record Shows" hint="recorded, not reconstructed">
        {!open ? (
          <p className="text-[var(--muted)]">Pick a record to see the memories it retrieved, the model calls it made and the stored payload.</p>
        ) : (
          <>
            <div className="mb-3 rounded-xl bg-[var(--panel-2)] p-3 text-sm">
              <div className="mb-1 flex flex-wrap items-center gap-2">
                <Pill color={colorFor(open.type)}>{open.type.replace(/_/g, " ")}</Pill>
                <Pill color="#58b368">recorded</Pill>
                <span className="tabular text-xs text-[var(--muted)]">
                  {formatDayTime(open.sim_time)}, step {formatNumber(open.step)}
                </span>
              </div>
              <p>{recordSummary(open, name)}</p>
            </div>
            <h3 className="font-display font-bold">Memories retrieved for this decision</h3>
            {open.trace_ids.length ? (
              <ul className="mb-3 mt-1 space-y-2 text-sm">
                {open.trace_ids.map((tid) => {
                  const t = data?.traces[tid];
                  if (!t) return <li key={tid} className="text-[var(--muted)]">{tid} (trace not kept)</li>;
                  return (
                    <li key={tid} className="rounded-xl bg-[var(--panel-2)] p-2.5">
                      <p className="text-xs text-[var(--muted)]">
                        <span translate="no">{t.purpose}</span>, {formatNumber(t.delivered)} delivered, {formatNumber(t.excluded)} excluded
                      </p>
                      <p className="font-semibold">“{t.query}”</p>
                      <ul className="mt-1 space-y-0.5 pl-3">
                        {(t.top ?? []).map((m: Json) => (
                          <li key={m.id}>
                            <span className="rounded-md bg-[var(--panel)] px-1 text-xs font-bold" translate="no">
                              {m.kind}
                            </span>{" "}
                            {m.description} <span className="tabular text-xs text-[var(--muted)]">{formatDecimal(m.score)}</span>
                          </li>
                        ))}
                      </ul>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="mb-3 text-sm text-[var(--muted)]">This record cites no retrieval.</p>
            )}
            <h3 className="font-display font-bold">Model calls</h3>
            {open.call_ids.length || open.calls_at_time?.length ? (
              <ul className="mb-3 mt-1 space-y-0.5 text-sm">
                {[...open.call_ids.map((id) => ({ id, ...(data?.calls[String(id)] ?? {}), cited: true })), ...(open.calls_at_time ?? []).filter((c) => !open.call_ids.includes(c.id)).map((c) => ({ ...c, cited: false }))].map((c: Json) => (
                  <li key={c.id}>
                    <span className="tabular text-[var(--muted)]">#{c.id}</span> <span translate="no">{c.task ?? "call"}</span> <span className="text-[var(--muted)]">{c.status ?? ""}</span>
                    {c.attempt_kind === "repair" ? <Pill color="#d99a26">repair</Pill> : null}
                    {!c.cited ? <span className="ml-1 text-xs text-[var(--muted)]">(same time, not cited by the record)</span> : null}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mb-3 text-sm text-[var(--muted)]">No model call at this time.</p>
            )}
            <h3 className="font-display font-bold">Stored payload</h3>
            <pre className="mt-1 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-2xl bg-[var(--panel-2)] p-3 font-mono text-xs leading-relaxed" translate="no">
              {JSON.stringify(open.payload, null, 1)}
            </pre>
            <p className="mt-2 text-xs text-[var(--muted)]">{data?.note ?? RECORDED_NOTE}</p>
          </>
        )}
      </Card>
    </div>
  );
}

// ------------------------------------------------------------------ network
function Graph({ nodes, edges, color, name, size = 360 }: { nodes: string[]; edges: [string, string][]; color: (id: string) => string; name: (id: string) => string; size?: number }) {
  const pos = circleLayout(nodes, size);
  return (
    <svg viewBox={`0 0 ${size} ${size}`} className="mx-auto block w-full max-w-sm" role="img" aria-label={`Social network with ${nodes.length} residents and ${edges.length} mutual ties`}>
      {edges.map(([a, b]) => (
        <line key={`${a}-${b}`} x1={pos[a][0]} y1={pos[a][1]} x2={pos[b][0]} y2={pos[b][1]} stroke="#4a82dd" strokeWidth={2.5} strokeLinecap="round" opacity={0.75} />
      ))}
      {nodes.map((n) => (
        <g key={n}>
          <circle cx={pos[n][0]} cy={pos[n][1]} r={13} fill={color(n)} stroke="var(--panel)" strokeWidth={3} />
          <text x={pos[n][0]} y={pos[n][1] + 27} textAnchor="middle" fontSize={12} fontFamily="Fredoka, sans-serif" fontWeight={600} fill="var(--text)">
            {name(n).split(" ")[0]}
          </text>
        </g>
      ))}
    </svg>
  );
}

function Sparkline({ series, keyName, color, label }: { series: Json[]; keyName: string; color: string; label: string }) {
  const w = 300;
  const h = 70;
  const vals = series.map((s) => Number(s[keyName] ?? 0));
  const max = Math.max(1e-9, ...vals);
  const pts = vals.map((v, i) => `${(i / Math.max(1, vals.length - 1)) * (w - 8) + 4},${h - 14 - (v / max) * (h - 24)}`).join(" ");
  return (
    <div className="rounded-xl bg-[var(--panel-2)] p-2">
      <div className="flex items-baseline justify-between text-xs">
        <span className="font-semibold">{label}</span>
        <span className="tabular text-[var(--muted)]">now {formatDecimal(vals[vals.length - 1] ?? 0)}</span>
      </div>
      <svg viewBox={`0 0 ${w} ${h}`} className="block w-full" aria-hidden="true">
        <polyline points={pts} fill="none" stroke={color} strokeWidth={2.5} strokeLinejoin="round" strokeLinecap="round" />
      </svg>
    </div>
  );
}

export function Network({ agent, agents, refresh }: { agent: string; agents: Json[]; refresh: number }) {
  const base = useResearch<Json>("network", [refresh]);
  const [idx, setIdx] = useState<number | null>(null);
  const series: Json[] = base.data?.series ?? [];
  const last = series.length - 1;
  const at = idx != null && idx < last ? (series[idx]?.sim_time as string) : null;
  const past = useResearch<Json>(at && !DEMO ? `network?at=${encodeURIComponent(at)}` : null);
  const nw = at && past.data ? past.data : base.data;
  const name = nameOf(agents);
  const color = colorOf(agents);
  if (base.error) return <Missing what="the social network" error={base.error} />;
  if (!nw) return <p className="text-[var(--muted)]">{base.loading ? "Reading relationship records…" : ""}</p>;
  const m = nw.measures ?? {};
  const nodes = agents.map((a) => a.id as string);
  const edges = (m.edges ?? []) as [string, string][];
  const mine = ((nw.states ?? []) as Json[]).filter((s) => s.agent_id === agent).sort((a, b) => b.familiarity - a.familiarity);
  const cfg = nw.config ?? {};
  return (
    <>
      <Card title="Social Network" hint={`ties need familiarity ≥ ${nw.threshold} in both directions; appraisal ${cfg.appraisal ?? "none"}; informs prompts ${cfg.inform_prompts ? "yes" : "no"}`}>
        {series.length > 1 && !DEMO ? (
          <div className="mb-3 flex items-center gap-3">
            <label htmlFor="nw-time" className="whitespace-nowrap font-display text-sm font-semibold tabular">
              {formatDayTime((at ?? series[last].sim_time) as string)}
            </label>
            <input id="nw-time" type="range" min={0} max={last} value={idx ?? last} onChange={(e) => setIdx(Number(e.target.value))} className="w-full accent-[var(--color-sun)]" />
          </div>
        ) : null}
        <div className="mb-3 flex flex-wrap gap-2">
          <Stat value={m.density ?? "–"} label="density" color="#4a82dd" />
          <Stat value={m.edge_count ?? 0} label="mutual ties" />
          <Stat value={m.components ?? 0} label="groups" color="#2a9d96" />
          <Stat value={m.isolates ?? 0} label="on their own" />
          <Stat value={m.reciprocity ?? "–"} label="reciprocity" />
          <Stat value={m.clustering ?? "–"} label="clustering" />
          <Stat value={m.mean_familiarity ?? "–"} label="mean familiarity" color="#ee8a5c" />
          <Stat value={m.mean_valence ?? "–"} label="mean valence" color="#e2629b" />
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <Graph nodes={nodes} edges={edges} color={color} name={name} />
          <div className="grid content-start gap-2">
            {series.length > 1 ? (
              <>
                <Sparkline series={series} keyName="density" color="#4a82dd" label="Density over the run" />
                <Sparkline series={series} keyName="edge_count" color="#e2629b" label="Mutual ties over the run" />
                <Sparkline series={series} keyName="mean_familiarity" color="#ee8a5c" label="Mean familiarity over the run" />
              </>
            ) : (
              <p className="text-sm text-[var(--muted)]">The run is too short for a time series yet.</p>
            )}
          </div>
        </div>
        <p className="mt-3 text-xs text-[var(--muted)]">
          Rules: a conversation adds {cfg.familiarity_gain_conversation ?? "?"} of the remaining distance to 1, being nearby adds {cfg.familiarity_gain_presence ?? "?"} at most every {cfg.presence_cooldown_minutes ?? "?"} minutes, familiarity fades by {cfg.decay_per_day ?? "?"} per day without contact. Every update is logged, so the slider replays the record.
        </p>
      </Card>
      <Card title={`${name(agent).split(" ")[0]}'s Own Records`} hint="what this resident could be told in its prompts; never the other side's record">
        {mine.length ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr>
                  <th className={th}>Resident</th>
                  <th className={th}>Familiarity</th>
                  <th className={`${th} tabular`}>Talks</th>
                  <th className={`${th} tabular`}>Seen</th>
                  <th className={th}>Feeling</th>
                  <th className={th}>Last</th>
                </tr>
              </thead>
              <tbody>
                {mine.map((s) => (
                  <tr key={s.other_id} className="border-t border-[var(--line)]">
                    <td className={`${td} font-semibold`}>
                      <span className="mr-1.5 inline-block size-2.5 rounded-full align-middle" style={{ background: color(s.other_id) }} aria-hidden="true" />
                      {name(s.other_id)}
                    </td>
                    <td className={td}>
                      <span className="inline-block h-2 w-28 overflow-hidden rounded-full bg-[var(--panel-2)] align-middle">
                        <span className="block h-full rounded-full bg-[#ee8a5c]" style={{ width: `${Math.round(s.familiarity * 100)}%` }} />
                      </span>{" "}
                      <span className="text-xs text-[var(--muted)]">{familiarityWord(s.familiarity)}</span>
                    </td>
                    <td className={`${td} tabular`}>{s.conversations}</td>
                    <td className={`${td} tabular`}>{s.presence}</td>
                    <td className={td}>{s.appraisals ? `${valenceWord(s.valence)} (${formatDecimal(s.valence)})` : <span className="text-[var(--muted)]">not appraised</span>}</td>
                    <td className={`${td} tabular text-[var(--muted)]`}>{s.last_interaction_at ? formatDayTime(s.last_interaction_at) : "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm text-[var(--muted)]">No records yet: this resident has not met anyone since the run began.</p>
        )}
      </Card>
    </>
  );
}

// ------------------------------------------------------------------ behavior
const HOUR_KEYS: [string, string, string][] = [
  ["action", "actions", "#4a82dd"],
  ["replan", "replans", "#625f75"],
  ["non_continue_reactions", "reactions", "#ee8a5c"],
  ["conversation", "conversations", "#e2629b"],
  ["reflection", "reflections", "#9b6fd6"],
];

export function Behavior({ agents, refresh }: { agents: Json[]; refresh: number }) {
  const { data, error, loading } = useResearch<Json>("behavior", [refresh]);
  const name = nameOf(agents);
  const color = colorOf(agents);
  if (error) return <Missing what="behavior measures" error={error} />;
  if (!data) return <p className="text-[var(--muted)]">{loading ? "Counting actions, plans and reactions…" : ""}</p>;
  const p = data.pooled ?? {};
  const hours: Json[] = data.by_hour ?? [];
  const max = Math.max(1, ...hours.map((h) => HOUR_KEYS.reduce((s, [k]) => s + Number(h[k] ?? 0), 0)));
  const failures = (p.action_failures ?? 0) + (p.constraint_refusals ?? 0) + (p.plan_failures ?? 0);
  return (
    <>
      <Card title="Behavior" hint={`from the run's own plans, events and frames, ${data.span?.start ? formatDayTime(data.span.start) : ""} to ${data.span?.end ? formatDayTime(data.span.end) : "now"}`}>
        <div className="mb-3 flex flex-wrap gap-2">
          <Stat value={percent(p.scheduled_share)} label="actions from own schedule" color="#4a82dd" />
          <Stat value={percent(p.plan_adherence)} label="hour blocks followed" color="#2a9d96" />
          <Stat value={percent(p.idle_share)} label="time idle" />
          <Stat value={p.replans_per_agent ?? "–"} label="replans per resident" />
          <Stat value={percent(p.reaction_rate)} label="reactions that changed course" color="#ee8a5c" />
          <Stat value={p.conversations_per_agent ?? "–"} label="conversations per resident" color="#e2629b" />
          <Stat value={failures} label="failures and refusals" color={failures ? "#b3261e" : undefined} />
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr>
                <th className={th}>Resident</th>
                <th className={`${th} tabular`}>Actions</th>
                <th className={`${th} tabular`}>Scheduled</th>
                <th className={`${th} tabular`}>Blocks followed</th>
                <th className={`${th} tabular`}>Replans</th>
                <th className={`${th} tabular`}>Reacted</th>
                <th className={`${th} tabular`}>Idle</th>
                <th className={`${th} tabular`}>Talks</th>
                <th className={`${th} tabular`}>Failures</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(data.agents as Record<string, Json>).map(([aid, a]) => (
                <tr key={aid} className="border-t border-[var(--line)]">
                  <td className={`${td} font-semibold`}>
                    <span className="mr-1.5 inline-block size-2.5 rounded-full align-middle" style={{ background: color(aid) }} aria-hidden="true" />
                    {name(aid)}
                  </td>
                  <td className={`${td} tabular`}>{a.actions}</td>
                  <td className={`${td} tabular`}>{percent(a.scheduled_share)}</td>
                  <td className={`${td} tabular`}>
                    {a.blocks_followed}/{a.hour_blocks}
                  </td>
                  <td className={`${td} tabular`}>{a.replans}</td>
                  <td className={`${td} tabular`}>
                    {a.non_continue_reactions}/{a.reaction_decisions}
                  </td>
                  <td className={`${td} tabular`}>{percent(a.idle_share)}</td>
                  <td className={`${td} tabular`}>{a.conversations}</td>
                  <td className={`${td} tabular`}>{a.action_failures + a.constraint_refusals + a.plan_failures}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <Card title="Each Hour of the Day">
        {hours.length ? (
          <>
            <div className="flex h-44 items-end gap-1 overflow-x-auto pb-1">
              {hours.map((h) => (
                <div key={h.hour} className="flex min-w-6 flex-1 flex-col-reverse items-stretch" title={`${h.hour}: ${HOUR_KEYS.map(([k, l]) => `${h[k] ?? 0} ${l}`).join(", ")}`}>
                  {HOUR_KEYS.map(([k, l, c]) => (
                    <div key={k} style={{ height: `${(Number(h[k] ?? 0) / max) * 150}px`, background: c }} className="w-full first:rounded-b-md last:rounded-t-md" aria-label={`${h[k] ?? 0} ${l}`} />
                  ))}
                  <span className="mt-1 text-center text-[10px] tabular text-[var(--muted)]">{h.hour.slice(11, 13)}</span>
                </div>
              ))}
            </div>
            <div className="mt-2 flex flex-wrap gap-3 text-xs">
              {HOUR_KEYS.map(([k, l, c]) => (
                <span key={k} className="inline-flex items-center gap-1">
                  <span className="inline-block size-2.5 rounded-sm" style={{ background: c }} aria-hidden="true" /> {l}
                </span>
              ))}
            </div>
          </>
        ) : (
          <p className="text-sm text-[var(--muted)]">Nothing recorded yet.</p>
        )}
        <p className="mt-2 text-xs text-[var(--muted)]">Scheduled: the action's task came from the resident's own plan rather than a reaction, wait, conversation or replan. Blocks followed: hour blocks in which at least one scheduled action started.</p>
      </Card>
    </>
  );
}

// ------------------------------------------------------------------ beliefs
export function Beliefs({ agents, refresh }: { agents: Json[]; refresh: number }) {
  const { data, error, loading } = useResearch<Json>("beliefs", [refresh]);
  const name = nameOf(agents);
  const color = colorOf(agents);
  if (error) return <Missing what="the belief ledger" error={error} />;
  if (!data) return <p className="text-[var(--muted)]">{loading ? "Reading what each resident has been told…" : ""}</p>;
  const topics = Object.keys(data.beliefs ?? {});
  if (!topics.length) return <p className="text-[var(--muted)]">This scenario seeds no events to follow.</p>;
  const ids = agents.map((a) => a.id as string);
  return (
    <>
      <p className="mb-3 text-sm text-[var(--muted)]">{data.note}</p>
      {topics.map((t) => {
        const per = data.beliefs[t] as Record<string, Json>;
        const s = data.summary.topics[t];
        const so: Record<string, Json> = {};
        for (const r of (data.second_order?.[t] ?? []) as Json[]) so[`${r.agent_id}|${r.about}`] = r;
        const probes = ((data.tom_probes ?? []) as Json[]).filter((r) => r.event === t);
        return (
          <Card key={t} title={t.replace(/_/g, " ")}>
            <div className="mb-3 flex flex-wrap gap-2">
              <Stat value={`${s.holders.length}/${ids.length}`} label="have a received memory" color="#4a82dd" />
              <Stat value={percent(s.knowledge_coverage)} label="know who else knows" color="#2a9d96" />
              <Stat value={s.grounded_unsupported} label="grounds about someone with no memory" />
              <Stat value={s.with_conflicting_details.length} label="hold differing details" color={s.with_conflicting_details.length ? "#d99a26" : undefined} />
            </div>
            <div className="grid gap-4 xl:grid-cols-2">
              <div>
                <h3 className="mb-1 font-display font-bold">Who has a received memory</h3>
                <table className="w-full text-sm">
                  <thead>
                    <tr>
                      <th className={th}>Resident</th>
                      <th className={th}>Knows</th>
                      <th className={th}>First</th>
                      <th className={th}>From</th>
                      <th className={th}>Differing</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ids.map((a) => (
                      <tr key={a} className="border-t border-[var(--line)]">
                        <td className={`${td} font-semibold`}>
                          <span className="mr-1.5 inline-block size-2.5 rounded-full align-middle" style={{ background: color(a) }} aria-hidden="true" />
                          {name(a)}
                        </td>
                        <td className={td}>{per[a]?.holds ? <Pill color="#58b368">yes</Pill> : <span className="text-[var(--muted)]">no</span>}</td>
                        <td className={`${td} tabular text-[var(--muted)]`}>{per[a]?.first_exposure_at ? formatDayTime(per[a].first_exposure_at) : "–"}</td>
                        <td className={td}>{(per[a]?.sources ?? []).map(name).join(", ") || (per[a]?.holds ? "seeded" : "–")}</td>
                        <td className={td}>{(per[a]?.conflicting_details ?? []).join(", ") || "–"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div>
                <h3 className="mb-1 font-display font-bold">Who has grounds to think who knows</h3>
                <p className="mb-1 text-xs text-[var(--muted)]">Rows: the resident; columns: who they could believe knows. “told” they said it to them, “heard” they heard it from them; “?” means the other knows but nothing this resident experienced shows it.</p>
                <table className="w-full text-sm">
                  <thead>
                    <tr>
                      <th className={th}></th>
                      {ids.map((b) => (
                        <th key={b} className={th}>
                          {name(b).split(" ")[0]}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {ids.map((a) => (
                      <tr key={a} className="border-t border-[var(--line)]">
                        <td className={`${td} font-semibold`}>{name(a).split(" ")[0]}</td>
                        {ids.map((b) => {
                          if (a === b) return <td key={b} className={`${td} text-[var(--muted)]`}>·</td>;
                          const r = so[`${a}|${b}`];
                          return (
                            <td key={b} className={td} title={r?.status ?? ""}>
                              {r?.basis ? <Pill color={r.basis === "told" ? "#4a82dd" : r.basis === "heard" ? "#ee8a5c" : "#9b6fd6"}>{r.basis}</Pill> : r?.other_holds ? <span className="text-[var(--muted)]">?</span> : ""}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            {probes.length ? (
              <>
                <h3 className="mb-1 mt-4 font-display font-bold">Theory-of-Mind probe</h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr>
                        <th className={th}>Asked</th>
                        <th className={th}>About</th>
                        <th className={th}>Says they know</th>
                        <th className={th}>Grounds</th>
                        <th className={th}>Really knows</th>
                        <th className={th}>Label</th>
                        <th className={th}>Answer</th>
                      </tr>
                    </thead>
                    <tbody>
                      {probes.map((r, i) => (
                        <tr key={i} className="border-t border-[var(--line)]">
                          <td className={`${td} font-semibold`}>{name(r.agent_id)}</td>
                          <td className={td}>{name(r.about)}</td>
                          <td className={td}>{r.claims_other_knows == null ? "?" : r.claims_other_knows ? "yes" : "no"}</td>
                          <td className={td}>{r.grounds ?? "–"}</td>
                          <td className={td}>{r.other_holds ? "yes" : "no"}</td>
                          <td className={td}>
                            <Pill color={r.label.startsWith("grounded") || r.label === "correct_negative" ? "#58b368" : r.label === "over_attribution" ? "#b3261e" : "#d99a26"}>{TOM_LABELS[r.label] ?? r.label}</Pill>
                          </td>
                          <td className={`${td} text-[var(--muted)]`}>{String(r.answer).slice(0, 140)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            ) : (
              <p className="mt-3 text-xs text-[var(--muted)]">No Theory-of-Mind probe recorded for this run. An experiment with the <span translate="no">tom</span> metric adds one.</p>
            )}
          </Card>
        );
      })}
    </>
  );
}
