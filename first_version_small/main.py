from simulation import SimulationFeatures

simulation_features = SimulationFeatures()

process_list = simulation_features.process_list
process_list.sort(key=lambda x: x.release_time, reverse=True)

print(process_list)