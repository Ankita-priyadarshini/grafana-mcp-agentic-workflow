import asyncio
import os
import uuid
import json
from typing import List, Dict, Any, Optional
from datetime import datetime
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn
import redis
from zoneinfo import ZoneInfo
import tzlocal
from fastapi.middleware.cors import CORSMiddleware

# Load environment variables
load_dotenv()

# MCP + LangChain with HTTP Streamable support
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from langgraph.prebuilt import create_react_agent
from langchain_google_genai import ChatGoogleGenerativeAI

# Redis client
redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    db=0,
    decode_responses=True
)

def get_session_key(uid: str) -> str:
    return f"session:{uid}"

# FastAPI models
class QueryRequest(BaseModel):
    query: str
    uid: Optional[str] = None

class QueryResponse(BaseModel):
    uid: str
    response: str
    is_new_session: bool
    agent_used: str
    suggested_next_actions: Optional[List[str]] = None

# Agent Classification
def classify_query_intent(query: str) -> str:
    query_lower = query.lower().strip()
    dashboard_keywords = [
        'dashboard', 'panel', 'metric', 'cpu', 'memory', 'disk', 'network',
        'visualization', 'graph', 'chart', 'create dashboard', 'make dashboard',
        'cpu usage', 'memory usage', 'performance', 'system metrics'
    ]
    alert_keywords = [
        'alert', 'notification', 'threshold', 'rule', 'warning', 'alarm',
        'firing', 'trigger', 'escalation', 'alert rule', 'notify'
    ]
    log_keywords = [
        'log', 'error', 'exception', 'debug', 'trace', 'search', 'show logs',
        'error logs', 'list logs', 'find errors', 'show errors', 'service', 'log analysis',
        'log search', 'stderr', 'container', 'stdout', 'syslog'
    ]
    dashboard_score = sum(1 for keyword in dashboard_keywords if keyword in query_lower)
    alert_score = sum(1 for keyword in alert_keywords if keyword in query_lower)
    log_score = sum(1 for keyword in log_keywords if keyword in query_lower)

    if log_score > dashboard_score and log_score > alert_score:
        return "log_search"
    elif dashboard_score > alert_score:
        return "dashboard"
    elif alert_score > 0:
        return "alert"
    else:
        if any(word in query_lower for word in ['error', 'issue', 'problem', 'fail', 'exception']):
            return "log_search"
        return "coordinator"

# Base Agent Class
class BaseGrafanaAgent:
    def __init__(self, agent_type: str):
        self.agent_type = agent_type
        self.model = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            api_key=os.environ.get("GOOGLE_API_KEY")
        )
        self.grafana_server_url = os.environ.get("GRAFANA_MCP_SERVER_URL", "http://localhost:8000")

    def get_system_prompt(self) -> str:
        local_tz = ZoneInfo(tzlocal.get_localzone_name())
        current_time = datetime.now(local_tz)
        formatted_time = current_time.strftime("%Y-%m-%d %H:%M:%S %Z")
        base_prompt = f"""
You are a specialized AI agent for Grafana observability tasks.
Current time: {formatted_time}
User timezone: IST (Indian Standard Time)

IMPORTANT RULES:
- Always query available datasources first and use their UIDs dynamically
- Convert all timestamps to IST format: YYYY-MM-DD HH:MM:SS IST
- Provide clear, actionable responses
- Be concise but helpful
"""
        return base_prompt + self.get_specialized_prompt()

    def get_specialized_prompt(self) -> str:
        return ""

    async def process_query(self, chat_history: List[Dict[str, str]]) -> str:
        try:
            system_prompt = {"role": "system", "content": self.get_system_prompt()}
            full_history = [system_prompt] + chat_history
            client = MultiServerMCPClient({
                "grafana": {
                    "url": f"{self.grafana_server_url}/mcp",
                    "transport": "streamable_http",
                }
            })
            tools = await client.get_tools()
            agent = create_react_agent(self.model, tools)
            result = await agent.ainvoke({"messages": full_history})

            if result and "messages" in result and len(result["messages"]) > 0:
                content = result["messages"][-1].content
                if isinstance(content, list):
                    if all(isinstance(item, str) for item in content):
                        return "\n".join(content)
                    else:
                        return "\n".join(str(item) for item in content)
                elif isinstance(content, str):
                    return content
                else:
                    return str(content)
            else:
                return "I apologize, but I couldn't process your request. Please try again."
        except Exception as e:
            print(f"Error in {self.agent_type} agent: {str(e)}")
            import traceback
            traceback.print_exc()
            return f"Sorry, I encountered an error while processing your request: {str(e)}"

