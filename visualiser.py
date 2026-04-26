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

CAT_LABELS = {
    "user"      : "User Process",
    "sys_proc"  : "System Process",
    "disk_load" : "Disk Load",
    "disk_save" : "Disk Save",
    "idle"      : "Idle",
    "syscall"   : "Syscall",
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


def _fmt_list(lst):
    """Format a number list without trailing .0 for whole numbers."""
    return ", ".join(str(int(x)) if x == int(x) else str(x) for x in lst)


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
    TICK_STEP    = max(1, int(t_max / 30))   # ~30 ticks max

    # Fixed large coordinate space — viewBox scales it to fill the container.
    # min-width:900px so scroll only appears at very high zoom levels.
    svg_w    = 2000
    usable_w = svg_w - MARGIN_LEFT - 40
    svg_h    = MARGIN_TOP + len(lanes) * (LANE_H + LANE_GAP) + 60

    def tx(t):
        return MARGIN_LEFT + (t / t_max) * usable_w

    def lane_y(label):
        idx = lane_index.get(label, 0)
        return MARGIN_TOP + idx * (LANE_H + LANE_GAP)

    svg_parts = []
    # width:100% always fills the wrapper; min-width:900px triggers scroll only at extreme zoom.
    # preserveAspectRatio="none" stretches bars horizontally to fill available width.
    svg_parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {svg_w} {svg_h}" '
        f'preserveAspectRatio="none" '
        f'style="width:100%; min-width:900px; height:{svg_h}px; display:block; '
        f'font-family:\'Courier New\',monospace; background:#1a1a2e;">'
    )

    # Which lanes have at least one bar (for idle indicator)
    active_lanes = {
        (f"CPU{cpu_id}" if isinstance(cpu_id, int) else cpu_id)
        for (_, _, cpu_id, _, _) in gantt
    }

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
        if label not in active_lanes:
            cx = MARGIN_LEFT + usable_w // 2
            cy = y + LANE_H // 2 + 4
            svg_parts.append(
                f'<text x="{cx}" y="{cy}" text-anchor="middle" '
                f'fill="#2e3a50" font-size="11" font-style="italic">idle</text>'
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
        dur = f"{end - start:.2f}"
        cat_label = _escape(CAT_LABELS.get(cat, cat))

        svg_parts.append(
            f'<rect class="gantt-bar" x="{x1:.1f}" y="{y}" width="{w:.1f}" height="{BAR_H}" '
            f'fill="{col}" rx="3" opacity="0.92" '
            f'data-pid="{pid_label}" data-cat="{cat_label}" '
            f'data-start="{start:.2f}" data-end="{end:.2f}" data-dur="{dur}"/>'
        )
        if w > 24:
            svg_parts.append(
                f'<text x="{(x1+x2)/2:.1f}" y="{y + BAR_H//2 + 5}" '
                f'text-anchor="middle" fill="{tcol}" font-size="10" '
                f'font-weight="bold" style="pointer-events:none">{pid_label}</text>'
            )

    # Legend — only categories present in this simulation
    cats_used = {cat for (_, _, _, _, cat) in gantt}
    legend_x = MARGIN_LEFT
    legend_y = svg_h - 24
    for cat, col in COLOURS.items():
        if cat not in cats_used:
            continue
        lbl = CAT_LABELS.get(cat, cat)
        svg_parts.append(
            f'<rect x="{legend_x}" y="{legend_y - 10}" width="14" height="12" fill="{col}" rx="2"/>'
        )
        svg_parts.append(
            f'<text x="{legend_x + 18}" y="{legend_y}" fill="#8899bb" font-size="11">{lbl}</text>'
        )
        legend_x += 130

    svg_parts.append('</svg>')
    gantt_svg = "\n".join(svg_parts)

    # --- Event log table ---
    table_rows = []
    for entry in log:
        cpu = f"CPU{entry.cpu_id}" if entry.cpu_id is not None else "SYS"
        pid = f"P{entry.pid}" if entry.pid is not None else "SYS"
        dur = f"{entry.duration:.2f}" if entry.duration is not None else "-"
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

    # --- Summary statistics ---
    finished_count = sum(1 for p in processes if p.state == "FINISHED")
    ctx_switches   = sum(1 for e in log if e.action == "SLICE_EXPIRE")
    evictions      = sum(1 for e in log if "EVICT" in e.action)
    disk_loads     = sum(1 for e in log if e.action == "LOADED_TO_RAM")

    # --- Process summary table ---
    proc_rows = []
    for p in processes:
        state_col = "#70C8FF" if p.state == "FINISHED" else "#FF6B35"
        rel = int(p.release_time) if p.release_time == int(p.release_time) else p.release_time
        proc_rows.append(
            f'<tr>'
            f'<td>P{p.pid}</td>'
            f'<td>{rel}</td>'
            f'<td>{p.memory} MB</td>'
            f'<td>{_fmt_list(p.bursts)}</td>'
            f'<td>{_fmt_list(p.syscall_times) if p.syscall_times else "-"}</td>'
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
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Inter:wght@300;400;600;800&display=swap');
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  :root {{
    --bg:     #0d0d1a;
    --bg2:    #12122a;
    --bg3:    #1a1a3a;
    --accent: #70C8FF;
    --orange: #FF6B35;
    --text:   #dde8f8;
    --muted:  #6a82a8;
    --border: #2a2a4a;
    --mono:   'JetBrains Mono', 'Courier New', monospace;
  }}
  html, body {{ background: var(--bg); color: var(--text); font-family: 'Inter', sans-serif; }}
  body {{ padding: 32px; }}

  h1 {{ font-size: 2rem; font-weight: 800; letter-spacing: .08em;
        background: linear-gradient(90deg, var(--accent), var(--orange));
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        margin-bottom: 4px; }}
  .subtitle {{ color: var(--muted); font-family: var(--mono);
               font-size: .82rem; margin-bottom: 32px; letter-spacing: .03em; }}

  .params-grid {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 12px; margin-bottom: 40px;
  }}
  .param-card {{
    background: var(--bg2); border: 1px solid var(--border);
    border-radius: 8px; padding: 14px 18px;
  }}
  .param-card .label {{ font-size: .7rem; color: var(--muted); text-transform: uppercase;
                        letter-spacing: .1em; font-family: var(--mono); }}
  .param-card .value {{ font-size: 1.4rem; font-weight: 600; color: var(--accent); margin-top: 4px; }}

  h2 {{ font-size: 1.1rem; font-weight: 600; letter-spacing: .06em;
        color: var(--accent); text-transform: uppercase;
        border-left: 3px solid var(--orange); padding-left: 12px;
        margin: 36px 0 16px; }}

  .gantt-wrapper {{
    background: var(--bg2); border: 1px solid var(--border);
    border-radius: 10px; overflow-x: auto; padding: 16px;
  }}

  table {{ width: 100%; border-collapse: collapse; font-size: .84rem;
           font-family: var(--mono); font-weight: 400; }}
  thead tr {{ background: var(--bg3); }}
  th {{ padding: 10px 14px; text-align: left; color: var(--muted);
        text-transform: uppercase; font-size: .68rem; letter-spacing: .12em;
        font-weight: 700; border-bottom: 1px solid var(--border); }}
  td {{ padding: 9px 14px; border-bottom: 1px solid #1e1e36; color: var(--text);
        font-weight: 400; line-height: 1.5; }}
  tr:hover td {{ background: #1e1e3a; }}
  .table-wrapper {{ max-height: 480px; overflow-y: auto;
                    border: 1px solid var(--border); border-radius: 8px; }}

  .stats-grid {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 10px; margin-bottom: 8px;
  }}
  .stat-card {{
    background: var(--bg2); border: 1px solid var(--border);
    border-radius: 8px; padding: 12px 16px;
  }}
  .stat-card .label {{ font-size: .68rem; color: var(--muted); text-transform: uppercase;
                       letter-spacing: .1em; font-family: var(--mono); }}
  .stat-card .value {{ font-size: 1.3rem; font-weight: 600; color: var(--text); margin-top: 3px; }}

  footer {{ margin-top: 48px; padding: 20px 0; border-top: 1px solid var(--border);
            text-align: center; color: var(--muted); font-size: .75rem;
            font-family: var(--mono); letter-spacing: .04em; }}

  /* Gantt bar hover */
  .gantt-bar {{ cursor: default; transition: opacity .12s, filter .12s; }}
  .gantt-bar:hover {{ opacity: 1 !important; filter: brightness(1.18); }}

  /* Tooltip */
  #gantt-tip {{
    position: fixed; display: none; pointer-events: none; z-index: 200;
    background: #161630; border: 1px solid #3a3a6a;
    border-radius: 8px; padding: 10px 14px;
    font-family: var(--mono); font-size: .78rem; color: var(--text);
    box-shadow: 0 6px 20px rgba(0,0,0,.6);
    min-width: 170px; line-height: 1.7;
  }}
  #gantt-tip .tip-title {{ font-weight: 700; font-size: .82rem;
                           color: var(--accent); margin-bottom: 4px; }}
  #gantt-tip .tip-row   {{ color: var(--muted); }}
  #gantt-tip .tip-row span {{ color: var(--text); }}
