

class Process:
    def __init__(self, rtime):
        # default values for process
        self.task_list_times = [5,2,3,9,4,6]
        self.task_stack = self.get_task_list_stack()
        self.required_memory = 128
        self.release_time = rtime

    def set_task_list_times(self, new_task_list_times):
        self.task_list_times = new_task_list_times
    def get_task_list_stack(self):
        return [(task_time, 'U' if it % 2 == 0 else 'S') for it, task_time in enumerate(self.task_list_times)]
    def update_task_list_stack(self):
        self.task_stack = []
        for it, task_time in enumerate(self.task_list_times):
            task_type = 'U' if it % 2 ==0 else 'S'
            self.task_stack.append((task_time, task_type))

    def __str__(self):
        return f"RT: {self.release_time}, T: {self.task_list_times}"

class SimulationFeatures:
    def __init__(self):
        # default values for simulation
        self.nr_processors = 3
        self.ram_memory_kb = 512 # Noted in KB
        self.transfer_rate_cost_per_byte = 0.12
        self.scheduling_slice = 5
        self.process_list = [Process(1), Process(2), Process(3)]


    def __str__(self):
        return f"Process list: {self.process_list}"