# Specialized Agents
class DashboardAgent(BaseGrafanaAgent):
    def __init__(self):
        super().__init__("dashboard")

    def get_specialized_prompt(self) -> str:
        return """
 Dashboard for metrics:
- If the user says "make a CPU graph", do the following:
  1. Find a Prometheus datasource (use the first if only one exists).
  2. Search metric names for common CPU usage metrics (e.g., node_cpu_seconds_total, container_cpu_usage_seconds_total).
  3. Choose a default PromQL query like 100 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m])) by (instance) or rate(container_cpu_usage_seconds_total[5m]).
  4. Create a new dashboard with a panel showing that metric.
  5. Respond with confirmation, the dashboard link, and follow-up options:
     - Add memory graph
     - Rename panel or dashboard
     - Change time range
  6. Important: When calling update_dashboard, pass the dashboard input as a structured object, not as a string. Do NOT wrap the dashboard JSON inside quotes or YAML | blocks. Never wrap the dashboard definition in quotes or strings. It must be a raw structured JSON object (in JSON) or proper nested object (in YAML), not a stringified blob.

 Dashboard for logs (error analysis):
- If the user says "make an error log panel", "show errors in logs", or "make a dashboard for error", do the following:
  1. Find a Loki datasource (use the first if only one exists).
  2. Search for common log streams, prioritizing in this order:
     - {job="k8s", level="error"} (structured logging with level)
     - {job="k8s"} |~ "(?i)(error|err|exception|fail)" (regex for k8s logs)
     - {app="*"} |= "error" or {container="*"} |= "error" (fallbacks)
     - {job="varlogs"} |= "error" (legacy/traditional logs)
  3. Choose default LogQL queries:
     - For raw logs: {job="k8s", level="error"}
     - For time series: rate({job="k8s", level="error"}[5m])
- For grouping: rate({job="k8s", level="error"}[5m]) by (container)
  4. Create a new dashboard with the following panels:
     - Panel 1: *Error Logs* (Logs visualization) — raw error logs
     - Panel 2: *Error Rate Over Time* (Time Series) — trend over time
     - Panel 3: *Errors by Container* (Time Series) — grouped errors
     - Set dashboard time range to "Last 1 hour" and auto-refresh to "30s"
  5. Respond with confirmation, the dashboard link, and follow-up options:
     - Add warnings panel (using level="warning" or |~ "(?i)warn")
     - Change log query or regex pattern
     - Group errors by container, pod, or namespace
     - Adjust time range or add more filters
     - Filter by specific namespace or container
  6. Important: When calling update_dashboard, pass the dashboard input as a structured object, not as a string. Do NOT wrap the dashboard JSON inside quotes or YAML | blocks. Never wrap the dashboard definition in quotes or strings. It must be a raw structured JSON object (in JSON) or proper nested object (in YAML), not a stringified blob. - When setting panel color options, use only supported palette modes like palette-classic, palette-classic-by-name, continuous-*, shades, or thresholds. - Do NOT use palette_classic or any value with underscore — it will break.

"""  # You already have the full prompt text.

