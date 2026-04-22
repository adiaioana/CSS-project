"""
Round-Robin Preemptive Scheduler Simulation
============================================
Single-file simulation engine. No external libraries used except
the standard library (heapq for the event queue, collections for deque).
"""

import heapq
from collections import deque


# ---------------------------------------------------------------------------
# Constants – process / event states
# ---------------------------------------------------------------------------
STATE_READY        = "READY"        # in RAM, waiting for CPU
STATE_RUNNING      = "RUNNING"      # on a CPU
STATE_WAITING_SYS  = "WAITING_SYS"  # waiting for system process
STATE_LOADING      = "LOADING"      # being loaded from disk
STATE_SAVING       = "SAVING"       # being saved to disk (evicted)
STATE_ON_DISK      = "ON_DISK"      # fully on disk
STATE_NOT_ARRIVED  = "NOT_ARRIVED"  # before release time
STATE_FINISHED     = "FINISHED"     # all execution intervals done

# Event types
EV_PROCESS_RELEASE   = "PROCESS_RELEASE"
EV_SLICE_EXPIRE      = "SLICE_EXPIRE"
EV_SYSCALL_BEGIN     = "SYSCALL_BEGIN"
EV_SYSCALL_END       = "SYSCALL_END"
EV_SYS_PROC_RELEASE  = "SYS_PROC_RELEASE"
EV_SYS_PROC_END      = "SYS_PROC_END"
EV_DISK_TRANSFER_END = "DISK_TRANSFER_END"
EV_PROCESS_FINISH    = "PROCESS_FINISH"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class Process:
    def __init__(self, pid, release_time, memory, bursts, syscall_times):
        """
        bursts       : list of CPU burst lengths  [b0, b1, b2, ...]
        syscall_times: list of system call durations between bursts [s0, s1, ...]
                       len(syscall_times) == len(bursts) - 1
        """
        self.pid          = pid
        self.release_time = release_time
        self.memory       = memory          # MB required
        self.bursts       = bursts          # original burst list
        self.syscall_times = syscall_times  # original syscall durations

        # Mutable execution state
        self.burst_index      = 0           # which burst we are in
        self.burst_remaining  = bursts[0]   # remaining time in current burst
        self.slice_remaining  = 0           # remaining time in current slice
        self.state            = STATE_NOT_ARRIVED
        self.last_processor   = None        # last CPU it ran on (for affinity)
        self.last_used_time   = -1          # for LRU eviction
        self.in_memory        = False       # True if currently in RAM

        # Pending syscall info (set when a syscall begins)
        self.pending_syscall_duration = 0

    def is_finished(self):
        return self.burst_index >= len(self.bursts)

    def __repr__(self):
        return f"P{self.pid}(state={self.state}, burst={self.burst_index}/{len(self.bursts)}, rem={self.burst_remaining})"


class Processor:
    def __init__(self, cpu_id):
        self.cpu_id   = cpu_id
        self.process  = None   # currently running Process or None

    def is_free(self):
        return self.process is None

    def __repr__(self):
        return f"CPU{self.cpu_id}({'idle' if self.is_free() else self.process.pid})"


class Event:
    """Comparable event for the min-heap."""
    # tie-break priority: lower number = higher priority at same time
    TYPE_PRIORITY = {
        EV_DISK_TRANSFER_END : 0,
        EV_SYS_PROC_END      : 1,
        EV_SYSCALL_BEGIN     : 2,
        EV_PROCESS_FINISH    : 3,
        EV_SLICE_EXPIRE      : 4,
        EV_SYS_PROC_RELEASE  : 5,
        EV_PROCESS_RELEASE   : 6,
        EV_SYSCALL_END       : 7,
    }

    _counter = 0  # insertion-order tiebreak

    def __init__(self, time, etype, payload=None):
        self.time    = time
        self.etype   = etype
        self.payload = payload          # dict with extra info
        Event._counter += 1
        self._seq = Event._counter

    def __lt__(self, other):
        if self.time != other.time:
            return self.time < other.time
        sp = Event.TYPE_PRIORITY.get(self.etype, 99)
        op = Event.TYPE_PRIORITY.get(other.etype, 99)
        if sp != op:
            return sp < op
        return self._seq < other._seq

    def __repr__(self):
        return f"Event({self.etype} @{self.time} payload={self.payload})"


