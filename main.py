"""
main.py — Entry point for the Round-Robin Scheduler Simulation.

Usage:
    python main.py <input_file> [--out-text output.txt] [--out-html output.html]

If output paths are not specified, defaults to:
    simulation_log.txt
    simulation_gantt.html
"""

import sys
import os

# Allow running from any directory
sys.path.insert(0, os.path.dirname(__file__))

from parser import parse_input_file, build_text_report
from simulator import Simulator
from visualiser import generate_html


def main():
    args = sys.argv[1:]
    if not args:
        print("Usage: python main.py <input_file> [--out-text file.txt] [--out-html file.html]")
        sys.exit(1)

    input_file = args[0]
    out_text   = "simulation_log.txt"
    out_html   = "simulation_gantt.html"

    i = 1
    while i < len(args):
        if args[i] == "--out-text" and i + 1 < len(args):
            out_text = args[i + 1]; i += 2
        elif args[i] == "--out-html" and i + 1 < len(args):
            out_html = args[i + 1]; i += 2
        else:
            i += 1

    print(f"[*] Parsing input: {input_file}")
    params, processes = parse_input_file(input_file)

    print(f"[*] Running simulation ({params['num_processors']} CPUs, "
          f"{params['ram_size']}MB RAM, {len(processes)} processes)")
    sim = Simulator(params, processes)
    log, gantt = sim.run()

    print(f"[*] Writing text report -> {out_text}")
    report = build_text_report(log, gantt, params, processes)
    with open(out_text, 'w', encoding='utf-8') as fh:
        fh.write(report)

    print(f"[*] Writing HTML visualisation -> {out_html}")
    generate_html(log, gantt, params, processes, out_html)

    print(f"[*] Done.  {len(log)} log entries, {len(gantt)} Gantt intervals.")
    print()
    # Print brief summary to stdout
    finished = sum(1 for p in processes if p.state == "FINISHED")
    print(f"    Processes finished : {finished}/{len(processes)}")
    print(f"    Simulation end time: {sim.time:.2f}")


if __name__ == "__main__":
    main()