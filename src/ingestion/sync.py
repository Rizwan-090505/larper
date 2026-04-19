import httpx
from typing import Dict, Any, Optional
from config import settings


class ToDoListClient:
    def __init__(self):
        self.base_url = "https://api.todoist.com/rest/v2"
        self.headers = {
            "Authorization": f"Bearer {settings.API_KEY}",
            "Content-Type": "application/json"
        }

    async def create_task(self, content: str, due_date: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """Create a new task on ToDoList."""
        data = {"content": content}
        if due_date:
            data["due_date"] = due_date
        data.update(kwargs)  # Allow additional fields like priority, labels, etc.

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/tasks",
                headers=self.headers,
                json=data
            )
            response.raise_for_status()
            return response.json()

    async def get_task(self, task_id: str) -> Dict[str, Any]:
        """Retrieve a task from ToDoList by ID."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/tasks/{task_id}",
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()

    async def update_task(self, task_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing task on ToDoList."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/tasks/{task_id}",
                headers=self.headers,
                json=updates
            )
            response.raise_for_status()
            return response.json()

    async def delete_task(self, task_id: str) -> None:
        """Delete a task from ToDoList."""
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{self.base_url}/tasks/{task_id}",
                headers=self.headers
            )
            response.raise_for_status()


# Global client instance
todolist_client = ToDoListClient()