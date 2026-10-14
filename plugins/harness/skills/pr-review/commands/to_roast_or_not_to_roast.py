import random
import sys


def should_add_roast() -> bool:
    # Simulate a decision process with a random choice
    selection = random.choice([True, False])
    print(f'harness:roast-my-code should be added to subagent dispatch: {selection}')
    return selection

if __name__ == "__main__":
    sys.exit(0 if should_add_roast() else 1)