</style>
</head>
<body>
<div id="gantt-tip"></div>

<h1>Scheduler Simulation</h1>
<p class="subtitle">Preemptive Round-Robin &nbsp;|&nbsp; Virtual Memory (LRU) &nbsp;|&nbsp; Periodic System Process</p>

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

<h2>Simulation Summary</h2>
<div class="stats-grid">
  <div class="stat-card"><div class="label">Total Time</div><div class="value">{t_max:.2f}</div></div>
  <div class="stat-card"><div class="label">Processes Finished</div><div class="value">{finished_count} / {len(processes)}</div></div>
  <div class="stat-card"><div class="label">Context Switches</div><div class="value">{ctx_switches}</div></div>
  <div class="stat-card"><div class="label">RAM Evictions</div><div class="value">{evictions}</div></div>
  <div class="stat-card"><div class="label">Disk Loads</div><div class="value">{disk_loads}</div></div>
</div>

<h2>Event Log</h2>
<div class="table-wrapper">
<table>
  <thead><tr><th>Time (units)</th><th>CPU (core)</th><th>PID</th><th>Action (event type)</th><th>Duration (units)</th><th>Detail</th></tr></thead>
  <tbody>{table_html}</tbody>
</table>
</div>

<footer>Round-Robin Scheduler Simulation &nbsp;|&nbsp; Software Quality</footer>

<script>
(function() {{
  var tip = document.getElementById('gantt-tip');
  document.querySelectorAll('.gantt-bar').forEach(function(bar) {{
    bar.addEventListener('mousemove', function(e) {{
      tip.innerHTML =
        '<div class="tip-title">' + bar.dataset.pid + ' &mdash; ' + bar.dataset.cat + '</div>' +
        '<div class="tip-row">Start &nbsp;<span>' + bar.dataset.start + '</span></div>' +
        '<div class="tip-row">End &nbsp;&nbsp;&nbsp;<span>' + bar.dataset.end + '</span></div>' +
        '<div class="tip-row">Duration <span>' + bar.dataset.dur + '</span></div>';
      var x = e.clientX + 16, y = e.clientY - 12;
      if (x + 190 > window.innerWidth) x = e.clientX - 200;
      tip.style.left = x + 'px';
      tip.style.top  = y + 'px';
      tip.style.display = 'block';
    }});
    bar.addEventListener('mouseleave', function() {{
      tip.style.display = 'none';
    }});
  }});
}})();
</script>
</body>
</html>"""

    with open(output_path, 'w') as fh:
        fh.write(html)