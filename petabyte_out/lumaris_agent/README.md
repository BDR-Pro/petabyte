# Petabyte Agent

The Petabyte Agent is a lightweight node agent that connects to the Petabyte marketplace API to execute computing tasks.

## Features

- Automatic task fetching from Api.petabyte.market
- Python notebook execution (local execution, no Docker required)
- Virtual machine management (Docker containers on Windows)
- NiceHash-like web UI for monitoring and configuration
- Secure API key authentication
- Real-time task statistics and activity logs

## Installation

### Prerequisites

- Python 3.8 or higher
- Windows 10/11 (for .exe build)
- Internet connection

### From Source

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set environment variables (optional):
```bash
set PETABYTE_API_KEY=your_api_key_here
set AGENT_ID=your_unique_agent_id
```

3. Run the agent:
```bash
python main.py
```

4. Open the UI in your browser:
```
http://127.0.0.1:5000
```

### Build Standalone .exe

1. Install PyInstaller:
```bash
pip install pyinstaller
```

2. Run the build script:
```bash
python build_exe.py
```

3. The executable will be in the `dist` folder:
```
dist/PetabyteAgent.exe
```

## Configuration

The agent can be configured through:
- Environment variables
- The web UI (http://127.0.0.1:5000)
- Configuration file (coming soon)

### Environment Variables

- `PETABYTE_API_KEY`: Your API key from the Petabyte marketplace
- `AGENT_ID`: Unique identifier for this agent (auto-generated if not set)
- `FASTAPI_SERVER_URL`: API server URL (default: https://Api.petabyte.market)

## Usage

1. **Start the Agent**: Run `PetabyteAgent.exe` or `python main.py`
2. **Access the UI**: Open http://127.0.0.1:5000 in your browser
3. **Monitor Tasks**: View real-time status, task statistics, and activity logs
4. **Configure**: Update API key and agent settings through the UI

## Task Types

### Notebook Tasks
- Executes Python notebook code locally
- Supports all standard Python libraries
- Returns execution results to the API

### VM Tasks
- Launches Docker containers (Windows compatible)
- Configurable CPU, RAM, and GPU resources
- Returns VM connection details to the API

## API Communication

The agent communicates with the API using:
- **Heartbeat**: Every 5 seconds to check for new tasks
- **Task Fetching**: Retrieves assigned tasks
- **Result Submission**: Sends execution results back
- **VM Details**: Reports VM connection information

## Troubleshooting

### Agent not connecting to API
- Check your API key in the UI configuration
- Verify internet connection
- Ensure Api.petabyte.market is accessible

### Tasks not executing
- Check Python environment and dependencies
- Review activity log in the UI
- Verify notebook code is valid Python

### VM tasks failing
- Ensure Docker is installed and running (for VM tasks)
- Check system resources (CPU, RAM)
- Review error messages in the activity log

## License

See LICENSE file for details.

## Support

For issues and questions, visit: https://petabyte.market

