"""honest-drive-mcp — minimal Google Drive MCP server with full permission management.

Fills a real gap in the official Anthropic Drive connector, which cannot set
or modify sharing permissions on files/folders. Same trust model as the rest
of the honest-* family: your data flows only between your machine and Google.

Exposes 8 tools over MCP stdio: list_files, get_file, read_file, create_file,
create_folder, share_file, list_permissions, remove_permission.

Author: Bartosz Kuć <firma@bartosza.pl>
Repo:   https://github.com/bartosz-kuc/honest-drive-mcp
License: MIT
"""

import asyncio
import base64
import io
import json
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

# Full drive scope needed for sharing/permission management (the whole point of this MCP).
SCOPES = ["https://www.googleapis.com/auth/drive"]

HERE = Path(__file__).parent
CRED_PATH = HERE / "credentials.json"
TOKEN_PATH = HERE / "token.json"


def get_service():
    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CRED_PATH), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json())
    return build("drive", "v3", credentials=creds, cache_discovery=False)


server = Server("drive-personal")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="list_files",
            description=(
                "List/search files. Use Drive query syntax in `query` "
                "(e.g. \"name contains 'invoice' and mimeType='application/pdf'\"). "
                "Optional folder_id restricts to that folder's direct children."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Drive query, e.g. \"name contains 'foo'\""},
                    "folder_id": {"type": "string", "description": "If set, restrict to children of this folder"},
                    "max_results": {"type": "integer", "default": 50, "maximum": 200},
                    "include_trashed": {"type": "boolean", "default": False},
                },
            },
        ),
        Tool(
            name="get_file",
            description="Get full metadata for a file/folder by id.",
            inputSchema={
                "type": "object",
                "properties": {"file_id": {"type": "string"}},
                "required": ["file_id"],
            },
        ),
        Tool(
            name="read_file",
            description=(
                "Download file content. For text files returns UTF-8 text; for binary "
                "files returns base64. Google-native docs are exported (Docs→text, Sheets→CSV, Slides→text)."
            ),
            inputSchema={
                "type": "object",
                "properties": {"file_id": {"type": "string"}},
                "required": ["file_id"],
            },
        ),
        Tool(
            name="create_file",
            description=(
                "Upload a file. Pass content as `text_content` (UTF-8 string) OR `base64_content` "
                "(for binary). If parent_id omitted, file lands in My Drive root."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "parent_id": {"type": "string"},
                    "mime_type": {"type": "string", "description": "e.g. text/plain, image/jpeg, application/pdf"},
                    "text_content": {"type": "string"},
                    "base64_content": {"type": "string"},
                },
                "required": ["name", "mime_type"],
            },
        ),
        Tool(
            name="create_folder",
            description="Create a folder. If parent_id omitted, folder lands in My Drive root.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "parent_id": {"type": "string"},
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="share_file",
            description=(
                "Share a file or folder with someone. Missing in the official connector. "
                "Roles: reader (view), commenter, writer (edit), fileOrganizer, organizer, owner. "
                "send_notification=false by default (no email sent to recipient)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_id": {"type": "string"},
                    "email": {"type": "string", "description": "Recipient email"},
                    "role": {
                        "type": "string",
                        "enum": ["reader", "commenter", "writer", "fileOrganizer", "organizer", "owner"],
                        "default": "reader",
                    },
                    "send_notification": {"type": "boolean", "default": False},
                    "message": {"type": "string", "description": "Optional message included in notification email (only if send_notification=true)"},
                },
                "required": ["file_id", "email"],
            },
        ),
        Tool(
            name="list_permissions",
            description="List all permissions on a file/folder (who has access and with what role).",
            inputSchema={
                "type": "object",
                "properties": {"file_id": {"type": "string"}},
                "required": ["file_id"],
            },
        ),
        Tool(
            name="remove_permission",
            description="Revoke a specific permission by permission_id (get ids from list_permissions).",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_id": {"type": "string"},
                    "permission_id": {"type": "string"},
                },
                "required": ["file_id", "permission_id"],
            },
        ),
    ]


GOOGLE_EXPORT_MAP = {
    "application/vnd.google-apps.document": ("text/plain", "text"),
    "application/vnd.google-apps.spreadsheet": ("text/csv", "text"),
    "application/vnd.google-apps.presentation": ("text/plain", "text"),
}

