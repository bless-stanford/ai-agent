import os
from dotenv import load_dotenv
from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.mistral_ai import (
    MistralAIChatCompletion,
    MistralAIChatPromptExecutionSettings
)

class KernelBuilder:
    @staticmethod
    def create_kernel(
        model_id: str = "mistral-large-latest",  # or "mistral-small", "mistral-large"
        load_env: bool = True
    ) -> Kernel:
        """
        Creates and configures a Semantic Kernel instance with Mistral AI.
        
        Args:
            model_id (str): The Mistral AI model to use
            service_id (str): Service identifier for the chat completion service
            load_env (bool): Whether to load environment variables from .env file
            
        Returns:
            Kernel: Configured Semantic Kernel instance
        
        Environment Variables Required:
            MISTRAL_API_KEY: Your Mistral AI API key
        """
        # Load environment variables if requested
        if load_env:
            load_dotenv()
        
        # Get API key from environment variables
        api_key = os.getenv("MISTRAL_API_KEY")
        if not api_key:
            raise ValueError("MISTRAL_API_KEY environment variable is not set")

        # Create kernel instance
        kernel = Kernel()
        
        # Create chat completion service
        chat_completion_service = MistralAIChatCompletion(
            ai_model_id=model_id,
            api_key=api_key,
        )
        
        # Add the chat service to the kernel
        kernel.add_service(chat_completion_service)
        
        return kernel

    @staticmethod
    def get_default_settings() -> MistralAIChatPromptExecutionSettings:
        """
        Creates default execution settings for Mistral AI chat completion.
        
        Returns:
            MistralAIChatPromptExecutionSettings: Default settings for chat completion
        """
        return MistralAIChatPromptExecutionSettings()