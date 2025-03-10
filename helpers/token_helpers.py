import os
import json
import logging
from datetime import datetime
from cryptography.fernet import Fernet

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
    """A file-based token storage system for managing OAuth tokens."""
    
    def __init__(self, storage_file="user_tokens.json"):
        """
        Initialize the token storage.
        
        Args:
            storage_file (str): Path to the token storage file
        """
        self.storage_file = storage_file
        # Initialize the storage file if it doesn't exist
        if not os.path.exists(storage_file):
            with open(storage_file, 'w') as f:
                json.dump({}, f)
    
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