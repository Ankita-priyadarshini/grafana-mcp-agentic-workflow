# Complete Grafana MCP Agentic Workflow Setup Guide

This guide provides step-by-step instructions for setting up the complete Grafana MCP Agentic Workflow system, including the plugin, backend services, and MCP server components.

## System Architecture Overview

The system consists of three main components:
1. **Frontend Plugin**: React-based Grafana plugin for user interface
2. **Backend Service**: Python-based agent with LLM integration
3. **MCP Server**: Go-based server for Grafana API communication

## Prerequisites

### Required Software
- **Node.js**: v16+ and npm
- **Python**: v3.8+
- **Go**: v1.19+
- **Docker & Docker Compose**: For containerized services
- **uv**: Python package manager (optional but recommended)
- **Git**: For cloning repositories

### Required API Keys
- **Grafana API Key**: Service account token from your Grafana instance
- **Google API Key**: For Gemini LLM integration
- **LangChain API Key**: For tracing and monitoring (from LangSmith)
- **OpenAI API Key**: Optional, for future OpenAI integration

---

## Part 1: Plugin Setup

### Step 1: Clone and Install Plugin Dependencies

```bash
# Clone the repository
git clone <repository-url>
cd myorg-llmplugin-app

# Install Node.js dependencies
npm install
```

### Step 2: Build the Plugin

Choose one of the following based on your needs:

```bash
# For development (with hot reload)
npm run dev

# For production build
npm run build
```

### Step 3: Start Docker Services

Open a new terminal window and navigate to the same directory:

```bash
# Navigate to the cloned directory
cd <cloned-directory>

# Start Docker services
docker compose up
```

**Note**: This will start supporting services like Redis, databases, or other containerized components required by the system.

---

## Part 2: Backend Setup

### Step 1: Create Environment Configuration

Create a `.env` file in the backend directory with the following configuration:

```bash
# Grafana Configuration
GRAFANA_URL=*************************
GRAFANA_API_KEY=*******************

# LLM API Keys
OPENAI_API_KEY=****************************************************
GOOGLE_API_KEY=*******************************

# LangChain Configuration
LANGCHAIN_API_KEY=***************************
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT=grafana-agent-debug

# Redis Configuration
REDIS_HOST=localhost
REDIS_PORT=6379
```

### Step 2: Configure API Keys

You need to update the following keys in your `.env` file:

#### Grafana API Key
1. Navigate to your Grafana instance
2. Go to **Administration > Users and access > Service accounts**
3. Create a new service account or use existing one
4. Generate a new token
5. Copy the token and replace `GRAFANA_API_KEY` value

#### Google API Key
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing one
3. Enable the Gemini API
4. Create credentials (API Key)
5. Replace `GOOGLE_API_KEY` value

