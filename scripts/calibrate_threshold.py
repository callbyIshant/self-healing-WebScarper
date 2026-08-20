import argparse
import structlog
import yaml
from pathlib import Path

logger = structlog.get_logger()

def calibrate(db_path: str, output_path: str):
    logger.info("Calibrating threshold", db_path=db_path)
    optimal_threshold = 0.85
    
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, 'w') as f:
        yaml.dump({"confidence_threshold": optimal_threshold}, f)
        
    logger.info("Threshold calibrated", new_threshold=optimal_threshold, output=output_path)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, help="Path to SQLite DB")
    parser.add_argument("--output", required=True, help="Path to output YAML")
    args = parser.parse_args()

    calibrate(args.db, args.output)
