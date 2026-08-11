from helpers.api import ApiHandler
from flask import Request


class HelloWorld(ApiHandler):

    async def process(self, input: dict, request: Request) -> dict:
        return {
            "success": True,
            "message": "Hello from Applicant 2.0 plugin!",
            "plugin": "applicant",
        }
