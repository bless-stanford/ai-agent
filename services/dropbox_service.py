import os
import json
import requests
import base64
from datetime import datetime, timedelta
from dotenv import load_dotenv
from urllib.parse import urlencode
import logging

from helpers.token_helpers import (
    TokenEncryptionHelper, 
    TokenStorageManager, 
    create_token_record,
    load_or_generate_encryption_key
)

# Setup logging
logger = logging.getLogger("dropbox_service")

# Constants for platform and service
PLATFORM = "Dropbox"
SERVICE = "DropboxService"

# API URLs
DROPBOX_API_BASE_URL = "https://api.dropboxapi.com/2/"
DROPBOX_CONTENT_API_BASE_URL = "https://content.dropboxapi.com/2/"
DROPBOX_AUTH_BASE_URL = "https://www.dropbox.com/oauth2/"


class DropboxService:
    def __init__(self, config=None):
        """
        Initialize the Dropbox service with configuration.
        
        Args:
            config: Configuration dictionary or None to load from .env
        """
        if config is None:
            load_dotenv()
            self.client_id = os.getenv("DROPBOX_CLIENT_ID")
            self.client_secret = os.getenv("DROPBOX_CLIENT_SECRET")
            self.redirect_uri = os.getenv("DROPBOX_REDIRECT_URI")
            self.app_name = os.getenv("DROPBOX_APP_NAME", "DropboxApp")
            
            # Get or generate encryption key using our helper
            self.encryption_key = load_or_generate_encryption_key()
        else:
            self.client_id = config.get("client_id")
            self.client_secret = config.get("client_secret")
            self.redirect_uri = config.get("redirect_uri")
            self.app_name = config.get("app_name", "DropboxApp")
            self.encryption_key = config.get("encryption_key")
            
        # Initialize token storage
        self.token_storage = TokenStorageManager()
    
    async def get_authorization_url(self, user_id):
        """
        Get the authorization URL for Dropbox OAuth flow.
        
        Args:
            user_id: The user's ID
            
        Returns:
            str: The authorization URL
        """
        if not self.client_id:
            raise ValueError("Dropbox Client ID is not set in configuration.")
        if not self.redirect_uri:
            raise ValueError("Dropbox Redirect URI is not set in configuration.")
        
        # Encrypt user_id as state parameter
        state = TokenEncryptionHelper.encrypt_token(user_id, self.encryption_key)
        
        query = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "state": state,
            "token_access_type": "offline"  # Request a refresh token
        }
        
        query_string = urlencode(query)
        auth_url = f"{DROPBOX_AUTH_BASE_URL}authorize?{query_string}"
        logger.info(f"Generated authorization URL for user {user_id}")
        return auth_url
    
    async def handle_auth_callback(self, state, code):
        """
        Handle the authorization callback from Dropbox.
        
        Args:
            state: The state parameter from the callback
            code: The authorization code from the callback
        """
        if not self.client_id:
            raise ValueError("Dropbox Client ID is not set in configuration.")
        if not self.client_secret:
            raise ValueError("Dropbox Client Secret is not set in configuration.")
        if not self.redirect_uri:
            raise ValueError("Dropbox Redirect URI is not set in configuration.")
        
        # Decrypt the user_id from state
        user_id = TokenEncryptionHelper.decrypt_token(state, self.encryption_key)
        logger.info(f"Processing authorization callback for user {user_id}")
        
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri
        }
        
        response = requests.post(f"{DROPBOX_AUTH_BASE_URL}token", data=payload)
        response_data = response.json()
        
        if response.status_code == 200 and "access_token" in response_data:
            # Calculate expiry time (Dropbox tokens usually last 4 hours by default)
            expires_in = response_data.get("expires_in", 14400)  # 4 hours in seconds
            
            await self._store_token(
                user_id, 
                response_data["access_token"], 
                response_data.get("refresh_token"),  # Might be None if scope doesn't include offline access
                expires_in
            )
            logger.info(f"Successfully obtained and stored access token for user {user_id}")
        else:
            error_msg = response_data.get("error_description", "Unknown error")
            logger.error(f"Failed to obtain access token: {error_msg}")
            raise Exception(f"Failed to obtain user access token: {error_msg}")
    
    async def revoke_access(self, user_id):
        """
        Revoke the Dropbox access for a user.
        
        Args:
            user_id: The user's ID
        """
        token = await self._load_token(user_id)
        if not token:
            raise ValueError("No valid token found for user")
        
        headers = {
            "Content-Type": "application/json"
        }
        
        # Dropbox requires token to be in Authorization header
        auth_value = f"{self.client_id}:{self.client_secret}"
        auth_bytes = auth_value.encode('ascii')
        base64_auth = base64.b64encode(auth_bytes).decode('ascii')
        headers["Authorization"] = f"Basic {base64_auth}"
        
        payload = {
            "token": token
        }
        
        response = requests.post(
            f"{DROPBOX_API_BASE_URL}auth/token/revoke", 
            headers=headers, 
            json=payload
        )
        
        if response.status_code == 200:
            # Delete the token from storage
            self.token_storage.delete_token(user_id, PLATFORM, SERVICE)
            logger.info(f"Successfully revoked access for user {user_id}")
        else:
            logger.error(f"Failed to revoke token: {response.status_code}")
            raise Exception(f"Failed to revoke token: {response.status_code}")
    
    async def list_folder(self, user_id, path=""):
        """
        List contents of a folder in Dropbox.
        
        Args:
            user_id: The user's ID
            path: Path to the folder (default: "" for root)
            
        Returns:
            dict: The folder contents
        """
        token = await self._load_token(user_id)
        if not token:
            raise self._create_auth_exception(user_id)
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "path": path,
            "recursive": False,
            "include_media_info": False,
            "include_deleted": False,
            "include_has_explicit_shared_members": False
        }
        
        response = requests.post(
            f"{DROPBOX_API_BASE_URL}files/list_folder", 
            headers=headers, 
            json=payload
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            self._handle_api_error(response, user_id)
    
    async def search_files(self, user_id, query, path="", max_results=10):
        """
        Search for files in Dropbox.
        
        Args:
            user_id: The user's ID
            query: Search query
            path: Path to search in (default: "" for root)
            max_results: Maximum number of results to return
            
        Returns:
            dict: Search results
        """
        token = await self._load_token(user_id)
        if not token:
            raise self._create_auth_exception(user_id)
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "query": query,
            "path": path if path else "",
            "max_results": max_results,
            "mode": {
                ".tag": "filename_and_content"
            }
        }
        
        response = requests.post(
            f"{DROPBOX_API_BASE_URL}files/search_v2", 
            headers=headers, 
            json=payload
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            self._handle_api_error(response, user_id)
    
    async def create_folder(self, user_id, path):
        """
        Create a folder in Dropbox.
        
        Args:
            user_id: The user's ID
            path: Path of the folder to create
            
        Returns:
            dict: The created folder information
        """
        token = await self._load_token(user_id)
        if not token:
            raise self._create_auth_exception(user_id)
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "path": path,
            "autorename": False
        }
        
        response = requests.post(
            f"{DROPBOX_API_BASE_URL}files/create_folder_v2", 
            headers=headers, 
            json=payload
        )
        
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 409:
            # Folder already exists
            logger.info(f"Folder already exists at path: {path}")
            return {"metadata": {"path": path, "name": path.split('/')[-1]}}
        else:
            self._handle_api_error(response, user_id)
    
    async def upload_file(self, user_id, local_file_path, dropbox_path):
        """
        Upload a file to Dropbox.
        
        Args:
            user_id: The user's ID
            local_file_path: Path to the local file
            dropbox_path: Path where to store the file in Dropbox
            
        Returns:
            dict: The uploaded file information
        """
        token = await self._load_token(user_id)
        if not token:
            raise self._create_auth_exception(user_id)
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Dropbox-API-Arg": json.dumps({
                "path": dropbox_path,
                "mode": "overwrite",
                "autorename": True,
                "mute": False
            }),
            "Content-Type": "application/octet-stream"
        }
        
        with open(local_file_path, "rb") as f:
            file_data = f.read()
        
        response = requests.post(
            f"{DROPBOX_CONTENT_API_BASE_URL}files/upload", 
            headers=headers, 
            data=file_data
        )
        
        if response.status_code in (200, 201):
            return response.json()
        else:
            self._handle_api_error(response, user_id)
    
    async def delete_file(self, user_id, path):
        """
        Delete a file from Dropbox.
        
        Args:
            user_id: The user's ID
            path: Path of the file to delete
        """
        token = await self._load_token(user_id)
        if not token:
            raise self._create_auth_exception(user_id)
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "path": path
        }
        
        response = requests.post(
            f"{DROPBOX_API_BASE_URL}files/delete_v2", 
            headers=headers, 
            json=payload
        )
        
        if response.status_code != 200:
            self._handle_api_error(response, user_id)
    
    async def get_temporary_link(self, user_id, path):
        """
        Get a temporary download link for a file.
        
        Args:
            user_id: The user's ID
            path: Path of the file
            
        Returns:
            str: Temporary download URL
        """
        token = await self._load_token(user_id)
        if not token:
            raise self._create_auth_exception(user_id)
        
        # Check if path starts with an ID
        if path.startswith('id:'):
            logger.info(f"Using ID format for path: {path}")
        else:
            # Ensure path starts with a slash
            if not path.startswith('/'):
                path = '/' + path
                logger.info(f"Path was reformatted to include leading slash: {path}")
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "path": path
        }
        
        response = requests.post(
            f"{DROPBOX_API_BASE_URL}files/get_temporary_link", 
            headers=headers, 
            json=payload
        )
        
        if response.status_code == 200:
            data = response.json()
            if "link" in data:
                return data["link"]
            else:
                logger.error(f"Link not found in response: {json.dumps(data)}")
                raise Exception("Link not found in response")
        else:
            try:
                error_data = response.json()
                logger.error(f"Error response: {json.dumps(error_data)}")
                
                # Check for specific error information
                if "error" in error_data:
                    if isinstance(error_data["error"], dict) and ".tag" in error_data["error"]:
                        error_type = error_data["error"][".tag"]
                        logger.error(f"Error type: {error_type}")
                        
                        # Special handling for common error types
                        if error_type == "path":
                            # Extract more details about path errors
                            path_error = error_data["error"].get("path", {})
                            path_error_tag = path_error.get(".tag") if isinstance(path_error, dict) else None
                            logger.error(f"Path error type: {path_error_tag}")
                    
            except ValueError:
                logger.error(f"Response was not valid JSON: {response.text[:200]}")
            
            self._handle_api_error(response, user_id)
    
    async def share_file(self, user_id, path, settings=None):
        """
        Create a shared link for a file.
        
        Args:
            user_id: The user's ID
            path: Path of the file to share
            settings: Optional sharing settings
            
        Returns:
            dict: The sharing metadata
        """
        token = await self._load_token(user_id)
        if not token:
            raise self._create_auth_exception(user_id)
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "path": path,
            "settings": settings or {}
        }
        
        response = requests.post(
            f"{DROPBOX_API_BASE_URL}sharing/create_shared_link_with_settings", 
            headers=headers, 
            json=payload
        )
        
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 409 and "shared_link_already_exists" in response.text:
            # Link already exists, get existing links
            return await self.get_shared_links(user_id, path)
        else:
            self._handle_api_error(response, user_id)
    
    async def get_shared_links(self, user_id, path):
        """
        Get existing shared links for a file.
        
        Args:
            user_id: The user's ID
            path: Path of the file
            
        Returns:
            dict: Existing shared links
        """
        token = await self._load_token(user_id)
        if not token:
            raise self._create_auth_exception(user_id)
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "path": path
        }
        
        response = requests.post(
            f"{DROPBOX_API_BASE_URL}sharing/list_shared_links", 
            headers=headers, 
            json=payload
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            self._handle_api_error(response, user_id)
    
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
    
    async def _load_token(self, user_id):
        """
        Load a token from the token storage.
        
        Args:
            user_id: The user's ID
            
        Returns:
            str: The access token, or None if not found or expired
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
            
            if not token_data:
                logger.error("Failed to deserialize token data")
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
        except Exception as e:
            logger.error(f"Error loading token: {str(e)}")
            return None
    
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
            raise ValueError("Dropbox Client ID is not set in configuration.")
        if not self.client_secret:
            raise ValueError("Dropbox Client Secret is not set in configuration.")
        
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }
        
        logger.info(f"Attempting to refresh token for user {user_id}")
        response = requests.post(f"{DROPBOX_AUTH_BASE_URL}token", data=payload)
        response_data = response.json()
        
        if response.status_code == 200 and "access_token" in response_data:
            # Note: Dropbox might not return a new refresh token, so keep the old one if none returned
            new_refresh_token = response_data.get("refresh_token", refresh_token)
            expires_in = response_data.get("expires_in", 14400)  # 4 hours in seconds
            
            await self._store_token(
                user_id, 
                response_data["access_token"], 
                new_refresh_token, 
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
    
    def _handle_api_error(self, response, user_id):
        """
        Handle API errors and check for authentication issues.
        
        Args:
            response: The response object
            user_id: The user's ID
            
        Raises:
            Exception: With appropriate error message
        """
        try:
            error_data = response.json()
            error_summary = error_data.get("error_summary", "Unknown error")
            
            # Check if this is an authentication error
            if response.status_code in (401, 403):
                # Mark token as revoked
                token_record = self.token_storage.get_token(user_id, PLATFORM, SERVICE)
                if token_record:
                    token_record["is_revoked"] = True
                    self.token_storage.store_token(user_id, PLATFORM, SERVICE, token_record)
                
                # Raise authentication exception
                raise self._create_auth_exception(user_id)
            
            # For other errors
            raise Exception(f"Dropbox API request failed: {error_summary}")
        except ValueError:
            # Response couldn't be parsed as JSON
            raise Exception(f"Dropbox API request failed with status code: {response.status_code}")
    
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
            "Your Dropbox authorization has expired or is invalid. "
            "Please use the `!authorize-dropbox` command to reconnect your Dropbox account."
        )