class AlertAgent(BaseGrafanaAgent):
    def __init__(self):
        super().__init__("alert")

    def get_specialized_prompt(self) -> str:
        return """
You are the ALERT SPECIALIST
 Alert Management:
- You can READ and ANALYZE existing alert rules using list_alert_rules and get_alert_rule_by_uid.
- For alert CREATION requests:
  1. First, create a dashboard panel with the appropriate metric or log query that would trigger the alert.
  2. Explain to the user: "I've created a dashboard panel that tracks [metric/condition]. To set up the alert, you can click the 'Alert' tab in the panel editor and configure the alert rule with your threshold."
  3. Provide the exact PromQL or LogQL query they should use.
  4. Offer to help them understand alert rule configuration.

  Example response for "create alert if error threshold breaches 1":
  "I'll create a dashboard panel to track your error rate. Here's what I'm setting up:

  *Error Rate Query*: rate({level="error"}[5m])  
  *Threshold*: 1 error per second  
  [Creates dashboard panel]

  To complete the alert setup:
  1. Open the panel → Edit → Alert tab  
  2. Set condition: rate({level="error"}[5m]) > 1  
  3. Configure notification channels  
  4. Set evaluation frequency (e.g., every 1m)  

  Would you like me to explain any of these steps in detail?"
"""  # You already have the full prompt text.

class LogSearchAgent(BaseGrafanaAgent):
    def __init__(self):
        super().__init__("log_search")

    def get_specialized_prompt(self) -> str:
        return """
You are the LOG SEARCH SPECIALIST
 Datasource Handling:
- Always start by querying the available datasources.
- Retrieve the UID of the relevant datasource dynamically. Do NOT hardcode.
- Use the UID in all queries (logs, metrics, dashboards, etc.).

 Log Queries (via Loki):
- Only use log data to answer.
- Do NOT use tools unrelated to logs.
- Strictly include only logs within the requested time window.

 If asked to show logs or show errors:
- Filter logs using level = "error"; if unavailable, try severity, log_level, or status.
- Format each log entry as plain key-value pairs (no braces, no JSON), for example:
  message: OOMKilled  
  timestamp: 2025-06-23 14:12:00 IST  
  container: auth-service
- After each log, add:
  suggestion: <your suggestion here>
- You may provide brief reasoning if helpful.

 If asked to summarize logs or summarize errors/issues:
- Query only level = error logs or standard error-pattern logs.
- DO NOT return raw logs.
- Provide a natural language summary of grouped issues.
- Mention affected services and timestamps.
- End with a recommendation.
- Example: Between 14:45 and 14:48, the auth-service encountered repeated OOMKilled errors. Investigate memory usage or resource limits.

 If asked a diagnostic question (e.g., “which service was OOMKilled?”):
- Use error logs to respond concisely (2-3 lines).
- DO NOT return raw logs.
- Mention affected container and timestamp if available.
- Provide a recommendation if relevant.
- Example: The auth-service was terminated at 14:47 due to an OOMKilled error. Consider adjusting memory limits.
"""  # You already have the full prompt text.

class CoordinatorAgent(BaseGrafanaAgent):
    def __init__(self):
        super().__init__("coordinator")

    def get_specialized_prompt(self) -> str:
        return """
You are the COORDINATOR agent. Your role:

CAPABILITIES:
- Handle general Grafana questions
- Provide overviews and guidance
- List available tools and capabilities

WORKFLOW:
1. Query available datasources
2. List available tools if asked
3. Provide helpful guidance

Focus on general assistance and tool discovery.
"""  # You already have the full prompt text.

# Multi-Agent System
class MultiAgentGrafanaSystem:
    def __init__(self):
        self.dashboard_agent = DashboardAgent()
        self.alert_agent = AlertAgent()
        self.log_agent = LogSearchAgent()
        self.coordinator = CoordinatorAgent()

    async def process_query(self, query: str, chat_history: List[Dict[str, str]]) -> Dict[str, Any]:
        agent_type = classify_query_intent(query)
        if agent_type == "dashboard":
            agent = self.dashboard_agent
        elif agent_type == "alert":
            agent = self.alert_agent
        elif agent_type == "log_search":
            agent = self.log_agent
        else:
            agent = self.coordinator
        response = await agent.process_query(chat_history)
        suggestions = self.get_suggestions(agent_type, response)
        return {
            "response": response,
            "agent_used": agent_type,
            "suggested_next_actions": suggestions
        }

    def get_suggestions(self, agent_type: str, response: str) -> List[str]:
        suggestion_map = {
            "dashboard": [
                "Add more panels to dashboard",
                "Create alerts for metrics",
                "Configure dashboard variables"
            ],
            "alert": [
                "Review alert thresholds",
                "Configure notifications",
                "Test alert conditions"
            ],
            "log_search": [
                "Create log dashboard",
                "Set up error alerts",
                "Filter by specific service"
            ],
            "coordinator": [
                "Create a dashboard",
                "Search for errors",
                "Set up alerts"
            ]
        }
        return suggestion_map.get(agent_type, [])[:3]

