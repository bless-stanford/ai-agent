import os
import json
import requests
from datetime import datetime, timedelta
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from urllib.parse import urlencode
import logging

# Setup logging
logger = logging.getLogger("box_service")

# Constants for platform and service
PLATFORM = "Box"
SERVICE = "BoxService"

# API URLs
BOX_API_BASE_URL = "https://api.box.com/2.0/"
BOX_AUTH_BASE_URL = "https://account.box.com/api/oauth2/"
BOX_UPLOAD_API_BASE_URL = "https://upload.box.com/api/2.0/"

class TokenEncryptionHelper:
    @staticmethod
    def encrypt_token(token_str, encryption_key):
        """Encrypts a token string using Fernet symmetric encryption."""
        f = Fernet(encryption_key)
        return f.encrypt(token_str.encode()).decode()
    
    @staticmethod
    def decrypt_token(encrypted_token, encryption_key):
        """Decrypts an encrypted token string using Fernet symmetric encryption."""
        f = Fernet(encryption_key)
        return f.decrypt(encrypted_token.encode()).decode()

class TokenStorageManager:
    """A simple file-based token storage system."""
    
    def __init__(self, storage_file="user_tokens.json"):
        self.storage_file = storage_file
        # Initialize the storage file if it doesn't exist
        if not os.path.exists(storage_file):
            with open(storage_file, 'w') as f:
                json.dump({}, f)
    
    def get_token(self, user_id, platform, service):
        """Retrieve a token from storage."""
        try:
            with open(self.storage_file, 'r') as f:
                tokens = json.load(f)
                
            key = f"{user_id}_{platform}_{service}"
            return tokens.get(key)
        except Exception as e:
            logger.error(f"Error retrieving token: {str(e)}")
            return None
    
    def store_token(self, user_id, platform, service, token_data):
        """Store a token in storage."""
        try:
            with open(self.storage_file, 'r') as f:
                tokens = json.load(f)
            
            key = f"{user_id}_{platform}_{service}"
            tokens[key] = token_data
            
            with open(self.storage_file, 'w') as f:
                json.dump(tokens, f)
            
            logger.info(f"Token stored successfully for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error storing token: {str(e)}")
            return False
    
    def delete_token(self, user_id, platform, service):
        """Delete a token from storage."""
        try:
            with open(self.storage_file, 'r') as f:
                tokens = json.load(f)
            
            key = f"{user_id}_{platform}_{service}"
            if key in tokens:
                del tokens[key]
            
            with open(self.storage_file, 'w') as f:
                json.dump(tokens, f)
            
            logger.info(f"Token deleted successfully for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting token: {str(e)}")
            return False

