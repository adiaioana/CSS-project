import unittest
from unittest.mock import patch, MagicMock
from collections import deque
import simulator
from simulator import Process, Processor, Event, Simulator

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

class TestEvent(unittest.TestCase):
    def test_event_lt(self):
        ev1 = Event(10, simulator.EV_PROCESS_RELEASE)
        ev2 = Event(15, simulator.EV_PROCESS_RELEASE)
        self.assertTrue(ev1 < ev2)

class TestSimulator(unittest.TestCase):
    def setUp(self):
        self.params = {
            "num_processors": 2, "ram_size": 256, "time_slice": 4,
            "sys_proc_period": 20, "sys_proc_duration": 2, "disk_transfer_rate": 50
        }
        
        # MOCK CLASS "Process" entirely. No logic from Process will execute.
        self.p0 = MagicMock(spec=Process)
        self.p0.pid = 0
        self.p0.memory = 100
        self.p0.state = simulator.STATE_NOT_ARRIVED
        self.p0.in_memory = False
        
        self.p1 = MagicMock(spec=Process)
        self.p1.pid = 1
        self.p1.memory = 200
        self.p1.state = simulator.STATE_NOT_ARRIVED
        self.p1.in_memory = False
        
        self.processes = [self.p0, self.p1]

        # MOCK CLASS "Processor" inside Simulator.__init__
        with patch('simulator.Processor') as MockProcessor:
            self.cpu0 = MagicMock(spec=Processor)
            self.cpu0.cpu_id = 0
            self.cpu0.is_free.return_value = True
            
            self.cpu1 = MagicMock(spec=Processor)
            self.cpu1.cpu_id = 1
            self.cpu1.is_free.return_value = True
            
            # Simulator will receive mocked CPUs
            MockProcessor.side_effect = [self.cpu0, self.cpu1]
            self.sim = Simulator(self.params, self.processes)

    def test_ram_available(self):
        self.sim.ram_used = 200
        self.assertTrue(self.sim._ram_available(56))
        self.assertFalse(self.sim._ram_available(57))

    def test_admit_process_enough_ram(self):
        self.sim._enqueue_ready = MagicMock()
        self.sim._schedule = MagicMock()
        self.sim._admit_process(0)
        self.assertTrue(self.p0.in_memory)
        self.assertEqual(self.sim.ram_used, 100)
        self.assertIn(0, self.sim.in_ram)
        self.sim._enqueue_ready.assert_called_once_with(self.p0)
        self.sim._schedule.assert_called_once()

    def test_admit_process_wait_for_ram(self):
        self.sim.ram_used = 256
        self.sim._lru_evict_for = MagicMock(return_value=[])
        self.sim._admit_process(1) 
        self.assertEqual(self.p1.state, simulator.STATE_ON_DISK)
        self.assertIn(1, self.sim.waiting_for_ram)

    def test_lru_evict_for(self):
        self.sim.ram_used = 200
        self.sim.in_ram = [0, 1]
        self.p0.state = simulator.STATE_READY
        self.p0.in_memory = True
        self.p1.state = simulator.STATE_RUNNING
        self.p1.in_memory = True
        
        p2 = MagicMock(spec=Process)
        p2.pid = 2
        p2.memory = 150
        self.sim.processes.append(p2)
        
        evicted = self.sim._lru_evict_for(2)
        
        self.assertEqual(evicted, [0])
        self.assertEqual(self.p0.state, simulator.STATE_SAVING)
        self.assertFalse(self.p0.in_memory)
        self.assertEqual(self.sim.ram_used, 100)
        self.assertTrue(self.sim.disk_busy)

    def test_schedule_invalid_cpu(self):
        self.sim._preferred_cpu = MagicMock(return_value=None)
        self.p0.state = simulator.STATE_READY
        self.sim.ready_queue.append(self.p0)
        self.sim._schedule()
        self.assertEqual(len(self.sim.ready_queue), 1)

    def test_handle_slice_expire_stale_event(self):
        # MOCK CLASS "Event"
        ev = MagicMock(spec=Event)
        ev.payload = {"pid": 0, "cpu_id": 0}
        self.cpu0.process = None
        self.sim._handle_slice_expire(ev)
        self.assertEqual(self.p0.state, simulator.STATE_NOT_ARRIVED)

    @patch('simulator.heapq.heappush')
    def test_push_event_mocked(self, mock_push):
        ev = MagicMock(spec=Event)
        self.sim.push(ev)
        mock_push.assert_called_once_with(self.sim._events, ev)

    def test_release_ram(self):
        self.sim.ram_used = 100
        self.sim.in_ram = [0]
        self.p0.in_memory = True
        self.sim._release_ram(0)
        self.assertFalse(self.p0.in_memory)
        self.assertEqual(self.sim.ram_used, 0)
        self.assertNotIn(0, self.sim.in_ram)

    def test_load_process(self):
        self.sim._pump_disk = MagicMock()
        self.sim._load_process(0)
        self.assertEqual(self.p0.state, simulator.STATE_LOADING)
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

    @patch('simulator.Event')
    def test_try_run_sys_proc_runs(self, MockEvent):
        self.sim.sys_proc_pending = True
        self.sim._free_processors = MagicMock(return_value=[self.cpu1])
        self.sim.push = MagicMock()
        self.sim.pending_syscalls = [(self.p0, 2.0)]
        
        self.sim._try_run_sys_proc()
        
        self.assertTrue(self.sim.sys_proc_running)
        self.assertFalse(self.sim.sys_proc_pending)
        self.assertEqual(self.sim.sys_proc_cpu, 1)
        self.assertEqual(self.cpu1.process, "SYS")
        self.assertEqual(len(self.sim.pending_syscalls), 0)
        self.sim.push.assert_called_once()

    def test_handle_process_release(self):
        self.sim._admit_process = MagicMock()
        ev = MagicMock(spec=Event)
        ev.payload = {"pid": 0}
        self.sim._handle_process_release(ev)
        self.sim._admit_process.assert_called_once_with(0)

    def test_handle_slice_expire_valid(self):
        self.sim._gantt_end = MagicMock()
        self.sim._schedule = MagicMock()
        self.sim._try_run_sys_proc = MagicMock()
        self.sim._try_admit_waiting = MagicMock()
        
        self.cpu0.process = self.p0
        self.p0.pid = 0
        self.p0.burst_remaining = 10
        self.p0.slice_remaining = 4
        
        ev = MagicMock(spec=Event)
        ev.payload = {"pid": 0, "cpu_id": 0}
        self.sim._handle_slice_expire(ev)
        
        self.assertEqual(self.p0.burst_remaining, 6)
        self.assertEqual(self.p0.slice_remaining, 0)
        self.assertIsNone(self.cpu0.process)
        self.assertEqual(self.p0.state, simulator.STATE_READY)
        self.assertIn(self.p0, self.sim.ready_queue)
        
        self.sim._gantt_end.assert_called_once_with(0)
        self.sim._schedule.assert_called_once()
        self.sim._try_run_sys_proc.assert_called_once()
        self.sim._try_admit_waiting.assert_called_once()

    def test_handle_process_finish_with_syscall(self):
        self.p0.burst_index = 0
        self.p0.syscall_times = [2.0]
        self.p0.bursts = [5.0, 5.0]
        self.p0.is_finished.return_value = False
        self.cpu0.process = self.p0
        
        self.sim._gantt_end = MagicMock()
        self.sim._schedule = MagicMock()
        self.sim._try_run_sys_proc = MagicMock()
        self.sim._try_admit_waiting = MagicMock()
        
        ev = MagicMock(spec=Event)
        ev.payload = {"pid": 0, "cpu_id": 0}
        self.sim._handle_process_finish(ev)
        
        self.assertEqual(self.p0.burst_remaining, 5.0)
        self.assertEqual(self.p0.state, simulator.STATE_WAITING_SYS)
        self.assertTrue(self.sim.sys_proc_pending)
        self.assertEqual(len(self.sim.pending_syscalls), 1)

    def test_handle_process_finish_fully_done(self):
        self.p0.burst_index = 0
        self.p0.syscall_times = []
        self.p0.bursts = [5.0]
        self.p0.is_finished.return_value = True
        self.cpu0.process = self.p0
        
        self.sim._gantt_end = MagicMock()
        self.sim._release_ram = MagicMock()
        self.sim._schedule = MagicMock()
        self.sim._try_run_sys_proc = MagicMock()
        self.sim._try_admit_waiting = MagicMock()
        
        ev = MagicMock(spec=Event)
        ev.payload = {"pid": 0, "cpu_id": 0}
        self.sim._handle_process_finish(ev)
        
        self.assertEqual(self.p0.state, simulator.STATE_FINISHED)
        self.sim._release_ram.assert_called_once_with(0)

    def test_handle_sys_proc_release(self):
        self.sim._try_run_sys_proc = MagicMock()
        self.sim.sys_proc_running = False
        self.p0.state = simulator.STATE_READY
        ev = MagicMock(spec=Event)
        self.sim._handle_sys_proc_release(ev)
        self.assertTrue(self.sim.sys_proc_pending)
        self.sim._try_run_sys_proc.assert_called_once()

    def test_handle_sys_proc_end(self):
        self.p0.state = simulator.STATE_WAITING_SYS
        self.p0.burst_index = 1
        self.p0.bursts = [5.0, 5.0]
        self.p0.is_finished.return_value = False
        
        self.cpu0.process = "SYS"
        self.sim.sys_proc_running = True
        
        self.sim._gantt_end = MagicMock()
        self.sim._enqueue_ready = MagicMock()
        self.sim._schedule = MagicMock()
        self.sim._try_run_sys_proc = MagicMock()
        self.sim._try_admit_waiting = MagicMock()
        
        batch = [(self.p0, 2.0)]
        ev = MagicMock(spec=Event)
        ev.payload = {"cpu_id": 0, "batch": batch}
        self.sim._handle_sys_proc_end(ev)
        
        self.assertFalse(self.sim.sys_proc_running)
        self.assertIsNone(self.cpu0.process)
        self.sim._gantt_end.assert_called_once_with(0)
        self.sim._enqueue_ready.assert_called_once_with(self.p0)

    def test_handle_disk_transfer_end_save(self):
        self.p0.state = simulator.STATE_SAVING
        self.p0.is_finished.return_value = False
        self.sim.disk_busy = True
        
        self.sim._gantt_end = MagicMock()
        self.sim._pump_disk = MagicMock()
        self.sim._schedule = MagicMock()
        self.sim._try_run_sys_proc = MagicMock()
        self.sim._try_admit_waiting = MagicMock()
        
        ev = MagicMock(spec=Event)
        ev.payload = {"pid": 0, "direction": "save"}
        self.sim._handle_disk_transfer_end(ev)
        
        self.assertEqual(self.p0.state, simulator.STATE_ON_DISK)
        self.assertFalse(self.p0.in_memory)
        self.assertIn(0, self.sim.waiting_for_ram)
        self.sim._pump_disk.assert_called_once()

    def test_handle_disk_transfer_end_load(self):
        self.p0.state = simulator.STATE_LOADING
        self.sim.disk_busy = True
        self.sim.ram_used = 0
        
        self.sim._gantt_end = MagicMock()
        self.sim._enqueue_ready = MagicMock()
        self.sim._pump_disk = MagicMock()
        self.sim._schedule = MagicMock()
        self.sim._try_run_sys_proc = MagicMock()
        self.sim._try_admit_waiting = MagicMock()
        
        ev = MagicMock(spec=Event)
        ev.payload = {"pid": 0, "direction": "load"}
        self.sim._handle_disk_transfer_end(ev)
        
        self.assertTrue(self.p0.in_memory)
        self.assertEqual(self.sim.ram_used, 100)
        self.assertIn(0, self.sim.in_ram)
        self.sim._enqueue_ready.assert_called_once_with(self.p0)

    def test_gantt_start(self):
        self.sim.time = 5.0
        self.sim._gantt_start(0, 10, "user")
        self.assertIn(0, self.sim._running_start)
        self.assertEqual(self.sim._running_start[0], (5.0, 10, "user"))

    def test_gantt_end(self):
        self.sim.time = 10.0
        self.sim._running_start[0] = (5.0, 10, "user")
        self.sim._gantt_end(0)
        self.assertNotIn(0, self.sim._running_start)
        self.assertEqual(len(self.sim.gantt), 1)
        self.assertEqual(self.sim.gantt[0], (5.0, 10.0, 0, 10, "user"))

    def test_gantt_end_invalid_start(self):
        # Time didn't advance
        self.sim.time = 5.0
        self.sim._running_start[0] = (5.0, 10, "user")
        self.sim._gantt_end(0)
        self.assertEqual(len(self.sim.gantt), 0)

    def test_try_admit_waiting_empty(self):
        self.sim.waiting_for_ram.clear()
        self.sim._try_admit_waiting()

    def test_try_admit_waiting_fits(self):
        self.sim.waiting_for_ram.append(0)
        self.sim.ram_used = 0
        self.p0.memory = 100
        
        self.sim._enqueue_ready = MagicMock()
        self.sim._schedule = MagicMock()
        
        self.sim._try_admit_waiting()
        
        self.assertEqual(len(self.sim.waiting_for_ram), 0)
        self.assertTrue(self.p0.in_memory)
        self.assertEqual(self.sim.ram_used, 100)
        self.assertIn(0, self.sim.in_ram)
        self.sim._enqueue_ready.assert_called_once_with(self.p0)
        self.sim._schedule.assert_called_once()

    def test_try_admit_waiting_needs_evict_fits(self):
        self.sim.waiting_for_ram.append(0)
        self.sim.ram_used = 200
        self.p0.memory = 100
        
        self.sim._lru_evict_for = MagicMock(return_value=[1]) # Evicted P1
        self.sim._ram_available = MagicMock(side_effect=[False, True]) # Fails first, fits after evict
        
        self.sim._enqueue_ready = MagicMock()
        self.sim._schedule = MagicMock()
        
        self.sim._try_admit_waiting()
        
        self.assertEqual(len(self.sim.waiting_for_ram), 0)
        self.assertTrue(self.p0.in_memory)
        self.sim._enqueue_ready.assert_called_once()
        self.sim._schedule.assert_called_once()

    def test_try_admit_waiting_needs_evict_queued(self):
        self.sim.waiting_for_ram.append(0)
        self.sim.ram_used = 200
        self.p0.memory = 100
        self.p0.state = simulator.STATE_READY
        
        self.sim._lru_evict_for = MagicMock(return_value=[1]) # Evicted P1
        self.sim._ram_available = MagicMock(side_effect=[False, False]) # Fails even after evict trigger
        
        self.sim._try_admit_waiting()
        
        self.assertEqual(len(self.sim.waiting_for_ram), 0)
        self.assertEqual(self.p0.state, simulator.STATE_ON_DISK)
        self.assertEqual(len(self.sim.disk_queue), 1)
        self.assertEqual(self.sim.disk_queue[0], (0, "load", 2.0))

    def test_enqueue_ready_not_in_mem(self):
        self.p0.in_memory = False
        self.sim._admit_process = MagicMock()
        self.sim._enqueue_ready(self.p0)
        self.sim._admit_process.assert_called_once_with(0)

    def test_enqueue_ready_in_mem(self):
        self.p0.in_memory = True
        self.sim.in_ram = [0, 1]
        self.sim.time = 50.0
        self.sim._enqueue_ready(self.p0)
        self.assertEqual(self.p0.state, simulator.STATE_READY)
        self.assertEqual(self.p0.last_used_time, 50.0)
        self.assertEqual(self.sim.in_ram, [1, 0])
        self.assertIn(self.p0, self.sim.ready_queue)

    def test_pump_disk_empty(self):
        self.sim.disk_busy = False
        self.sim._pump_disk()

    @patch('simulator.Event')
    def test_pump_disk_starts_transfer(self, MockEvent):
        self.sim.disk_busy = False
        self.sim.disk_queue.append((0, "load", 5.0))
        self.sim.time = 10.0
        self.sim._log = MagicMock()
        self.sim._gantt_start = MagicMock()
        self.sim.push = MagicMock()
        
        self.sim._pump_disk()
        
        self.assertTrue(self.sim.disk_busy)
        self.assertEqual(len(self.sim.disk_queue), 0)
        self.assertEqual(self.p0.state, simulator.STATE_LOADING)
        self.sim._gantt_start.assert_called_once_with("DISK", 0, "disk_load")
        self.sim.push.assert_called_once()

    def test_schedule_no_free(self):
        self.sim._free_processors = MagicMock(return_value=[])
        self.sim.ready_queue.append(self.p0)
        self.sim._schedule()
        self.assertIn(self.p0, self.sim.ready_queue)

    def test_schedule_skips_stale(self):
        self.sim._free_processors = MagicMock(return_value=[self.cpu0])
        self.cpu0.process = None
        self.p0.state = simulator.STATE_RUNNING
        self.sim.ready_queue.append(self.p0)
        self.sim._schedule()
        self.assertEqual(len(self.sim.ready_queue), 0)
        self.assertIsNone(self.cpu0.process)

    def test_schedule_assigns(self):
        self.sim._free_processors = MagicMock(return_value=[self.cpu0])
        self.p0.state = simulator.STATE_READY
        self.sim.ready_queue.append(self.p0)
        self.sim._preferred_cpu = MagicMock(return_value=self.cpu0)
        self.sim._dispatch = MagicMock()
        
        self.sim._schedule()
        
        self.assertEqual(len(self.sim.ready_queue), 0)
        self.sim._dispatch.assert_called_once_with(self.p0, self.cpu0)

    @patch('simulator.Event')
    def test_dispatch_burst_fits(self, MockEvent):
        self.cpu0.is_free.return_value = True
        self.p0.state = simulator.STATE_READY
        self.p0.burst_remaining = 3.0
        self.sim.params["time_slice"] = 4.0
        
        self.sim._log = MagicMock()
        self.sim._gantt_start = MagicMock()
        self.sim.push = MagicMock()
        
        self.sim._dispatch(self.p0, self.cpu0)
        
        self.assertEqual(self.p0.state, simulator.STATE_RUNNING)
        self.assertEqual(self.p0.last_processor, 0)
        self.assertEqual(self.cpu0.process, self.p0)
        self.assertEqual(self.p0.slice_remaining, 3.0)
        
        MockEvent.assert_called_once_with(self.sim.time + 3.0, simulator.EV_PROCESS_FINISH, {"pid": 0, "cpu_id": 0})
        self.sim.push.assert_called_once()

    @patch('simulator.Event')
    def test_dispatch_slice_expires(self, MockEvent):
        self.cpu0.is_free.return_value = True
        self.p0.state = simulator.STATE_READY
        self.p0.burst_remaining = 10.0
        self.sim.params["time_slice"] = 4.0
        
        self.sim._log = MagicMock()
        self.sim._gantt_start = MagicMock()
        self.sim.push = MagicMock()
        
        self.sim._dispatch(self.p0, self.cpu0)
        
        self.assertEqual(self.p0.slice_remaining, 4.0)
        MockEvent.assert_called_once_with(self.sim.time + 4.0, simulator.EV_SLICE_EXPIRE, {"pid": 0, "cpu_id": 0})

    def test_preempt(self):
        self.cpu0.process = self.p0
        self.p0.slice_remaining = 2.0
        self.sim.time = 10.0
        self.sim.params["time_slice"] = 4.0
        
        self.sim._gantt_end = MagicMock()
        
        process = self.sim._preempt(self.cpu0)
        
        self.assertEqual(process, self.p0)
        self.assertIsNone(self.cpu0.process)
        self.assertEqual(self.p0.state, simulator.STATE_READY)
        self.sim._gantt_end.assert_called_once_with(0)

    def test_run_main_loop(self):
        self.sim._schedule_initial_events = MagicMock()
        self.sim._events = [1, 2] # Force loop execution
        
        ev = MagicMock(spec=Event)
        ev.time = 5.0
        ev.etype = "UNKNOWN_EVENT"
        
        self.sim.pop = MagicMock(side_effect=[ev, IndexError()])
        
        self.p0.state = simulator.STATE_FINISHED
        self.p1.state = simulator.STATE_FINISHED
        
        log, gantt = self.sim.run()
        
        self.assertEqual(self.sim.time, 5.0)
        self.assertEqual(log, self.sim.log)
        self.assertEqual(gantt, self.sim.gantt)
        self.sim._schedule_initial_events.assert_called_once()

if __name__ == '__main__':
    unittest.main()
