"""
Graphical output: generates a self-contained HTML file with
  1. A Gantt chart (SVG-based, no external libs)
  2. An event log table
"""

# Colour palette per category
COLOURS = {
    "user"      : "#4A9EFF",
    "sys_proc"  : "#FF6B35",
    "disk_load" : "#A8D8A8",
    "disk_save" : "#FFD166",
    "idle"      : "#2A2A3A",
    "syscall"   : "#C678DD",
}

LABEL_COLOUR = {
    "user"      : "#ffffff",
    "sys_proc"  : "#ffffff",
    "disk_load" : "#1a1a2e",
    "disk_save" : "#1a1a2e",
    "idle"      : "#888888",
    "syscall"   : "#ffffff",
}


def _escape(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def generate_html(log, gantt, params, processes, output_path):
    """Write a self-contained HTML visualisation to output_path."""

    if not gantt:
        t_max = 1.0
    else:
        t_max = max(end for (_, end, *_) in gantt)

    # Lanes: one per CPU + one for DISK
    num_cpus = params["num_processors"]
    lanes = [f"CPU{i}" for i in range(num_cpus)] + ["DISK"]
    lane_index = {label: i for i, label in enumerate(lanes)}

    # SVG dimensions
    MARGIN_LEFT  = 80
    MARGIN_TOP   = 60
    LANE_H       = 44
    LANE_GAP     = 8
    BAR_H        = 30
    BAR_OFFSET_Y = (LANE_H - BAR_H) // 2
    TICK_STEP    = max(1, int(t_max / 20))  # ~20 ticks max

    svg_w = 1200
    usable_w = svg_w - MARGIN_LEFT - 20
    svg_h = MARGIN_TOP + len(lanes) * (LANE_H + LANE_GAP) + 60

    def tx(t):
        return MARGIN_LEFT + (t / t_max) * usable_w

    def lane_y(label):
        idx = lane_index.get(label, 0)
        return MARGIN_TOP + idx * (LANE_H + LANE_GAP)

    svg_parts = []
    svg_parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{svg_w}" height="{svg_h}" '
        f'style="font-family:\'Courier New\',monospace;background:#1a1a2e;">'
    )

    # Background lanes
    for label in lanes:
        y = lane_y(label)
        svg_parts.append(
            f'<rect x="{MARGIN_LEFT}" y="{y}" '
            f'width="{usable_w}" height="{LANE_H}" '
            f'fill="#12122a" rx="4"/>'
        )
        svg_parts.append(
            f'<text x="{MARGIN_LEFT - 6}" y="{y + LANE_H//2 + 5}" '
            f'text-anchor="end" fill="#8899bb" font-size="12">{label}</text>'
        )

    # Time axis ticks
    t = 0
    while t <= t_max:
        x = tx(t)
        svg_parts.append(
            f'<line x1="{x:.1f}" y1="{MARGIN_TOP - 8}" '
            f'x2="{x:.1f}" y2="{svg_h - 30}" '
            f'stroke="#2a2a4a" stroke-width="1"/>'
        )
        svg_parts.append(
            f'<text x="{x:.1f}" y="{MARGIN_TOP - 12}" '
            f'text-anchor="middle" fill="#556688" font-size="10">{t:.0f}</text>'
        )
        t += TICK_STEP

    # Gantt bars
    for (start, end, cpu_id, pid, cat) in gantt:
        label = f"CPU{cpu_id}" if isinstance(cpu_id, int) else cpu_id
        y   = lane_y(label) + BAR_OFFSET_Y
        x1  = tx(start)
        x2  = tx(end)
        w   = max(x2 - x1, 1)
        col = COLOURS.get(cat, "#888")
        tcol = LABEL_COLOUR.get(cat, "#fff")
        pid_label = f"P{pid}" if pid != "SYS" else "SYS"
        dur = f"{end - start:.1f}"
        title_txt = _escape(f"{pid_label} [{cat}] {start:.2f}–{end:.2f} (dur={dur})")

        svg_parts.append(
            f'<rect x="{x1:.1f}" y="{y}" width="{w:.1f}" height="{BAR_H}" '
            f'fill="{col}" rx="3" opacity="0.92">'
            f'<title>{title_txt}</title></rect>'
        )
        if w > 24:
            svg_parts.append(
                f'<text x="{(x1+x2)/2:.1f}" y="{y + BAR_H//2 + 5}" '
                f'text-anchor="middle" fill="{tcol}" font-size="10" '
                f'font-weight="bold">{pid_label}</text>'
            )

    # Legend
    legend_x = MARGIN_LEFT
    legend_y = svg_h - 24
    for cat, col in COLOURS.items():
        svg_parts.append(
            f'<rect x="{legend_x}" y="{legend_y - 10}" width="14" height="12" fill="{col}" rx="2"/>'
        )
        svg_parts.append(
            f'<text x="{legend_x + 18}" y="{legend_y}" fill="#8899bb" font-size="11">{cat}</text>'
        )
        legend_x += 110

    svg_parts.append('</svg>')
    gantt_svg = "\n".join(svg_parts)

    # --- Event log table ---
    table_rows = []
    for entry in log:
        cpu = f"CPU{entry.cpu_id}" if entry.cpu_id is not None else "SYS"
        pid = f"P{entry.pid}" if entry.pid is not None else "SYS"
        dur = f"{entry.duration:.2f}" if entry.duration is not None else "—"
        table_rows.append(
            f'<tr>'
            f'<td>{entry.time:.3f}</td>'
            f'<td>{_escape(cpu)}</td>'
            f'<td>{_escape(pid)}</td>'
            f'<td>{_escape(entry.action)}</td>'
            f'<td>{_escape(dur)}</td>'
            f'<td>{_escape(entry.detail)}</td>'
            f'</tr>'
        )
    table_html = "\n".join(table_rows)

    # --- Process summary table ---
    proc_rows = []
    for p in processes:
        state_col = "#4A9EFF" if p.state == "FINISHED" else "#FF6B35"
        proc_rows.append(
            f'<tr>'
            f'<td>P{p.pid}</td>'
            f'<td>{p.release_time}</td>'
            f'<td>{p.memory} MB</td>'
            f'<td>{p.bursts}</td>'
            f'<td>{p.syscall_times}</td>'
            f'<td style="color:{state_col}">{p.state}</td>'
            f'</tr>'
        )
    proc_html = "\n".join(proc_rows)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<title>Scheduler Simulation</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Exo+2:wght@300;600;800&display=swap');
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  :root {{
    --bg:     #0d0d1a;
    --bg2:    #12122a;
    --bg3:    #1a1a3a;
    --accent: #4A9EFF;
    --orange: #FF6B35;
    --text:   #c8d8f0;
    --muted:  #556688;
    --border: #2a2a4a;
  }}
  html, body {{ background: var(--bg); color: var(--text); font-family: 'Exo 2', sans-serif; }}
  body {{ padding: 32px; }}

  h1 {{ font-size: 2rem; font-weight: 800; letter-spacing: .08em;
        background: linear-gradient(90deg, var(--accent), var(--orange));
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        margin-bottom: 4px; }}
  .subtitle {{ color: var(--muted); font-family: 'Share Tech Mono', monospace;
               font-size: .85rem; margin-bottom: 32px; letter-spacing: .05em; }}

  .params-grid {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 12px; margin-bottom: 40px;
  }}
  .param-card {{
    background: var(--bg2); border: 1px solid var(--border);
    border-radius: 8px; padding: 14px 18px;
  }}
  .param-card .label {{ font-size: .7rem; color: var(--muted); text-transform: uppercase;
                        letter-spacing: .1em; font-family: 'Share Tech Mono', monospace; }}
  .param-card .value {{ font-size: 1.4rem; font-weight: 600; color: var(--accent); margin-top: 4px; }}

  h2 {{ font-size: 1.1rem; font-weight: 600; letter-spacing: .06em;
        color: var(--accent); text-transform: uppercase;
        border-left: 3px solid var(--orange); padding-left: 12px;
        margin: 36px 0 16px; }}

  .gantt-wrapper {{
    background: var(--bg2); border: 1px solid var(--border);
    border-radius: 10px; overflow-x: auto; padding: 16px;
  }}

  table {{ width: 100%; border-collapse: collapse; font-size: .82rem;
           font-family: 'Share Tech Mono', monospace; }}
  thead tr {{ background: var(--bg3); }}
  th {{ padding: 10px 14px; text-align: left; color: var(--muted);
        text-transform: uppercase; font-size: .7rem; letter-spacing: .1em;
        border-bottom: 1px solid var(--border); }}
  td {{ padding: 8px 14px; border-bottom: 1px solid #1e1e36; color: var(--text); }}
  tr:hover td {{ background: #1e1e3a; }}
  .table-wrapper {{ max-height: 480px; overflow-y: auto;
                    border: 1px solid var(--border); border-radius: 8px; }}

  footer {{ margin-top: 48px; text-align: center; color: var(--muted);
            font-size: .75rem; font-family: 'Share Tech Mono', monospace; }}
</style>
</head>
<body>

<h1>Scheduler Simulation</h1>
<p class="subtitle">Preemptive Round-Robin · Virtual Memory (LRU) · Periodic System Process</p>

<div class="params-grid">
  <div class="param-card"><div class="label">Processors</div><div class="value">{params['num_processors']}</div></div>
  <div class="param-card"><div class="label">RAM</div><div class="value">{params['ram_size']} MB</div></div>
  <div class="param-card"><div class="label">Time Slice</div><div class="value">{params['time_slice']}</div></div>
  <div class="param-card"><div class="label">SysProc Period</div><div class="value">{params['sys_proc_period']}</div></div>
  <div class="param-card"><div class="label">SysProc Duration</div><div class="value">{params['sys_proc_duration']}</div></div>
  <div class="param-card"><div class="label">Disk Rate</div><div class="value">{params['disk_transfer_rate']} MB/t</div></div>
</div>

<h2>Processes</h2>
<div class="table-wrapper">
<table>
  <thead><tr><th>PID</th><th>Release</th><th>Memory</th><th>Bursts</th><th>Syscalls</th><th>Final State</th></tr></thead>
  <tbody>{proc_html}</tbody>
</table>
</div>

<h2>Gantt Chart</h2>
<div class="gantt-wrapper">
{gantt_svg}
</div>

<h2>Event Log</h2>
<div class="table-wrapper">
<table>
  <thead><tr><th>Time</th><th>CPU</th><th>PID</th><th>Action</th><th>Duration</th><th>Detail</th></tr></thead>
  <tbody>{table_html}</tbody>
</table>
</div>

<footer>Generated by RR-Scheduler Simulation Engine</footer>
</body>
</html>"""

    with open(output_path, 'w') as fh:
        fh.write(html)