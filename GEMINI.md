
# GEMINI.md

## Project Overview

This project is a Python-based web application named "AMEET v1.0", which appears to be an "AI collective intelligence discussion platform". It is built using the FastAPI framework and utilizes a variety of technologies, including:

*   **Backend:** Python, FastAPI, Gunicorn, Uvicorn
*   **Databases:** Redis, MongoDB (with Beanie ORM), and likely MySQL (based on the config).
*   **AI/ML:** LangChain, with integrations for OpenAI, Google, and Anthropic models.
*   **Deployment:** Docker, Google Cloud Run

The application exposes a RESTful API with endpoints for users and administrators, and serves a simple frontend built with HTML and likely some JavaScript.

## Building and Running

### Local Development

To run the application locally, you will need to have Python 3.11, Redis, and MongoDB installed.

1.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

2.  **Set up Environment Variables:**
    Create a `.env` file in the root of the project and populate it with the necessary environment variables, such as database connection strings and API keys. Refer to `src/app/core/config.py` for a list of required variables.

3.  **Run the Application:**
    ```bash
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
    ```

### Docker

The project includes a `Dockerfile` for containerizing the application.

1.  **Build the Docker Image:**
    ```bash
    docker build -t ameet-v1 .
    ```

2.  **Run the Docker Container:**
    ```bash
    docker run -p 8080:8080 ameet-v1
    ```

### Deployment

The `cloudbuild.yaml` file contains the configuration for deploying the application to Google Cloud Run. The deployment is triggered by pushes to the repository and is handled by Google Cloud Build.

## Development Conventions

*   **Code Style:** The code appears to follow the PEP 8 style guide.
*   **Testing:** There are no dedicated test files visible in the provided directory structure, so the testing practices are unclear.
*   **Dependencies:** Python dependencies are managed with `pip-compile` from a `requirements.in` file.
*   **Configuration:** Application configuration is managed through environment variables and a `.env` file, loaded by `pydantic-settings`.
