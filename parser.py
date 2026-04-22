"""
Input file parser for the Round-Robin scheduler simulation.

File format
-----------
# Lines starting with # are comments and are ignored.
# Blank lines are ignored.

[params]
num_processors    = 2
ram_size          = 256        # MB
time_slice        = 4
sys_proc_period   = 20
sys_proc_duration = 2          # default duration when no syscalls are pending
disk_transfer_rate = 50        # MB per time unit

[processes]
# release_time  memory  burst0 syscall0 burst1 syscall1 burst2 ...
# The sequence alternates: burst syscall burst syscall ... burst
# (always starts and ends with a burst)
0   64   5 2 3 4 9 4 6
5   32   8 1 4
10  128  2 3 7 2 5

The numbers after memory are: b0 s0 b1 s1 b2 ... bN
where N = number of bursts - 1.
"""

import re


def _strip_comment(line):
    idx = line.find('#')
    if idx >= 0:
        line = line[:idx]
    return line.strip()


def parse_input_file(path):
    """
    Parse the simulation input file.
    Returns (params dict, list of Process objects).
    """
    # Import here to avoid circular dependency at module level
    from simulator import Process

    with open(path, 'r') as fh:
        lines = fh.readlines()

    section = None
    raw_params = {}
    process_lines = []

    for raw in lines:
        line = _strip_comment(raw)
        if not line:
            continue
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1].strip().lower()
            continue
        if section == 'params':
            # key = value
            if '=' in line:
                key, _, val = line.partition('=')
                raw_params[key.strip()] = val.strip()
        elif section == 'processes':
            process_lines.append(line)

    # Convert params
    params = {
        "num_processors":    int(raw_params["num_processors"]),
        "ram_size":          int(raw_params["ram_size"]),
        "time_slice":        float(raw_params["time_slice"]),
        "sys_proc_period":   float(raw_params["sys_proc_period"]),
        "sys_proc_duration": float(raw_params.get("sys_proc_duration", "1")),
        "disk_transfer_rate": float(raw_params["disk_transfer_rate"]),
    }

    # Parse processes
    processes = []
    for pid, line in enumerate(process_lines):
        tokens = re.split(r'\s+', line)
        assert len(tokens) >= 3, f"Process line too short: {line!r}"
        release_time = float(tokens[0])
        memory       = int(tokens[1])
        sequence     = [float(x) for x in tokens[2:]]

        # sequence: b0 [s0 b1 [s1 b2 ...]]
        assert len(sequence) % 2 == 1, \
            f"Process {pid}: sequence must be odd length (bursts interleaved with syscalls). Got: {sequence}"

        bursts = sequence[0::2]       # indices 0, 2, 4, ...
        syscalls = sequence[1::2]     # indices 1, 3, 5, ...

        processes.append(Process(pid, release_time, memory, bursts, syscalls))

    return params, processes


def build_text_report(log, gantt, params, processes):
    """
    Build a human-readable text report of the simulation.
    Returns a string.
    """
    lines = []
    lines.append("=" * 72)
    lines.append("  ROUND-ROBIN SCHEDULER SIMULATION — EXECUTION LOG")
    lines.append("=" * 72)
    lines.append(f"  Processors      : {params['num_processors']}")
    lines.append(f"  RAM             : {params['ram_size']} MB")
    lines.append(f"  Time slice      : {params['time_slice']}")
    lines.append(f"  SysProc period  : {params['sys_proc_period']}")
    lines.append(f"  SysProc duration: {params['sys_proc_duration']}")
    lines.append(f"  Disk xfer rate  : {params['disk_transfer_rate']} MB/t")
    lines.append("")
    lines.append("  PROCESSES")
    lines.append("  " + "-" * 60)
    for p in processes:
        lines.append(f"  P{p.pid}: release={p.release_time}  mem={p.memory}MB  "
                     f"bursts={p.bursts}  syscalls={p.syscall_times}")
    lines.append("")
    lines.append("  EVENT LOG")
    lines.append("  " + "-" * 60)
    for entry in log:
        lines.append("  " + repr(entry))
    lines.append("")
    lines.append("  GANTT INTERVALS")
    lines.append("  " + "-" * 60)
    for (start, end, cpu_id, pid, cat) in sorted(gantt):
        cpu_label = f"CPU{cpu_id}" if isinstance(cpu_id, int) else cpu_id
        lines.append(f"  [{start:>8.2f} – {end:>8.2f}]  {cpu_label:<6}  P{pid:<4}  {cat}")
    lines.append("=" * 72)
    return "\n".join(lines)