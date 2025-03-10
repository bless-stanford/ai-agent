from semantic_kernel.kernel import Kernel
from services.box_service import BoxService
from services.dropbox_service import DropboxService
from plugins.box_plugin import BoxPlugins
from plugins.dropbox_plugin import DropboxPlugins
import logging

logger = logging.getLogger("cloud_plugin_manager")

class CloudPluginManager:
    """
    Manager for cloud storage plugins to use with Semantic Kernel.
    Consolidates Box and Dropbox plugins into a single interface.
    """
    
    def __init__(self, box_service=None, dropbox_service=None):
        """
        Initialize the cloud plugin manager with service instances.
        If no services are provided, new ones will be created.
        
        Args:
            box_service: BoxService instance or None
            dropbox_service: DropboxService instance or None
        """
        self.box_service = box_service or BoxService()
        self.dropbox_service = dropbox_service or DropboxService()
        
        # Initialize plugin instances
        self.box_plugins = BoxPlugins(self.box_service)
        self.dropbox_plugins = DropboxPlugins(self.dropbox_service)
    
    def register_plugins(self, kernel: Kernel) -> Kernel:
        """
        Register all cloud storage plugins with the given kernel.
        
        Args:
            kernel: The Semantic Kernel instance
            
        Returns:
            Kernel: The same kernel with plugins registered
        """
        try:
            # Register Box plugins
            kernel.add_plugin(self.box_plugins, "box")
            logger.info("Box plugins registered with kernel")
            
            # Register Dropbox plugins
            kernel.add_plugin(self.dropbox_plugins, "dropbox")
            logger.info("Dropbox plugins registered with kernel")
            
            return kernel
        except Exception as e:
            logger.error(f"Error registering cloud plugins: {str(e)}")
            raise
    
    def get_plugin_descriptions(self) -> str:
        """
        Get a user-friendly description of all available cloud plugins.
        
        Returns:
            str: Formatted text with plugin descriptions
        """
        descriptions = "# Available Cloud Storage Plugins\n\n"
        
        # Box plugins
        descriptions += "## Box Plugins\n"
        descriptions += "Use these to interact with your Box account:\n"
        descriptions += "- `box.create_folder`: Create a new folder in Box\n"
        descriptions += "- `box.search_file`: Search for files in Box\n"
        descriptions += "- `box.delete_file`: Delete a file from Box\n"
        descriptions += "- `box.get_file_download_link`: Get a download link for a Box file\n"
        descriptions += "- `box.get_file_view_link`: Get a shareable view link for a Box file\n"
        descriptions += "- `box.share_file`: Share a Box file with another user\n\n"
        
        # Dropbox plugins
        descriptions += "## Dropbox Plugins\n"
        descriptions += "Use these to interact with your Dropbox account:\n"
        descriptions += "- `dropbox.create_folder`: Create a new folder in Dropbox\n"
        descriptions += "- `dropbox.search_file`: Search for files in Dropbox\n"
        descriptions += "- `dropbox.list_folder`: List files and folders in a Dropbox path\n"
        descriptions += "- `dropbox.delete_file`: Delete a file from Dropbox\n"
        descriptions += "- `dropbox.get_file_download_link`: Get a temporary download link for a Dropbox file\n"
        descriptions += "- `dropbox.share_file`: Create a shared link for a Dropbox file\n"
        
        return descriptions
    
    def update_user_context(self, kernel: Kernel, user_id: str) -> None:
        """
        Update the kernel context with user ID for cloud storage operations.
        
        Args:
            kernel: The Semantic Kernel instance
            user_id: The user's ID for cloud storage authentication
        """
        try:
            # Set user_id in variables
            if hasattr(kernel, 'data'):
                kernel.data["user_id"] = user_id
            elif hasattr(kernel, 'variables'):
                kernel.variables["user_id"] = user_id
            
            logger.info(f"Kernel context updated with user ID: {user_id}")
        except Exception as e:
            logger.error(f"Error updating kernel context: {str(e)}")
            raise