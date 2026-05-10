import unittest
from unittest.mock import mock_open, patch, MagicMock
from parser import parse_input_file, build_text_report

class TestParser(unittest.TestCase):

    @patch('simulator.Process')
    def test_parse_valid_input(self, MockProcess):
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
        MockProcess.assert_called_once_with(0, 0.0, 64, [5.0, 3.0], [2.0])

    def test_parse_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            parse_input_file("non_existent_file_for_testing.txt")

    @patch('simulator.Process')
    def test_parse_invalid_sequence_even_length(self, MockProcess):
        invalid_data = (
            "[params]\n"
            "num_processors = 2\n"
            "ram_size = 256\n"
            "time_slice = 4\n"
            "sys_proc_period = 20\n"
            "sys_proc_duration = 2\n"
            "disk_transfer_rate = 50\n"
            "[processes]\n"
            "0 64 5 2\n"
        )
        with patch('builtins.open', mock_open(read_data=invalid_data)):
            with self.assertRaises(AssertionError):
                parse_input_file("dummy_path")

    def test_parse_missing_params(self):
        invalid_data = (
            "[params]\n"
            "num_processors = 2\n"
            "[processes]\n"
            "0 64 5\n"
        )
        with patch('builtins.open', mock_open(read_data=invalid_data)):
            with self.assertRaises(KeyError):
                parse_input_file("dummy_path")

    def test_build_text_report(self):
        params = {
            "num_processors": 2, "ram_size": 256, "time_slice": 4,
            "sys_proc_period": 20, "sys_proc_duration": 2, "disk_transfer_rate": 50
        }
        # Use mocked processes
        mock_p = MagicMock()
        mock_p.pid = 0
        mock_p.release_time = 0.0
        mock_p.memory = 64
        mock_p.bursts = [5.0]
        mock_p.syscall_times = []
        processes = [mock_p]
        
        report = build_text_report([], [], params, processes)
        self.assertIn("ROUND-ROBIN SCHEDULER SIMULATION", report)
        self.assertIn("P0", report)

if __name__ == '__main__':
    unittest.main()
