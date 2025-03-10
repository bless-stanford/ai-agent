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
SYSTEM_PROMPT = """You are a helpful assistant named Dodobot that can access and manage a user's Box cloud storage. 
You can search for files, create folders, get download links, view links, share files, and delete files.
You can process natural language requests about Box files.

When a user asks about Box files, folders, or cloud storage, use the appropriate Box function to handle their request.
Never ask the user for their user ID, as it is automatically provided by the system.

If a user's Box account needs to be authorized or reauthorized, tell them to use the !authorize-box command.

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
        
        # Add the user ID to the kernel arguments for Box plugin access
        kernel_arguments = KernelArguments()
        # Store the user ID with the exact key name expected by the plugin functions
        user_id = str(message.author.id)
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
            
            # Check if response content contains Box auth error
            if "Your Box authorization has expired" in response.content or \
               "Please use the `!authorize-box` command" in response.content:
                error_message = (
                    "It looks like I need access to your Box account to perform this task. "
                    "Please use the `!authorize-box` command to connect your Box account."
                )
                self.chat_history.add_assistant_message(error_message)
                return [error_message]
                
            # Add the assistant's response to the chat history
            self.chat_history.add_assistant_message(response.content)
            
            # Log the response for debugging (exclude sensitive data)
            logger.info(f"Generated response for user {message.author.id} (length: {len(response.content)})")
            
            # Always return a list of chunks, even for short messages
            if len(response.content) > self.MAX_LENGTH:
                return self.split_response(response.content)
            return [response.content]
            
        except Exception as e:
            logger.error(f"Error processing request: {str(e)}", exc_info=True)
            
            # Check if this is an authentication error
            if "Box authorization has expired" in str(e) or "!authorize-box" in str(e):
                error_message = (
                    "I need to connect to your Box account to perform this task. "
                    "Please use the `!authorize-box` command to authorize access."
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