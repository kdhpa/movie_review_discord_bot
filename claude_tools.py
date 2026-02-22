"""
Claude Tools - Tool definitions and executor for Anthropic API
"""

import os
import glob as glob_module
import re


# Tool definitions for Anthropic Messages API
FILE_TOOLS = [
    {
        "name": "read_file",
        "description": "Read the contents of a file at the specified path. Returns the file content as text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to the file to read"
                }
            },
            "required": ["path"]
        }
    },
    {
        "name": "write_file",
        "description": "Write content to a file at the specified path. Creates the file if it doesn't exist, or overwrites it if it does.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to the file to write"
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file"
                }
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "edit_file",
        "description": "Edit a file by replacing old_string with new_string. The old_string must match exactly.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to the file to edit"
                },
                "old_string": {
                    "type": "string",
                    "description": "The exact string to find and replace"
                },
                "new_string": {
                    "type": "string",
                    "description": "The string to replace old_string with"
                }
            },
            "required": ["path", "old_string", "new_string"]
        }
    },
    {
        "name": "list_files",
        "description": "List files in the specified directory. Returns a list of file and directory names.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to the directory to list. Use '.' for current directory."
                }
            },
            "required": ["path"]
        }
    },
    {
        "name": "search_files",
        "description": "Search for files matching a glob pattern. Returns a list of matching file paths.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern to match files (e.g., '*.py', '**/*.js')"
                }
            },
            "required": ["pattern"]
        }
    },
    {
        "name": "grep",
        "description": "Search for a pattern in files. Returns matching lines with file paths and line numbers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regular expression pattern to search for"
                },
                "path": {
                    "type": "string",
                    "description": "File or directory path to search in. Defaults to current directory."
                },
                "include": {
                    "type": "string",
                    "description": "Glob pattern to filter files (e.g., '*.py')"
                }
            },
            "required": ["pattern"]
        }
    }
]


class ToolExecutor:
    """Executes tool calls within a restricted working directory"""

    def __init__(self, working_dir: str):
        self.working_dir = os.path.abspath(working_dir)

    def _resolve_path(self, path: str) -> str:
        """Resolve a relative path to an absolute path within working_dir"""
        # Handle absolute paths by making them relative
        if os.path.isabs(path):
            path = os.path.relpath(path, self.working_dir)

        resolved = os.path.normpath(os.path.join(self.working_dir, path))

        # Security: ensure the resolved path is within working_dir
        if not resolved.startswith(self.working_dir):
            raise ValueError(f"Path '{path}' is outside working directory")

        return resolved

    def execute(self, tool_name: str, tool_input: dict) -> str:
        """Execute a tool and return the result as a string"""
        try:
            if tool_name == "read_file":
                return self._read_file(tool_input["path"])
            elif tool_name == "write_file":
                return self._write_file(tool_input["path"], tool_input["content"])
            elif tool_name == "edit_file":
                return self._edit_file(
                    tool_input["path"],
                    tool_input["old_string"],
                    tool_input["new_string"]
                )
            elif tool_name == "list_files":
                return self._list_files(tool_input["path"])
            elif tool_name == "search_files":
                return self._search_files(tool_input["pattern"])
            elif tool_name == "grep":
                return self._grep(
                    tool_input["pattern"],
                    tool_input.get("path", "."),
                    tool_input.get("include")
                )
            else:
                return f"Error: Unknown tool '{tool_name}'"
        except Exception as e:
            return f"Error: {str(e)}"

    def _read_file(self, path: str) -> str:
        """Read a file and return its contents"""
        resolved = self._resolve_path(path)

        if not os.path.exists(resolved):
            return f"Error: File '{path}' not found"

        if not os.path.isfile(resolved):
            return f"Error: '{path}' is not a file"

        try:
            with open(resolved, 'r', encoding='utf-8') as f:
                content = f.read()
            return content
        except UnicodeDecodeError:
            return f"Error: Cannot read '{path}' as text (binary file?)"

    def _write_file(self, path: str, content: str) -> str:
        """Write content to a file"""
        resolved = self._resolve_path(path)

        # Create parent directories if needed
        parent_dir = os.path.dirname(resolved)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)

        with open(resolved, 'w', encoding='utf-8') as f:
            f.write(content)

        return f"Successfully wrote to '{path}'"

    def _edit_file(self, path: str, old_string: str, new_string: str) -> str:
        """Edit a file by replacing old_string with new_string"""
        resolved = self._resolve_path(path)

        if not os.path.exists(resolved):
            return f"Error: File '{path}' not found"

        with open(resolved, 'r', encoding='utf-8') as f:
            content = f.read()

        if old_string not in content:
            return f"Error: Could not find the specified text in '{path}'"

        # Count occurrences
        count = content.count(old_string)
        if count > 1:
            return f"Error: Found {count} occurrences of the text. Please provide more context to make it unique."

        new_content = content.replace(old_string, new_string, 1)

        with open(resolved, 'w', encoding='utf-8') as f:
            f.write(new_content)

        return f"Successfully edited '{path}'"

    def _list_files(self, path: str) -> str:
        """List files in a directory"""
        resolved = self._resolve_path(path)

        if not os.path.exists(resolved):
            return f"Error: Directory '{path}' not found"

        if not os.path.isdir(resolved):
            return f"Error: '{path}' is not a directory"

        entries = []
        for entry in sorted(os.listdir(resolved)):
            full_path = os.path.join(resolved, entry)
            if os.path.isdir(full_path):
                entries.append(f"[DIR]  {entry}")
            else:
                entries.append(f"[FILE] {entry}")

        if not entries:
            return "(empty directory)"

        return "\n".join(entries)

    def _search_files(self, pattern: str) -> str:
        """Search for files matching a glob pattern"""
        search_pattern = os.path.join(self.working_dir, pattern)
        matches = glob_module.glob(search_pattern, recursive=True)

        # Convert to relative paths
        relative_matches = []
        for match in matches:
            rel_path = os.path.relpath(match, self.working_dir)
            if os.path.isfile(match):
                relative_matches.append(rel_path)

        if not relative_matches:
            return f"No files found matching '{pattern}'"

        return "\n".join(sorted(relative_matches))

    def _grep(self, pattern: str, path: str, include: str = None) -> str:
        """Search for a pattern in files"""
        resolved = self._resolve_path(path)

        try:
            regex = re.compile(pattern)
        except re.error as e:
            return f"Error: Invalid regex pattern: {e}"

        results = []
        max_results = 100  # Limit results to prevent huge outputs

        if os.path.isfile(resolved):
            files_to_search = [resolved]
        elif os.path.isdir(resolved):
            # Get all files in directory
            if include:
                search_pattern = os.path.join(resolved, "**", include)
            else:
                search_pattern = os.path.join(resolved, "**", "*")
            files_to_search = [f for f in glob_module.glob(search_pattern, recursive=True) if os.path.isfile(f)]
        else:
            return f"Error: Path '{path}' not found"

        for file_path in files_to_search:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    for line_num, line in enumerate(f, 1):
                        if regex.search(line):
                            rel_path = os.path.relpath(file_path, self.working_dir)
                            results.append(f"{rel_path}:{line_num}: {line.rstrip()}")
                            if len(results) >= max_results:
                                results.append(f"... (limited to {max_results} results)")
                                return "\n".join(results)
            except (UnicodeDecodeError, PermissionError):
                continue

        if not results:
            return f"No matches found for pattern '{pattern}'"

        return "\n".join(results)