# ---------------------------------------------------------------------------
# Log entry
# ---------------------------------------------------------------------------

class LogEntry:
    def __init__(self, time, cpu_id, pid, action, duration=None, detail=""):
        self.time     = time
        self.cpu_id   = cpu_id   # None for disk / system-level events
        self.pid      = pid      # None for system process own entries
        self.action   = action
        self.duration = duration
        self.detail   = detail

    def __repr__(self):
        cpu = f"CPU{self.cpu_id}" if self.cpu_id is not None else "SYS "
        pid = f"P{self.pid}" if self.pid is not None else "SYS"
        dur = f" dur={self.duration}" if self.duration is not None else ""
        return f"[t={self.time:>8.2f}] {cpu} {pid:>4} | {self.action:<22}{dur}  {self.detail}"


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------

class Simulator:
    def __init__(self, params, processes):
        """
        params keys:
            num_processors   int
            ram_size         int   (MB)
            time_slice       float
            sys_proc_period  float
            sys_proc_duration float  (execution time of one system process run)
            disk_transfer_rate float (MB / time_unit)
        processes: list of Process objects
        """
        self.params     = params
        self.processes  = processes
        self.processors = [Processor(i) for i in range(params["num_processors"])]

        # Event queue
        self._events = []

        # Ready queue (FIFO for round-robin)
        self.ready_queue = deque()

        # Processes waiting for RAM (can't be loaded yet because all in-RAM are running)
        self.waiting_for_ram = deque()  # pids of processes that need to be loaded

        # System process state
        self.sys_proc_pending    = False   # released but not yet running
        self.sys_proc_running    = False
        self.sys_proc_cpu        = None    # which CPU it occupies
        self.pending_syscalls    = []      # list of (process, syscall_duration)
        self.sys_proc_queue      = deque() # queued syscall batches

        # Virtual memory: list of pids currently in RAM (ordered for LRU)
        self.ram_used   = 0                # total MB in RAM
        self.in_ram     = []               # list of pids, LRU-ordered (oldest first)

        # Disk transfer state (serial)
        self.disk_busy  = False
        self.disk_queue = deque()          # (pid, direction, callback_event_type)

        # Log
        self.log = []

        # Current simulation time
        self.time = 0.0

        # For Gantt: list of (start, end, cpu_id, pid_or_label, category)
        # category: "user", "syscall", "disk_load", "disk_save", "sys_proc", "idle"
        self.gantt = []
        self._running_start = {}   # cpu_id -> (start_time, pid, category)

    # ------------------------------------------------------------------
    # Event helpers
    # ------------------------------------------------------------------

    def push(self, event):
        heapq.heappush(self._events, event)

    def pop(self):
        return heapq.heappop(self._events)

    def _log(self, cpu_id, pid, action, duration=None, detail=""):
        entry = LogEntry(self.time, cpu_id, pid, action, duration, detail)
        self.log.append(entry)

    def _gantt_start(self, cpu_id, pid, category):
        self._running_start[cpu_id] = (self.time, pid, category)

    def _gantt_end(self, cpu_id):
        if cpu_id in self._running_start:
            start, pid, cat = self._running_start.pop(cpu_id)
            if self.time > start:
                self.gantt.append((start, self.time, cpu_id, pid, cat))

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _schedule_initial_events(self):
        for p in self.processes:
            self.push(Event(p.release_time, EV_PROCESS_RELEASE, {"pid": p.pid}))
        # System process periodic releases
        t = self.params["sys_proc_period"]
        while t <= self._simulation_end():
            self.push(Event(t, EV_SYS_PROC_RELEASE, {}))
            t += self.params["sys_proc_period"]

    def _simulation_end(self):
        # Upper bound: sum of all bursts + all syscalls + all potential disk times + slack
        total = 0
        for p in self.processes:
            total += sum(p.bursts) + sum(p.syscall_times)
            total += (p.memory / self.params["disk_transfer_rate"]) * 2 * len(p.bursts)
        return p.release_time + total * 3 + 1000

    # ------------------------------------------------------------------
    # Virtual memory
    # ------------------------------------------------------------------

    def _ram_available(self, needed):
        return (self.ram_used + needed) <= self.params["ram_size"]

    def _release_ram(self, pid):
        """Free the RAM held by a finished process and update LRU list."""
        p = self._get_proc(pid)
        if p.in_memory:
            p.in_memory = False
            self.ram_used -= p.memory
            if pid in self.in_ram:
                self.in_ram.remove(pid)
            self._log(None, pid, "RAM_FREED",
                      detail=f"process finished, freed {p.memory}MB")

    def _lru_evict_for(self, pid):
        """
        Evict LRU processes (saving each to disk) until there is enough
        space for process pid. Returns list of evicted pids.
        Pumps the disk queue after queuing all saves.
        """
        p = self._get_proc(pid)
        evicted = []
        # Only evict processes that are not currently running or loading
        while not self._ram_available(p.memory):
            # Find LRU candidate: oldest in in_ram that is evictable
            candidate_pid = None
            for candidate in self.in_ram:
                if candidate == pid:
                    continue
                cp = self._get_proc(candidate)
                # Never evict running, loading, or already-saving processes
                if cp.state in (STATE_READY, STATE_FINISHED):
                    candidate_pid = candidate
                    break
            if candidate_pid is None:
                break
            cp = self._get_proc(candidate_pid)
            self.in_ram.remove(candidate_pid)
            self.ram_used -= cp.memory
            cp.in_memory = False
            # Remove from ready queue if present
            if cp.state == STATE_READY:
                # Mark saving; scheduler will skip stale entries
                cp.state = STATE_SAVING
            else:
                cp.state = STATE_SAVING
            evicted.append(candidate_pid)
            transfer_time = cp.memory / self.params["disk_transfer_rate"]
            self._log(None, candidate_pid, "EVICT→DISK", transfer_time,
                      f"LRU evict, size={cp.memory}MB")
            self.disk_queue.append((candidate_pid, "save", transfer_time))
        # Pump disk so saves (and subsequent loads) begin
        self._pump_disk()
        return evicted

    def _load_process(self, pid):
        """Enqueue a disk→RAM transfer for pid (after any pending saves finish)."""
        p = self._get_proc(pid)
        transfer_time = p.memory / self.params["disk_transfer_rate"]
        p.state = STATE_LOADING
        self._log(None, pid, "LOAD←DISK_QUEUED", transfer_time,
                  f"size={p.memory}MB, rate={self.params['disk_transfer_rate']}MB/t")
        self.disk_queue.append((pid, "load", transfer_time))
        self._pump_disk()

    def _pump_disk(self):
        """Start the next disk transfer if disk is free."""
        if self.disk_busy or not self.disk_queue:
            return
        pid, direction, duration = self.disk_queue.popleft()
        self.disk_busy = True
        self.push(Event(self.time + duration, EV_DISK_TRANSFER_END,
                        {"pid": pid, "direction": direction}))
        cat = "disk_load" if direction == "load" else "disk_save"
        if direction == "load":
            p = self._get_proc(pid)
            p.state = STATE_LOADING
            self._log(None, pid, "LOAD←DISK_START", duration,
                      f"size={p.memory}MB")
        self._gantt_start("DISK", pid, cat)

    def _try_admit_waiting(self):
        """
        After RAM may have freed up, try to admit the front of waiting_for_ram.
        We admit at most one process per call to avoid immediately evicting
        a process that was just admitted.
        """
        if not self.waiting_for_ram:
            return
        pid = self.waiting_for_ram[0]
        p = self._get_proc(pid)

        if self._ram_available(p.memory):
            self.waiting_for_ram.popleft()
            p.in_memory = True
            self.ram_used += p.memory
            self.in_ram.append(pid)
            self._enqueue_ready(p)
            self._schedule()
            return

        evicted = self._lru_evict_for(pid)
        if self._ram_available(p.memory):
            self.waiting_for_ram.popleft()
            p.in_memory = True
            self.ram_used += p.memory
            self.in_ram.append(pid)
            self._enqueue_ready(p)
            self._schedule()
        elif evicted:
            # Saves are queued; queue load to follow after saves complete
            self.waiting_for_ram.popleft()
            p.state = STATE_ON_DISK
            self.disk_queue.append(
                (pid, "load", p.memory / self.params["disk_transfer_rate"]))
            # _lru_evict_for already called _pump_disk
        # else: still can't fit — leave in waiting_for_ram, retry next event

    # ------------------------------------------------------------------
    # Scheduler
    # ------------------------------------------------------------------

    def _free_processors(self):
        return [cpu for cpu in self.processors if cpu.is_free()]

    def _get_proc(self, pid):
        return self.processes[pid]

    def _preferred_cpu(self, process):
        """Return the CPU the process last ran on if free, else any free CPU."""
        free = self._free_processors()
        if not free:
            return None
        if process.last_processor is not None:
            for cpu in free:
                if cpu.cpu_id == process.last_processor:
                    return cpu
        return free[0]

    def _dispatch(self, process, cpu):
        """Put process onto cpu and set up the appropriate expiry event."""
        assert cpu.is_free(), f"CPU{cpu.cpu_id} is not free"
        assert process.state == STATE_READY, f"P{process.pid} not READY (state={process.state})"

        process.state = STATE_RUNNING
        process.last_processor = cpu.cpu_id
        cpu.process = process

        ts = self.params["time_slice"]
        if process.burst_remaining <= ts:
            # This burst will finish within the slice
            run_time  = process.burst_remaining
            ev_type   = EV_PROCESS_FINISH
        else:
            run_time  = ts
            ev_type   = EV_SLICE_EXPIRE

        process.slice_remaining = run_time
        self._log(cpu.cpu_id, process.pid, "DISPATCH", run_time,
                  f"burst_rem={process.burst_remaining:.2f} slice={ts}")
        self._gantt_start(cpu.cpu_id, process.pid, "user")
        self.push(Event(self.time + run_time, ev_type,
                        {"pid": process.pid, "cpu_id": cpu.cpu_id}))

    def _preempt(self, cpu):
        """
        Preempt the process currently on cpu (slice expired or higher priority).
        Does NOT put it back in the ready queue here — caller decides.
        """
        process = cpu.process
        elapsed = self.time - (self.time - (self.params["time_slice"] - process.slice_remaining))
        # Update burst remaining based on actual elapsed (we trust event timing)
        cpu.process = None
        process.state = STATE_READY
        self._gantt_end(cpu.cpu_id)
        return process

    def _schedule(self):
        """
        Main scheduling loop: assign ready processes to free CPUs.
        Called whenever a CPU becomes free or a new process enters READY.
        System process has already been handled separately.
        """
        free = self._free_processors()
        while free and self.ready_queue:
            process = self.ready_queue.popleft()
            if process.state != STATE_READY:
                # Stale entry (process state changed); skip
                continue
            cpu = self._preferred_cpu(process)
            if cpu is None:
                # Put back; no free CPU
                self.ready_queue.appendleft(process)
                break
            free = [c for c in free if c != cpu]
            self._dispatch(process, cpu)

    def _enqueue_ready(self, process):
        """
        Mark process as READY and add to ready queue.
        If process is not in memory, trigger load via _admit_process instead.
        """
        if not process.in_memory:
            self._admit_process(process.pid)
            return
        process.state = STATE_READY
        process.last_used_time = self.time
        # Refresh LRU position
        if process.pid in self.in_ram:
            self.in_ram.remove(process.pid)
        self.in_ram.append(process.pid)
        self.ready_queue.append(process)

    # ------------------------------------------------------------------
    # System process
    # ------------------------------------------------------------------

    def _try_run_sys_proc(self):
        """If system process is pending and a CPU is free, run it."""
        if not self.sys_proc_pending or self.sys_proc_running:
            return
        free = self._free_processors()
        if not free:
            return
        cpu = free[0]
        # Preempt nothing – system process only takes a free CPU
        self.sys_proc_running = True
        self.sys_proc_pending = False
        self.sys_proc_cpu = cpu.cpu_id
        cpu.process = "SYS"  # sentinel

        # Collect all currently pending syscalls into one batch
        batch = list(self.pending_syscalls)
        self.pending_syscalls = []

        total_sys_time = sum(dur for _, dur in batch) if batch else self.params["sys_proc_duration"]
        self._log(cpu.cpu_id, None, "SYS_PROC_START", total_sys_time,
                  f"handling {len(batch)} syscall(s)")
        self._gantt_start(cpu.cpu_id, "SYS", "sys_proc")
        self.push(Event(self.time + total_sys_time, EV_SYS_PROC_END,
                        {"cpu_id": cpu.cpu_id, "batch": batch}))

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _handle_process_release(self, ev):
        pid = ev.payload["pid"]
        p = self._get_proc(pid)
        self._log(None, pid, "RELEASED", detail=f"mem={p.memory}MB")
        self._admit_process(pid)

    def _admit_process(self, pid):
        """
        Try to place process pid into RAM.
        Cases:
          1. Enough free RAM right now  -> put in RAM, enqueue READY.
          2. Need eviction, candidates exist -> evict (ram_used decremented),
             saves queued to disk, load queued after saves.
          3. No eviction possible (all in-RAM are RUNNING/LOADING) ->
             defer to waiting_for_ram; retry on next RAM-freeing event.
        """
        p = self._get_proc(pid)
        if p.in_memory:
            return

        if self._ram_available(p.memory):
            p.in_memory = True
            self.ram_used += p.memory
            self.in_ram.append(pid)
            self._enqueue_ready(p)
            self._schedule()
            return

        evicted = self._lru_evict_for(pid)   # decrements ram_used for evicted procs

        if self._ram_available(p.memory):
            if evicted:
                # Saves queued to disk; load comes after them
                p.state = STATE_ON_DISK
                self.disk_queue.append(
                    (pid, "load", p.memory / self.params["disk_transfer_rate"]))
                # _lru_evict_for already called _pump_disk
            else:
                p.in_memory = True
                self.ram_used += p.memory
                self.in_ram.append(pid)
                self._enqueue_ready(p)
                self._schedule()
        else:
            # Cannot evict anything (all occupants running) — defer
            p.state = STATE_ON_DISK
            if pid not in self.waiting_for_ram:
                self.waiting_for_ram.append(pid)
                self._log(None, pid, "WAIT_FOR_RAM",
                          detail=f"deferred — ram_used={self.ram_used}/{self.params['ram_size']} MB")

    def _handle_slice_expire(self, ev):
        pid    = ev.payload["pid"]
        cpu_id = ev.payload["cpu_id"]
        p = self._get_proc(pid)
        cpu = self.processors[cpu_id]

        # Guard against stale events
        if cpu.process is None or cpu.process == "SYS" or cpu.process.pid != pid:
            return

        p.burst_remaining -= self.params["time_slice"]
        p.slice_remaining = 0

        self._gantt_end(cpu_id)
        cpu.process = None
        p.state = STATE_READY
        self._log(cpu_id, pid, "SLICE_EXPIRE",
                  detail=f"burst_rem={p.burst_remaining:.2f}")
        self.ready_queue.append(p)
        self._schedule()
        self._try_run_sys_proc()
        self._try_admit_waiting()

    def _handle_process_finish(self, ev):
        pid    = ev.payload["pid"]
        cpu_id = ev.payload["cpu_id"]
        p = self._get_proc(pid)
        cpu = self.processors[cpu_id]

        if cpu.process is None or cpu.process == "SYS" or cpu.process.pid != pid:
            return  # stale

        p.burst_remaining = 0
        self._gantt_end(cpu_id)
        cpu.process = None

        # Is there a syscall after this burst?
        if p.burst_index < len(p.syscall_times):
            syscall_dur = p.syscall_times[p.burst_index]
            p.burst_index += 1
            # Load next burst if there is one
            if p.burst_index < len(p.bursts):
                p.burst_remaining = p.bursts[p.burst_index]
            p.state = STATE_WAITING_SYS
            p.pending_syscall_duration = syscall_dur
            self._log(cpu_id, pid, "SYSCALL_ISSUED", syscall_dur,
                      f"syscall #{p.burst_index}")
            self.pending_syscalls.append((p, syscall_dur))
            self.sys_proc_pending = True
            self._try_run_sys_proc()
        else:
            # No more syscalls after this burst — advance to next burst if any
            p.burst_index += 1
            if p.burst_index < len(p.bursts):
                p.burst_remaining = p.bursts[p.burst_index]
                self._enqueue_ready(p)
            else:
                p.state = STATE_FINISHED
                self._log(cpu_id, pid, "FINISHED", detail=f"t={self.time:.2f}")
                self._release_ram(pid)

        self._schedule()
        self._try_run_sys_proc()
        self._try_admit_waiting()

    def _handle_syscall_end(self, ev):
        # Not used directly; syscall completion is handled inside SYS_PROC_END
        pass

    def _handle_sys_proc_release(self, ev):
        # Stop firing sys_proc if all user processes are done
        if all(p.state == STATE_FINISHED for p in self.processes):
            return
        self._log(None, None, "SYS_PROC_RELEASED",
                  detail=f"period={self.params['sys_proc_period']}")
        if not self.sys_proc_running:
            self.sys_proc_pending = True
        self._try_run_sys_proc()

    def _handle_sys_proc_end(self, ev):
        cpu_id = ev.payload["cpu_id"]
        batch  = ev.payload["batch"]
        cpu = self.processors[cpu_id]

        self._gantt_end(cpu_id)
        cpu.process = None
        self.sys_proc_running = False
        self.sys_proc_cpu = None

        self._log(cpu_id, None, "SYS_PROC_END",
                  detail=f"completed {len(batch)} syscall(s)")

        # Wake up processes whose syscalls were handled
        for (proc, _) in batch:
            if proc.state == STATE_WAITING_SYS:
                self._log(None, proc.pid, "SYSCALL_COMPLETE",
                          detail=f"burst_index now {proc.burst_index}")
                if not proc.is_finished() and proc.burst_index < len(proc.bursts):
                    self._enqueue_ready(proc)
                else:
                    proc.state = STATE_FINISHED
                    self._log(None, proc.pid, "FINISHED", detail=f"t={self.time:.2f}")
                    self._release_ram(proc.pid)

        # If more pending syscalls accumulated while sys_proc ran, mark pending again
        if self.pending_syscalls:
            self.sys_proc_pending = True

        self._schedule()
        self._try_run_sys_proc()
        self._try_admit_waiting()

    def _handle_disk_transfer_end(self, ev):
        pid       = ev.payload["pid"]
        direction = ev.payload["direction"]
        p = self._get_proc(pid)
        self._gantt_end("DISK")
        self.disk_busy = False

        if direction == "save":
            p.state = STATE_ON_DISK
            p.in_memory = False
            self._log(None, pid, "SAVED_TO_DISK", detail=f"size={p.memory}MB")
            # If this process was evicted mid-run (still has work to do),
            # put it back in waiting_for_ram so it gets reloaded when space frees up
            if p.state != STATE_FINISHED and not p.is_finished():
                if pid not in self.waiting_for_ram:
                    self.waiting_for_ram.append(pid)
        else:  # load
            p.in_memory = True
            self.ram_used += p.memory
            if pid not in self.in_ram:
                self.in_ram.append(pid)
            self._log(None, pid, "LOADED_TO_RAM", detail=f"size={p.memory}MB")
            self._enqueue_ready(p)

        # Advance disk queue
        self._pump_disk()
        self._schedule()
        self._try_run_sys_proc()
        self._try_admit_waiting()

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self):
        self._schedule_initial_events()

        while self._events:
            ev = self.pop()
            self.time = ev.time

            if ev.etype == EV_PROCESS_RELEASE:
                self._handle_process_release(ev)
            elif ev.etype == EV_SLICE_EXPIRE:
                self._handle_slice_expire(ev)
            elif ev.etype == EV_PROCESS_FINISH:
                self._handle_process_finish(ev)
            elif ev.etype == EV_SYSCALL_END:
                self._handle_syscall_end(ev)
            elif ev.etype == EV_SYS_PROC_RELEASE:
                self._handle_sys_proc_release(ev)
            elif ev.etype == EV_SYS_PROC_END:
                self._handle_sys_proc_end(ev)
            elif ev.etype == EV_DISK_TRANSFER_END:
                self._handle_disk_transfer_end(ev)

            # Early exit: all processes finished
            if all(p.state == STATE_FINISHED for p in self.processes):
                break

        return self.log, self.gantt