TEXT_MIME_PREFIXES = ("text/", "application/json", "application/xml", "application/javascript")


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    svc = get_service()

    if name == "list_files":
        parts = []
        if arguments.get("query"):
            parts.append(arguments["query"])
        if arguments.get("folder_id"):
            parts.append(f"'{arguments['folder_id']}' in parents")
        if not arguments.get("include_trashed", False):
            parts.append("trashed=false")
        q = " and ".join(parts) if parts else None

        params: dict[str, Any] = {
            "pageSize": arguments.get("max_results", 50),
            "fields": "files(id,name,mimeType,size,modifiedTime,parents,webViewLink,owners(emailAddress))",
        }
        if q:
            params["q"] = q
        result = svc.files().list(**params).execute()
        return [TextContent(type="text", text=json.dumps(result.get("files", []), ensure_ascii=False, indent=2))]

    if name == "get_file":
        meta = svc.files().get(
            fileId=arguments["file_id"],
            fields="id,name,mimeType,size,modifiedTime,createdTime,parents,webViewLink,owners,capabilities,shared,starred,trashed",
        ).execute()
        return [TextContent(type="text", text=json.dumps(meta, ensure_ascii=False, indent=2))]

    if name == "read_file":
        file_id = arguments["file_id"]
        meta = svc.files().get(fileId=file_id, fields="mimeType,name,size").execute()
        mime = meta.get("mimeType", "")

        buf = io.BytesIO()
        if mime in GOOGLE_EXPORT_MAP:
            export_mime, encoding = GOOGLE_EXPORT_MAP[mime]
            request = svc.files().export_media(fileId=file_id, mimeType=export_mime)
        else:
            request = svc.files().get_media(fileId=file_id)
            encoding = "text" if any(mime.startswith(p) for p in TEXT_MIME_PREFIXES) else "base64"

        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

        data = buf.getvalue()
        if encoding == "text":
            return [TextContent(type="text", text=json.dumps({
                "name": meta.get("name"),
                "mime_type": mime,
                "encoding": "text",
                "content": data.decode("utf-8", errors="replace"),
            }, ensure_ascii=False))]
        return [TextContent(type="text", text=json.dumps({
            "name": meta.get("name"),
            "mime_type": mime,
            "encoding": "base64",
            "content": base64.b64encode(data).decode("ascii"),
        }))]

    if name == "create_file":
        text = arguments.get("text_content")
        b64 = arguments.get("base64_content")
        if (text is None) == (b64 is None):
            raise ValueError("Pass exactly one of text_content or base64_content.")
        raw = text.encode("utf-8") if text is not None else base64.b64decode(b64)

        metadata: dict[str, Any] = {"name": arguments["name"]}
        if arguments.get("parent_id"):
            metadata["parents"] = [arguments["parent_id"]]
        media = MediaIoBaseUpload(io.BytesIO(raw), mimetype=arguments["mime_type"], resumable=False)
        created = svc.files().create(
            body=metadata, media_body=media,
            fields="id,name,mimeType,size,webViewLink,parents",
        ).execute()
        return [TextContent(type="text", text=json.dumps(created, ensure_ascii=False, indent=2))]

    if name == "create_folder":
        metadata: dict[str, Any] = {
            "name": arguments["name"],
            "mimeType": "application/vnd.google-apps.folder",
        }
        if arguments.get("parent_id"):
            metadata["parents"] = [arguments["parent_id"]]
        created = svc.files().create(
            body=metadata,
            fields="id,name,webViewLink,parents",
        ).execute()
        return [TextContent(type="text", text=json.dumps(created, ensure_ascii=False, indent=2))]

    if name == "share_file":
        perm_body: dict[str, Any] = {
            "type": "user",
            "role": arguments.get("role", "reader"),
            "emailAddress": arguments["email"],
        }
        params: dict[str, Any] = {
            "fileId": arguments["file_id"],
            "body": perm_body,
            "sendNotificationEmail": arguments.get("send_notification", False),
            "fields": "id,type,role,emailAddress",
        }
        if arguments.get("message") and arguments.get("send_notification"):
            params["emailMessage"] = arguments["message"]
        # Ownership transfer needs an extra flag.
        if arguments.get("role") == "owner":
            params["transferOwnership"] = True
        result = svc.permissions().create(**params).execute()
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    if name == "list_permissions":
        result = svc.permissions().list(
            fileId=arguments["file_id"],
            fields="permissions(id,type,role,emailAddress,domain,displayName)",
        ).execute()
        return [TextContent(type="text", text=json.dumps(result.get("permissions", []), ensure_ascii=False, indent=2))]

    if name == "remove_permission":
        svc.permissions().delete(
            fileId=arguments["file_id"],
            permissionId=arguments["permission_id"],
        ).execute()
        return [TextContent(type="text", text=json.dumps({
            "deleted": True,
            "file_id": arguments["file_id"],
            "permission_id": arguments["permission_id"],
        }))]

    raise ValueError(f"Unknown tool: {name}")


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def sync_main():
    """Sync entry point for console script."""
    asyncio.run(main())


if __name__ == "__main__":
    sync_main()
