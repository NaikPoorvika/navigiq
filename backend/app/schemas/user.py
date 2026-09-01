from pydantic import BaseModel
from uuid import UUID

# Shared properties
class UserBase(BaseModel):
    email: str
    is_active: bool = True
    is_superuser: bool = False

# Properties to receive via API on creation
class UserCreate(UserBase):
    password: str

# Properties to return via API
class UserResponse(UserBase):
    id: UUID
    
    class Config:
        from_attributes = True
