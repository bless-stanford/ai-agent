class BoxFolder:
    """
    Model representing a Box folder.
    """
    def __init__(self, 
                 id=None, 
                 name=None, 
                 parent=None, 
                 created_at=None, 
                 modified_at=None, 
                 item_collection=None, 
                 **kwargs):
        self.id = id
        self.name = name
        self.parent = parent
        self.created_at = created_at
        self.modified_at = modified_at
        self.item_collection = item_collection
        
        # Store additional properties
        for key, value in kwargs.items():
            setattr(self, key, value)

    @classmethod
    def from_dict(cls, data):
        """Create a BoxFolder instance from a dictionary."""
        return cls(**data)


class BoxFile:
    """
    Model representing a Box file.
    """
    def __init__(self, 
                 id=None, 
                 name=None, 
                 parent=None, 
                 created_at=None, 
                 modified_at=None, 
                 size=None, 
                 extension=None, 
                 shared_link=None, 
                 **kwargs):
        self.id = id
        self.name = name
        self.parent = parent
        self.created_at = created_at
        self.modified_at = modified_at
        self.size = size
        self.extension = extension
        self.shared_link = shared_link
        
        # Store additional properties
        for key, value in kwargs.items():
            setattr(self, key, value)

    @classmethod
    def from_dict(cls, data):
        """Create a BoxFile instance from a dictionary."""
        return cls(**data)


class BoxTokenData:
    """
    Model representing Box token data for storage.
    """
    def __init__(self, access_token=None, refresh_token=None, expires_at=None):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_at = expires_at

    def to_dict(self):
        """Convert to dictionary for serialization."""
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at
        }

    @classmethod
    def from_dict(cls, data):
        """Create a BoxTokenData instance from a dictionary."""
        return cls(
            access_token=data.get("access_token"),
            refresh_token=data.get("refresh_token"),
            expires_at=data.get("expires_at")
        )


class BoxTokenResponse:
    """
    Model representing the response from Box token endpoint.
    """
    def __init__(self, access_token=None, refresh_token=None, expires_in=None, token_type=None):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_in = expires_in
        self.token_type = token_type

    @classmethod
    def from_dict(cls, data):
        """Create a BoxTokenResponse instance from a dictionary."""
        return cls(
            access_token=data.get("access_token"),
            refresh_token=data.get("refresh_token"),
            expires_in=data.get("expires_in"),
            token_type=data.get("token_type")
        )