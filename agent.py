import discord
from semantic_kernel.contents import ChatHistory
from kernel.kernel_builder import KernelBuilder

MISTRAL_MODEL = "mistral-large-latest"
SYSTEM_PROMPT = "You are a helpful assistant. Your name is Dodobot"

class MistralAgent:
    def __init__(self):
        self.kernel = KernelBuilder.create_kernel(model_id=MISTRAL_MODEL)
        self.settings = KernelBuilder.get_default_settings()
        self.chat_service = self.kernel.get_service()

    async def run(self, message: discord.Message):
        # Create chat history and add messages
        chat_history = ChatHistory()
        chat_history.add_system_message(SYSTEM_PROMPT)
        chat_history.add_user_message(message.content)

        response = await self.chat_service.get_chat_message_content(
            chat_history=chat_history,
            settings=self.settings
        )
        
        return response.content