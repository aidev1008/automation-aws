# Catche Automation Project

A web automation project using Playwright and FastAPI to automate login processes and web interactions.

## Features

- **Playwright Integration**: Automated browser interactions with Chromium, Firefox, or WebKit
- **FastAPI REST API**: RESTful endpoints for automation control
- **Configuration Management**: JSON-based configuration for credentials and site settings
- **Environment Variables**: Configurable settings through .env file
- **Screenshot Capture**: Take screenshots of automated sessions
- **Headless/Headful Mode**: Configurable browser display mode

## Project Structure

```
Catche Automation/
├── main.py              # FastAPI application
├── automation.py        # Playwright automation logic
├── models.py           # Pydantic models for API
├── config.json         # Configuration file with credentials
├── requirements.txt    # Python dependencies
├── .env               # Environment variables
├── README.md          # This file
└── venv/              # Virtual environment
```

## Installation

1. **Activate virtual environment**:
   ```powershell
   .\venv\Scripts\Activate.ps1
   ```

2. **Install dependencies**:
   ```powershell
   pip install -r requirements.txt
   ```

3. **Install Playwright browsers**:
   ```powershell
   playwright install
   ```

## Configuration

### Environment Variables (.env)
- `HEADLESS`: Run browser in headless mode (true/false)
- `BROWSER_TYPE`: Browser to use (chromium/firefox/webkit)
- `TIMEOUT`: Page timeout in milliseconds
- `VIEWPORT_WIDTH`/`VIEWPORT_HEIGHT`: Browser viewport size
- `API_HOST`/`API_PORT`: FastAPI server configuration

### Credentials (config.json)
Update the `config.json` file with your actual credentials:
```json
{
    "credentials": {
        "username": "your_username",
        "password": "your_actual_password"
    },
    "site_config": {
        "base_url": "https://lendly.catch-e.net.au",
        "login_path": "/core/login.phpo",
        "login_params": {
            "i": "",
            "user_login": "ben.lazzaro",
            "screen_width": 1536,
            "screen_height": 960
        }
    }
}
```

## Usage

### Start the API Server

```powershell
python main.py
```

The API will be available at `http://localhost:8000`

### API Documentation

Visit `http://localhost:8000/docs` for interactive API documentation.

### API Endpoints

- **POST /login**: Perform automated login
- **POST /quick-login**: Quick login with standalone function
- **GET /screenshot**: Take screenshot of current page
- **GET /page-content**: Get current page content
- **POST /navigate**: Navigate to specific URL
- **POST /reset-browser**: Reset browser instance
- **GET /config**: Get current configuration
- **POST /update-config**: Update configuration

### Example API Usage

```python
import requests

# Login request
response = requests.post("http://localhost:8000/login", json={
    "username": "your_username",
    "password": "your_password"
})

print(response.json())
```

### Standalone Usage

```python
import asyncio
from automation import quick_login

async def main():
    result = await quick_login(
        username="your_username",
        password="your_password"
    )
    print(result)

asyncio.run(main())
```

## Site-Specific Configuration

The project is configured for the Lendly Catch-e site:
- **URL**: https://lendly.catch-e.net.au/core/login.phpo
- **Parameters**: Includes screen dimensions and user login
- **Auto-detection**: The automation tries multiple selectors for login forms

## Browser Support

- **Chromium** (default)
- **Firefox**
- **WebKit**

Change browser type in `.env` file:
```
BROWSER_TYPE=firefox
```

## Headless Mode

Control browser visibility:
- `HEADLESS=true`: Run browser in background
- `HEADLESS=false`: Show browser window (useful for debugging)

## Error Handling

The application includes comprehensive error handling for:
- Browser initialization failures
- Page navigation issues
- Login form detection problems
- Network timeouts
- Configuration errors

## Security Notes

- Keep `config.json` secure and never commit actual passwords
- Use environment variables for sensitive configuration
- The API masks passwords in configuration endpoints
- Consider using encrypted credential storage for production

## Development

### Running in Development Mode

```powershell
# With auto-reload
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Taking Screenshots

Screenshots are automatically saved and can be accessed via the `/screenshot` endpoint.

### Debugging

Set `HEADLESS=false` in `.env` to see browser interactions in real-time.

## Troubleshooting

1. **Import Errors**: Make sure virtual environment is activated and dependencies are installed
2. **Browser Issues**: Run `playwright install` to ensure browsers are installed
3. **Login Failures**: Check if site structure has changed and update selectors if needed
4. **Timeout Errors**: Increase `TIMEOUT` value in `.env` file

## License

This project is for educational and automation purposes.