import re
import sys
import subprocess
import time

def verilog2dimacs(path, target_state, unroll_times):
    gate_regex = r"(and|not)\s+\S+\s*\((.+?)\);" # Regex to find gates
    state_reg_line_regex = r"\breg\s+([^;]*\bS\d+\b[^;]*);" # Regex to find state register declarations
    state_var_regex = r"\bS\d+\b" # Regex to find state variables
    top = path.split('/')[-1].replace('.v', '') # Extract the top module name from the file path

    with open(path, 'r') as f:
        data = f.read()

    original_net_map = {}
    original_clauses = []

    # Function to map variables to integers
    def map_vars(net): 
        if net not in original_net_map:
            original_net_map[net] = len(original_net_map) + 1
        return original_net_map[net]

    # Function to process gates and create clauses
    def process_gate(gate, output, inputs):
        if gate == 'and':
            output_var = map_vars(output) # Map the output variable
            inputs_vars = [map_vars(inp) for inp in inputs] # Map the input variables
            for inp_var in inputs_vars: # Creating the clause for (~output OR input)
                original_clauses.append(f"-{output_var} {inp_var} 0")  # (~output OR input)
            # Creating the clause for (output OR ~input1 OR ~input2 ...)
            all_inputs_negated = " ".join([f"-{inp}" for inp in inputs_vars])
            original_clauses.append(f"{output_var} {all_inputs_negated} 0")
        elif gate == 'not':
            original_clauses.append(f"-{map_vars(output)} -{map_vars(inputs[0])} 0")
            original_clauses.append(f"{map_vars(output)} {map_vars(inputs[0])} 0")

    # Processing state register declarations to map variables
    for line in re.findall(state_reg_line_regex, data):
        for var in re.findall(state_var_regex, line):
            map_vars(var)

    # Parsing gates and creating clauses
    for gate, net_str in re.findall(gate_regex, data, re.DOTALL):
        nets = [n.strip() for n in net_str.split(',')]
        process_gate(gate, nets[0], nets[1:])
    
    total_vars = len(original_net_map)
    clauses = []
    
    # Set initial state to 0
    for var in original_net_map:
        if var.startswith('S') and var[1:].isdigit():  # Check if the variable is a state variable in the format Sx
            clauses.append(f"-{original_net_map[var]} 0")  # Set state variable to '0'


    # Replicate and adjust clauses for each unrolling
    for u in range(unroll_times+1):
        offset = u * total_vars
        for clause in original_clauses:
            new_clause = ""
            for lit in clause.split():
                if lit == '0':
                    new_clause += " 0"
                elif lit.startswith('-'):
                    var_idx = int(lit[1:]) + offset
                    new_clause += f" -{var_idx}"
                elif lit.isdigit():
                    var_idx = int(lit) + offset
                    new_clause += f" {var_idx}"
            clauses.append(new_clause)

        # Connect NS outputs to S inputs after each unrolling, except before the first
        if u > 0:
            for ns in filter(lambda n: n.startswith('NS'), original_net_map):
                s_var = 'S' + ns[2:]  # Corresponding state variable
                ns_idx = original_net_map[ns] + (u - 1) * total_vars
                s_idx = original_net_map[s_var] + u * total_vars
                clauses.append(f"{ns_idx} -{s_idx} 0")
                clauses.append(f"-{ns_idx} {s_idx} 0")

    # Handle the target state for the last set of NS variables
    for i, bit in enumerate(reversed(target_state)):
        ns_var = f'NS{i}'
        ns_idx = original_net_map[ns_var] + unroll_times * total_vars
        if bit == '1':
            clauses.append(f"{ns_idx} 0")
        else:
            clauses.append(f"-{ns_idx} 0")

    final_total_vars = total_vars * (unroll_times + 1)

    return top, final_total_vars, clauses

def write_dimacs(top, total_vars, clauses):
    dimacs_file_path = f'{top}.dimacs'
    with open(dimacs_file_path, 'w') as f:
        f.write(f'c {top}\np cnf {total_vars} {len(clauses)}\n')
        for clause in clauses:
            f.write(f"{clause}\n")
    return dimacs_file_path  # Return the path for use with PicoSAT.

def run_picosat(dimacs_file_path):
    start_time = time.time()
    # result = subprocess.run(['picosat', dimacs_file_path])
    result = subprocess.run(['picosat', dimacs_file_path], capture_output=True, text=True)
    end_time = time.time()  # Capture end time
    runtime = end_time - start_time  # Calculate runtime
    
    print(result.stdout)
    # Print runtime uptil 4th decimal place
    print(f"PicoSAT Runtime: {runtime:.4f} seconds")
    
    
    

if __name__ == '__main__':
    if len(sys.argv) != 4:
        print("Usage: python script.py <verilog_file_path> <target_state> <unroll_times>")
        sys.exit(1)

    path = sys.argv[1]
    target_state = sys.argv[2]
    unroll_times = int(sys.argv[3]) - 1
    
    top, total_vars, clauses = verilog2dimacs(path, target_state, unroll_times)
    dimacs_file_path = write_dimacs(top, total_vars, clauses)
    print(f'DIMACS file "{dimacs_file_path}" has been created.')

    # Run PicoSAT on the generated DIMACS file.
    run_picosat(dimacs_file_path)
    