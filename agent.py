# agent.py
import discord
import re
from semantic_kernel.contents import ChatHistory
from kernel.kernel_builder import KernelBuilder
from semantic_kernel.functions import KernelArguments
from semantic_kernel.connectors.ai.function_choice_behavior import FunctionChoiceBehavior
import logging
import json
import os
from datetime import datetime, timedelta

from services.box_service import BoxService
from services.dropbox_service import DropboxService
from services.google_drive_service import GoogleDriveService
from services.gmail_service import GmailService

from plugins.cloud_plugin_manager import CloudPluginManager

logger = logging.getLogger("agent")

MISTRAL_MODEL = "mistral-large-latest"
SYSTEM_PROMPT = """You are a helpful assistant named Dodobot that can access and manage various cloud services.
You can interact with services like Box, Dropbox, Gmail, Google Drive, Google Calendar and others to search for files, create folders, get download links, manage calendars, etc.

Never ask the user for their user ID, as it is automatically provided by the system.
Do not expose implementation, internal values or functions to the user

For download and view links, always format your response consistently like this:
1. Start with a brief confirmation message (e.g., "Here is the download link for [filename]:")
2. Then provide the actual link on a separate line
3. Do not include raw function call data in your responses

If a service needs authorization, tell the user to use the !authorize-[service] command (e.g., !authorize-box).

Format your responses using Discord-compatible Markdown:
- Use **bold** for emphasis
- Use *italics* for secondary emphasis
- Use `code` for technical terms, commands, or short code snippets
- Use ```language
  code block
  ``` for multi-line code (where 'language' is python, javascript, etc)
- Use > for quotes
- Use ||text|| for spoilers

Do not use # for headers or * - for bullet points as these don't render in Discord.
Keep responses concise when possible, as Discord has a 2000-character limit per message."""

