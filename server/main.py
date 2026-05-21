from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from auth import create_access_token, verify_token
from claude_client import ClaudeCliError, ask_claude
from config import settings

app = FastAPI(
    title="yclaude",
    description=(
        "Lightweight backend that issues bearer tokens and bridges natural-language "
        "requests to the locally installed Claude CLI."
    ),
    version="0.1.0",
)


class TokenRequest(BaseModel):
    api_key: str = Field(
        ...,
        description="Master API key configured on the server",
        examples=["change-me"],
    )
    client_id: str | None = Field(
        default=None,
        description="Optional identifier for the requesting client",
        examples=["test-user"],
    )


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class ChatRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=1,
        description="Natural language question",
        examples=["오늘 추천 점심 메뉴"],
    )
    model: str | None = Field(
        default=None,
        description=f"Claude model alias or ID. Defaults to '{settings.default_model}'.",
        examples=["opus"],
    )


class ChatResponse(BaseModel):
    answer: str
    model: str


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/auth/token", response_model=TokenResponse, tags=["auth"])
async def issue_token(req: TokenRequest) -> TokenResponse:
    if req.api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key"
        )

    subject = req.client_id or "default"
    token, expires_in = create_access_token(subject)
    return TokenResponse(access_token=token, expires_in=expires_in)


@app.post("/chat", response_model=ChatResponse, tags=["chat"])
async def chat(
    req: ChatRequest, subject: str = Depends(verify_token)
) -> ChatResponse:
    model = (req.model or settings.default_model).strip()
    try:
        answer = await ask_claude(req.question, model)
    except ClaudeCliError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        )
    return ChatResponse(answer=answer, model=model)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=False)
