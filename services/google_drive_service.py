import os
import json
import logging
from datetime import datetime, timedelta
from urllib.parse import urlencode
from dotenv import load_dotenv

import requests
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

from helpers.token_helpers import (
    TokenEncryptionHelper, 
    TokenStorageManager, 
    create_token_record,
    load_or_generate_encryption_key
)

# Setup logging
logger = logging.getLogger("google_drive_service")

# Constants for platform and service
PLATFORM = "Google"
SERVICE = "GoogleDriveService"

# API URLs
GOOGLE_AUTH_BASE_URL = "https://accounts.google.com/o/oauth2/"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"

# Scopes for Google Drive API
SCOPES = ['https://www.googleapis.com/auth/drive']


class GoogleDriveService:
    def __init__(self, config=None):
        """
        Initialize the Google Drive service with configuration.
        
        Args:
            config: Configuration dictionary or None to load from .env
        """
        if config is None:
            load_dotenv()
            self.client_id = os.getenv("GOOGLE_CLIENT_ID")
            self.client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
            self.redirect_uri = os.getenv("GOOGLE_DRIVE_REDIRECT_URI")
            self.app_name = os.getenv("GOOGLE_APP_NAME", "GoogleDriveApp")
            
            # Get or generate encryption key using our helper
            self.encryption_key = load_or_generate_encryption_key()
        else:
            self.client_id = config.get("client_id")
            self.client_secret = config.get("client_secret")
            self.redirect_uri = config.get("redirect_uri")
            self.app_name = config.get("app_name", "GoogleDriveApp")
            self.encryption_key = config.get("encryption_key")
            
        # Initialize token storage
        self.token_storage = TokenStorageManager()

    async def get_authorization_url(self, user_id):
        """
        Get the authorization URL for Google OAuth flow.
        
        Args:
            user_id: The user's ID
            
        Returns:
            str: The authorization URL
        """
        if not self.client_id:
            raise ValueError("Google Client ID is not set in configuration.")
        if not self.redirect_uri:
            raise ValueError("Google Redirect URI is not set in configuration.")
        
        # Encrypt user_id as state parameter
        state = TokenEncryptionHelper.encrypt_token(user_id, self.encryption_key)
        
        # Create a Flow instance
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "auth_uri": f"{GOOGLE_AUTH_BASE_URL}auth",
                    "token_uri": GOOGLE_TOKEN_URL,
                    "redirect_uris": [self.redirect_uri]
                }
            },
            scopes=SCOPES,
            redirect_uri=self.redirect_uri
        )
        
        # Generate authorization URL
        auth_url, _ = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            state=state,
            prompt='consent'  # Always show consent screen to get refresh token
        )
        
        logger.info(f"Generated authorization URL for user {user_id}")
        return auth_url
    
    async def handle_auth_callback(self, state, code):
        """
        Handle the authorization callback from Google.
        
        Args:
            state: The state parameter from the callback
            code: The authorization code from the callback
        """
        if not self.client_id:
            raise ValueError("Google Client ID is not set in configuration.")
        if not self.client_secret:
            raise ValueError("Google Client Secret is not set in configuration.")
        if not self.redirect_uri:
            raise ValueError("Google Redirect URI is not set in configuration.")
        
        # Decrypt the user_id from state
        user_id = TokenEncryptionHelper.decrypt_token(state, self.encryption_key)
        logger.info(f"Processing authorization callback for user {user_id}")
        
        # Create a Flow instance - but don't specify scopes this time
        # This lets the flow accept whatever scopes Google returns
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "auth_uri": f"{GOOGLE_AUTH_BASE_URL}auth",
                    "token_uri": GOOGLE_TOKEN_URL,
                    "redirect_uris": [self.redirect_uri]
                }
            },
            scopes=None,  # Allow any scope to be returned
            redirect_uri=self.redirect_uri
        )
        
        # Exchange code for token
        try:
            flow.fetch_token(code=code)
            credentials = flow.credentials
            
            # Store token
            await self._store_token(
                user_id,
                credentials.token,
                credentials.refresh_token,
                credentials.expiry.timestamp() - datetime.now().timestamp()
            )
            logger.info(f"Successfully obtained and stored access token for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to obtain access token: {str(e)}")
            raise Exception(f"Failed to obtain user access token: {str(e)}")
    
    async def revoke_access(self, user_id):
        """
        Revoke the Google Drive access for a user.
        
        Args:
            user_id: The user's ID
        """
        token_data = await self._get_token_data(user_id)
        if not token_data:
            raise ValueError("No valid token found for user")
        
        token = token_data.get("access_token")
        if not token:
            raise ValueError("No valid access token found for user")
        
        # Revoke the token
        params = {'token': token}
        response = requests.post(GOOGLE_REVOKE_URL, params=params)
        
        if response.status_code in (200, 204):
            # Delete the token from storage
            self.token_storage.delete_token(user_id, PLATFORM, SERVICE)
            logger.info(f"Successfully revoked access for user {user_id}")
        else:
            logger.error(f"Failed to revoke token: {response.status_code}")
            raise Exception(f"Failed to revoke token: {response.status_code}")
    
    async def create_folder(self, user_id, folder_name, parent_folder_id="root"):
        """
        Create a folder in Google Drive.
        
        Args:
            user_id: The user's ID
            folder_name: Name of the folder to create
            parent_folder_id: ID of the parent folder (default: "root")
            
        Returns:
            dict: The created folder information
        """
        service = await self._get_drive_service(user_id)
        
        folder_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [parent_folder_id]
        }
        
        try:
            folder = service.files().create(
                body=folder_metadata,
                fields='id, name, mimeType, webViewLink'
            ).execute()
            
            return folder
        except Exception as e:
            logger.error(f"Failed to create folder: {str(e)}")
            raise Exception(f"Failed to create folder: {str(e)}")
    
    async def upload_file(self, user_id, file_path, file_name=None, parent_folder_id="root", mime_type=None, description=None):
        """
        Upload a file to Google Drive.
        
        Args:
            user_id: The user's ID
            file_path: Path to the local file
            file_name: Name to use for the file in Google Drive (defaults to local filename)
            parent_folder_id: ID of the parent folder (default: "root")
            mime_type: MIME type of the file (if None, will be guessed)
            description: Optional description for the file
            
        Returns:
            dict: The uploaded file information with file ID and webViewLink
        """
        service = await self._get_drive_service(user_id)
        
        # Use the original filename if none provided
        if not file_name:
            file_name = os.path.basename(file_path)
        
        # Create file metadata
        file_metadata = {
            'name': file_name,
            'parents': [parent_folder_id]
        }
        
        if description:
            file_metadata['description'] = description
        
        # Create a media upload instance
        media = MediaFileUpload(file_path, mimetype=mime_type, resumable=True)
        
        # Upload the file
        try:
            file = service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, name, mimeType, webViewLink'
            ).execute()
            
            return file
        except Exception as e:
            logger.error(f"Failed to upload file: {str(e)}")
            raise Exception(f"Failed to upload file: {str(e)}")
    
    async def delete_file(self, user_id, file_id):
        """
        Delete a file from Google Drive.
        
        Args:
            user_id: The user's ID
            file_id: ID of the file to delete
        """
        service = await self._get_drive_service(user_id)
        
        try:
            service.files().delete(fileId=file_id).execute()
            logger.info(f"Successfully deleted file {file_id}")
        except Exception as e:
            logger.error(f"Failed to delete file: {str(e)}")
            raise Exception(f"Failed to delete file: {str(e)}")
    
    async def list_files(self, user_id, folder_id="root", page_size=100, query=None):
        """
        List files in a folder in Google Drive.
        
        Args:
            user_id: The user's ID
            folder_id: ID of the folder (default: "root")
            page_size: Maximum number of files to return
            query: Optional query string to filter results
            
        Returns:
            list: The files in the folder
        """
        service = await self._get_drive_service(user_id)
        
        # Build the query string
        q = f"'{folder_id}' in parents and trashed = false"
        if query:
            q += f" and {query}"
        
        # List files in the folder
        results = []
        page_token = None
        
        while True:
            try:
                response = service.files().list(
                    q=q,
                    pageSize=page_size,
                    spaces='drive',
                    fields='nextPageToken, files(id, name, mimeType, size, modifiedTime, webViewLink)',
                    pageToken=page_token
                ).execute()
                
                results.extend(response.get('files', []))
                page_token = response.get('nextPageToken')
                
                if not page_token:
                    break
            except Exception as e:
                logger.error(f"Failed to list files: {str(e)}")
                raise Exception(f"Failed to list files: {str(e)}")
        
        return results
    
    async def get_file(self, user_id, file_id):
        """
        Get a file's metadata from Google Drive.
        
        Args:
            user_id: The user's ID
            file_id: ID of the file
            
        Returns:
            dict: The file metadata
        """
        service = await self._get_drive_service(user_id)
        
        try:
            file = service.files().get(
                fileId=file_id,
                fields='id, name, mimeType, size, modifiedTime, webViewLink, webContentLink'
            ).execute()
            
            return file
        except Exception as e:
            logger.error(f"Failed to get file: {str(e)}")
            raise Exception(f"Failed to get file: {str(e)}")
    
    async def download_file(self, user_id, file_id, local_path=None):
        """
        Download a file from Google Drive.
        
        Args:
            user_id: The user's ID
            file_id: ID of the file to download
            local_path: Path where to save the file locally (if None, returns file content as bytes)
            
        Returns:
            bytes or None: File content as bytes if local_path is None, otherwise None
        """
        service = await self._get_drive_service(user_id)
        
        try:
            # Get file metadata to get file name if not provided
            file_metadata = service.files().get(fileId=file_id, fields='name').execute()
            
            # Create request to download file
            request = service.files().get_media(fileId=file_id)
            
            if local_path:
                # If path is a directory, append the file name
                if os.path.isdir(local_path):
                    local_path = os.path.join(local_path, file_metadata['name'])
                
                # Download to file
                with open(local_path, 'wb') as f:
                    downloader = MediaIoBaseDownload(f, request)
                    done = False
                    while not done:
                        status, done = downloader.next_chunk()
                        logger.info(f"Download progress: {int(status.progress() * 100)}%")
                return None
            else:
                # Download to memory
                from io import BytesIO
                fh = BytesIO()
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    status, done = downloader.next_chunk()
                    logger.info(f"Download progress: {int(status.progress() * 100)}%")
                fh.seek(0)
                return fh.read()
        except Exception as e:
            logger.error(f"Failed to download file: {str(e)}")
            raise Exception(f"Failed to download file: {str(e)}")
    
    async def move_file(self, user_id, file_id, new_parent_folder_id):
        """
        Move a file to a different folder in Google Drive.
        
        Args:
            user_id: The user's ID
            file_id: ID of the file to move
            new_parent_folder_id: ID of the destination folder
            
        Returns:
            dict: The updated file metadata
        """
        service = await self._get_drive_service(user_id)
        
        try:
            # Get current parents
            file = service.files().get(fileId=file_id, fields='parents').execute()
            previous_parents = ",".join(file.get('parents', []))
            
            # Move the file to the new folder
            file = service.files().update(
                fileId=file_id,
                addParents=new_parent_folder_id,
                removeParents=previous_parents,
                fields='id, parents'
            ).execute()
            
            return file
        except Exception as e:
            logger.error(f"Failed to move file: {str(e)}")
            raise Exception(f"Failed to move file: {str(e)}")
    
    async def search_files(self, user_id, query, max_results=10):
        """
        Search for files in Google Drive.
        
        Args:
            user_id: The user's ID
            query: Search query
            max_results: Maximum number of results to return
            
        Returns:
            list: Search results
        """
        logger.info(f"Searching for files with query '{query}' for user {user_id}")
        
        service = await self._get_drive_service(user_id)
        
        # Sanitize the query to prevent injection
        query = query.replace("'", "\\'")
        
        try:
            results = []
            page_token = None
            
            while True:
                logger.info(f"Making API request to search files with query: name contains '{query}'")
                response = service.files().list(
                    q=f"name contains '{query}' and trashed = false",
                    spaces='drive',
                    fields='nextPageToken, files(id, name, mimeType, size, modifiedTime, webViewLink)',
                    pageSize=max_results,
                    pageToken=page_token
                ).execute()
                
                files_found = response.get('files', [])
                logger.info(f"API returned {len(files_found)} files for this page")
                
                results.extend(files_found)
                page_token = response.get('nextPageToken')
                
                if not page_token or len(results) >= max_results:
                    break
            
            logger.info(f"Total files found: {len(results)}")
            for i, file in enumerate(results[:5]):
                logger.info(f"File {i+1}: {file.get('name', 'Unknown')} (ID: {file.get('id', 'Unknown')})")
            
            return results[:max_results]
        except Exception as e:
            logger.error(f"Failed to search files: {str(e)}", exc_info=True)
            raise Exception(f"Failed to search files: {str(e)}")
    
    async def search_files_content(self, user_id, query, max_results=10, mime_type=None):
        """
        Search for files with both titles and content that match the query.
        
        Args:
            user_id: The user's ID
            query: Search query
            max_results: Maximum number of results to return
            mime_type: Optional MIME type filter (e.g., 'application/vnd.google-apps.document')
            
        Returns:
            list: Search results
        """
        service = await self._get_drive_service(user_id)
        
        # Sanitize the query to prevent injection
        query = query.replace("'", "\\'")
        
        # Build the query string
        q = f"fullText contains '{query}' and trashed = false"
        if mime_type:
            q += f" and mimeType='{mime_type}'"
        
        try:
            results = []
            page_token = None
            
            while True:
                response = service.files().list(
                    q=q,
                    spaces='drive',
                    fields='nextPageToken, files(id, name, mimeType, size, modifiedTime, webViewLink)',
                    pageSize=max_results,
                    pageToken=page_token
                ).execute()
                
                results.extend(response.get('files', []))
                page_token = response.get('nextPageToken')
                
                if not page_token or len(results) >= max_results:
                    break
            
            return results[:max_results]
        except Exception as e:
            logger.error(f"Failed to search files content: {str(e)}")
            raise Exception(f"Failed to search files content: {str(e)}")
    
    async def search_google_docs(self, user_id, query, max_results=10):
        """
        Search specifically for Google Docs.
        
        Args:
            user_id: The user's ID
            query: Search query
            max_results: Maximum number of results to return
            
        Returns:
            list: Search results for Google Docs
        """
        return await self.search_files_content(
            user_id, 
            query, 
            max_results, 
            mime_type='application/vnd.google-apps.document'
        )
    
    async def search_google_forms(self, user_id, query, max_results=10):
        """
        Search specifically for Google Forms.
        
        Args:
            user_id: The user's ID
            query: Search query
            max_results: Maximum number of results to return
            
        Returns:
            list: Search results for Google Forms
        """
        return await self.search_files_content(
            user_id, 
            query, 
            max_results, 
            mime_type='application/vnd.google-apps.form'
        )
    
    async def search_google_sheets(self, user_id, query, max_results=10):
        """
        Search specifically for Google Sheets.
        
        Args:
            user_id: The user's ID
            query: Search query
            max_results: Maximum number of results to return
            
        Returns:
            list: Search results for Google Sheets
        """
        return await self.search_files_content(
            user_id, 
            query, 
            max_results, 
            mime_type='application/vnd.google-apps.spreadsheet'
        )
    
    async def share_file(self, user_id, file_id, email, role):
        """
        Share a file with another user.
        
        Args:
            user_id: The user's ID
            file_id: ID of the file to share
            email: Email of the user to share with
            role: Role to assign (reader, writer, commenter)
            
        Returns:
            dict: The created permission
        """
        service = await self._get_drive_service(user_id)
        
        # Define the permission
        permission = {
            'type': 'user',
            'role': role,
            'emailAddress': email
        }
        
        try:
            # Create the permission
            result = service.permissions().create(
                fileId=file_id,
                body=permission,
                fields='id'
            ).execute()
            
            return result
        except Exception as e:
            logger.error(f"Failed to share file: {str(e)}")
            raise Exception(f"Failed to share file: {str(e)}")
    
    async def get_document_comments(self, user_id, document_id):
        """
        Get comments for a Google Doc.
        
        Args:
            user_id: The user's ID
            document_id: ID of the document
            
        Returns:
            list: Comments on the document
        """
        service = await self._get_drive_service(user_id)
        
        try:
            # Get comments for the document
            result = service.comments().list(
                fileId=document_id,
                fields='comments(id, content, anchor, htmlContent, quotedFileContent)'
            ).execute()
            
            # Format the comments similar to the C# implementation
            formatted_comments = []
            for comment in result.get('comments', []):
                formatted_comment = {
                    'comment_id': comment.get('id'),
                    'content': comment.get('content'),
                }
                
                # Add quoted file content if available
                quoted_content = comment.get('quotedFileContent')
                if quoted_content:
                    formatted_comment['quoted_file_content'] = {
                        'mime_type': quoted_content.get('mimeType'),
                        'value': quoted_content.get('value')
                    }
                
                formatted_comments.append(formatted_comment)
            
            return formatted_comments
        except Exception as e:
            logger.error(f"Failed to get document comments: {str(e)}")
            raise Exception(f"Failed to get document comments: {str(e)}")
    
    async def copy_document(self, user_id, source_file_id, new_title):
        """
        Create a copy of a document.
        
        Args:
            user_id: The user's ID
            source_file_id: ID of the document to copy
            new_title: Title for the new document
            
        Returns:
            str: The ID of the new document
        """
        service = await self._get_drive_service(user_id)
        
        try:
            # Copy the document
            body = {'name': new_title}
            file = service.files().copy(
                fileId=source_file_id, 
                body=body,
                fields='id, webViewLink'
            ).execute()
            
            return file['id']
        except Exception as e:
            logger.error(f"Failed to copy document: {str(e)}")
            raise Exception(f"Failed to copy document: {str(e)}")
    
    async def get_folders(self, user_id, parent_folder_id=None):
        """
        Get folders in Google Drive.
        
        Args:
            user_id: The user's ID
            parent_folder_id: Optional parent folder ID to list folders within
            
        Returns:
            list: Folders
        """
        service = await self._get_drive_service(user_id)
        
        # Build the query string
        q = "mimeType='application/vnd.google-apps.folder' and trashed = false"
        if parent_folder_id:
            q += f" and '{parent_folder_id}' in parents"
        
        try:
            results = []
            page_token = None
            
            while True:
                response = service.files().list(
                    q=q,
                    spaces='drive',
                    fields='nextPageToken, files(id, name, createdTime)',
                    pageToken=page_token
                ).execute()
                
                results.extend(response.get('files', []))
                page_token = response.get('nextPageToken')
                
                if not page_token:
                    break
            
            return results
        except Exception as e:
            logger.error(f"Failed to get folders: {str(e)}")
            raise Exception(f"Failed to get folders: {str(e)}")
    
    async def _store_token(self, user_id, access_token, refresh_token, expires_in):
        """
        Store a token in the token storage.
        
        Args:
            user_id: The user's ID
            access_token: The access token
            refresh_token: The refresh token
            expires_in: Expiration time in seconds
        """
        token_data = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": (datetime.utcnow() + timedelta(seconds=expires_in)).timestamp()
        }
        
        # Serialize and encrypt the token data
        serialized_token = json.dumps(token_data)
        encrypted_token = TokenEncryptionHelper.encrypt_token(serialized_token, self.encryption_key)
        
        # Store in the token storage using the helper function
        token_record = create_token_record(encrypted_token)
        
        self.token_storage.store_token(user_id, PLATFORM, SERVICE, token_record)
    
    async def _get_token_data(self, user_id):
        """
        Get token data from storage.
        
        Args:
            user_id: The user's ID
            
        Returns:
            dict: The token data or None if not found
        """
        token_record = self.token_storage.get_token(user_id, PLATFORM, SERVICE)
        
        if not token_record or not token_record.get("is_active") or token_record.get("is_revoked"):
            logger.info(f"No valid token found in the storage for user {user_id}")
            return None
        
        try:
            encrypted_token = token_record.get("encrypted_token")
            if not encrypted_token:
                return None
            
            decrypted_token = TokenEncryptionHelper.decrypt_token(encrypted_token, self.encryption_key)
            token_data = json.loads(decrypted_token)
            
            return token_data
        except Exception as e:
            logger.error(f"Error getting token data: {str(e)}")
            return None
    
    async def _load_token(self, user_id):
        """
        Load a token from the token storage.
        
        Args:
            user_id: The user's ID
            
        Returns:
            str: The access token, or None if not found or expired
        """
        token_data = await self._get_token_data(user_id)
        
        if not token_data:
            return None
        
        # Check if token is expired
        expires_at = token_data.get("expires_at")
        if expires_at and expires_at <= datetime.utcnow().timestamp():
            logger.info(f"Token expired for user {user_id}, attempting to refresh")
            refresh_token = token_data.get("refresh_token")
            if refresh_token:
                try:
                    return await self._refresh_token(user_id, refresh_token)
                except Exception as e:
                    logger.error(f"Error refreshing token: {str(e)}")
                    return None
            return None
        
        return token_data.get("access_token")
    
    async def _refresh_token(self, user_id, refresh_token):
        """
        Refresh an expired token.
        
        Args:
            user_id: The user's ID
            refresh_token: The refresh token
            
        Returns:
            str: The new access token
        """
        if not self.client_id:
            raise ValueError("Google Client ID is not set in configuration.")
        if not self.client_secret:
            raise ValueError("Google Client Secret is not set in configuration.")
        
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }
        
        logger.info(f"Attempting to refresh token for user {user_id}")
        response = requests.post(GOOGLE_TOKEN_URL, data=payload)
        response_data = response.json()
        
        if response.status_code == 200 and "access_token" in response_data:
            # Store the new token
            expires_in = response_data.get("expires_in", 3600)  # Default to 1 hour
            await self._store_token(
                user_id, 
                response_data["access_token"], 
                refresh_token,  # Keep the existing refresh token if not provided
                expires_in
            )
            logger.info(f"Successfully refreshed token for user {user_id}")
            return response_data["access_token"]
        else:
            error_msg = response_data.get("error_description", "Unknown error")
            logger.error(f"Failed to refresh token: {error_msg}")
            # If refresh fails, mark the token as revoked so we don't keep trying
            token_record = self.token_storage.get_token(user_id, PLATFORM, SERVICE)
            if token_record:
                token_record["is_revoked"] = True
                self.token_storage.store_token(user_id, PLATFORM, SERVICE, token_record)
            raise Exception(f"Failed to refresh token: {error_msg}")
    
    async def _get_drive_service(self, user_id):
        """
        Get an authenticated Google Drive service instance.
        
        Args:
            user_id: The user's ID
            
        Returns:
            Resource: The Drive service instance
        """
        token_data = await self._get_token_data(user_id)
        
        if not token_data:
            raise self._create_auth_exception(user_id)
        
        # Check if token is expired
        expires_at = token_data.get("expires_at")
        if expires_at and expires_at <= datetime.utcnow().timestamp():
            # Refresh the token
            refresh_token = token_data.get("refresh_token")
            if not refresh_token:
                raise self._create_auth_exception(user_id)
            
            try:
                token_data["access_token"] = await self._refresh_token(user_id, refresh_token)
            except Exception:
                raise self._create_auth_exception(user_id)
        
        # Create credentials from token data
        expiry = datetime.fromtimestamp(token_data.get("expires_at", 0))
        credentials = Credentials(
            token=token_data.get("access_token"),
            refresh_token=token_data.get("refresh_token"),
            token_uri=GOOGLE_TOKEN_URL,
            client_id=self.client_id,
            client_secret=self.client_secret,
            expiry=expiry
        )
        
        # Build the Drive service
        try:
            service = build('drive', 'v3', credentials=credentials)
            return service
        except Exception as e:
            logger.error(f"Failed to build Drive service: {str(e)}")
            raise self._create_auth_exception(user_id)
    
    def _create_auth_exception(self, user_id):
        """
        Create an authentication exception with reauthorization instructions.
        
        Args:
            user_id: The user's ID
            
        Returns:
            Exception: With reauthorization instructions
        """
        # Don't try to generate an auth URL here, just return the instruction
        return Exception(
            "Your Google Drive authorization has expired or is invalid. "
            "Please use the `!authorize-gdrive` command to reconnect your Google Drive account."
        )
    
    async def add_comment_to_document(self, user_id, file_id, content, target_text=None, anchor=None):
        """
        Add a comment to a Google Doc.
        
        Args:
            user_id: The user's ID
            file_id: ID of the document
            content: Comment content
            target_text: Optional text to anchor the comment to
            anchor: Optional anchor object (used instead of target_text if provided)
            
        Returns:
            dict: The created comment
        """
        service = await self._get_drive_service(user_id)
        
        try:
            comment = {
                'content': content
            }
            
            # If anchor is provided, use it
            if anchor:
                comment['anchor'] = anchor
            # If target_text is provided, create an anchor for it
            elif target_text:
                # Get the document content to find the target text
                # This requires using the Google Docs API, not just Drive
                # We'd need to add the Documents API scope and build a docs service
                # For simplicity, we're just using a placeholder here
                comment['quotedFileContent'] = {
                    'value': target_text
                }
            
            result = service.comments().create(
                fileId=file_id,
                body=comment,
                fields='id, content, anchor'
            ).execute()
            
            return result
        except Exception as e:
            logger.error(f"Failed to add comment to document: {str(e)}")
            raise Exception(f"Failed to add comment to document: {str(e)}")