class MistralAgent:
    def __init__(self, max_context_messages=4):
        self.kernel = KernelBuilder.create_kernel(model_id=MISTRAL_MODEL)
        self.settings = KernelBuilder.get_default_settings()
        
        # Enable function calling in the settings
        self.settings.function_choice_behavior = FunctionChoiceBehavior.Auto()
        
        self.chat_service = self.kernel.get_service()
        self.chat_history = ChatHistory()
        self.chat_history.add_system_message(SYSTEM_PROMPT)
        self.MAX_LENGTH = 1900  # Leave room for extra characters
        self.max_context_messages = max_context_messages
        
        # Initialize cloud services
        self.box_service = BoxService()
        self.dropbox_service = DropboxService()
        self.google_drive_service = GoogleDriveService()
        self.gmail_service = GmailService()
        
        # Initialize plugin manager and register plugins
        self.cloud_plugin_manager = CloudPluginManager(
            box_service=self.box_service,
            dropbox_service=self.dropbox_service,
            google_drive_service=self.google_drive_service,
            gmail_service=self.gmail_service
        )
        
        # Register all cloud plugins with the kernel
        self.cloud_plugin_manager.register_plugins(self.kernel)
        
        # Add plugin descriptions to chat history to help the model understand available functions
        plugin_descriptions = self.cloud_plugin_manager.get_plugin_descriptions()
        self.chat_history.add_system_message(plugin_descriptions)

    def _trim_chat_history(self):
        """Keep only the most recent messages within the context window."""
        # Count number of non-system messages
        messages = [msg for msg in self.chat_history.messages if msg.role != "system"]
        
        # If we have more messages than our limit, remove oldest ones
        if len(messages) > self.max_context_messages:
            # Get the system message(s)
            system_messages = [msg for msg in self.chat_history.messages if msg.role == "system"]
            
            # Keep only the most recent messages
            recent_messages = messages[-self.max_context_messages:]
            
            # Reset chat history with system messages and recent context
            self.chat_history = ChatHistory()
            for msg in system_messages:
                self.chat_history.add_system_message(msg.content)
            
            # Add back recent messages in order
            for msg in recent_messages:
                if msg.role == "user":
                    self.chat_history.add_user_message(msg.content)
                elif msg.role == "assistant":
                    self.chat_history.add_assistant_message(msg.content)

    async def run(self, message: discord.Message):
        original_content = message.content
        user_id = str(message.author.id)

        # Handle file attachments
        attachment_info = ""
        file_paths = []
        if message.attachments:
            # Create temp directory if it doesn't exist
            if not os.path.exists("temp"):
                os.makedirs("temp")
                
            # Download all attachments
            for i, attachment in enumerate(message.attachments):
                file_path = f"temp/{attachment.filename}"
                await attachment.save(file_path)
                file_paths.append(file_path)
                attachment_info += f"\n[Attachment {i+1}: {attachment.filename}, path: {file_path}]"

        # Add attachment info to the message
        if attachment_info:
            augmented_content = f"{original_content}\n\n[system: user_id={user_id}, attached_files=true]{attachment_info}"
        else:
            augmented_content = f"{original_content}\n\n[system: user_id={user_id}]"

        # Add the user's message to the chat history
        self.chat_history.add_user_message(augmented_content)
        
        # Trim history before getting response
        self._trim_chat_history()
        
        # Add the user ID to the kernel arguments for plugin access
        kernel_arguments = KernelArguments()
        kernel_arguments["user_id"] = user_id
        
        # Add file paths to the kernel arguments if there are any
        if file_paths:
            kernel_arguments["file_paths"] = file_paths
            if len(file_paths) == 1:
                kernel_arguments["file_path"] = file_paths[0]
        
        # CALENDAR EVENT PREPROCESSING
        # Check if this is a calendar event creation request
        calendar_patterns = [
            r"add (?:a )?(?:calendar )?event",
            r"schedule (?:a )?(?:calendar )?event", 
            r"create (?:a )?(?:calendar )?event",
            r"add to (?:my )?calendar",
            r"put (?:this )?(?:on|in) (?:my )?calendar"
        ]
        
        is_calendar_request = any(re.search(pattern, original_content.lower()) for pattern in calendar_patterns)
        
        if is_calendar_request:
            # Add preprocessing instructions to help the model format the date properly
            # This gives the AI clearer instructions about how to handle dates
            # Add preprocessing instructions to help the model format the date properly
            # This gives the AI clearer instructions about how to handle dates
            
            # # Get current date
            # today = datetime.now()
            # tomorrow = today + timedelta(days=1)

            # # Ensure we're working with the current year explicitly
            # # current_year = today.year

            # # Check for specific year mentions
            # year_pattern = r'\b(20\d{2})\b'  # Matches years like 2024, 2025, etc.
            # year_match = re.search(year_pattern, original_content)
            # specified_year = int(year_match.group(1)) if year_match else current_year

            # # Log the year detection
            # logger.info(f"Year detection: current_year={current_year}, specified_year={specified_year}")

            calendar_helper = f"""
            [SYSTEM NOTE: This appears to be a calendar event request. Use these guidelines:
            0. The current date is 2025-03-12
            1. When parsing dates like "tomorrow", "next week", etc., convert them to specific dates based on the current date 
            2. Always use YYYY-MM-DD format for dates with the current year 2025
            3. For "tomorrow", use the day right after the specified day
            4. For requests without a specified year, always use 2025
            5. For times, use 24-hour format (HH:MM)
            6. Be sure to set the start_date_time and end_date_time parameters explicitly with the year 2025
                        """
            
            # calendar_helper = f"""
            # [SYSTEM NOTE: This appears to be a calendar event request. Use these guidelines:
            # 1. When parsing dates like "tomorrow", "next week", etc., convert them to specific dates based on the current date ({today.strftime('%B %d, %Y')})
            # 2. Always use YYYY-MM-DD format for dates with the current year {current_year}
            # 3. For "tomorrow", use {tomorrow.strftime('%B %d, %Y')}
            # 4. For requests without a specified year, always use {current_year}
            # 5. For times, use 24-hour format (HH:MM)
            # 6. Be sure to set the start_date_time and end_date_time parameters explicitly with the year {current_year}]
            #             """
            # Insert into chat history
            self.chat_history.add_system_message(calendar_helper)
            
            # Check for relative date terms
            tomorrow_patterns = [r"tomorrow", r"next day"]
            has_tomorrow = any(re.search(pattern, original_content.lower()) for pattern in tomorrow_patterns)
            
            # Extract the time
            time_patterns = [
                r"at (\d{1,2})(?::(\d{2}))?\s*(am|pm|AM|PM)?",  # matches "at 3pm", "at 3:30pm", "at 15:00"
                r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|AM|PM)"  # matches "3pm", "3:30pm"
            ]
            
            event_time = None
            for pattern in time_patterns:
                match = re.search(pattern, original_content)
                if match:
                    hour = int(match.group(1))
                    minute = int(match.group(2)) if match.group(2) else 0
                    ampm = match.group(3).lower() if match.group(3) else None
                    
                    # Convert to 24-hour format
                    if ampm == "pm" and hour < 12:
                        hour += 12
                    elif ampm == "am" and hour == 12:
                        hour = 0
                    
                    event_time = (hour, minute)
                    break
            
            # Default to noon if no time specified
            if event_time is None:
                event_time = (12, 0)
            
            # Create ISO formatted datetime strings
            if has_tomorrow:
                event_date = tomorrow
            else:
                event_date = today
                
            # Create datetime with the specified time
            event_start = event_date.replace(hour=event_time[0], minute=event_time[1], second=0, microsecond=0)
            event_end = event_start + timedelta(hours=1)  # Default to 1-hour events
            
            # Format as ISO 8601
            start_iso = event_start.isoformat()
            end_iso = event_end.isoformat()
            
            # Add these to the kernel arguments
            kernel_arguments["explicit_start_time"] = start_iso
            kernel_arguments["explicit_end_time"] = end_iso
            
            # Log the processed dates
            logger.info(f"Calendar event preprocessing: Identified start={start_iso}, end={end_iso}")
        
        # Update user context in cloud plugin manager
        self.cloud_plugin_manager.update_user_context(self.kernel, user_id)
        
        # Log the user ID to verify it's correct
        logger.info(f"Setting user_id in kernel arguments to: {user_id}")
        
        try:
            # Log the request for debugging
            logger.info(f"Processing request from user {message.author.id}: {message.content}")
            
            # Get response with function calling enabled
            response = await self.chat_service.get_chat_message_content(
                chat_history=self.chat_history,
                settings=self.settings,
                kernel=self.kernel,
                arguments=kernel_arguments
            )
            
            # If this is a calendar request, we need to manually adjust the function call
            if is_calendar_request and response.content.startswith('[{"name":') and '"arguments":' in response.content:
                try:
                    function_data = json.loads(response.content)
                    if isinstance(function_data, list) and len(function_data) > 0:
                        func_call = function_data[0]
                        func_name = func_call.get("name", "")
                        
                        # If this is a calendar add_event function
                        if "add_event" in func_name:
                            args = func_call.get("arguments", {})
                            
                            # Check if we have explicit times calculated
                            if "explicit_start_time" in kernel_arguments and "explicit_end_time" in kernel_arguments:
                                # Override the start and end times
                                args["start_date_time"] = kernel_arguments["explicit_start_time"]
                                args["end_date_time"] = kernel_arguments["explicit_end_time"]
                                
                                # Update the function call with corrected arguments
                                func_call["arguments"] = args
                                function_data[0] = func_call
                                
                                # Execute the function call manually with the corrected data
                                plugin_name, function_name = func_name.split('.')
                                plugin = getattr(self.cloud_plugin_manager, f"{plugin_name}_plugins")
                                function = getattr(plugin, function_name)
                                
                                # Execute with the corrected arguments
                                result = await function(**args)
                                
                                # Create a proper response
                                summary = args.get("summary", "event")
                                response.content = f"I've added your {summary} to your calendar for tomorrow ({tomorrow.strftime('%A, %B %d, %Y')}) at {event_time[0]}:{event_time[1]:02d}. {result}"
                                
                                # Log the adjustment
                                logger.info(f"Adjusted calendar event datetime: {args['start_date_time']} to {args['end_date_time']}")
                except Exception as e:
                    logger.error(f"Error processing calendar function call: {str(e)}", exc_info=True)
            
            # Rest of the function remains unchanged
            # Handle raw function call responses
            elif response.content.startswith('[{"name":') and '"arguments":' in response.content:
                try:
                    # Try to parse it and format it nicely
                    function_data = json.loads(response.content)
                    if isinstance(function_data, list) and len(function_data) > 0:
                        func_call = function_data[0]
                        func_name = func_call.get("name", "")
                        args = func_call.get("arguments", {})
                        query = args.get("query", "")
                        
                        # Determine which service is being used
                        if "box" in func_name.lower():
                            service_name = "Box"
                        elif "dropbox" in func_name.lower():
                            service_name = "Dropbox"
                        elif "gdrive" in func_name.lower() or "google_drive" in func_name.lower():
                            service_name = "Google Drive"
                        elif "gmail" in func_name.lower() or "email" in func_name.lower():
                            service_name = "Gmail"
                        else:
                            service_name = "cloud service"
                        
                        # Determine action type
                        if "get_file_download_link" in func_name or "download" in func_name:
                            formatted_response = f"I'll retrieve the download link for '{query}' from {service_name}..."
                        elif "search" in func_name:
                            if service_name == "Gmail":
                                formatted_response = f"I'm searching for emails with query '{query}' in your {service_name} account..."
                            else:
                                formatted_response = f"I'm searching for '{query}' in your {service_name} account..."
                        elif "share" in func_name:
                            formatted_response = f"I'll prepare to share '{query}' from your {service_name} account..."
                        elif "create_calendar" in func_name:
                            calendar_name = args.get("calendar_name", "new calendar")
                            formatted_response = f"I'm creating a new calendar '{calendar_name}' in your Google Calendar account..."
                        elif "add_event" in func_name or "create_event" in func_name:
                            summary = args.get("summary", "event")
                            formatted_response = f"I'm adding the event '{summary}' to your Google Calendar..."
                        elif "create" in func_name:
                            formatted_response = f"I'll create '{query}' in your {service_name} account..."
                        elif "delete" in func_name:
                            formatted_response = f"I'll prepare to delete '{query}' from your {service_name} account..."
                        elif "list" in func_name or "get_events" in func_name:
                            path = args.get("path", "root folder")
                            formatted_response = f"I'll list the contents in your {service_name} account..."
                        elif "upload" in func_name:
                            file_name = args.get("file_name", "your file")
                            formatted_response = f"I'm uploading '{file_name}' to your {service_name} account..."
                        elif "get_recent_emails" in func_name:
                            unread_only = args.get("unread_only", False)
                            status = "unread " if unread_only else ""
                            formatted_response = f"I'm retrieving your recent {status}emails from Gmail..."
                        elif "get_email" in func_name:
                            message_id = args.get("message_id", "")
                            formatted_response = f"I'm retrieving the email message from Gmail..."
                        elif "send_email" in func_name:
                            to_address = args.get("to_address", "")
                            formatted_response = f"I'm sending an email to {to_address}..."
                        elif "mark_as_read" in func_name:
                            formatted_response = f"I'm marking the email as read in your Gmail account..."
                        else:
                            formatted_response = f"I'm processing your {service_name} request..."
                        
                        response.content = formatted_response
                except Exception as parse_error:
                    logger.error(f"Error parsing function call: {str(parse_error)}")
                    response.content = "I'm processing your request..."
            
            # Check for authorization errors across different services
            auth_error_phrases = [
                "authorization has expired", 
                "needs to be authorized", 
                "Please use the `!authorize",
                "not authorized",
                "authorization required",
                "Google Drive authorization has expired",
                "Gmail authorization has expired"
            ]
            
            if any(phrase in response.content for phrase in auth_error_phrases):
                # Extract the service name if available
                service_match = re.search(r'!authorize-(\w+)', response.content)
                service_name = service_match.group(1) if service_match else "service"
                
                error_message = (
                    f"I need access to your {service_name} account to perform this task. "
                    f"Please use the `!authorize-{service_name}` command to connect your account."
                )
                self.chat_history.add_assistant_message(error_message)
                
                # Clean up temporary files
                for path in file_paths:
                    if os.path.exists(path):
                        os.remove(path)
                
                return [error_message]
            
            # Add the assistant's response to the chat history
            self.chat_history.add_assistant_message(response.content)
            
            # Format links consistently for better UI
            formatted_content = response.content
            
            # Generic link pattern that should match most download links
            link_pattern = r'(https?://\S+)'
            
            if re.search(link_pattern, formatted_content):
                file_name = None
                
                # Try to extract filename from the context
                filename_patterns = [
                    r"file ['\"]([^'\"]+)['\"]",
                    r"file (\S+\.\w+)",
                    r"download link for ['\"]?([^'\"]+)['\"]?",
                    r"link for ['\"]?([^'\"]+)['\"]?"
                ]
                
                for pattern in filename_patterns:
                    match = re.search(pattern, formatted_content, re.IGNORECASE)
                    if match:
                        file_name = match.group(1)
                        break
                
                # If we found a filename and it looks like a proper filename with extension
                if file_name and '.' in file_name:
                    links = re.findall(link_pattern, formatted_content)
                    for link in links:
                        # Skip links that appear to be part of instructions or formatting
                        if "!authorize" in link or "example" in link.lower():
                            continue
                        
                        # Format a download button
                        if not formatted_content.startswith("Download"):
                            # Only insert a clear Download line if we don't already have one
                            if "download" not in formatted_content.lower()[:50]:
                                formatted_content = f"Download {file_name}\n\n{formatted_content}"
            
            # Log the response for debugging
            logger.info(f"Generated response for user {message.author.id} (length: {len(formatted_content)})")
            
            # Clean up temporary files
            for path in file_paths:
                if os.path.exists(path):
                    os.remove(path)
            
            # Always return a list of chunks
            if len(formatted_content) > self.MAX_LENGTH:
                return self.split_response(formatted_content)
            return [formatted_content]
            
        except Exception as e:
            logger.error(f"Error processing request: {str(e)}", exc_info=True)
            
            # Clean up temporary files on error
            for path in file_paths:
                if os.path.exists(path):
                    os.remove(path)
            
            # Check for authentication errors in the exception
            if any(phrase in str(e) for phrase in ["authorization", "authorize", "authenticate"]):
                service_match = re.search(r'!authorize-(\w+)', str(e))
                service_name = service_match.group(1) if service_match else "service"
                
                error_message = (
                    f"I need to connect to your {service_name} account to perform this task. "
                    f"Please use the `!authorize-{service_name}` command to authorize access."
                )
                self.chat_history.add_assistant_message(error_message)
                return [error_message]
            
            # For other errors
            error_message = f"Sorry, I encountered an error while processing your request. Please try again later."
            self.chat_history.add_assistant_message(error_message)
            return [error_message]

    def split_response(self, content: str) -> list[str]:
        chunks = []
        
        # Use regex to split content into code blocks and regular text
        code_block_pattern = r'(```(?:\w+\n)?[\s\S]*?```)'
        parts = re.split(code_block_pattern, content)
        
        current_chunk = ""
        
        for part in parts:
            if part.strip() == "":
                continue
                
            is_code_block = part.startswith('```') and part.endswith('```')
            
            if is_code_block:
                # If current chunk plus code block would exceed limit
                if len(current_chunk) + len(part) > self.MAX_LENGTH:
                    if current_chunk:
                        chunks.append(current_chunk.strip())
                    # If code block itself exceeds limit, split it
                    if len(part) > self.MAX_LENGTH:
                        code_chunks = self._split_code_block(part)
                        chunks.extend(code_chunks)
                    else:
                        current_chunk = part
                else:
                    current_chunk += ('\n' if current_chunk else '') + part
            else:
                # Split non-code text by sentences
                sentences = re.split(r'([.!?]\s+)', part)
                
                for i in range(0, len(sentences), 2):
                    sentence = sentences[i]
                    punctuation = sentences[i + 1] if i + 1 < len(sentences) else ''
                    full_sentence = sentence + punctuation
                    
                    # If adding this sentence would exceed limit
                    if len(current_chunk) + len(full_sentence) > self.MAX_LENGTH:
                        if current_chunk:
                            chunks.append(current_chunk.strip())
                        current_chunk = full_sentence
                    else:
                        current_chunk += full_sentence
        
        if current_chunk:
            chunks.append(current_chunk.strip())
        
        # Post-process chunks to ensure proper markdown closing
        return self._ensure_markdown_consistency(chunks)

    def _split_code_block(self, code_block: str) -> list[str]:
        """Split a large code block into smaller chunks while preserving syntax."""
        # Extract language if present
        first_line_end = code_block.find('\n')
        language = code_block[3:first_line_end].strip() if first_line_end > 3 else ''
        
        # Remove original backticks and language
        code = code_block[3 + len(language):].strip('`').strip()
        
        chunks = []
        current_chunk = ''
        
        for line in code.split('\n'):
            if len(current_chunk) + len(line) + 8 > self.MAX_LENGTH:  # 8 accounts for backticks and newline
                if current_chunk:
                    chunks.append(f"```{language}\n{current_chunk.strip()}```")
                current_chunk = line
            else:
                current_chunk += ('\n' if current_chunk else '') + line
        
        if current_chunk:
            chunks.append(f"```{language}\n{current_chunk.strip()}```")
        
        return chunks

    def _ensure_markdown_consistency(self, chunks: list[str]) -> list[str]:
        """Ensure that markdown formatting is properly closed in each chunk."""
        processed_chunks = []
        
        for i, chunk in enumerate(chunks):
            # Track open formatting
            bold_count = chunk.count('**') % 2
            italic_count = chunk.count('*') % 2
            spoiler_count = chunk.count('||') % 2
            
            # Close any open formatting
            if bold_count:
                chunk += '**'
            if italic_count:
                chunk += '*'
            if spoiler_count:
                chunk += '||'
                
            # If this is not the last chunk and ends with a partial code block
            if i < len(chunks) - 1 and chunk.count('```') % 2:
                chunk += '\n```'
                
            processed_chunks.append(chunk)
        
        return processed_chunks