#### LangChain API Key
1. Visit [LangSmith](https://smith.langchain.com/)
2. Create an account or sign in
3. Generate a new API key
4. Replace `LANGCHAIN_API_KEY` value

### Step 3: Install Python Dependencies

```bash
# Install dependencies from requirements.txt
pip install -r requirements.txt
```

### Step 4: Run the Backend Service

You have two options to run the backend:

#### Option A: Using uv (Recommended)

```bash
# Download and install uv
curl -Ls https://astral.sh/uv/install.sh | bash

# Set up uv environment
source $HOME/.local/bin/env

# Verify installation
uv --version

# Create virtual environment
uv venv

# Activate the environment
source .venv/bin/activate

# Run the backend service
uv run --active all-agent-gemini-streamable-http.py
```

#### Option B: Using npm

```bash
# Run using npm (ensure package.json is configured properly)
npm start
```

### Step 5: LLM Configuration Notes

- **Current Setup**: The system is configured to use **Google Gemini LLM** by default.
- **Performance**: Gemini has been observed to perform better than the existing OpenAI models for this specific use case.
- **Future Flexibility**: The OpenAI API key is included for future integration if better OpenAI models become available or if your organization prefers OpenAI models.
- **Model Switching**: To switch between models, modify the LLM configuration in the Python backend code.

---

## Part 3: MCP Server Setup

### Step 1: Set Environment Variables

Open a new terminal and set the required environment variables:

```bash
# Export Grafana configuration
export GRAFANA_URL=http://localhost:3000
export GRAFANA_API_KEY=****************************
```

**Important**: Replace the `GRAFANA_API_KEY` with your actual API key from Step 2.2.

### Step 2: Clone and Setup MCP Server

```bash
# Clone the official Grafana MCP repository
git clone https://github.com/grafana/mcp-grafana

# Navigate to the MCP directory
cd mcp-grafana

# Navigate to the command directory
cd cmd

# Navigate to the MCP Grafana command
cd mcp-grafana
```

### Step 3: Run the MCP Server

```bash
# Run the MCP server with streamable HTTP transport
go run main.go -t streamable-http
```

**Transport Options**:
- `-t streamable-http`: Uses HTTP-based streaming transport
- `-t stdio`: Uses standard input/output transport (default)

---

## System Startup Sequence

To start the complete system, follow this sequence:

### Terminal 1: Plugin Development
```bash
cd myorg-llmplugin-app
npm install
npm run dev
```

### Terminal 2: Docker Services
```bash
cd <cloned-directory>
docker compose up
```

### Terminal 3: Backend Service
```bash
cd <backend-directory>
source .venv/bin/activate  # if using uv
uv run --active all-agent-gemini-streamable-http.py
```

### Terminal 4: MCP Server
```bash
export GRAFANA_URL=http://localhost:3000
export GRAFANA_API_KEY=<your-api-key>
cd mcp-grafana/cmd/mcp-grafana
go run main.go -t streamable-http
```

---

## Verification Steps

### 1. Check Plugin Status
- Access Grafana at `http://localhost:3000`
- Navigate to plugins section
- Verify your plugin is loaded and active

### 2. Check Backend Service
- Look for successful startup messages
- Verify API connections are established
- Check logs for any errors

### 3. Check MCP Server
- Verify server starts without errors
- Check that it connects to Grafana API
- Confirm transport layer is working

### 4. Test Integration
- Use the plugin interface to trigger backend operations
- Verify data flows between all components
- Check LangChain tracing in LangSmith dashboard

---

## Troubleshooting

### Common Issues

#### Plugin Build Errors
```bash
# Clear node modules and reinstall
rm -rf node_modules package-lock.json
npm install
```

#### Backend Connection Issues
- Verify all API keys are correctly set
- Check `.env` file formatting
- Ensure all required services are running

#### MCP Server Issues
- Verify Grafana is accessible
- Check API key permissions
- Ensure Go environment is properly set up

#### Docker Issues
```bash
# Restart Docker services
docker compose down
docker compose up --build
```

### Debug Mode

Enable verbose logging for better troubleshooting:

```bash
# Backend with debug logging
PYTHONPATH=. python -m uvicorn main:app --reload --log-level debug

# MCP Server with debug mode
go run main.go -t streamable-http -debug
```

---

## Configuration Files Summary

### `.env` File Template
```bash
GRAFANA_URL=http://localhost:3000
GRAFANA_API_KEY=<your-grafana-api-key>
OPENAI_API_KEY=<your-openai-api-key>
GOOGLE_API_KEY=<your-google-api-key>
LANGCHAIN_API_KEY=<your-langchain-api-key>
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT=grafana-agent-debug
REDIS_HOST=localhost
REDIS_PORT=6379
```

## Quick Start Commands

Once everything is set up, use these commands to start the system:

```bash
# Terminal 1 - Plugin
cd myorg-llmplugin-app && npm run dev

# Terminal 2 - Docker
docker compose up

# Terminal 3 - Backend
cd backend && source .venv/bin/activate && uv run --active all-agent-gemini-streamable-http.py

# Terminal 4 - MCP Server
export GRAFANA_URL=http://localhost:3000 && export GRAFANA_API_KEY=<your-key> && cd mcp-grafana/cmd/mcp-grafana && go run main.go -t streamable-http
```

---
