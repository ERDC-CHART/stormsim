import json
import argparse
from pathlib import Path
from stormsim.hydrograph_manipulator import run_hydro_manipulator

def load_config(path: Path):
    with open(path, 'r') as f:
        return json.load(f)[0]  # config is a list of 1 dict, as eurotop's is

def main():
    parser = argparse.ArgumentParser(description="Hydrograph Manipulator CLI Wrapper")
    parser.add_argument("--config", type=str, default="config-files/hydroManipulator_config.json", help="Path to the config JSON")
    args = parser.parse_args()
    
    config_path = Path(args.config)
    config = load_config(config_path)
    print(f"Using CLI Entry point with config: {config_path}")
    
    result = run_hydro_manipulator(config)
    print(result)

if __name__ == "__main__":
    main()
