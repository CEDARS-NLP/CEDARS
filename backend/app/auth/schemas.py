from pydantic import BaseModel, EmailStr


class RegisterRequest(BaseModel):
    email: EmailStr
    name: str
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class LoginResponse(BaseModel):
    message: str = "Login successful"
    user: "UserResponse"


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str
    is_active: bool
