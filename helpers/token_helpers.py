import os
import json
import logging
from datetime import datetime
from cryptography.fernet import Fernet
from azure.storage.blob import BlobServiceClient

# Setup logging
logger = logging.getLogger("token_helpers")

class TokenEncryptionHelper:
    """Helper class for encrypting and decrypting tokens."""
    
    @staticmethod
    def encrypt_token(token_str, encryption_key):
        """
        Encrypts a token string using Fernet symmetric encryption.
        
        Args:
            token_str (str): The token string to encrypt
            encryption_key (bytes): The encryption key
            
        Returns:
            str: The encrypted token as a string
        """
        f = Fernet(encryption_key)
        return f.encrypt(token_str.encode()).decode()
    
    @staticmethod
    def decrypt_token(encrypted_token, encryption_key):
        """
        Decrypts an encrypted token string using Fernet symmetric encryption.
        
        Args:
            encrypted_token (str): The encrypted token string
            encryption_key (bytes): The encryption key
            
        Returns:
            str: The decrypted token string
        """
        f = Fernet(encryption_key)
        return f.decrypt(encrypted_token.encode()).decode()
    
    @staticmethod
    def generate_key():
        """
        Generates a new Fernet encryption key.
        
        Returns:
            bytes: A new encryption key
        """
        return Fernet.generate_key()


class TokenStorageManager:
    """A storage system for managing OAuth tokens with Azure Blob Storage support."""
    
    def __init__(self, container_name="user-tokens", blob_name="user_tokens.json"):
        """
        Initialize the token storage.
        
        Args:
            container_name (str): Name of the Azure Blob container
            blob_name (str): Name of the blob for token storage
        """
        self.blob_name = blob_name
        self.container_name = container_name
        
        # Get the connection string from environment variable
        connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        if not connection_string:
            logger.warning("AZURE_STORAGE_CONNECTION_STRING not found. Using local file storage.")
            self.use_blob_storage = False
            self.storage_file = "user_tokens.json"
            # Initialize the storage file if it doesn't exist
            if not os.path.exists(self.storage_file):
                with open(self.storage_file, 'w') as f:
                    json.dump({}, f)
        else:
            self.use_blob_storage = True
            self.blob_service_client = BlobServiceClient.from_connection_string(connection_string)
            
            # Create container if it doesn't exist
            try:
                container_client = self.blob_service_client.get_container_client(self.container_name)
                if not container_client.exists():
                    self.blob_service_client.create_container(self.container_name)
                    logger.info(f"Created container: {self.container_name}")
            except Exception as e:
                logger.error(f"Error creating container: {str(e)}")
                self.use_blob_storage = False
    
    def get_token(self, user_id, platform, service):
        """
        Retrieve a token from storage.
        
        Args:
            user_id (str): The user's ID
            platform (str): The platform name (e.g., "Box", "Dropbox")
            service (str): The service name (e.g., "BoxService")
            
        Returns:
            dict: The token record or None if not found
        """
        try:
            if self.use_blob_storage:
                # Get the blob
                blob_client = self.blob_service_client.get_blob_client(
                    container=self.container_name, 
                    blob=self.blob_name
                )
                
                if blob_client.exists():
                    # Download the blob content
                    blob_content = blob_client.download_blob().readall()
                    tokens = json.loads(blob_content)
                else:
                    # Blob doesn't exist, create an empty dictionary
                    tokens = {}
            else:
                # Use local file
                with open(self.storage_file, 'r') as f:
                    tokens = json.load(f)
                
            key = f"{user_id}_{platform}_{service}"
            return tokens.get(key)
        except Exception as e:
            logger.error(f"Error retrieving token: {str(e)}")
            return None
    
    def store_token(self, user_id, platform, service, token_data):
        """
        Store a token in storage.
        
        Args:
            user_id (str): The user's ID
            platform (str): The platform name (e.g., "Box", "Dropbox")
            service (str): The service name (e.g., "BoxService")
            token_data (dict): The token data to store
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if self.use_blob_storage:
                # Get the blob
                blob_client = self.blob_service_client.get_blob_client(
                    container=self.container_name, 
                    blob=self.blob_name
                )
                
                if blob_client.exists():
                    # Download existing blob content
                    blob_content = blob_client.download_blob().readall()
                    tokens = json.loads(blob_content)
                else:
                    # Blob doesn't exist, create an empty dictionary
                    tokens = {}
            else:
                # Use local file
                with open(self.storage_file, 'r') as f:
                    tokens = json.load(f)
            
            key = f"{user_id}_{platform}_{service}"
            tokens[key] = token_data
            
            if self.use_blob_storage:
                # Upload the updated tokens
                blob_client.upload_blob(json.dumps(tokens), overwrite=True)
            else:
                # Write to local file
                with open(self.storage_file, 'w') as f:
                    json.dump(tokens, f)
            
            logger.info(f"Token stored successfully for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error storing token: {str(e)}")
            return False
    
    def delete_token(self, user_id, platform, service):
        """
        Delete a token from storage.
        
        Args:
            user_id (str): The user's ID
            platform (str): The platform name (e.g., "Box", "Dropbox")
            service (str): The service name (e.g., "BoxService")
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if self.use_blob_storage:
                # Get the blob
                blob_client = self.blob_service_client.get_blob_client(
                    container=self.container_name, 
                    blob=self.blob_name
                )
                
                if blob_client.exists():
                    # Download existing blob content
                    blob_content = blob_client.download_blob().readall()
                    tokens = json.loads(blob_content)
                else:
                    # Blob doesn't exist, nothing to delete
                    return True
            else:
                # Use local file
                with open(self.storage_file, 'r') as f:
                    tokens = json.load(f)
            
            key = f"{user_id}_{platform}_{service}"
            if key in tokens:
                del tokens[key]
            
            if self.use_blob_storage:
                # Upload the updated tokens
                blob_client.upload_blob(json.dumps(tokens), overwrite=True)
            else:
                # Write to local file
                with open(self.storage_file, 'w') as f:
                    json.dump(tokens, f)
            
            logger.info(f"Token deleted successfully for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting token: {str(e)}")
            return False


def create_token_record(encrypted_token):
    """
    Create a standard token record structure.
    
    Args:
        encrypted_token (str): The encrypted token string
        
    Returns:
        dict: A standardized token record
    """
    return {
        "encrypted_token": encrypted_token,
        "is_active": True,
        "is_revoked": False,
        "created_at": datetime.utcnow().timestamp()
    }


def load_or_generate_encryption_key(env_key_name="ENCRYPTION_KEY"):
    """
    Load an encryption key from environment variable or generate a new one.
    
    Args:
        env_key_name (str): Name of the environment variable
        
    Returns:
        bytes: The encryption key
    """
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    encryption_key = os.getenv(env_key_name)
    
    if not encryption_key:
        # Generate a new key if none exists
        encryption_key = Fernet.generate_key().decode()
        # Log a warning since we should save this key
        logger.warning(f"No encryption key found. Generated new key. Add to .env: {env_key_name}={encryption_key}")
    
    return encryption_key.encode() if isinstance(encryption_key, str) else encryption_key