# FastAPI Setup
app = FastAPI(title="Multi-Agent Grafana MCP API", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

multi_agent_system = MultiAgentGrafanaSystem()

@app.get("/")
async def root():
    return {
        "message": "Multi-Agent Grafana MCP API is running",
        "agents": {
            "dashboard": "Handles dashboard creation and metrics visualization",
            "alert": "Manages alert rules and notifications",
            "log_search": "Searches and analyzes logs",
            "coordinator": "Handles general queries and guidance"
        }
    }

@app.post("/query")
async def query_grafana(request: QueryRequest):
    if request.uid is None:
        uid = str(uuid.uuid4())
        is_new_session = True
        redis_client.hset(f"meta:{uid}", mapping={
            "created_at": datetime.now().isoformat(),
            "last_used": datetime.now().isoformat()
        })
    else:
        uid = request.uid
        is_new_session = not redis_client.exists(get_session_key(uid))
        if is_new_session:
            redis_client.hset(f"meta:{uid}", mapping={
                "created_at": datetime.now().isoformat(),
                "last_used": datetime.now().isoformat()
            })
        else:
            redis_client.hset(f"meta:{uid}", "last_used", datetime.now().isoformat())

    history_raw = redis_client.lrange(get_session_key(uid), 0, -1)
    chat_history = []
    for item in history_raw:
        entry = json.loads(item)
        chat_history.append({"role": "user", "content": entry["query"]})
        chat_history.append({"role": "assistant", "content": entry["response"]})

    chat_history.append({"role": "user", "content": request.query})

    try:
        result = await multi_agent_system.process_query(request.query, chat_history)
        entry = {
            "query": request.query,
            "response": result["response"],
            "agent_used": result["agent_used"],
            "timestamp": datetime.now().isoformat()
        }
        redis_client.rpush(get_session_key(uid), json.dumps(entry))
        return QueryResponse(
            uid=uid,
            response=result["response"],
            is_new_session=is_new_session,
            agent_used=result["agent_used"],
            suggested_next_actions=result.get("suggested_next_actions", [])
        )
    except Exception as e:
        return QueryResponse(
            uid=uid,
            response=f"I apologize, but I encountered an error processing your request: {str(e)}",
            is_new_session=is_new_session,
            agent_used="error",
            suggested_next_actions=["Try rephrasing your question", "Check system status"]
        )

@app.get("/session/{uid}")
async def get_session_history(uid: str):
    if not redis_client.exists(get_session_key(uid)):
        return {"error": "Session not found"}
    history_raw = redis_client.lrange(get_session_key(uid), 0, -1)
    history = [json.loads(item) for item in history_raw]
    meta = redis_client.hgetall(f"meta:{uid}")
    return {
        "uid": uid,
        "history": history,
        "created_at": meta.get("created_at"),
        "last_used": meta.get("last_used"),
        "total_queries": len(history)
    }

@app.get("/sessions")
async def list_all_sessions():
    session_keys = redis_client.keys("meta:*")
    sessions = []
    for key in session_keys:
        uid = key.split(":")[1]
        meta = redis_client.hgetall(key)
        total_queries = redis_client.llen(get_session_key(uid))
        sessions.append({
            "uid": uid,
            "created_at": meta.get("created_at"),
            "last_used": meta.get("last_used"),
            "total_queries": total_queries
        })
    return {
        "total_sessions": len(sessions),
        "sessions": sessions
    }

@app.get("/health")
async def health_check():
    try:
        redis_client.ping()
        redis_status = "healthy"
    except:
        redis_status = "unhealthy"
    return {
        "status": "healthy",
        "redis": redis_status,
        "agents": ["dashboard", "alert", "log_search", "coordinator"]
    }

# Entry point
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8020)
