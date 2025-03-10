import discord
import re
from semantic_kernel.contents import ChatHistory
from kernel.kernel_builder import KernelBuilder
from services.box_service import BoxService
from plugins.box_plugin import BoxPlugins
from semantic_kernel.functions import KernelArguments
from semantic_kernel.connectors.ai.function_choice_behavior import FunctionChoiceBehavior
import logging
import json

logger = logging.getLogger("agent")

MISTRAL_MODEL = "mistral-large-latest"
SYSTEM_PROMPT = """You are a helpful assistant named Dodobot that can access and manage various cloud services.
You can interact with services like Box, Dropbox, Gmail, and others to search for files, create folders, get download links, etc.

When a user asks about files, folders, or cloud storage, use the appropriate function to handle their request.
Never ask the user for their user ID, as it is automatically provided by the system.

For download and view links, always format your response consistently like this:
1. Start with a brief confirmation message (e.g., "Here is the download link for [filename]:")
2. Then provide the actual link on a separate line
3. Do not include raw function call data in your responses

If a service needs authorization, tell the user to use the !authorize-[service] command (e.g., !authorize-box, !authorize-dropbox).

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
    def __init__(self, max_context_messages=10):
        self.kernel = KernelBuilder.create_kernel(model_id=MISTRAL_MODEL)
        self.settings = KernelBuilder.get_default_settings()
        
        # Enable function calling in the settings
        self.settings.function_choice_behavior = FunctionChoiceBehavior.Auto()
        
        self.chat_service = self.kernel.get_service()
        self.chat_history = ChatHistory()
        self.chat_history.add_system_message(SYSTEM_PROMPT)
        self.MAX_LENGTH = 1900  # Leave room for extra characters
        self.max_context_messages = max_context_messages
        
        # Register Box plugins with the kernel
        self.box_service = BoxService()
        self.box_plugins = BoxPlugins(self.box_service)
        self.kernel.add_plugin(self.box_plugins, "Box")

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

        augmented_content = f"{original_content}\n\n[system: user_id={user_id}]"

        # Add the user's message to the chat history
        self.chat_history.add_user_message(augmented_content)
        
        # Trim history before getting response
        self._trim_chat_history()
        
        # Add the user ID to the kernel arguments for plugin access
        kernel_arguments = KernelArguments()
        kernel_arguments["user_id"] = user_id
        
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
            
            # Handle raw function call responses
            if response.content.startswith('[{"name":') and '"arguments":' in response.content:
                try:
                    # Try to parse it and format it nicely
                    function_data = json.loads(response.content)
                    if isinstance(function_data, list) and len(function_data) > 0:
                        func_call = function_data[0]
                        func_name = func_call.get("name", "")
                        args = func_call.get("arguments", {})
                        query = args.get("query", "")
                        
                        # Generic handling for various services and functions
                        service_name = func_name.split('-')[0] if '-' in func_name else ""
                        action_type = func_name.split('-')[1] if '-' in func_name else func_name
                        
                        if "get_file_download_link" in action_type or "download" in action_type:
                            formatted_response = f"I'll retrieve the download link for '{query}' from {service_name}..."
                        elif "search" in action_type:
                            formatted_response = f"I'm searching for '{query}' in your {service_name} account..."
                        elif "share" in action_type:
                            formatted_response = f"I'll prepare to share '{query}' from your {service_name} account..."
                        elif "create" in action_type:
                            formatted_response = f"I'll create '{query}' in your {service_name} account..."
                        elif "delete" in action_type:
                            formatted_response = f"I'll prepare to delete '{query}' from your {service_name} account..."
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
                "authorization required"
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
            
            # Always return a list of chunks
            if len(formatted_content) > self.MAX_LENGTH:
                return self.split_response(formatted_content)
            return [formatted_content]
            
        except Exception as e:
            logger.error(f"Error processing request: {str(e)}", exc_info=True)
            
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