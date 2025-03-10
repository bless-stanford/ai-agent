from semantic_kernel.functions import kernel_function
from semantic_kernel.functions.kernel_function_from_prompt import KernelFunctionFromPrompt
from services.dropbox_service import DropboxService
import logging

logger = logging.getLogger("dropbox_plugins")

class DropboxPlugins:
    """
    Plugins for interacting with Dropbox cloud storage.
    """
    
    def __init__(self, dropbox_service=None):
        """
        Initialize the Dropbox plugins with a DropboxService.
        If no service is provided, a new one will be created.
        """
        self.dropbox_service = dropbox_service or DropboxService()
    
    @kernel_function(
        name="create_folder",
        description="Creates a new folder in the user's Dropbox account"
    )
    async def create_folder(
        self,
        folder_path: str,
        user_id: str = None,
        kernel = None
    ) -> str:
        """
        Creates a new folder in the user's Dropbox account.
        
        Args:
            folder_path: Full path of the folder to create (e.g., "/Documents/Projects")
            user_id: The user's ID (automatically provided)
            
        Returns:
            str: Success message with folder details or error message
        """
        try:
            if not user_id:
                return "Error: User ID not available. Please try again later."
            
            # Ensure path starts with /
            if not folder_path.startswith('/'):
                folder_path = '/' + folder_path
            
            folder = await self.dropbox_service.create_folder(user_id, folder_path)
            
            if folder and 'metadata' in folder:
                return f"Folder '{folder_path}' created successfully!"
            else:
                return f"Failed to create folder '{folder_path}'."
                
        except Exception as e:
            logger.error(f"Error creating folder: {str(e)}")
            return f"An error occurred while creating the folder: {str(e)}"
    
    @kernel_function(
        name="search_file",
        description="Searches for files in the user's Dropbox account and returns details in a user friendly way"
    )
    async def search_file(
        self,
        query: str,
        path: str = "",
        user_id: str = None,
        kernel = None
    ) -> str:
        """
        Searches for files in the user's Dropbox account.
        
        Args:
            query: Search query or file name
            path: Path to search in (default: root folder)
            user_id: The user's ID (automatically provided)
            
        Returns:
            str: File details or search results summary
        """
        try:
            # Get user_id from kernel.data instead of function parameter
            if not user_id and kernel and hasattr(kernel, 'arguments'):
                user_id = kernel.arguments.get("user_id")
            
            if not user_id:
                return "Error: User ID not available. Please try again later."
            
            search_results = await self.dropbox_service.search_files(user_id, query, path)
            
            if not search_results or not search_results.get('matches') or len(search_results['matches']) == 0:
                return f"No files found matching '{query}'."
            
            # In Dropbox API, the metadata is nested under the match object
            files = [match['metadata'] for match in search_results['matches']]
            
            if len(files) == 1:
                return self._create_file_detail(files[0])
            
            # If multiple files, return a summary
            return self._create_search_results_summary(files)
                
        except Exception as e:
            logger.error(f"Error searching files: {str(e)}")
            return f"An error occurred while searching for files: {str(e)}"
    
    @kernel_function(
        name="list_folder",
        description="Lists files and folders in a specific path in the user's Dropbox"
    )
    async def list_folder(
        self,
        path: str = "",
        user_id: str = None,
        kernel = None
    ) -> str:
        """
        Lists files and folders in a specific path in the user's Dropbox.
        
        Args:
            path: Path to list (default: root folder)
            user_id: The user's ID (automatically provided)
            
        Returns:
            str: List of files and folders
        """
        try:
            if not user_id:
                return "Error: User ID not available. Please try again later."
            
            folder_contents = await self.dropbox_service.list_folder(user_id, path)
            
            if not folder_contents or not folder_contents.get('entries') or len(folder_contents['entries']) == 0:
                return f"No files or folders found in path '{path or 'root'}'."
            
            entries = folder_contents['entries']
            
            # Return formatted list of entries
            return self._create_folder_listing(entries, path)
                
        except Exception as e:
            logger.error(f"Error listing folder: {str(e)}")
            return f"An error occurred while listing the folder contents: {str(e)}"
    
    @kernel_function(
        name="delete_file",
        description="Searches and deletes a file from the user's Dropbox account"
    )
    async def delete_file(
        self,
        query: str,
        path: str = "",
        user_id: str = None,
        kernel = None
    ) -> str:
        """
        Searches and deletes a file from the user's Dropbox account.
        
        Args:
            query: Search query or file name
            path: Path to search in (default: root folder)
            user_id: The user's ID (automatically provided)
            kernel: Semantic Kernel instance for finding most relevant file
            
        Returns:
            str: Success message or error message
        """
        try:
            if not user_id:
                return "Error: User ID not available. Please try again later."
            
            search_results = await self.dropbox_service.search_files(user_id, query, path)
            
            if not search_results or not search_results.get('matches') or len(search_results['matches']) == 0:
                return f"No files found matching '{query}'."
            
            # In Dropbox API, the metadata is nested under the match object
            files = [match['metadata'] for match in search_results['matches']]
            
            if len(files) == 1:
                file = files[0]
                file_path = file.get('path_display', file.get('path_lower', 'unknown_path'))
                await self.dropbox_service.delete_file(user_id, file_path)
                return f"File '{file_path}' has been successfully deleted."
            
            # If multiple files and kernel is provided, find most relevant
            if kernel and len(files) > 1:
                most_relevant_file = await self._find_most_relevant_file(kernel, files, query)
                
                if most_relevant_file:
                    file_path = most_relevant_file.get('path_display', most_relevant_file.get('path_lower', 'unknown_path'))
                    await self.dropbox_service.delete_file(user_id, file_path)
                    return f"File '{file_path}' has been successfully deleted."
            
            # If multiple files and no most relevant found, return summary
            return f"Multiple files found matching '{query}'. Please be more specific:\n" + \
                   "\n".join([f"- {file.get('path_display', file.get('name', 'Unnamed'))}" for file in files[:5]])
                
        except Exception as e:
            logger.error(f"Error deleting file: {str(e)}")
            return f"An error occurred while deleting the file: {str(e)}"
    
    @kernel_function(
        name="get_file_download_link",
        description="Gets a temporary download link for a file in the user's Dropbox account"
    )
    async def get_file_download_link(
        self,
        query: str,
        path: str = "",
        user_id: str = None,
        kernel = None
    ) -> str:
        """
        Gets a temporary download link for a file in the user's Dropbox account.
        
        Args:
            query: Search query or file name
            path: Path to search in (default: root folder)
            user_id: The user's ID (automatically provided)
            kernel: Semantic Kernel instance for finding most relevant file
            
        Returns:
            str: Download link or error message
        """
        try:
            if not user_id:
                return "Error: User ID not available. Please try again later."
            
            search_results = await self.dropbox_service.search_files(user_id, query, path)
            
            if not search_results or not search_results.get('matches') or len(search_results['matches']) == 0:
                return f"No files found matching '{query}'."
            
            # In Dropbox API, the metadata is nested under the match object
            files = []
            for match in search_results['matches']:
                metadata = match['metadata']
                # Check if we have a double-nested metadata structure
                if metadata.get('.tag') == 'metadata' and 'metadata' in metadata:
                    files.append(metadata['metadata'])
                else:
                    files.append(metadata)
            
            if len(files) == 1:
                file = files[0]
                file_path = file.get('path_display', file.get('path_lower', 'unknown_path'))
                
                # Try using file ID if available, otherwise use path
                file_id = file.get('id')
                if file_id:
                    download_link = await self.dropbox_service.get_temporary_link(user_id, file_id)
                else:
                    download_link = await self.dropbox_service.get_temporary_link(user_id, file_path)
                    
                return f"Download link for file '{file_path}':\n{download_link}"
            
            # If multiple files and kernel is provided, find most relevant
            if kernel and len(files) > 1:
                most_relevant_file = await self._find_most_relevant_file(kernel, files, query)
                
                if most_relevant_file:
                    file_path = most_relevant_file.get('path_display', most_relevant_file.get('path_lower', 'unknown_path'))
                    
                    # Try using file ID if available, otherwise use path
                    file_id = most_relevant_file.get('id')
                    if file_id:
                        download_link = await self.dropbox_service.get_temporary_link(user_id, file_id)
                    else:
                        download_link = await self.dropbox_service.get_temporary_link(user_id, file_path)
                        
                    return f"Download link for file '{file_path}':\n{download_link}"
            
            # If multiple files and no most relevant found, return summary
            return f"Multiple files found matching '{query}'. Please be more specific:\n" + \
                "\n".join([f"- {file.get('path_display', file.get('name', 'Unnamed'))}" for file in files[:5]])
                
        except Exception as e:
            logger.error(f"Error getting download link: {str(e)}")
            return f"An error occurred while getting the download link: {str(e)}"
    
    @kernel_function(
        name="share_file",
        description="Creates a shared link for a file in the user's Dropbox account"
    )
    async def share_file(
        self,
        query: str,
        path: str = "",
        user_id: str = None,
        kernel = None
    ) -> str:
        """
        Creates a shared link for a file in the user's Dropbox account.
        
        Args:
            query: Search query or file name
            path: Path to search in (default: root folder)
            user_id: The user's ID (automatically provided)
            kernel: Semantic Kernel instance for finding most relevant file
            
        Returns:
            str: Shared link or error message
        """
        try:
            if not user_id:
                return "Error: User ID not available. Please try again later."
            
            search_results = await self.dropbox_service.search_files(user_id, query, path)
            
            if not search_results or not search_results.get('matches') or len(search_results['matches']) == 0:
                return f"No files found matching '{query}'."
            
            # In Dropbox API, the metadata is nested under the match object
            files = [match['metadata'] for match in search_results['matches']]
            
            if len(files) == 1:
                file = files[0]
                file_path = file.get('path_display', file.get('path_lower', 'unknown_path'))
                sharing_info = await self.dropbox_service.share_file(user_id, file_path)
                
                # Extract the URL from sharing info
                shared_url = self._extract_shared_url(sharing_info)
                if shared_url:
                    return f"Shared link for file '{file_path}':\n{shared_url}"
                else:
                    return f"File was shared but couldn't retrieve the URL."
            
            # If multiple files and kernel is provided, find most relevant
            if kernel and len(files) > 1:
                most_relevant_file = await self._find_most_relevant_file(kernel, files, query)
                
                if most_relevant_file:
                    file_path = most_relevant_file.get('path_display', most_relevant_file.get('path_lower', 'unknown_path'))
                    sharing_info = await self.dropbox_service.share_file(user_id, file_path)
                    
                    # Extract the URL from sharing info
                    shared_url = self._extract_shared_url(sharing_info)
                    if shared_url:
                        return f"Shared link for file '{file_path}':\n{shared_url}"
                    else:
                        return f"File was shared but couldn't retrieve the URL."
            
            # If multiple files and no most relevant found, return summary
            return f"Multiple files found matching '{query}'. Please be more specific:\n" + \
                   "\n".join([f"- {file.get('path_display', file.get('name', 'Unnamed'))}" for file in files[:5]])
                
        except Exception as e:
            logger.error(f"Error sharing file: {str(e)}")
            return f"An error occurred while sharing the file: {str(e)}"
    
    def _extract_shared_url(self, sharing_info):
        """Extract shared URL from Dropbox sharing info response."""
        if not sharing_info:
            return None
        
        # Handle different response formats
        # First, try the direct response from create_shared_link_with_settings
        if 'url' in sharing_info:
            return sharing_info['url']
        
        # Then, try the list_shared_links response format
        if 'links' in sharing_info and sharing_info['links']:
            for link in sharing_info['links']:
                if 'url' in link:
                    return link['url']
        
        return None
    
    async def _find_most_relevant_file(self, kernel, files, user_query):
        """
        Find the most relevant file from a list based on user query.
        
        Args:
            kernel: Semantic Kernel instance
            files: List of files
            user_query: The user's query
            
        Returns:
            dict: The most relevant file or None
        """
        try:
            # Create a function from prompt
            rank_files_function = KernelFunctionFromPrompt(
                function_name="RankFilesByRelevance",
                plugin_name=None,
                prompt="Given the user query: '{{$userQuery}}' and a list of file paths, "
                    "rank them by relevance and return the index of the most relevant file. "
                    "Do not add any comments or explanation to the response.\n"
                    "File list: {{$fileList}}",
                template_format="semantic-kernel"
            )
            
            # Create file list string with paths that are more relevant for Dropbox
            file_list = "\n".join([
                f"{i}: Path: {file.get('path_display', file.get('path_lower', file.get('name', 'Unnamed')))}"
                for i, file in enumerate(files)
            ])
            
            # Create kernel arguments
            kernel_arguments = {
                "userQuery": user_query,
                "fileList": file_list
            }
            
            # Invoke the function
            result = await kernel.invoke(rank_files_function, **kernel_arguments)

            # Get the value from the result - might be a list or a string
            result_value = result.value

            # Handle different result types
            if isinstance(result_value, list) and len(result_value) > 0:
                result_text = str(result_value[0]).strip()
            elif isinstance(result_value, str):
                result_text = result_value.strip()
            else:
                # Fallback
                result_text = str(result_value).strip()

            try:
                most_relevant_index = int(result_text)
                if 0 <= most_relevant_index < len(files):
                    return files[most_relevant_index]
            except ValueError:
                logger.warning(f"Could not parse the relevance index from AI result: {result_text}")
            
            return None
            
        except Exception as e:
            logger.error(f"Error finding most relevant file: {str(e)}")
            return None
    
    def _create_file_detail(self, file):
        """Create a detailed text representation of a file."""
        detail = "**File Details:**\n"
        
        # Use path_display as primary identifier
        path = file.get('path_display', file.get('path_lower', 'Unknown path'))
        name = file.get('name', path.split('/')[-1] if path != 'Unknown path' else 'Unknown')
        
        detail += f"**Name:** {name}\n"
        detail += f"**Path:** {path}\n"
        
        # Add ID if available
        if 'id' in file:
            detail += f"**ID:** {file['id']}\n"
        
        # Format file size if available
        if 'size' in file:
            size_bytes = file['size']
            size_str = self._format_file_size(size_bytes)
            detail += f"**Size:** {size_str}\n"
        
        # Add dates if available
        if 'server_modified' in file:
            detail += f"**Modified At:** {file['server_modified']}\n"
        if 'client_modified' in file:
            detail += f"**Client Modified At:** {file['client_modified']}\n"
        
        # Add file type if available
        if '.tag' in file:
            detail += f"**Type:** {file['.tag']}\n"
        
        # Add content hash if available (for version tracking)
        if 'content_hash' in file:
            detail += f"**Content Hash:** {file['content_hash'][:10]}...\n"
        
        return detail
    
    def _create_search_results_summary(self, files):
        """Create a summary of multiple search results."""
        summary = "**Multiple files found. Here are the details:**\n\n"
        
        for i, file in enumerate(files[:5], 1):  # Limit to 5 files and number them
            path = file.get('path_display', file.get('path_lower', 'Unknown path'))
            name = file.get('name', path.split('/')[-1] if path != 'Unknown path' else 'Unknown')
            
            summary += f"**{i}. {name}**\n"
            summary += f"   Path: {path}\n"
            
            # Add size if available
            if 'size' in file:
                size_str = self._format_file_size(file['size'])
                summary += f"   Size: {size_str}\n"
            
            # Add type if available
            if '.tag' in file:
                summary += f"   Type: {file['.tag']}\n"
            
            summary += "\n"
        
        if len(files) > 5:
            summary += f"\n...and {len(files) - 5} more files.\n"
        
        summary += "\nPlease provide a more specific query to find the exact file you want."
        
        return summary
    
    def _create_folder_listing(self, entries, path):
        """Create a formatted listing of folder contents."""
        path_display = path or "root folder"
        listing = f"**Contents of {path_display}:**\n\n"
        
        # Separate folders and files
        folders = [entry for entry in entries if entry.get('.tag') == 'folder']
        files = [entry for entry in entries if entry.get('.tag') == 'file']
        
        # Sort by name
        folders.sort(key=lambda x: x.get('name', '').lower())
        files.sort(key=lambda x: x.get('name', '').lower())
        
        # Add folders first
        if folders:
            listing += "**Folders:**\n"
            for folder in folders:
                name = folder.get('name', 'Unnamed folder')
                path = folder.get('path_display', folder.get('path_lower', 'Unknown path'))
                listing += f"📁 {name} (Path: {path})\n"
            listing += "\n"
        
        # Then add files
        if files:
            listing += "**Files:**\n"
            for file in files:
                name = file.get('name', 'Unnamed file')
                path = file.get('path_display', file.get('path_lower', 'Unknown path'))
                
                # Add size if available
                size_info = ""
                if 'size' in file:
                    size_str = self._format_file_size(file['size'])
                    size_info = f", Size: {size_str}"
                
                listing += f"📄 {name} (Path: {path}{size_info})\n"
            listing += "\n"
        
        if not folders and not files:
            listing += "This folder is empty."
        
        return listing
    
    def _format_file_size(self, bytes):
        """Format file size in human-readable form."""
        sizes = ["B", "KB", "MB", "GB", "TB"]
        order = 0
        size = float(bytes)
        while size >= 1024 and order < len(sizes) - 1:
            order += 1
            size /= 1024
        
        return f"{size:.2f} {sizes[order]}"