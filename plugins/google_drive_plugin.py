import json
import os
from semantic_kernel.functions import kernel_function
from semantic_kernel.functions.kernel_function_from_prompt import KernelFunctionFromPrompt
from services.google_drive_service import GoogleDriveService
import logging

logger = logging.getLogger("google_drive_plugins")

class GoogleDrivePlugins:
    """
    Plugins for interacting with Google Drive cloud storage.
    """
    
    def __init__(self, drive_service=None):
        """
        Initialize the Google Drive plugins with a GoogleDriveService.
        If no service is provided, a new one will be created.
        """
        self.drive_service = drive_service or GoogleDriveService()
    
    @kernel_function(
        name="create_folder",
        description="Creates a new folder in the user's Google Drive account"
    )
    async def create_folder(
        self,
        folder_name: str,
        parent_folder_id: str = "root",
        user_id: str = None,
        kernel = None
    ) -> str:
        """
        Creates a new folder in the user's Google Drive account.
        
        Args:
            folder_name: Name of the folder to create
            parent_folder_id: ID of the parent folder (default: "root" for root)
            user_id: The user's ID (automatically provided)
            
        Returns:
            str: Success message with folder details or error message
        """
        try:
            if not user_id:
                return "Error: User ID not available. Please try again later."
            
            folder = await self.drive_service.create_folder(user_id, folder_name, parent_folder_id)
            
            if folder:
                return f"Folder '{folder_name}' created successfully with ID: {folder['id']}"
            else:
                return f"Failed to create folder '{folder_name}'."
                
        except Exception as e:
            logger.error(f"Error creating folder: {str(e)}")
            return f"An error occurred while creating the folder: {str(e)}"
    
    @kernel_function(
        name="search_file",
        description="Searches for files in the user's Google Drive account and returns details in a user friendly way"
    )
    async def search_file(
        self,
        query: str,
        user_id: str = None,
        kernel = None
    ) -> str:
        """
        Searches for files in the user's Google Drive account.
        
        Args:
            query: Search query or file name
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
            
            files = await self.drive_service.search_files(user_id, query)
            
            if not files or len(files) == 0:
                return f"No files found matching '{query}'."
            
            if len(files) == 1:
                return self._create_file_detail(files[0])
            
            # If multiple files, return a summary
            return self._create_search_results_summary(files)
                
        except Exception as e:
            logger.error(f"Error searching files: {str(e)}")
            return f"An error occurred while searching for files: {str(e)}"
    
    @kernel_function(
        name="delete_file",
        description="Searches and deletes a file from the user's Google Drive account"
    )
    async def delete_file(
        self,
        query: str,
        user_id: str = None,
        kernel = None
    ) -> str:
        """
        Searches and deletes a file from the user's Google Drive account.
        
        Args:
            query: Search query or file name
            user_id: The user's ID (automatically provided)
            kernel: Semantic Kernel instance for finding most relevant file
            
        Returns:
            str: Success message or error message
        """
        try:
            if not user_id:
                return "Error: User ID not available. Please try again later."
            
            files = await self.drive_service.search_files(user_id, query)
            
            if not files or len(files) == 0:
                return f"No files found matching '{query}'."
            
            if len(files) == 1:
                file = files[0]
                await self.drive_service.delete_file(user_id, file['id'])
                return f"File '{file['name']}' has been successfully deleted."
            
            # If multiple files and kernel is provided, find most relevant
            if kernel and len(files) > 1:
                most_relevant_file = await self._find_most_relevant_file(kernel, files, query)
                
                if most_relevant_file:
                    await self.drive_service.delete_file(user_id, most_relevant_file['id'])
                    return f"File '{most_relevant_file['name']}' has been successfully deleted."
            
            # If multiple files and no most relevant found, return summary
            return f"Multiple files found matching '{query}'. Please be more specific:\n" + \
                   "\n".join([f"- {file['name']}" for file in files[:5]])
                
        except Exception as e:
            logger.error(f"Error deleting file: {str(e)}")
            return f"An error occurred while deleting the file: {str(e)}"
            
    @kernel_function(
        name="upload_file",
        description="Uploads an attached file to the user's Google Drive account"
    )
    async def upload_file(
        self,
        file_url: str,
        file_name: str = None,
        parent_folder_id: str = "root",
        user_id: str = None,
        kernel = None
    ) -> str:
        """
        Uploads an attached file to the user's Google Drive account.
        
        Args:
            file_url: URL or path to the local file
            file_name: Optional name to use when storing the file (if different from source)
            parent_folder_id: ID of the parent folder (default: "root")
            user_id: The user's ID (automatically provided)
            
        Returns:
            str: Success message with file details or error message
        """
        try:
            if not user_id:
                return "Error: User ID not available. Please try again later."
            
            # Create temp directory if it doesn't exist
            if not os.path.exists("temp"):
                os.makedirs("temp")
            
            # If no file name provided, use the original name from URL
            if not file_name and file_url:
                file_name = os.path.basename(file_url)
            
            # Handle the case where file is already downloaded
            if os.path.exists(file_url):
                local_file_path = file_url
            else:
                # Could add code here to download from a URL if needed
                return "Error: File not found. Please attach a file directly to your message."
            
            # Upload to Google Drive
            file_info = await self.drive_service.upload_file(
                user_id, 
                local_file_path, 
                file_name, 
                parent_folder_id
            )
            
            # Create a response with file details
            if file_info and 'id' in file_info:
                response = f"✅ File '{file_name}' uploaded successfully to Google Drive!\n"
                response += f"**File ID:** {file_info['id']}\n"
                
                # Add webViewLink if available
                if 'webViewLink' in file_info:
                    response += f"**View Link:** {file_info['webViewLink']}"
                    
                return response
            else:
                return f"File upload completed, but no file information was returned."
            
        except Exception as e:
            logger.error(f"Error uploading file: {str(e)}")
            return f"An error occurred while uploading the file: {str(e)}"
    
    @kernel_function(
        name="get_file_download_link",
        description="Gets a download link for a file in the user's Google Drive account"
    )
    async def get_file_download_link(
        self,
        query: str,
        user_id: str = None,
        kernel = None
    ) -> str:
        """
        Gets a download link for a file in the user's Google Drive account.
        
        Args:
            query: Search query or file name
            user_id: The user's ID (automatically provided)
            kernel: Semantic Kernel instance for finding most relevant file
            
        Returns:
            str: Download link or error message
        """
        try:
            logger.info(f"Getting download link for query '{query}' from user {user_id}")
            
            if not user_id:
                logger.error("User ID not available")
                return "Error: User ID not available. Please try again later."
            
            logger.info(f"Searching for files matching '{query}'")
            files = await self.drive_service.search_files(user_id, query)
            
            logger.info(f"Found {len(files) if files else 0} files matching '{query}'")
            
            if not files or len(files) == 0:
                return f"No files found matching '{query}'."
            
            if len(files) == 1:
                file = files[0]
                logger.info(f"Found single file: {file.get('name', 'Unknown')}, ID: {file.get('id', 'Unknown')}")
                
                logger.info(f"Getting file details for ID: {file['id']}")
                file_info = await self.drive_service.get_file(user_id, file['id'])
                
                logger.info(f"File details: {json.dumps(file_info, indent=2)}")
                
                if 'webContentLink' in file_info and file_info['webContentLink']:
                    logger.info(f"Found download link: {file_info['webContentLink']}")
                    return f"Download link for file '{file['name']}':\n{file_info['webContentLink']}"
                elif 'webViewLink' in file_info and file_info['webViewLink']:
                    logger.info(f"No download link found, using view link: {file_info['webViewLink']}")
                    return f"No direct download link available for '{file['name']}'. You can access it via this view link instead:\n{file_info['webViewLink']}"
                else:
                    logger.warning(f"No links found for file: {file['name']}")
                    return f"No direct links available for '{file['name']}'. You may need to access it via the Google Drive web interface."
            
            # If multiple files and kernel is provided, find most relevant
            if kernel and len(files) > 1:
                logger.info(f"Multiple files found, attempting to find most relevant")
                most_relevant_file = await self._find_most_relevant_file(kernel, files, query)
                
                if most_relevant_file:
                    logger.info(f"Most relevant file: {most_relevant_file.get('name', 'Unknown')}")
                    
                    file_info = await self.drive_service.get_file(user_id, most_relevant_file['id'])
                    logger.info(f"File details for most relevant: {json.dumps(file_info, indent=2)}")
                    
                    if 'webContentLink' in file_info and file_info['webContentLink']:
                        return f"Download link for file '{most_relevant_file['name']}':\n{file_info['webContentLink']}"
                    elif 'webViewLink' in file_info and file_info['webViewLink']:
                        return f"No direct download link available for '{most_relevant_file['name']}'. You can access it via this view link instead:\n{file_info['webViewLink']}"
                    else:
                        return f"No direct links available for '{most_relevant_file['name']}'."
            
            # If multiple files and no most relevant found, return summary
            file_list = "\n".join([f"- {file['name']}" for file in files[:5]])
            logger.info(f"Returning list of multiple files: {file_list}")
            return f"Multiple files found matching '{query}'. Please be more specific:\n{file_list}"
                
        except Exception as e:
            logger.error(f"Error getting download link: {str(e)}", exc_info=True)
            return f"An error occurred while getting the download link: {str(e)}"
    
    @kernel_function(
        name="get_file_view_link",
        description="Gets a shareable view link for a file in the user's Google Drive account"
    )
    async def get_file_view_link(
        self,
        query: str,
        user_id: str = None,
        kernel = None
    ) -> str:
        """
        Gets a shareable view link for a file in the user's Google Drive account.
        
        Args:
            query: Search query or file name
            user_id: The user's ID (automatically provided)
            kernel: Semantic Kernel instance for finding most relevant file
            
        Returns:
            str: View link or error message
        """
        try:
            if not user_id:
                return "Error: User ID not available. Please try again later."
            
            files = await self.drive_service.search_files(user_id, query)
            
            if not files or len(files) == 0:
                return f"No files found matching '{query}'."
            
            if len(files) == 1:
                file = files[0]
                file_info = await self.drive_service.get_file(user_id, file['id'])
                
                if 'webViewLink' in file_info and file_info['webViewLink']:
                    return f"View link for file '{file['name']}':\n{file_info['webViewLink']}"
                else:
                    return f"No view link available for '{file['name']}'."
            
            # If multiple files and kernel is provided, find most relevant
            if kernel and len(files) > 1:
                most_relevant_file = await self._find_most_relevant_file(kernel, files, query)
                
                if most_relevant_file:
                    file_info = await self.drive_service.get_file(user_id, most_relevant_file['id'])
                    
                    if 'webViewLink' in file_info and file_info['webViewLink']:
                        return f"View link for file '{most_relevant_file['name']}':\n{file_info['webViewLink']}"
                    else:
                        return f"No view link available for '{most_relevant_file['name']}'."
            
            # If multiple files and no most relevant found, return summary
            return f"Multiple files found matching '{query}'. Please be more specific:\n" + \
                   "\n".join([f"- {file['name']}" for file in files[:5]])
                
        except Exception as e:
            logger.error(f"Error getting view link: {str(e)}")
            return f"An error occurred while getting the view link: {str(e)}"
    
    @kernel_function(
        name="share_file",
        description="Shares a file with another user"
    )
    async def share_file(
        self,
        query: str,
        email: str,
        role: str = "reader",
        user_id: str = None,
        kernel = None
    ) -> str:
        """
        Shares a file with another user.
        
        Args:
            query: Search query or file name
            email: Email of the user to share with
            role: Role to assign (reader, writer, commenter)
            user_id: The user's ID (automatically provided)
            kernel: Semantic Kernel instance for finding most relevant file
            
        Returns:
            str: Success message or error message
        """
        try:
            if not user_id:
                return "Error: User ID not available. Please try again later."
            
            # Validate role (Google Drive uses reader, writer, commenter)
            valid_roles = ["reader", "writer", "commenter"]
            if role not in valid_roles:
                return f"Invalid role '{role}'. Valid roles are: {', '.join(valid_roles)}"
            
            files = await self.drive_service.search_files(user_id, query)
            
            if not files or len(files) == 0:
                return f"No files found matching '{query}'."
            
            if len(files) == 1:
                file = files[0]
                await self.drive_service.share_file(user_id, file['id'], email, role)
                
                file_info = await self.drive_service.get_file(user_id, file['id'])
                view_link = file_info.get('webViewLink', 'No view link available')
                
                return f"File '{file['name']}' has been shared with {email} as a {role}. They can access the file at: {view_link}"
            
            # If multiple files and kernel is provided, find most relevant
            if kernel and len(files) > 1:
                most_relevant_file = await self._find_most_relevant_file(kernel, files, query)
                
                if most_relevant_file:
                    await self.drive_service.share_file(user_id, most_relevant_file['id'], email, role)
                    
                    file_info = await self.drive_service.get_file(user_id, most_relevant_file['id'])
                    view_link = file_info.get('webViewLink', 'No view link available')
                    
                    return f"File '{most_relevant_file['name']}' has been shared with {email} as a {role}. They can access the file at: {view_link}"
            
            # If multiple files and no most relevant found, return summary
            return f"Multiple files found matching '{query}'. Please be more specific:\n" + \
                   "\n".join([f"- {file['name']}" for file in files[:5]])
                
        except Exception as e:
            logger.error(f"Error sharing file: {str(e)}")
            return f"An error occurred while sharing the file: {str(e)}"
    
    @kernel_function(
        name="move_file",
        description="Moves a file to a different folder in the user's Google Drive account"
    )
    async def move_file(
        self,
        query: str,
        destination_folder_id: str,
        user_id: str = None,
        kernel = None
    ) -> str:
        """
        Moves a file to a different folder.
        
        Args:
            query: Search query or file name
            destination_folder_id: ID of the destination folder
            user_id: The user's ID (automatically provided)
            kernel: Semantic Kernel instance for finding most relevant file
            
        Returns:
            str: Success message or error message
        """
        try:
            if not user_id:
                return "Error: User ID not available. Please try again later."
            
            files = await self.drive_service.search_files(user_id, query)
            
            if not files or len(files) == 0:
                return f"No files found matching '{query}'."
            
            if len(files) == 1:
                file = files[0]
                await self.drive_service.move_file(user_id, file['id'], destination_folder_id)
                return f"File '{file['name']}' has been successfully moved to the destination folder."
            
            # If multiple files and kernel is provided, find most relevant
            if kernel and len(files) > 1:
                most_relevant_file = await self._find_most_relevant_file(kernel, files, query)
                
                if most_relevant_file:
                    await self.drive_service.move_file(user_id, most_relevant_file['id'], destination_folder_id)
                    return f"File '{most_relevant_file['name']}' has been successfully moved to the destination folder."
            
            # If multiple files and no most relevant found, return summary
            return f"Multiple files found matching '{query}'. Please be more specific:\n" + \
                   "\n".join([f"- {file['name']}" for file in files[:5]])
                
        except Exception as e:
            logger.error(f"Error moving file: {str(e)}")
            return f"An error occurred while moving the file: {str(e)}"
    
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
                prompt="Given the user query: '{{$userQuery}}' and a list of file names, "
                    "rank them by relevance and return the index of the most relevant file. "
                    "Do not add any comments or explanation to the response.\n"
                    "File list: {{$fileList}}",
                template_format="semantic-kernel"
            )
            
            # Create file list string
            file_list = "\n".join([f"{i}: Name: {file['name']}" for i, file in enumerate(files)])
            
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
        detail += f"**Name:** {file.get('name', 'Unknown')}\n"
        detail += f"**ID:** {file.get('id', 'Unknown')}\n"
        
        # Format file size if available
        if 'size' in file:
            size_bytes = int(file['size'])
            size_str = self._format_file_size(size_bytes)
            detail += f"**Size:** {size_str}\n"
        
        # Add mime type if available
        if 'mimeType' in file:
            detail += f"**Type:** {file['mimeType']}\n"
        
        # Add dates if available
        if 'modifiedTime' in file:
            detail += f"**Modified At:** {file['modifiedTime']}\n"
        
        # Add view link if available
        if 'webViewLink' in file:
            detail += f"**View Link:** {file['webViewLink']}\n"
        
        # Add download link if available
        if 'webContentLink' in file:
            detail += f"**Download Link:** {file['webContentLink']}\n"
        
        return detail
    
    def _create_search_results_summary(self, files):
        """Create a summary of multiple search results."""
        summary = "**Multiple files found. Here are the details:**\n\n"
        
        for i, file in enumerate(files[:5], 1):  # Limit to 5 files and number them
            summary += f"**{i}. {file.get('name', 'Unknown')}**\n"
            summary += f"   ID: {file.get('id', 'Unknown')}\n"
            
            # Add size if available
            if 'size' in file:
                size_str = self._format_file_size(int(file['size']))
                summary += f"   Size: {size_str}\n"
            
            # Add type if available
            if 'mimeType' in file:
                summary += f"   Type: {file['mimeType']}\n"
            
            summary += "\n"
        
        if len(files) > 5:
            summary += f"\n...and {len(files) - 5} more files.\n"
        
        summary += "\nPlease provide a more specific query to find the exact file you want."
        
        return summary
    
    def _format_file_size(self, bytes):
        """Format file size in human-readable form."""
        sizes = ["B", "KB", "MB", "GB", "TB"]
        order = 0
        size = float(bytes)
        while size >= 1024 and order < len(sizes) - 1:
            order += 1
            size /= 1024
        
        return f"{size:.2f} {sizes[order]}"