"""Human-run inspection: uv run --project agent python -m gaze_agent.screen."""
from gaze_agent.screen import get_screen

if __name__ == "__main__":
    print(get_screen().to_prompt())
