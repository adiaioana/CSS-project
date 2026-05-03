import unittest
from unittest.mock import mock_open, patch
from parser import parse_input_file, build_text_report
from simulator import Process

class TestParser(unittest.TestCase):

    def test_parse_valid_input(self):
        valid_data = (
            "[params]\n"
            "num_processors = 2\n"
            "ram_size = 256\n"
            "time_slice = 4\n"
            "sys_proc_period = 20\n"
            "sys_proc_duration = 2\n"
            "disk_transfer_rate = 50\n"
            "\n"
            "[processes]\n"
            "0 64 5 2 3\n"
        )
        with patch('builtins.open', mock_open(read_data=valid_data)):
            params, processes = parse_input_file("dummy_path")
            
        self.assertEqual(params["num_processors"], 2)
        self.assertEqual(params["ram_size"], 256)
        self.assertEqual(params["time_slice"], 4.0)
        self.assertEqual(len(processes), 1)
        self.assertEqual(processes[0].pid, 0)
        self.assertEqual(processes[0].release_time, 0.0)
        self.assertEqual(processes[0].memory, 64)
        self.assertEqual(processes[0].bursts, [5.0, 3.0])
        self.assertEqual(processes[0].syscall_times, [2.0])

    def test_parse_missing_file(self):
        """Test how the parser handles a file that doesn't exist (should raise FileNotFoundError)"""
        with self.assertRaises(FileNotFoundError):
            parse_input_file("non_existent_file_for_testing.txt")

    def test_parse_invalid_sequence_even_length(self):
        """Test incorrect input data: sequence of execution times should be odd (starts and ends with burst)."""
        invalid_data = (
            "[params]\n"
            "num_processors = 2\n"
            "ram_size = 256\n"
            "time_slice = 4\n"
            "sys_proc_period = 20\n"
            "sys_proc_duration = 2\n"
            "disk_transfer_rate = 50\n"
            "[processes]\n"
            "0 64 5 2\n"  # Only 2 numbers in sequence (even length), violates assertion
        )
        with patch('builtins.open', mock_open(read_data=invalid_data)):
            with self.assertRaises(AssertionError):
                parse_input_file("dummy_path")

    def test_parse_missing_params(self):
        """Test incorrect input data: missing mandatory system parameters."""
        invalid_data = (
            "[params]\n"
            "num_processors = 2\n"
            # Missing ram_size, time_slice, etc.
            "[processes]\n"
            "0 64 5\n"
        )
        with patch('builtins.open', mock_open(read_data=invalid_data)):
            with self.assertRaises(KeyError):
                parse_input_file("dummy_path")
                
    def test_parse_malformed_process_line(self):
        """Test process line that has too few arguments"""
        invalid_data = (
            "[params]\n"
            "num_processors = 2\n"
            "ram_size = 256\n"
            "time_slice = 4\n"
            "sys_proc_period = 20\n"
            "sys_proc_duration = 2\n"
            "disk_transfer_rate = 50\n"
            "[processes]\n"
            "0 64\n"  # Missing bursts
        )
        with patch('builtins.open', mock_open(read_data=invalid_data)):
            with self.assertRaises(AssertionError):
                parse_input_file("dummy_path")

    def test_build_text_report(self):
        """Test that report building processes data without crashing."""
        params = {
            "num_processors": 2, "ram_size": 256, "time_slice": 4,
            "sys_proc_period": 20, "sys_proc_duration": 2, "disk_transfer_rate": 50
        }
        processes = [Process(0, 0, 64, [5.0], [])]
        report = build_text_report([], [], params, processes)
        self.assertIn("ROUND-ROBIN SCHEDULER SIMULATION", report)
        self.assertIn("P0", report)

if __name__ == '__main__':
    unittest.main()
