import unittest
from unittest.mock import patch, mock_open
from visualiser import generate_html
from simulator import LogEntry, Process

class TestVisualiser(unittest.TestCase):

    def test_generate_html_valid(self):
        """Test HTML generation with normal log and gantt data."""
        params = {
            "num_processors": 2, "ram_size": 256, "time_slice": 4,
            "sys_proc_period": 20, "sys_proc_duration": 2, "disk_transfer_rate": 50
        }
        processes = [
            Process(0, 0, 64, [5.0], [])
        ]
        processes[0].state = "FINISHED"

        log = [
            LogEntry(0.0, 0, 0, "DISPATCH", 4.0, "details")
        ]
        gantt = [
            (0.0, 4.0, 0, 0, "user")
        ]
        
        with patch('builtins.open', mock_open()) as mocked_file:
            generate_html(log, gantt, params, processes, "dummy.html")
            
            # Check if write was called
            mocked_file().write.assert_called()
            
            # Get the written HTML
            written_content = "".join(call.args[0] for call in mocked_file().write.mock_calls)
            self.assertIn("Scheduler Simulation", written_content)
            self.assertIn("CPU0", written_content)
            self.assertIn("DISPATCH", written_content)

    def test_generate_html_empty_gantt(self):
        """Test HTML generation handles empty gantt appropriately (should fallback t_max = 1.0)."""
        params = {"num_processors": 1, "ram_size": 256, "time_slice": 4, "sys_proc_period": 20, "sys_proc_duration": 2, "disk_transfer_rate": 50}
        with patch('builtins.open', mock_open()) as mocked_file:
            generate_html([], [], params, [], "dummy.html")
            written_content = "".join(call.args[0] for call in mocked_file().write.mock_calls)
            self.assertIn("Scheduler Simulation", written_content)

    def test_generate_html_incorrect_data(self):
        """Test handling of incorrect data types in Gantt (should raise Exception, demonstrating lack of safety net)."""
        params = {"num_processors": 1, "ram_size": 256, "time_slice": 4, "sys_proc_period": 20, "sys_proc_duration": 2, "disk_transfer_rate": 50}
        # Passing string instead of float for end time in gantt
        bad_gantt = [(0.0, "invalid_end_time", 0, 0, "user")]
        
        with patch('builtins.open', mock_open()):
            with self.assertRaises(TypeError):
                generate_html([], bad_gantt, params, [], "dummy.html")

if __name__ == '__main__':
    unittest.main()