class BoxService:
    def __init__(self, config=None):
        """
        Initialize the Box service with configuration.
        
        Args:
            config: Configuration dictionary or None to load from .env
        """
        if config is None:
            load_dotenv()
            self.client_id = os.getenv("BOX_CLIENT_ID")
            self.client_secret = os.getenv("BOX_CLIENT_SECRET")
            self.redirect_uri = os.getenv("BOX_REDIRECT_URI")
            
            # Get or generate encryption key
            encryption_key = os.getenv("ENCRYPTION_KEY")
            if not encryption_key:
                # Generate a new key if none exists
                encryption_key = Fernet.generate_key().decode()
                # Add this to your .env file manually or update it
                logger.warning("No encryption key found. Generated new key. Add to .env: "
                               f"ENCRYPTION_KEY={encryption_key}")
            
            self.encryption_key = encryption_key.encode() if isinstance(encryption_key, str) else encryption_key
        else:
            self.client_id = config.get("client_id")
            self.client_secret = config.get("client_secret")
            self.redirect_uri = config.get("redirect_uri")
            self.encryption_key = config.get("encryption_key", Fernet.generate_key())
            
        # Initialize token storage
        self.token_storage = TokenStorageManager()
    
    async def get_authorization_url(self, user_id):
        """
        Get the authorization URL for Box OAuth flow.
        
        Args:
            user_id: The user's ID
            
        Returns:
            str: The authorization URL
        """
        if not self.client_id:
            raise ValueError("Box Client ID is not set in configuration.")
        if not self.redirect_uri:
            raise ValueError("Box Redirect URI is not set in configuration.")
        
        # Encrypt user_id as state parameter
        state = TokenEncryptionHelper.encrypt_token(user_id, self.encryption_key)
        
        query = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "state": state
        }
        
        query_string = urlencode(query)
        auth_url = f"{BOX_AUTH_BASE_URL}authorize?{query_string}"
        logger.info(f"Generated authorization URL for user {user_id}")
        return auth_url
    
    async def handle_auth_callback(self, state, code):
        """
        Handle the authorization callback from Box.
        
        Args:
            state: The state parameter from the callback
            code: The authorization code from the callback
        """
        if not self.client_id:
            raise ValueError("Box Client ID is not set in configuration.")
        if not self.client_secret:
            raise ValueError("Box Client Secret is not set in configuration.")
        if not self.redirect_uri:
            raise ValueError("Box Redirect URI is not set in configuration.")
        
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
        
        response = requests.post(f"{BOX_AUTH_BASE_URL}token", data=payload)
        response_data = response.json()
        
        if response.status_code == 200 and "access_token" in response_data:
            await self._store_token(
                user_id, 
                response_data["access_token"], 
                response_data["refresh_token"], 
                response_data["expires_in"]
            )
            logger.info(f"Successfully obtained and stored access token for user {user_id}")
        else:
            error_msg = response_data.get("error_description", "Unknown error")
            logger.error(f"Failed to obtain access token: {error_msg}")
            raise Exception(f"Failed to obtain user access token: {error_msg}")
    
    async def revoke_access(self, user_id):
        """
        Revoke the Box access for a user.
        
        Args:
            user_id: The user's ID
        """
        token = await self._load_token(user_id)
        if not token:
            raise ValueError("No valid token found for user")
        
        if not self.client_id:
            raise ValueError("Box Client ID is not set in configuration.")
        if not self.client_secret:
            raise ValueError("Box Client Secret is not set in configuration.")
        
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "token": token
        }
        
        response = requests.post(f"{BOX_AUTH_BASE_URL}revoke", data=payload)
        
        if response.status_code == 200:
            # Delete the token from storage
            self.token_storage.delete_token(user_id, PLATFORM, SERVICE)
            logger.info(f"Successfully revoked access for user {user_id}")
        else:
            logger.error(f"Failed to revoke token: {response.status_code}")
            raise Exception(f"Failed to revoke token: {response.status_code}")
    
    async def create_folder(self, user_id, folder_name, parent_folder_id="0"):
        """
        Create a folder in Box.
        
        Args:
            user_id: The user's ID
            folder_name: Name of the folder to create
            parent_folder_id: ID of the parent folder (default: "0" for root)
            
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
            "name": folder_name,
            "parent": {"id": parent_folder_id}
        }
        
        response = requests.post(
            f"{BOX_API_BASE_URL}folders", 
            headers=headers, 
            json=payload
        )
        
        if response.status_code in (200, 201):
            return response.json()
        else:
            self._handle_api_error(response, user_id)
    
    async def search_for_file(self, user_id, query, limit=100):
        """
        Search for files in Box.
        
        Args:
            user_id: The user's ID
            query: Search query
            limit: Maximum number of results to return
            
        Returns:
            dict: Search results
        """
        token = await self._load_token(user_id)
        if not token:
            raise self._create_auth_exception(user_id)
        
        headers = {
            "Authorization": f"Bearer {token}"
        }
        
        params = {
            "query": query,
            "limit": limit,
            "type": "file"
        }
        
        response = requests.get(
            f"{BOX_API_BASE_URL}search", 
            headers=headers, 
            params=params
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            self._handle_api_error(response, user_id)
    
    async def delete_file(self, user_id, file_id):
        """
        Delete a file from Box.
        
        Args:
            user_id: The user's ID
            file_id: ID of the file to delete
        """
        token = await self._load_token(user_id)
        if not token:
            raise self._create_auth_exception(user_id)
        
        headers = {
            "Authorization": f"Bearer {token}"
        }
        
        response = requests.delete(
            f"{BOX_API_BASE_URL}files/{file_id}", 
            headers=headers
        )
        
        if response.status_code != 204:  # 204 No Content is success
            self._handle_api_error(response, user_id)
    
    async def upload_file(self, user_id, file_path, original_file_name, folder_id="0"):
        """
        Upload a file to Box.
        
        Args:
            user_id: The user's ID
            file_path: Path to the local file
            original_file_name: Original name of the file
            folder_id: ID of the folder to upload to (default: "0" for root)
            
        Returns:
            dict: The uploaded file information
        """
        token = await self._load_token(user_id)
        if not token:
            raise self._create_auth_exception(user_id)
        
        headers = {
            "Authorization": f"Bearer {token}"
        }
        
        attributes = json.dumps({
            "name": original_file_name,
            "parent": {"id": folder_id}
        })
        
        with open(file_path, 'rb') as file:
            files = {
                'attributes': (None, attributes, 'application/json'),
                'file': (original_file_name, file, 'application/octet-stream')
            }
            
            response = requests.post(
                f"{BOX_UPLOAD_API_BASE_URL}files/content", 
                headers=headers,
                files=files
            )
        
        if response.status_code in (200, 201):
            return response.json()['entries'][0]  # Box returns an entries array
        else:
            self._handle_api_error(response, user_id)
    
    async def get_file_download_link(self, user_id, file_id):
        """
        Get a download link for a file.
        
        Args:
            user_id: The user's ID
            file_id: ID of the file
            
        Returns:
            str: Download URL
        """
        token = await self._load_token(user_id)
        if not token:
            raise self._create_auth_exception(user_id)
        
        headers = {
            "Authorization": f"Bearer {token}"
        }
        
        # Box API redirects to the actual download URL, so we need to disable redirects
        response = requests.get(
            f"{BOX_API_BASE_URL}files/{file_id}/content", 
            headers=headers,
            allow_redirects=False
        )
        
        if response.status_code == 302:  # Redirect status code
            return response.headers.get('Location')
        else:
            self._handle_api_error(response, user_id)
    
    async def get_file_view_link(self, user_id, file_id):
        """
        Get a shared view link for a file.
        
        Args:
            user_id: The user's ID
            file_id: ID of the file
            
        Returns:
            str: Shared URL
        """
        token = await self._load_token(user_id)
        if not token:
            raise self._create_auth_exception(user_id)
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "shared_link": {"access": "open"}
        }
        
        response = requests.put(
            f"{BOX_API_BASE_URL}files/{file_id}", 
            headers=headers,
            json=payload
        )
        
        if response.status_code == 200:
            data = response.json()
            if "shared_link" in data and "url" in data["shared_link"]:
                return data["shared_link"]["url"]
            else:
                raise Exception("Shared link URL not found in response")
        else:
            self._handle_api_error(response, user_id)
    
    async def share_file(self, user_id, file_id, email, role):
        """
        Share a file with another user.
        
        Args:
            user_id: The user's ID
            file_id: ID of the file to share
            email: Email of the user to share with
            role: Role to assign (editor, viewer, etc.)
        """
        token = await self._load_token(user_id)
        if not token:
            raise self._create_auth_exception(user_id)
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "item": {"id": file_id, "type": "file"},
            "accessible_by": {"type": "user", "login": email},
            "role": role
        }
        
        response = requests.post(
            f"{BOX_API_BASE_URL}collaborations", 
            headers=headers,
            json=payload
        )
        
        if response.status_code not in (200, 201):
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
        
        # Store in the token storage
        token_record = {
            "encrypted_token": encrypted_token,
            "is_active": True,
            "is_revoked": False,
            "created_at": datetime.utcnow().timestamp()
        }
        
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
            raise ValueError("Box Client ID is not set in configuration.")
        if not self.client_secret:
            raise ValueError("Box Client Secret is not set in configuration.")
        
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }
        
        logger.info(f"Attempting to refresh token for user {user_id}")
        response = requests.post(f"{BOX_AUTH_BASE_URL}token", data=payload)
        response_data = response.json()
        
        if response.status_code == 200 and "access_token" in response_data:
            await self._store_token(
                user_id, 
                response_data["access_token"], 
                response_data["refresh_token"], 
                response_data["expires_in"]
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
            error_msg = error_data.get("message", "Unknown error")
            
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
            raise Exception(f"Box API request failed: {error_msg}")
        except ValueError:
            # Response couldn't be parsed as JSON
            raise Exception(f"Box API request failed with status code: {response.status_code}")
    
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
            "Your Box authorization has expired or is invalid. "
            "Please use the `!authorize-box` command to reconnect your Box account."
        )