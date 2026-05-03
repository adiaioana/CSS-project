import unittest
from unittest.mock import patch, MagicMock
from collections import deque
from simulator import Process, Processor, Event, Simulator, LogEntry
import simulator

class TestProcess(unittest.TestCase):
    def test_is_finished(self):
        p = Process(0, 0, 64, [5.0], [])
        self.assertFalse(p.is_finished())
        p.burst_index = 1
        self.assertTrue(p.is_finished())

class TestProcessor(unittest.TestCase):
    def test_is_free(self):
        cpu = Processor(0)
        self.assertTrue(cpu.is_free())
        cpu.process = "Dummy"
        self.assertFalse(cpu.is_free())

class TestSimulator(unittest.TestCase):
    def setUp(self):
        self.params = {
            "num_processors": 2, "ram_size": 256, "time_slice": 4,
            "sys_proc_period": 20, "sys_proc_duration": 2, "disk_transfer_rate": 50
        }
        self.processes = [
            Process(0, 0.0, 100, [10.0], []),
            Process(1, 1.0, 200, [5.0], []),
        ]
        self.sim = Simulator(self.params, self.processes)

    def test_ram_available(self):
        self.sim.ram_used = 200
        self.assertTrue(self.sim._ram_available(56))
        self.assertFalse(self.sim._ram_available(57))

    def test_admit_process_enough_ram(self):
        """Test admitting a process when there is enough RAM (using mocks for dependencies)."""
        self.sim._enqueue_ready = MagicMock()
        self.sim._schedule = MagicMock()
        
        self.sim._admit_process(0)
        
        self.assertTrue(self.processes[0].in_memory)
        self.assertEqual(self.sim.ram_used, 100)
        self.assertIn(0, self.sim.in_ram)
        self.sim._enqueue_ready.assert_called_once_with(self.processes[0])
        self.sim._schedule.assert_called_once()

    def test_admit_process_wait_for_ram(self):
        """Test behavior when RAM is full and no process is evictable."""
        self.sim.ram_used = 256
        # No processes in self.in_ram that are evictable, so _lru_evict_for returns []
        self.sim._lru_evict_for = MagicMock(return_value=[])
        
        self.sim._admit_process(1) # Needs 200, only 0 available
        
        self.assertEqual(self.processes[1].state, simulator.STATE_ON_DISK)
        self.assertIn(1, self.sim.waiting_for_ram)

    def test_lru_evict_for(self):
        """Test the LRU eviction policy selection."""
        # Fill RAM with dummy state
        self.sim.ram_used = 200
        self.sim.in_ram = [0, 1]
        self.processes[0].state = simulator.STATE_READY
        self.processes[0].in_memory = True
        self.processes[1].state = simulator.STATE_RUNNING
        self.processes[1].in_memory = True
        
        # We need 150 RAM for a new process P2, currently 56 free.
        # P0 is READY, P1 is RUNNING. P0 should be evicted.
        P2 = Process(2, 0.0, 150, [10.0], [])
        self.sim.processes.append(P2)
        
        evicted = self.sim._lru_evict_for(2)
        
        self.assertEqual(evicted, [0])
        self.assertEqual(self.processes[0].state, simulator.STATE_SAVING)
        self.assertFalse(self.processes[0].in_memory)
        self.assertEqual(self.sim.ram_used, 100)
        # Check disk is busy (since _pump_disk popped the queue)
        self.assertTrue(self.sim.disk_busy)

    def test_schedule_invalid_cpu(self):
        """Test scheduler handling if preferred cpu is invalid (incorrect data handling)."""
        self.sim._preferred_cpu = MagicMock(return_value=None)
        p = self.processes[0]
        p.state = simulator.STATE_READY
        self.sim.ready_queue.append(p)
        
        self.sim._schedule()
        
        # P0 should be put back into ready_queue since _preferred_cpu returned None
        self.assertEqual(len(self.sim.ready_queue), 1)

    def test_handle_slice_expire_stale_event(self):
        """Test that a stale slice expire event is safely ignored."""
        ev = Event(0, simulator.EV_SLICE_EXPIRE, {"pid": 0, "cpu_id": 0})
        # cpu0 is free, process 0 is not on it, so it's a stale event
        self.sim._handle_slice_expire(ev)
        # Should return silently without changing p0 state
        self.assertEqual(self.processes[0].state, simulator.STATE_NOT_ARRIVED)

    @patch('simulator.heapq.heappush')
    def test_push_event_mocked(self, mock_push):
        """Test isolated push behavior with mocked heapq."""
        ev = Event(10, simulator.EV_PROCESS_RELEASE, {"pid": 0})
        self.sim.push(ev)
        mock_push.assert_called_once_with(self.sim._events, ev)

    def test_simulation_bounds_extreme_time(self):
        """Test Simulator behaves fine with extremely large parameters (robustness check)."""
        self.sim.params["time_slice"] = 9999999.0
        self.sim.processes = [Process(0, 0, 10, [1.0], [])]
        log, gantt = self.sim.run()
        self.assertTrue(len(log) > 0)
        self.assertEqual(self.sim.processes[0].state, simulator.STATE_FINISHED)

    def test_release_ram(self):
        """Test isolated RAM release."""
        self.sim.ram_used = 100
        self.sim.in_ram = [0]
        self.processes[0].in_memory = True
        self.sim._release_ram(0)
        self.assertFalse(self.processes[0].in_memory)
        self.assertEqual(self.sim.ram_used, 0)
        self.assertNotIn(0, self.sim.in_ram)

    def test_load_process(self):
        """Test isolated _load_process queues correctly."""
        self.sim._pump_disk = MagicMock()
        self.sim._load_process(0)
        self.assertEqual(self.processes[0].state, simulator.STATE_LOADING)
        self.assertEqual(len(self.sim.disk_queue), 1)
        self.assertEqual(self.sim.disk_queue[0][0], 0)
        self.assertEqual(self.sim.disk_queue[0][1], "load")
        self.sim._pump_disk.assert_called_once()

    def test_try_run_sys_proc_no_pending(self):
        self.sim.sys_proc_pending = False
        self.sim._try_run_sys_proc()
        self.assertFalse(self.sim.sys_proc_running)

    def test_try_run_sys_proc_no_cpus(self):
        self.sim.sys_proc_pending = True
        self.sim._free_processors = MagicMock(return_value=[])
        self.sim._try_run_sys_proc()
        self.assertFalse(self.sim.sys_proc_running)

    def test_try_run_sys_proc_runs(self):
        self.sim.sys_proc_pending = True
        cpu = Processor(1)
        self.sim._free_processors = MagicMock(return_value=[cpu])
        self.sim.push = MagicMock()
        self.sim.pending_syscalls = [(self.processes[0], 2.0)]
        
        self.sim._try_run_sys_proc()
        
        self.assertTrue(self.sim.sys_proc_running)
        self.assertFalse(self.sim.sys_proc_pending)
        self.assertEqual(self.sim.sys_proc_cpu, 1)
        self.assertEqual(cpu.process, "SYS")
        self.assertEqual(len(self.sim.pending_syscalls), 0)
        self.sim.push.assert_called_once()
        self.assertEqual(self.sim.push.call_args[0][0].etype, simulator.EV_SYS_PROC_END)

    def test_handle_process_release(self):
        self.sim._admit_process = MagicMock()
        ev = Event(0, simulator.EV_PROCESS_RELEASE, {"pid": 0})
        self.sim._handle_process_release(ev)
        self.sim._admit_process.assert_called_once_with(0)

    def test_handle_slice_expire_valid(self):
        self.sim._gantt_end = MagicMock()
        self.sim._schedule = MagicMock()
        self.sim._try_run_sys_proc = MagicMock()
        self.sim._try_admit_waiting = MagicMock()
        cpu = self.sim.processors[0]
        cpu.process = self.processes[0]
        self.processes[0].burst_remaining = 10
        self.processes[0].slice_remaining = 4
        
        ev = Event(0, simulator.EV_SLICE_EXPIRE, {"pid": 0, "cpu_id": 0})
        self.sim._handle_slice_expire(ev)
        
        self.assertEqual(self.processes[0].burst_remaining, 6)
        self.assertEqual(self.processes[0].slice_remaining, 0)
        self.assertIsNone(cpu.process)
        self.assertEqual(self.processes[0].state, simulator.STATE_READY)
        self.assertIn(self.processes[0], self.sim.ready_queue)
        
        self.sim._gantt_end.assert_called_once_with(0)
        self.sim._schedule.assert_called_once()
        self.sim._try_run_sys_proc.assert_called_once()
        self.sim._try_admit_waiting.assert_called_once()

    def test_handle_process_finish_with_syscall(self):
        p = Process(0, 0, 64, [5.0, 5.0], [2.0])
        self.sim.processes[0] = p
        cpu = self.sim.processors[0]
        cpu.process = p
        
        self.sim._gantt_end = MagicMock()
        self.sim._schedule = MagicMock()
        self.sim._try_run_sys_proc = MagicMock()
        self.sim._try_admit_waiting = MagicMock()
        
        ev = Event(0, simulator.EV_PROCESS_FINISH, {"pid": 0, "cpu_id": 0})
        self.sim._handle_process_finish(ev)
        
        self.assertEqual(p.burst_remaining, 5.0)
        self.assertEqual(p.state, simulator.STATE_WAITING_SYS)
        self.assertTrue(self.sim.sys_proc_pending)
        self.assertEqual(len(self.sim.pending_syscalls), 1)

    def test_handle_process_finish_fully_done(self):
        p = Process(0, 0, 64, [5.0], [])
        self.sim.processes[0] = p
        cpu = self.sim.processors[0]
        cpu.process = p
        
        self.sim._gantt_end = MagicMock()
        self.sim._release_ram = MagicMock()
        self.sim._schedule = MagicMock()
        self.sim._try_run_sys_proc = MagicMock()
        self.sim._try_admit_waiting = MagicMock()
        
        ev = Event(0, simulator.EV_PROCESS_FINISH, {"pid": 0, "cpu_id": 0})
        self.sim._handle_process_finish(ev)
        
        self.assertEqual(p.state, simulator.STATE_FINISHED)
        self.sim._release_ram.assert_called_once_with(0)

    def test_handle_sys_proc_release(self):
        self.sim._try_run_sys_proc = MagicMock()
        self.sim.sys_proc_running = False
        ev = Event(0, simulator.EV_SYS_PROC_RELEASE, {})
        self.sim._handle_sys_proc_release(ev)
        self.assertTrue(self.sim.sys_proc_pending)
        self.sim._try_run_sys_proc.assert_called_once()

    def test_handle_sys_proc_end(self):
        p = Process(0, 0, 64, [5.0, 5.0], [2.0])
        p.state = simulator.STATE_WAITING_SYS
        p.burst_index = 1
        self.sim.processes[0] = p
        cpu = self.sim.processors[0]
        cpu.process = "SYS"
        self.sim.sys_proc_running = True
        
        self.sim._gantt_end = MagicMock()
        self.sim._enqueue_ready = MagicMock()
        self.sim._schedule = MagicMock()
        self.sim._try_run_sys_proc = MagicMock()
        self.sim._try_admit_waiting = MagicMock()
        
        batch = [(p, 2.0)]
        ev = Event(0, simulator.EV_SYS_PROC_END, {"cpu_id": 0, "batch": batch})
        self.sim._handle_sys_proc_end(ev)
        
        self.assertFalse(self.sim.sys_proc_running)
        self.assertIsNone(cpu.process)
        self.sim._gantt_end.assert_called_once_with(0)
        self.sim._enqueue_ready.assert_called_once_with(p)

    def test_handle_disk_transfer_end_save(self):
        p = self.processes[0]
        p.state = simulator.STATE_SAVING
        self.sim.disk_busy = True
        
        self.sim._gantt_end = MagicMock()
        self.sim._pump_disk = MagicMock()
        self.sim._schedule = MagicMock()
        self.sim._try_run_sys_proc = MagicMock()
        self.sim._try_admit_waiting = MagicMock()
        
        ev = Event(0, simulator.EV_DISK_TRANSFER_END, {"pid": 0, "direction": "save"})
        self.sim._handle_disk_transfer_end(ev)
        
        self.assertEqual(p.state, simulator.STATE_ON_DISK)
        self.assertFalse(p.in_memory)
        self.assertIn(0, self.sim.waiting_for_ram)
        self.sim._pump_disk.assert_called_once()

    def test_handle_disk_transfer_end_load(self):
        p = self.processes[0]
        p.state = simulator.STATE_LOADING
        self.sim.disk_busy = True
        self.sim.ram_used = 0
        
        self.sim._gantt_end = MagicMock()
        self.sim._enqueue_ready = MagicMock()
        self.sim._pump_disk = MagicMock()
        self.sim._schedule = MagicMock()
        self.sim._try_run_sys_proc = MagicMock()
        self.sim._try_admit_waiting = MagicMock()
        
        ev = Event(0, simulator.EV_DISK_TRANSFER_END, {"pid": 0, "direction": "load"})
        self.sim._handle_disk_transfer_end(ev)
        
        self.assertTrue(p.in_memory)
        self.assertEqual(self.sim.ram_used, 100)
        self.assertIn(0, self.sim.in_ram)
        self.sim._enqueue_ready.assert_called_once_with(p)

if __name__ == '__main__':
    unittest.main()
